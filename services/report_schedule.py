"""Durable performance report schedules with SMTP delivery."""
import asyncio
import json
import logging
import os
import smtplib
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from uuid import uuid4

from schemas import AuditActionType, AuditLogEntry, DashboardFilterParams
from services.export_service import export_metrics_report
from services.governance import database

logger = logging.getLogger(__name__)


def now():
    return datetime.now(timezone.utc)


def next_run(frequency, after):
    if frequency == "daily":
        return after + timedelta(days=1)
    if frequency == "weekly":
        return after + timedelta(days=7)
    year = after.year + (after.month == 12)
    month = after.month % 12 + 1
    return after.replace(year=year, month=month, day=1)


def tables(db):
    db.execute("""CREATE TABLE IF NOT EXISTS report_schedules
        (id TEXT PRIMARY KEY, payload TEXT NOT NULL, next_run TEXT NOT NULL,
         lease_until TEXT, last_run TEXT, last_status TEXT)""")


def list_schedules():
    with database() as db:
        tables(db)
        return [dict(json.loads(payload), id=ident, next_run=due,
                     last_run=last_run, last_status=status)
                for ident, payload, due, last_run, status in
                db.execute("SELECT id,payload,next_run,last_run,last_status FROM report_schedules ORDER BY next_run")]


def save_schedule(config, actor, ident=None):
    with database() as db:
        tables(db)
        db.execute("BEGIN IMMEDIATE")
        prior = db.execute("SELECT payload,next_run,last_run,last_status FROM report_schedules WHERE id=?", (ident,)).fetchone() if ident else None
        if ident and not prior:
            raise KeyError(ident)
        ident = ident or str(uuid4())
        previous = json.loads(prior[0]) if prior else None
        due = prior[1] if prior and previous["frequency"] == config["frequency"] else next_run(config["frequency"], now()).isoformat()
        db.execute("""INSERT OR REPLACE INTO report_schedules
            (id,payload,next_run,lease_until,last_run,last_status) VALUES (?,?,?,?,?,?)""",
            (ident, json.dumps(config), due, None, prior[2] if prior else None, prior[3] if prior else None))
        entry = AuditLogEntry(user_id=actor, action_type=AuditActionType.CONFIG_CHANGE,
                              targeted_metric=f"report_schedule.{ident}", previous_value=previous, new_value=config)
        db.execute("INSERT INTO audit VALUES (?)", (entry.model_dump_json(),))
    return ident


def delete_schedule(ident, actor):
    with database() as db:
        tables(db)
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT payload FROM report_schedules WHERE id=?", (ident,)).fetchone()
        if not row:
            raise KeyError(ident)
        db.execute("DELETE FROM report_schedules WHERE id=?", (ident,))
        entry = AuditLogEntry(user_id=actor, action_type=AuditActionType.CONFIG_CHANGE,
                              targeted_metric=f"report_schedule.{ident}", previous_value=json.loads(row[0]), new_value=None)
        db.execute("INSERT INTO audit VALUES (?)", (entry.model_dump_json(),))


def claim_due():
    current = now()
    with database() as db:
        tables(db)
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("""SELECT id,payload FROM report_schedules WHERE next_run<=?
            AND (lease_until IS NULL OR lease_until<?) ORDER BY next_run LIMIT 1""",
            (current.isoformat(), current.isoformat())).fetchone()
        if row:
            db.execute("UPDATE report_schedules SET lease_until=? WHERE id=?",
                       ((current + timedelta(minutes=10)).isoformat(), row[0]))
        return (row[0], json.loads(row[1])) if row else None


def finish(ident, config, error=None):
    current = now()
    with database() as db:
        tables(db)
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT payload FROM report_schedules WHERE id=?", (ident,)).fetchone()
        if row and json.loads(row[0]) == config:
            db.execute("""UPDATE report_schedules SET next_run=?,lease_until=NULL,last_run=?,last_status=?
                WHERE id=?""", ((current + timedelta(minutes=15) if error else next_run(config["frequency"], current)).isoformat(),
                               current.isoformat(), "failed" if error else "sent", ident))
            entry = AuditLogEntry(user_id="report_scheduler", action_type=AuditActionType.CONFIG_CHANGE,
                                  targeted_metric=f"report_schedule.{ident}.delivery",
                                  new_value={"status": "failed" if error else "sent", "error": str(error)[:200] if error else None})
            db.execute("INSERT INTO audit VALUES (?)", (entry.model_dump_json(),))


def send_email(recipient, content, media_type, filename):
    host = os.environ["REPORT_SMTP_HOST"]
    port = int(os.getenv("REPORT_SMTP_PORT", "587"))
    sender = os.environ["REPORT_SMTP_FROM"]
    message = EmailMessage()
    message["From"] = sender
    message["To"] = recipient
    message["Subject"] = "Relatório de desempenho do Dashboard SB100"
    message.set_content("Segue o relatório de desempenho agendado.")
    kind, subtype = media_type.split("/", 1)
    message.add_attachment(content, maintype=kind, subtype=subtype, filename=filename)
    with smtplib.SMTP(host, port, timeout=20) as smtp:
        if os.getenv("REPORT_SMTP_STARTTLS", "true").lower() == "true":
            smtp.starttls()
        if os.getenv("REPORT_SMTP_USER"):
            smtp.login(os.environ["REPORT_SMTP_USER"], os.environ["REPORT_SMTP_PASSWORD"])
        smtp.send_message(message)


async def run_due(app):
    while True:
        claimed = await asyncio.to_thread(claim_due)
        if claimed:
            ident, config = claimed
            try:
                service = getattr(app.state, "gcp_service", None)
                if service is None:
                    raise RuntimeError("Integração GCP indisponível")
                filters = DashboardFilterParams(period=config["period"], env=config["environment"])
                payload = await service.get_overview_payload(filters)
                if payload.data_source != "gcp":
                    raise RuntimeError("Dados reais indisponíveis")
                content, media_type, filename = export_metrics_report(payload, config["format"])
                await asyncio.to_thread(send_email, config["recipient"], content, media_type, filename)
                await asyncio.to_thread(finish, ident, config)
            except Exception as exc:
                logger.exception("Scheduled report failed for %s", ident)
                await asyncio.to_thread(finish, ident, config, exc)
        await asyncio.sleep(30)
