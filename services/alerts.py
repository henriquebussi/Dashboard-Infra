"""Evaluate persisted rules against available telemetry."""
from typing import List

from schemas import (AlertRule, AlertSeverity, CloudMetrics, DatabaseMetrics,
                     MetricReading, MetricStatus, ProcessingMetrics, SlaMetrics,
                     StorageMetrics, TokenUsageMetrics)
from services.governance import thresholds


def evaluate_local_alerts(
    database: DatabaseMetrics,
    cloud: CloudMetrics,
    storage: StorageMetrics,
    processing: ProcessingMetrics,
    tokens: TokenUsageMetrics,
    sla: SlaMetrics,
) -> List[AlertRule]:
    """Evaluate threshold configurations locally on server-side real readings.

    Zero calls to GCP Alerting APIs.
    """
    active_alerts: List[AlertRule] = []

    sections = {"database": database, "cloud": cloud, "storage": storage,
                "processing": processing, "tokens": tokens, "sla": sla}
    actions = {
        "database.cpu_io_percent": ("database.cpu-io", "Scale database tier or optimize slow queries causing CPU saturation."),
        "database.active_connections": ("database.connections", "Increase Cloud SQL connection pool limits or enable connection pooling (PgBouncer)."),
        "cloud.cpu_percent": ("cloud.cpu", "Scale out Compute Engine instance group or investigate runaway processes."),
        "cloud.uptime_percent": ("cloud.uptime", "Investigate VM node reboots and zone availability incidents."),
        "storage.bucket_volume_usage_percent": ("storage.buckets", "Enforce object lifecycle rules or archive cold objects to Nearline/Coldline."),
        "processing.failure_counts": ("processing.failures", "Review BigQuery job error logs and query syntax/quota exhaustion."),
        "tokens.error_rate_percent": ("tokens.error-rate", "Inspect Vertex AI model invocation latencies and quota limits."),
        "sla.availability_percent": ("sla.availability", "Initiate high-severity platform incident triage."),
    }
    for name, config in thresholds().items():
        category, _, field = name.partition(".")
        reading = getattr(sections.get(category), field, None)
        if not isinstance(reading, MetricReading) or not reading.available:
            continue
        metric_id, action = actions.get(name, (name, "Verifique a métrica e os recursos afetados."))
        evaluated_status = config.evaluate(reading.current_value)
        reading.status = evaluated_status
        if evaluated_status != MetricStatus.HEALTHY:
            sev = AlertSeverity.CRITICAL if evaluated_status == MetricStatus.CRITICAL else AlertSeverity.WARNING
            active_alerts.append(
                AlertRule(
                    metric_id=metric_id,
                    current_value=reading.current_value,
                    severity=sev,
                    suggested_action=action,
                )
            )

    return active_alerts
