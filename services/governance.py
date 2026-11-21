"""Persistent threshold overrides and their transactional audit history."""
import os
import sqlite3
from contextlib import contextmanager

from schemas import AuditActionType, AuditLogEntry, MetricThresholdConfig
from services.metrics_store import metrics_store


@contextmanager
def database():
    db = sqlite3.connect(os.environ.get("DASHBOARD_STATE_DB", "dashboard-state.sqlite3"))
    try:
        with db:
            db.execute("CREATE TABLE IF NOT EXISTS thresholds (name TEXT PRIMARY KEY, payload TEXT NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS audit (payload TEXT NOT NULL)")
            yield db
    finally:
        db.close()


def thresholds():
    rules = {rule.metric_name: rule for rule in metrics_store.list_thresholds()}
    with database() as db:
        for name, payload in db.execute("SELECT name, payload FROM thresholds"):
            rules[name] = MetricThresholdConfig.model_validate_json(payload)
    return rules


def save_threshold(config, actor):
    with database() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT payload FROM thresholds WHERE name=?", (config.metric_name,)).fetchone()
        prior = MetricThresholdConfig.model_validate_json(row[0]) if row else metrics_store.get_threshold(config.metric_name)
        entry = AuditLogEntry(user_id=actor, targeted_metric=config.metric_name,
                              reason=config.custom_rule_setter_metadata.get("reason"),
                              action_type=AuditActionType.THRESHOLD_UPDATE if prior else AuditActionType.THRESHOLD_CREATE,
                              previous_value=prior.model_dump(mode="json") if prior else None,
                              new_value=config.model_dump(mode="json"))
        db.execute("INSERT OR REPLACE INTO thresholds VALUES (?, ?)", (config.metric_name, config.model_dump_json()))
        db.execute("INSERT INTO audit VALUES (?)", (entry.model_dump_json(),))
        return entry


def audit_entries():
    with database() as db:
        return [AuditLogEntry.model_validate_json(row[0]) for row in db.execute("SELECT payload FROM audit ORDER BY rowid DESC")]
