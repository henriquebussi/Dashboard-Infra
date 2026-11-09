"""GCP FinOps Observatory - Metric Definition Registry.

Provides a typed, comprehensive mapping between UI statistics and canonical GCP
Cloud Monitoring metric types, aligners, reducers, grouping fields, value
transformations, and operational constraints.

Covers:
  - Database: Cloud SQL (MySQL, PostgreSQL), Memorystore
  - Compute: Compute Engine VM utilization, network, disk, Ops Agent metrics
  - Storage: Cloud Storage (GCS) daily snapshot awareness, IOPS, throughput
  - Processing: BigQuery in-flight jobs, query execution time, scanned bytes
  - Token Usage: Vertex AI token counts, error rates, model latencies
  - Platform SLA: Availability, error counts, saturation peak, growth
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence


@dataclass(frozen=True)
class MetricDefinition:
    """Specification for querying and interpreting a GCP time-series metric."""

    id: str
    category: str
    field_name: str
    gcp_metric_types: List[str]
    aligner: str = "ALIGN_MEAN"
    reducer: str = "REDUCE_MEAN"
    unit: str = "%"
    group_by_fields: List[str] = field(default_factory=list)
    filter_template: Optional[str] = None
    value_transform: Optional[Callable[[float], float]] = None
    is_daily_snapshot: bool = False
    requires_ops_agent: bool = False
    requires_billing: bool = False
    default_available: bool = True
    unavailable_reason: Optional[str] = None
    description: str = ""


# ---------------------------------------------------------------------------
# Metric Registry Catalog
# ---------------------------------------------------------------------------

METRIC_DEFINITIONS: Dict[str, MetricDefinition] = {
    # ── Database (Cloud SQL) ────────────────────────────────────────────────
    "database.qps": MetricDefinition(
        id="database.qps",
        category="database",
        field_name="qps",
        gcp_metric_types=[
            "cloudsql.googleapis.com/database/mysql/queries",
            "cloudsql.googleapis.com/database/postgresql/transaction_count",
            "cloudsql.googleapis.com/database/queries",
        ],
        aligner="ALIGN_RATE",
        reducer="REDUCE_SUM",
        unit="queries/sec",
        group_by_fields=["resource.labels.database_id"],
        description="Queries or transactions executed per second across managed DB instances",
    ),
    "database.active_connections": MetricDefinition(
        id="database.active_connections",
        category="database",
        field_name="active_connections",
        gcp_metric_types=[
            "cloudsql.googleapis.com/database/network/connections",
            "cloudsql.googleapis.com/database/connections",
        ],
        aligner="ALIGN_MEAN",
        reducer="REDUCE_SUM",
        unit="count",
        group_by_fields=["resource.labels.database_id"],
        description="Active open client connections to Cloud SQL instances",
    ),
    "database.locks": MetricDefinition(
        id="database.locks",
        category="database",
        field_name="locks",
        gcp_metric_types=[
            "cloudsql.googleapis.com/database/mysql/innodb_row_lock_waits",
            "cloudsql.googleapis.com/database/mysql/innodb_row_lock_time",
        ],
        aligner="ALIGN_MEAN",
        reducer="REDUCE_SUM",
        unit="count",
        group_by_fields=["resource.labels.database_id"],
        description="Number of database sessions actively waiting on row or table locks",
    ),
    "database.slow_queries_count": MetricDefinition(
        id="database.slow_queries_count",
        category="database",
        field_name="slow_queries_count",
        gcp_metric_types=[],  # Derived via Cloud Logging slow query sinks
        aligner="ALIGN_DELTA",
        reducer="REDUCE_SUM",
        unit="count",
        group_by_fields=["resource.labels.database_id"],
        description="Count of executed queries exceeding latency threshold (>1000ms)",
    ),
    "database.avg_response_time_ms": MetricDefinition(
        id="database.avg_response_time_ms",
        category="database",
        field_name="avg_response_time_ms",
        gcp_metric_types=[
            "cloudsql.googleapis.com/database/mysql/queries",
        ],
        aligner="ALIGN_PERCENTILE_95",
        reducer="REDUCE_MEAN",
        unit="ms",
        group_by_fields=["resource.labels.database_id"],
        description="Mean / P95 query execution duration across instances in milliseconds",
    ),
    "database.cpu_io_percent": MetricDefinition(
        id="database.cpu_io_percent",
        category="database",
        field_name="cpu_io_percent",
        gcp_metric_types=[
            "cloudsql.googleapis.com/database/cpu/utilization",
        ],
        aligner="ALIGN_MEAN",
        reducer="REDUCE_MEAN",
        unit="%",
        group_by_fields=["resource.labels.database_id"],
        value_transform=lambda v: round(v * 100.0, 2) if v <= 1.0 else round(v, 2),
        description="Cloud SQL vCPU utilization pressure percentage (0.0 to 100.0%)",
    ),
    "database.replication_lag_seconds": MetricDefinition(
        id="database.replication_lag_seconds",
        category="database",
        field_name="replication_lag_seconds",
        gcp_metric_types=[
            "cloudsql.googleapis.com/database/replication/replica_lag",
        ],
        aligner="ALIGN_MEAN",
        reducer="REDUCE_MAX",
        unit="s",
        group_by_fields=["resource.labels.database_id"],
        description="Replication delay behind primary instance in seconds",
    ),
    "database.up": MetricDefinition(
        id="database.up",
        category="database",
        field_name="up",
        gcp_metric_types=[
            "cloudsql.googleapis.com/database/up",
        ],
        aligner="ALIGN_MEAN",
        reducer="REDUCE_MEAN",
        unit="ratio",
        group_by_fields=["resource.labels.database_id"],
        description="Cloud SQL instance liveness and operational health status",
    ),

    # ── Compute Engine (Cloud Fleet) ────────────────────────────────────────
    "cloud.cpu_percent": MetricDefinition(
        id="cloud.cpu_percent",
        category="cloud",
        field_name="cpu_percent",
        gcp_metric_types=[
            "compute.googleapis.com/instance/cpu/utilization",
        ],
        aligner="ALIGN_MEAN",
        reducer="REDUCE_MEAN",
        unit="%",
        group_by_fields=["resource.labels.instance_id"],
        value_transform=lambda v: round(v * 100.0, 2) if v <= 1.0 else round(v, 2),
        description="Average vCPU core utilization percentage across VMs (0.0 to 100.0%)",
    ),
    "cloud.memory_percent": MetricDefinition(
        id="cloud.memory_percent",
        category="cloud",
        field_name="memory_percent",
        gcp_metric_types=[
            "agent.googleapis.com/memory/percent_used",
            "compute.googleapis.com/instance/memory/utilization",
        ],
        aligner="ALIGN_MEAN",
        reducer="REDUCE_MEAN",
        unit="%",
        group_by_fields=["resource.labels.instance_id"],
        requires_ops_agent=True,
        unavailable_reason="Requires Google Cloud Ops Agent installed on VMs",
        description="RAM working set memory percentage utilized across VMs",
    ),
    "cloud.disk_percent": MetricDefinition(
        id="cloud.disk_percent",
        category="cloud",
        field_name="disk_percent",
        gcp_metric_types=[
            "agent.googleapis.com/disk/percent_used",
            "compute.googleapis.com/instance/disk/utilization",
        ],
        aligner="ALIGN_MEAN",
        reducer="REDUCE_MEAN",
        unit="%",
        group_by_fields=["resource.labels.instance_id"],
        requires_ops_agent=True,
        unavailable_reason="Requires Google Cloud Ops Agent installed on VMs",
        description="Provisioned persistent disk capacity currently utilized percentage",
    ),
    "cloud.estimated_cost_usd": MetricDefinition(
        id="cloud.estimated_cost_usd",
        category="cloud",
        field_name="estimated_cost_usd",
        gcp_metric_types=[],
        unit="USD",
        requires_billing=True,
        default_available=False,
        unavailable_reason="Requires GCP Billing permissions",
        description="Projected cloud infrastructure charges for the active period in USD",
    ),
    "cloud.uptime_percent": MetricDefinition(
        id="cloud.uptime_percent",
        category="cloud",
        field_name="uptime_percent",
        gcp_metric_types=[
            "compute.googleapis.com/instance/uptime",
        ],
        aligner="ALIGN_RATE",
        reducer="REDUCE_MEAN",
        unit="%",
        group_by_fields=["resource.labels.instance_id"],
        value_transform=lambda v: min(100.0, max(0.0, round(v * 100.0, 2) if v <= 1.0 else 99.9)),
        description="Observed VM compute fleet availability and uptime percentage",
    ),
    "cloud.network_in": MetricDefinition(
        id="cloud.network_in",
        category="cloud",
        field_name="network_in",
        gcp_metric_types=[
            "compute.googleapis.com/instance/network/received_bytes_count",
        ],
        aligner="ALIGN_RATE",
        reducer="REDUCE_SUM",
        unit="B",
        group_by_fields=["resource.labels.instance_id"],
        description="Incoming network data transfer in bytes per second",
    ),
    "cloud.network_out": MetricDefinition(
        id="cloud.network_out",
        category="cloud",
        field_name="network_out",
        gcp_metric_types=[
            "compute.googleapis.com/instance/network/sent_bytes_count",
        ],
        aligner="ALIGN_RATE",
        reducer="REDUCE_SUM",
        unit="B",
        group_by_fields=["resource.labels.instance_id"],
        description="Outgoing network data transfer in bytes per second",
    ),
    "cloud.disk_read_bytes": MetricDefinition(
        id="cloud.disk_read_bytes",
        category="cloud",
        field_name="disk_read_bytes",
        gcp_metric_types=[
            "compute.googleapis.com/instance/disk/read_bytes_count",
        ],
        aligner="ALIGN_RATE",
        reducer="REDUCE_SUM",
        unit="B",
        group_by_fields=["resource.labels.instance_id"],
        description="Disk read transfer rate in bytes per second",
    ),
    "cloud.disk_write_bytes": MetricDefinition(
        id="cloud.disk_write_bytes",
        category="cloud",
        field_name="disk_write_bytes",
        gcp_metric_types=[
            "compute.googleapis.com/instance/disk/write_bytes_count",
        ],
        aligner="ALIGN_RATE",
        reducer="REDUCE_SUM",
        unit="B",
        group_by_fields=["resource.labels.instance_id"],
        description="Disk write transfer rate in bytes per second",
    ),

    # ── Storage (Cloud Storage GCS) ─────────────────────────────────────────
    "storage.total_usage": MetricDefinition(
        id="storage.total_usage",
        category="storage",
        field_name="total_usage",
        gcp_metric_types=[
            "storage.googleapis.com/storage/v2/total_bytes",
            "storage.googleapis.com/storage/total_bytes",
        ],
        aligner="ALIGN_MEAN",
        reducer="REDUCE_SUM",
        unit="GB",
        group_by_fields=["resource.labels.bucket_name"],
        is_daily_snapshot=True,
        value_transform=lambda v: round(v / (1024.0**3), 2),  # Bytes to GB
        description="Aggregate Cloud Storage object storage volume in Gigabytes (daily snapshot)",
    ),
    "storage.bucket_volume_usage_percent": MetricDefinition(
        id="storage.bucket_volume_usage_percent",
        category="storage",
        field_name="bucket_volume_usage_percent",
        gcp_metric_types=[
            "storage.googleapis.com/storage/v2/total_bytes",
            "storage.googleapis.com/storage/total_bytes",
        ],
        aligner="ALIGN_MEAN",
        reducer="REDUCE_MEAN",
        unit="%",
        group_by_fields=["resource.labels.bucket_name"],
        is_daily_snapshot=True,
        value_transform=lambda v: min(100.0, max(0.0, round((v / (1024.0**4)) * 10.0, 2))),  # scaled %
        description="Relative capacity pressure across monitored GCS buckets",
    ),
    "storage.iops": MetricDefinition(
        id="storage.iops",
        category="storage",
        field_name="iops",
        gcp_metric_types=[
            "storage.googleapis.com/storage/v2/request_count",
            "storage.googleapis.com/storage/request_count",
        ],
        aligner="ALIGN_RATE",
        reducer="REDUCE_SUM",
        unit="IOPS",
        group_by_fields=["resource.labels.bucket_name"],
        description="Read and write I/O requests per second across storage buckets",
    ),
    "storage.read_write_throughput_mb_s": MetricDefinition(
        id="storage.read_write_throughput_mb_s",
        category="storage",
        field_name="read_write_throughput_mb_s",
        gcp_metric_types=[
            "storage.googleapis.com/network/received_bytes_count",
            "storage.googleapis.com/network/sent_bytes_count",
        ],
        aligner="ALIGN_RATE",
        reducer="REDUCE_SUM",
        unit="MB/s",
        group_by_fields=["resource.labels.bucket_name"],
        value_transform=lambda v: round(v / (1024.0**2), 2),  # Bytes/s to MB/s
        description="Combined GCS network data transfer throughput in Megabytes per second",
    ),
    "storage.latency_ms": MetricDefinition(
        id="storage.latency_ms",
        category="storage",
        field_name="latency_ms",
        gcp_metric_types=[
            "storage.googleapis.com/storage/v2/request_count",
            "storage.googleapis.com/storage/request_count",
        ],
        aligner="ALIGN_PERCENTILE_95",
        reducer="REDUCE_MEAN",
        unit="ms",
        group_by_fields=["resource.labels.bucket_name"],
        description="Mean request latency for object storage operations in milliseconds",
    ),
    "storage.object_count": MetricDefinition(
        id="storage.object_count",
        category="storage",
        field_name="object_count",
        gcp_metric_types=[
            "storage.googleapis.com/storage/v2/object_count",
            "storage.googleapis.com/storage/object_count",
        ],
        aligner="ALIGN_MEAN",
        reducer="REDUCE_SUM",
        unit="count",
        group_by_fields=["resource.labels.bucket_name"],
        is_daily_snapshot=True,
        description="Total object count across Cloud Storage buckets (daily snapshot)",
    ),

    # ── Processing & Analytics (BigQuery) ───────────────────────────────────
    "processing.queued_jobs": MetricDefinition(
        id="processing.queued_jobs",
        category="processing",
        field_name="queued_jobs",
        gcp_metric_types=[
            "bigquery.googleapis.com/job/num_in_flight",
            "bigquery.googleapis.com/query/num_in_flight",
        ],
        aligner="ALIGN_MEAN",
        reducer="REDUCE_SUM",
        filter_template='metric.labels.job_state="PENDING"',
        unit="count",
        description="BigQuery jobs currently queued awaiting execution slots",
    ),
    "processing.running_jobs": MetricDefinition(
        id="processing.running_jobs",
        category="processing",
        field_name="running_jobs",
        gcp_metric_types=[
            "bigquery.googleapis.com/job/num_in_flight",
            "bigquery.googleapis.com/query/num_in_flight",
        ],
        aligner="ALIGN_MEAN",
        reducer="REDUCE_SUM",
        filter_template='metric.labels.job_state="RUNNING"',
        unit="count",
        description="BigQuery queries actively executing across slot capacity pools",
    ),
    "processing.avg_processing_time_seconds": MetricDefinition(
        id="processing.avg_processing_time_seconds",
        category="processing",
        field_name="avg_processing_time_seconds",
        gcp_metric_types=[
            "bigquery.googleapis.com/query/execution_times",
        ],
        aligner="ALIGN_PERCENTILE_95",
        reducer="REDUCE_MEAN",
        unit="s",
        value_transform=lambda v: round(v / 1000.0, 2) if v > 100.0 else round(v, 2),  # ms to s
        description="P95 / average query execution duration from dispatch to completion in seconds",
    ),
    "processing.failure_counts": MetricDefinition(
        id="processing.failure_counts",
        category="processing",
        field_name="failure_counts",
        gcp_metric_types=[
            "bigquery.googleapis.com/query/execution_count",
        ],
        aligner="ALIGN_DELTA",
        reducer="REDUCE_SUM",
        filter_template='metric.labels.execution_status="FAILURE"',
        unit="count",
        description="Count of failed or timed-out BigQuery jobs within the reporting window",
    ),
    "processing.bq_scanned_bytes": MetricDefinition(
        id="processing.bq_scanned_bytes",
        category="processing",
        field_name="bq_scanned_bytes",
        gcp_metric_types=[
            "bigquery.googleapis.com/query/scanned_bytes",
            "bigquery.googleapis.com/storage/stored_bytes",
        ],
        aligner="ALIGN_RATE",
        reducer="REDUCE_SUM",
        unit="MB/s",
        value_transform=lambda v: round(v / (1024.0**2), 2),
        description="Data volume scanned by BigQuery queries in Megabytes per second",
    ),

    # ── Token Usage & LLM (Vertex AI) ───────────────────────────────────────
    "tokens.daily_token_count": MetricDefinition(
        id="tokens.daily_token_count",
        category="tokens",
        field_name="daily_token_count",
        gcp_metric_types=[
            "aiplatform.googleapis.com/publisher/online_serving/token_count",
            "aiplatform.googleapis.com/prediction/online/prediction_count",
        ],
        aligner="ALIGN_RATE",
        reducer="REDUCE_SUM",
        unit="tokens",
        description="Total tokens processed across Vertex AI publisher model endpoints in 24h",
    ),
    "tokens.weekly_token_count": MetricDefinition(
        id="tokens.weekly_token_count",
        category="tokens",
        field_name="weekly_token_count",
        gcp_metric_types=[
            "aiplatform.googleapis.com/publisher/online_serving/token_count",
            "aiplatform.googleapis.com/prediction/online/prediction_count",
        ],
        aligner="ALIGN_RATE",
        reducer="REDUCE_SUM",
        unit="tokens",
        description="Total tokens processed across Vertex AI endpoints over rolling 7 days",
    ),
    "tokens.cost_per_model": MetricDefinition(
        id="tokens.cost_per_model",
        category="tokens",
        field_name="cost_per_model",
        gcp_metric_types=[],
        unit="USD",
        requires_billing=True,
        default_available=False,
        unavailable_reason="Requires GCP Billing permissions",
        description="Estimated model inference spend grouped by model family in USD",
    ),
    "tokens.error_rate_percent": MetricDefinition(
        id="tokens.error_rate_percent",
        category="tokens",
        field_name="error_rate_percent",
        gcp_metric_types=[
            "aiplatform.googleapis.com/publisher/online_serving/error_count",
            "aiplatform.googleapis.com/prediction/online/error_count",
        ],
        aligner="ALIGN_RATE",
        reducer="REDUCE_SUM",
        unit="%",
        description="Inference API error rate percentage (0.0 to 100.0%)",
    ),
    "tokens.rate_limit_breaches": MetricDefinition(
        id="tokens.rate_limit_breaches",
        category="tokens",
        field_name="rate_limit_breaches",
        gcp_metric_types=[],  # Extracted from Cloud Logging 429 quota events
        aligner="ALIGN_DELTA",
        reducer="REDUCE_SUM",
        unit="count",
        description="Count of requests throttled due to exceeding Vertex AI quota limits",
    ),

    # ── Platform SLA & Availability ─────────────────────────────────────────
    "sla.availability_percent": MetricDefinition(
        id="sla.availability_percent",
        category="sla",
        field_name="availability_percent",
        gcp_metric_types=[
            "cloudsql.googleapis.com/database/up",
            "compute.googleapis.com/instance/uptime",
        ],
        aligner="ALIGN_MEAN",
        reducer="REDUCE_MEAN",
        unit="%",
        value_transform=lambda v: min(100.0, max(0.0, round(v * 100.0, 2) if v <= 1.0 else round(v, 2))),
        description="Rolling service availability percentage against target uptime SLA",
    ),
    "sla.error_counts_4xx_5xx": MetricDefinition(
        id="sla.error_counts_4xx_5xx",
        category="sla",
        field_name="error_counts_4xx_5xx",
        gcp_metric_types=[],  # Derived from Cloud Logging severity>=ERROR
        aligner="ALIGN_DELTA",
        reducer="REDUCE_SUM",
        unit="count",
        description="Total HTTP 4xx and 5xx client and server error responses recorded",
    ),
    "sla.peak_usage_percent": MetricDefinition(
        id="sla.peak_usage_percent",
        category="sla",
        field_name="peak_usage_percent",
        gcp_metric_types=[
            "compute.googleapis.com/instance/cpu/utilization",
            "cloudsql.googleapis.com/database/cpu/utilization",
        ],
        aligner="ALIGN_MAX",
        reducer="REDUCE_MAX",
        unit="%",
        value_transform=lambda v: min(100.0, max(0.0, round(v * 100.0, 2) if v <= 1.0 else round(v, 2))),
        description="Highest observed system resource saturation percentage in the reporting window",
    ),
    "sla.growth_trend_percent": MetricDefinition(
        id="sla.growth_trend_percent",
        category="sla",
        field_name="growth_trend_percent",
        gcp_metric_types=[
            "cloudsql.googleapis.com/database/mysql/queries",
            "compute.googleapis.com/instance/network/received_bytes_count",
        ],
        aligner="ALIGN_RATE",
        reducer="REDUCE_SUM",
        unit="%",
        description="Relative workload volume growth or contraction percentage versus comparison period",
    ),
}


def get_metric_definition(category: str, field_name: str) -> Optional[MetricDefinition]:
    """Lookup a MetricDefinition by category and schema field name."""
    key = f"{category.lower()}.{field_name.lower()}"
    return METRIC_DEFINITIONS.get(key)


def get_category_definitions(category: str) -> List[MetricDefinition]:
    """Return all metric definitions belonging to a specific category."""
    cat = category.lower()
    return [d for d in METRIC_DEFINITIONS.values() if d.category == cat]
