from datetime import datetime, timezone
from unittest.mock import patch

from fastapi.testclient import TestClient

from main import app
from services import report_schedule


def test_admin_schedule_and_audit(monkeypatch, tmp_path):
    monkeypatch.setenv("DASHBOARD_STATE_DB", str(tmp_path / "reports.sqlite3"))
    client = TestClient(app)
    config = {
        "recipient": "infra@example.com", "frequency": "daily",
        "environment": "DEV", "period": "24h", "format": "pdf",
    }
    admin = ("admin@dashboard", "123")
    viewer = ("viewer@dashboard", "123")
    assert client.post("/api/v1/reports/schedules", json=config, auth=viewer).status_code == 403
    response = client.post("/api/v1/reports/schedules", json=config, auth=admin)
    assert response.status_code == 201
    ident = response.json()["id"]
    listed = client.get("/api/v1/reports/schedules", auth=admin)
    assert listed.status_code == 200
    assert listed.json()[0]["recipient"] == config["recipient"]
    assert client.get("/api/v1/reports/schedules", auth=viewer).status_code == 403
    config["frequency"] = "monthly"
    assert client.put(f"/api/v1/reports/schedules/{ident}", json=config, auth=admin).status_code == 200
    assert client.delete(f"/api/v1/reports/schedules/{ident}", auth=viewer).status_code == 403
    assert client.delete(f"/api/v1/reports/schedules/{ident}", auth=admin).status_code == 204
    events = client.get("/api/v1/audit-logs", auth=admin).json()
    changes = [entry for entry in events if entry["targeted_metric"] == f"report_schedule.{ident}"]
    assert len(changes) == 3
    assert all(entry["user_id"] == "admin@dashboard" for entry in changes)


def test_failed_delivery_retries_and_does_not_send_demo(monkeypatch, tmp_path):
    monkeypatch.setenv("DASHBOARD_STATE_DB", str(tmp_path / "reports.sqlite3"))
    config = {
        "recipient": "infra@example.com", "frequency": "weekly",
        "environment": "PROD", "period": "7d", "format": "csv",
    }
    ident = report_schedule.save_schedule(config, "admin@dashboard")
    with report_schedule.database() as db:
        db.execute("UPDATE report_schedules SET next_run=? WHERE id=?",
                   (datetime.now(timezone.utc).isoformat(), ident))
    claimed = report_schedule.claim_due()
    assert claimed == (ident, config)
    assert report_schedule.claim_due() is None
    report_schedule.finish(ident, config, RuntimeError("SMTP indisponível"))
    item = report_schedule.list_schedules()[0]
    assert item["last_status"] == "failed"
    assert datetime.fromisoformat(item["next_run"]) > datetime.now(timezone.utc)


def test_report_download_requires_admin(monkeypatch, tmp_path):
    monkeypatch.setenv("DASHBOARD_STATE_DB", str(tmp_path / "reports.sqlite3"))
    client = TestClient(app)
    path = "/api/v1/reports/download?environment=PROD&period=7d&format=pdf"
    assert client.get(path, auth=("viewer@dashboard", "123")).status_code == 403
    assert client.get(path, auth=("admin@dashboard", "123")).status_code == 503
