"""GCP Infrastructure & FinOps Dashboard - Pydantic v2 Data Schemas.

Production-grade, type-safe Pydantic v2 models covering metric categories,
historical time-series telemetry, operational filtering parameters, dynamic
threshold configurations, active alerting rules, audit logging, and RBAC contexts.

Designed specifically for Google Cloud Platform (GCP) enterprise observability
and FinOps workloads (Cloud SQL, Compute Engine, Cloud Storage, BigQuery,
Vertex AI, Pub/Sub, Memorystore).
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Union
from uuid import UUID, uuid4

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)
from typing_extensions import Self


# ============================================================================
# 1. ENUM DEFINITIONS
# ============================================================================


class Environment(str, Enum):
    """Target GCP deployment environment tier."""

    PROD = "PROD"
    STAGING = "STAGING"
    DEV = "DEV"


class TimePeriod(str, Enum):
    """Aggregation and observation time windows for metric dashboards."""

    ONE_HOUR = "1h"
    TWENTY_FOUR_HOURS = "24h"
    SEVEN_DAYS = "7d"
    THIRTY_DAYS = "30d"
    NINETY_DAYS = "90d"
    CUSTOM = "custom"


class MetricStatus(str, Enum):
    """Health classification status for an evaluated metric or resource."""

    HEALTHY = "HEALTHY"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


class AlertSeverity(str, Enum):
    """Severity classification level for threshold-triggered alert rules."""

    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


class ThresholdOperator(str, Enum):
    """Comparison operator used for evaluating thresholds against metric readings."""

    GREATER_THAN = ">"
    GREATER_THAN_OR_EQUAL = ">="
    LESS_THAN = "<"
    LESS_THAN_OR_EQUAL = "<="
    EQUAL = "=="
    NOT_EQUAL = "!="


class TrendDirection(str, Enum):
    """Trajectory direction of a time-series metric."""

    UP = "up"
    DOWN = "down"
    FLAT = "flat"


class MetricUnit(str, Enum):
    """Standardized physical and computational measurement units."""

    PERCENT = "%"
    MILLISECONDS = "ms"
    SECONDS = "s"
    MINUTES = "m"
    QPS = "queries/sec"
    COUNT = "count"
    USD = "USD"
    BYTES = "B"
    KILOBYTES = "KB"
    MEGABYTES = "MB"
    GIGABYTES = "GB"
    TERABYTES = "TB"
    MB_PER_SEC = "MB/s"
    GB_PER_SEC = "GB/s"
    IOPS = "IOPS"
    TOKENS = "tokens"
    REQUESTS = "requests"
    RATIO = "ratio"


class UserRole(str, Enum):
    """Enterprise Role-Based Access Control (RBAC) user roles."""

    INFRA_ADMIN = "INFRA_ADMIN"
    VIEW_ONLY = "VIEW_ONLY"


class Permission(str, Enum):
    """Granular platform and dashboard permissions."""

    # Observability & Read
    DASHBOARD_VIEW = "dashboard:view"
    METRICS_READ = "metrics:read"
    COST_READ = "cost:read"
    AUDIT_READ = "audit:read"
    ALERT_READ = "alert:read"

    # Governance & Operations
    THRESHOLD_WRITE = "threshold:write"
    ALERT_ACKNOWLEDGE = "alert:acknowledge"
    ALERT_RESOLVE = "alert:resolve"
    INFRA_REMEDIATE = "infra:remediate"
    CONFIG_MANAGE = "config:manage"
    RBAC_ADMIN = "rbac:admin"


class AuditActionType(str, Enum):
    """Auditable operational events and mutation categories."""

    THRESHOLD_CREATE = "THRESHOLD_CREATE"
    THRESHOLD_UPDATE = "THRESHOLD_UPDATE"
    THRESHOLD_DELETE = "THRESHOLD_DELETE"
    ALERT_TRIGGERED = "ALERT_TRIGGERED"
    ALERT_ACKNOWLEDGED = "ALERT_ACKNOWLEDGED"
    ALERT_RESOLVED = "ALERT_RESOLVED"
    CONFIG_CHANGE = "CONFIG_CHANGE"
    RBAC_ROLE_CHANGE = "RBAC_ROLE_CHANGE"
    RESOURCE_SCALED = "RESOURCE_SCALED"
    FILTER_APPLIED = "FILTER_APPLIED"


class GCPService(str, Enum):
    """GCP managed services integrated into the FinOps Observatory."""

    CLOUD_SQL = "Cloud SQL"
    COMPUTE_ENGINE = "Compute Engine"
    CLOUD_STORAGE = "Cloud Storage"
    BIGQUERY = "BigQuery"
    VERTEX_AI = "Vertex AI"
    PUB_SUB = "Pub/Sub"
    MEMORYSTORE = "Memorystore"
    GKE = "Google Kubernetes Engine"
    CLOUD_RUN = "Cloud Run"
    ALL_SERVICES = "All services"


# Default Role-Permission Mappings
DEFAULT_ROLE_PERMISSIONS: Dict[UserRole, List[Permission]] = {
    UserRole.VIEW_ONLY: [
        Permission.DASHBOARD_VIEW,
        Permission.METRICS_READ,
        Permission.COST_READ,
        Permission.AUDIT_READ,
        Permission.ALERT_READ,
    ],
    UserRole.INFRA_ADMIN: [
        Permission.DASHBOARD_VIEW,
        Permission.METRICS_READ,
        Permission.COST_READ,
        Permission.AUDIT_READ,
        Permission.ALERT_READ,
        Permission.THRESHOLD_WRITE,
        Permission.ALERT_ACKNOWLEDGE,
        Permission.ALERT_RESOLVE,
        Permission.INFRA_REMEDIATE,
        Permission.CONFIG_MANAGE,
        Permission.RBAC_ADMIN,
    ],
}


# ============================================================================
# 2. CORE TELEMETRY & TIME-SERIES PRIMITIVES
# ============================================================================


class TimeSeriesPoint(BaseModel):
    """Discrete single observation point in a temporal telemetry series."""

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        str_strip_whitespace=True,
    )

    timestamp: datetime = Field(
        ...,
        description="Observation timestamp with explicit UTC timezone awareness",
    )
    value: float = Field(
        ...,
        description="Finite numerical scalar value recorded at this timestamp",
    )

    @field_validator("timestamp", mode="before")
    @classmethod
    def ensure_utc(cls, v: Any) -> datetime:
        if isinstance(v, str):
            dt = datetime.fromisoformat(v.replace("Z", "+00:00"))
        elif isinstance(v, datetime):
            dt = v
        else:
            raise ValueError(f"Invalid timestamp format: {v}")
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)

    @field_validator("value")
    @classmethod
    def validate_finite_value(cls, v: float) -> float:
        if math.isnan(v) or math.isinf(v):
            raise ValueError("TimeSeriesPoint value must be finite (cannot be NaN or Inf).")
        return float(v)


class ResourceBreakdownItem(BaseModel):
    """Resource-level drill-down metric telemetry (e.g. per-instance or per-bucket)."""

    model_config = ConfigDict(
        populate_by_name=True,
        validate_assignment=True,
        extra="allow",
        str_strip_whitespace=True,
    )

    name: str = Field(
        ...,
        min_length=1,
        description="Target GCP resource name or identifier (e.g. 'orders-primary')",
    )
    region: Optional[str] = Field(
        default=None,
        description="GCP region or zone where the resource is deployed (e.g. 'us-central1')",
    )
    value: Union[float, str] = Field(
        ...,
        description="Resource-level metric value (numeric scalar or formatted string)",
    )
    detail: Optional[str] = Field(
        default=None,
        description="Contextual metadata (e.g., 'us-central1 · queries/sec')",
    )
    severity: Optional[AlertSeverity] = Field(
        default=None,
        description="Resource-level alert status if exceeding thresholds",
    )
    labels: Dict[str, str] = Field(
        default_factory=dict,
        description="GCP metric or resource labels identifying this resource instance",
    )
    series: List[float] = Field(
        default_factory=list,
        description="Chronological time-series values specifically for this resource",
    )


class MetricReading(BaseModel):
    """Comprehensive metric reading with current value, unit, status, and time-series telemetry.

    Supports automatic derivation of min, max, average, and trajectory trend
    when time-series points are supplied.
    """

    model_config = ConfigDict(
        populate_by_name=True,
        validate_assignment=True,
        extra="allow",
        str_strip_whitespace=True,
    )

    current_value: float = Field(
        ...,
        description="Current measured scalar value for the metric",
    )
    unit: Union[MetricUnit, str] = Field(
        ...,
        description="Standardized engineering or financial unit (e.g. '%', 'ms', 'queries/sec', 'USD')",
    )
    status: MetricStatus = Field(
        default=MetricStatus.HEALTHY,
        description="Current health evaluation status (HEALTHY, WARNING, CRITICAL)",
    )
    time_series: List[TimeSeriesPoint] = Field(
        default_factory=list,
        alias="time_series_points",
        description="Chronological time-series observation points",
    )
    change_percentage: Optional[float] = Field(
        default=None,
        description="Percentage change relative to the preceding baseline window",
    )
    trend: Optional[TrendDirection] = Field(
        default=None,
        description="Observed trend trajectory direction ('up', 'down', 'flat')",
    )
    min_value: Optional[float] = Field(
        default=None,
        description="Minimum value observed over the reporting time-series",
    )
    max_value: Optional[float] = Field(
        default=None,
        description="Maximum value observed over the reporting time-series",
    )
    avg_value: Optional[float] = Field(
        default=None,
        description="Arithmetic mean value observed over the reporting time-series",
    )
    resources: List[ResourceBreakdownItem] = Field(
        default_factory=list,
        description="Resource-level breakdown items contributing to this metric",
    )
    available: bool = Field(
        default=True,
        description="Whether this metric was successfully retrieved from real GCP infrastructure",
    )
    source: str = Field(
        default="gcp",
        description="Data provenance source: 'gcp', 'cache', 'demo', 'unavailable', 'estimated'",
    )
    reason: Optional[str] = Field(
        default=None,
        description="Human-readable explanation if metric is unavailable or estimated",
    )
    bucket_seconds: Optional[int] = Field(
        default=None,
        description="Bucket alignment period in seconds used for aggregation",
    )
    gcp_metric_types: List[str] = Field(
        default_factory=list,
        description="GCP Cloud Monitoring metric types queried for this reading",
    )
    timestamps: List[str] = Field(
        default_factory=list,
        description="Chronological ISO UTC timestamp strings matching time-series points",
    )
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Flexible auxiliary metadata (e.g. model costs, regional splits)",
    )

    @field_validator("current_value")
    @classmethod
    def validate_finite_current(cls, v: float) -> float:
        if math.isnan(v) or math.isinf(v):
            raise ValueError("current_value must be a finite numerical value.")
        return float(v)

    @field_validator("status", mode="before")
    @classmethod
    def normalize_status(cls, v: Any) -> MetricStatus:
        if isinstance(v, MetricStatus):
            return v
        if isinstance(v, str):
            clean = v.strip().upper()
            mapping = {
                "OK": MetricStatus.HEALTHY,
                "HEALTHY": MetricStatus.HEALTHY,
                "NORMAL": MetricStatus.HEALTHY,
                "NOMINAL": MetricStatus.HEALTHY,
                "WARN": MetricStatus.WARNING,
                "WARNING": MetricStatus.WARNING,
                "CRIT": MetricStatus.CRITICAL,
                "CRITICAL": MetricStatus.CRITICAL,
            }
            if clean in mapping:
                return mapping[clean]
        raise ValueError(f"Invalid metric status: '{v}'. Must be HEALTHY, WARNING, or CRITICAL.")

    @model_validator(mode="before")
    @classmethod
    def coerce_scalar_or_dict(cls, data: Any) -> Any:
        """Allows direct initialization from numeric scalars or partial dictionaries."""
        if isinstance(data, (int, float)):
            return {
                "current_value": float(data),
                "unit": "unit",
                "status": MetricStatus.HEALTHY,
            }
        return data

    @model_validator(mode="after")
    def compute_time_series_statistics(self) -> Self:
        """Derives statistical summaries and trajectory direction from time-series points."""
        if self.time_series:
            if not self.timestamps:
                self.timestamps = [p.timestamp.isoformat() for p in self.time_series]
            points = [p.value for p in self.time_series]
            if self.min_value is None:
                self.min_value = round(min(points), 4)
            if self.max_value is None:
                self.max_value = round(max(points), 4)
            if self.avg_value is None:
                self.avg_value = round(sum(points) / len(points), 4)
            if self.trend is None and len(points) >= 2:
                delta = points[-1] - points[0]
                denominator = abs(points[0]) if abs(points[0]) > 1e-6 else 1.0
                rel_change = (delta / denominator) * 100
                if rel_change > 1.0:
                    self.trend = TrendDirection.UP
                elif rel_change < -1.0:
                    self.trend = TrendDirection.DOWN
                else:
                    self.trend = TrendDirection.FLAT
        return self


# ============================================================================
# 3. BASE CATEGORY MODEL
# ============================================================================


class BaseMetricCategory(BaseModel):
    """Abstract foundational model for category-level metric collections."""

    model_config = ConfigDict(
        populate_by_name=True,
        validate_assignment=True,
        extra="forbid",
        str_strip_whitespace=True,
    )

    resource_id: Optional[str] = Field(
        default=None,
        description="GCP Resource identifier or fleet scope (e.g. 'orders-primary')",
    )
    environment: Optional[Environment] = Field(
        default=None,
        description="Deployment environment for this metric payload",
    )
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Evaluation timestamp in UTC",
    )

    @property
    def overall_status(self) -> MetricStatus:
        """Rolls up the aggregate health status across all constituent metrics.

        Priority order: CRITICAL > WARNING > HEALTHY.
        """
        statuses = [
            getattr(self, field_name).status
            for field_name, field_val in self.__dict__.items()
            if isinstance(field_val, MetricReading)
        ]
        if MetricStatus.CRITICAL in statuses:
            return MetricStatus.CRITICAL
        if MetricStatus.WARNING in statuses:
            return MetricStatus.WARNING
        return MetricStatus.HEALTHY

    def get_active_alerts(self) -> List[MetricReading]:
        """Returns all metrics within this category currently in an alert state."""
        return [
            reading
            for reading in self.__dict__.values()
            if isinstance(reading, MetricReading) and reading.status != MetricStatus.HEALTHY
        ]


# ============================================================================
# 4. CATEGORY METRIC MODELS (REQUIREMENT 1)
# ============================================================================


class DatabaseMetrics(BaseMetricCategory):
    """Database telemetry and pressure metrics for GCP Cloud SQL, Spanner, and Memorystore."""

    qps: MetricReading = Field(
        ...,
        alias="queries_per_second",
        description="Queries served per second across managed database instances",
    )
    active_connections: MetricReading = Field(
        ...,
        alias="connections",
        description="Current open client connections compared against provisioned pool capacity",
    )
    locks: MetricReading = Field(
        ...,
        alias="lock_waits",
        description="Number of database sessions actively waiting on row or table locks",
    )
    slow_queries_count: MetricReading = Field(
        ...,
        alias="slow_queries",
        description="Count of executed queries exceeding latency threshold (e.g. >500 ms)",
    )
    avg_response_time_ms: MetricReading = Field(
        ...,
        alias="response_time",
        description="Mean query execution time across all monitored database instances in milliseconds",
    )
    cpu_io_percent: MetricReading = Field(
        ...,
        alias="cpu_io",
        description="Combined compute and storage I/O utilization pressure percentage (0.0 to 100.0%)",
    )
    replication_lag_seconds: MetricReading = Field(
        ...,
        alias="replication_lag",
        description="Replication delay behind primary instance for cross-region read replicas in seconds",
    )

    @field_validator(
        "qps",
        "active_connections",
        "locks",
        "slow_queries_count",
        "avg_response_time_ms",
        "replication_lag_seconds",
    )
    @classmethod
    def validate_non_negative_metrics(cls, reading: MetricReading) -> MetricReading:
        if reading.current_value < 0:
            raise ValueError(f"Metric value cannot be negative: {reading.current_value}")
        return reading

    @field_validator("cpu_io_percent")
    @classmethod
    def validate_cpu_io_percentage(cls, reading: MetricReading) -> MetricReading:
        if not (0.0 <= reading.current_value <= 100.0):
            raise ValueError(f"cpu_io_percent must be between 0.0 and 100.0 (got {reading.current_value})")
        return reading


class CloudMetrics(BaseMetricCategory):
    """Compute fleet infrastructure utilization, FinOps spend, and availability metrics."""

    cpu_percent: MetricReading = Field(
        ...,
        alias="cpu",
        description="Average vCPU core utilization percentage across compute instances (0.0 to 100.0%)",
    )
    memory_percent: MetricReading = Field(
        ...,
        alias="memory",
        description="Working set RAM memory utilization percentage across VMs/containers (0.0 to 100.0%)",
    )
    disk_percent: MetricReading = Field(
        ...,
        alias="disk",
        description="Provisioned persistent disk capacity currently utilized percentage (0.0 to 100.0%)",
    )
    estimated_cost_usd: MetricReading = Field(
        ...,
        alias="cost",
        description="Projected cloud infrastructure charges for the active period in USD",
    )
    uptime_percent: MetricReading = Field(
        ...,
        alias="uptime",
        description="Observed service availability and uptime percentage (0.0 to 100.0%)",
    )

    @field_validator("cpu_percent", "memory_percent", "disk_percent", "uptime_percent")
    @classmethod
    def validate_percentages(cls, reading: MetricReading) -> MetricReading:
        if not (0.0 <= reading.current_value <= 100.0):
            raise ValueError(f"Percentage metric must be between 0.0 and 100.0 (got {reading.current_value})")
        return reading

    @field_validator("estimated_cost_usd")
    @classmethod
    def validate_cost_non_negative(cls, reading: MetricReading) -> MetricReading:
        if reading.current_value < 0:
            raise ValueError(f"estimated_cost_usd cannot be negative (got {reading.current_value})")
        return reading


class StorageMetrics(BaseMetricCategory):
    """Object and block storage usage, volume capacity, IOPS, throughput, and latency metrics."""

    total_usage: MetricReading = Field(
        ...,
        alias="usage",
        description="Aggregate object and persistent disk storage in use (GB or TB)",
    )
    bucket_volume_usage_percent: MetricReading = Field(
        ...,
        alias="bucket_usage",
        description="Average capacity consumed across monitored storage buckets or volumes (0.0 to 100.0%)",
    )
    iops: MetricReading = Field(
        ...,
        description="Read and write I/O operations executed per second across storage volumes",
    )
    read_write_throughput_mb_s: MetricReading = Field(
        ...,
        alias="throughput",
        description="Aggregate read/write data transfer throughput in Megabytes per second (MB/s)",
    )
    latency_ms: MetricReading = Field(
        ...,
        alias="latency",
        description="Mean request latency for object and block storage operations in milliseconds",
    )

    @field_validator("total_usage", "iops", "read_write_throughput_mb_s", "latency_ms")
    @classmethod
    def validate_non_negative(cls, reading: MetricReading) -> MetricReading:
        if reading.current_value < 0:
            raise ValueError(f"Storage metric reading cannot be negative: {reading.current_value}")
        return reading

    @field_validator("bucket_volume_usage_percent")
    @classmethod
    def validate_bucket_percentage(cls, reading: MetricReading) -> MetricReading:
        if not (0.0 <= reading.current_value <= 100.0):
            raise ValueError(
                f"bucket_volume_usage_percent must be between 0.0 and 100.0 (got {reading.current_value})"
            )
        return reading


class ProcessingMetrics(BaseMetricCategory):
    """Asynchronous job orchestration, distributed processing queues, and batch workflow telemetry."""

    queued_jobs: MetricReading = Field(
        ...,
        alias="queued",
        description="Number of jobs awaiting worker assignment in dispatch queues",
    )
    running_jobs: MetricReading = Field(
        ...,
        alias="running",
        description="Number of jobs actively executing across worker pools",
    )
    avg_processing_time_seconds: MetricReading = Field(
        ...,
        alias="processing_time",
        description="Average wall-clock execution duration from job start to completion in seconds",
    )
    failure_counts: MetricReading = Field(
        ...,
        alias="failures",
        description="Count of failed or timed-out job executions within the reporting window",
    )

    @field_validator(
        "queued_jobs",
        "running_jobs",
        "avg_processing_time_seconds",
        "failure_counts",
    )
    @classmethod
    def validate_processing_metrics(cls, reading: MetricReading) -> MetricReading:
        if reading.current_value < 0:
            raise ValueError(f"Processing metric cannot be negative: {reading.current_value}")
        return reading


class TokenUsageMetrics(BaseMetricCategory):
    """Large Language Model (LLM) inference volume, model spend, error rates, and quota telemetry."""

    daily_token_count: MetricReading = Field(
        ...,
        alias="tokens_day",
        description="Total tokens processed across managed endpoints within the last 24 hours",
    )
    weekly_token_count: MetricReading = Field(
        ...,
        alias="tokens_week",
        description="Total tokens processed across managed endpoints within the rolling 7-day period",
    )
    cost_per_model: MetricReading = Field(
        ...,
        alias="model_cost",
        description="Estimated inference spend grouped by model family (Gemini, Claude, Embeddings) in USD",
    )
    error_rate_percent: MetricReading = Field(
        ...,
        alias="error_rate",
        description="Failed inference API requests as a percentage of total requests (0.0 to 100.0%)",
    )
    rate_limit_breaches: MetricReading = Field(
        ...,
        alias="rate_limits",
        description="Number of client requests throttled due to exceeding configured quota limits",
    )

    @field_validator(
        "daily_token_count",
        "weekly_token_count",
        "cost_per_model",
        "rate_limit_breaches",
    )
    @classmethod
    def validate_non_negative_tokens(cls, reading: MetricReading) -> MetricReading:
        if reading.current_value < 0:
            raise ValueError(f"Token metric cannot be negative: {reading.current_value}")
        return reading

    @field_validator("error_rate_percent")
    @classmethod
    def validate_error_rate_percentage(cls, reading: MetricReading) -> MetricReading:
        if not (0.0 <= reading.current_value <= 100.0):
            raise ValueError(
                f"error_rate_percent must be between 0.0 and 100.0 (got {reading.current_value})"
            )
        return reading


class SlaMetrics(BaseMetricCategory):
    """Platform-level Service Level Agreement (SLA), HTTP error status counts, and capacity growth metrics."""

    availability_percent: MetricReading = Field(
        ...,
        alias="availability",
        description="Rolling service availability percentage against target uptime SLA (0.0 to 100.0%)",
    )
    error_counts_4xx_5xx: MetricReading = Field(
        ...,
        alias="errors",
        description="Total client (4xx) and server (5xx) HTTP error responses recorded in the reporting window",
    )
    peak_usage_percent: MetricReading = Field(
        ...,
        alias="peak",
        description="Highest observed system resource saturation percentage in the reporting window (0.0 to 100.0%)",
    )
    growth_trend_percent: MetricReading = Field(
        ...,
        alias="growth",
        description="Relative workload volume growth or contraction percentage versus the prior comparison period",
    )

    @field_validator("availability_percent", "peak_usage_percent")
    @classmethod
    def validate_sla_percentages(cls, reading: MetricReading) -> MetricReading:
        if not (0.0 <= reading.current_value <= 100.0):
            raise ValueError(f"SLA percentage must be between 0.0 and 100.0 (got {reading.current_value})")
        return reading

    @field_validator("error_counts_4xx_5xx")
    @classmethod
    def validate_error_counts(cls, reading: MetricReading) -> MetricReading:
        if reading.current_value < 0:
            raise ValueError(f"HTTP error counts cannot be negative: {reading.current_value}")
        return reading


# ============================================================================
# 5. SYSTEM & OPERATIONS MODELS (REQUIREMENT 2)
# ============================================================================


class DashboardFilterParams(BaseModel):
    """Interactive filtering parameters for scoping dashboard telemetry and aggregations."""

    model_config = ConfigDict(
        populate_by_name=True,
        validate_assignment=True,
        extra="forbid",
        str_strip_whitespace=True,
    )

    time_period: TimePeriod = Field(
        default=TimePeriod.TWENTY_FOUR_HOURS,
        alias="period",
        description="Temporal scope for dashboard metrics ('24h', '7d', '30d', 'custom')",
    )
    environment: Environment = Field(
        default=Environment.PROD,
        alias="env",
        description="Target deployment environment tier: PROD, STAGING, or DEV",
    )
    service: Optional[str] = Field(
        default=None,
        description="GCP Service filter (e.g., 'Cloud SQL', 'Compute Engine', 'BigQuery', 'All services')",
    )
    resource_id: Optional[str] = Field(
        default=None,
        alias="resource",
        description="Specific GCP resource identifier or name filter (e.g. 'orders-primary')",
    )
    start_time: Optional[datetime] = Field(
        default=None,
        description="Explicit UTC window start timestamp when time_period is 'custom'",
    )
    end_time: Optional[datetime] = Field(
        default=None,
        description="Explicit UTC window end timestamp when time_period is 'custom'",
    )
    bucket: Optional[str] = Field(
        default=None,
        description="Explicit alignment bucket override ('auto', '1m', '5m', '15m', '1h', '6h' or seconds)",
    )
    source: Optional[str] = Field(
        default=None,
        description="Mode override: 'demo' for mock mode, 'gcp' or omitted for live GCP mode",
    )

    @field_validator("environment", mode="before")
    @classmethod
    def normalize_environment(cls, v: Any) -> Environment:
        if isinstance(v, Environment):
            return v
        if isinstance(v, str):
            clean = v.strip().upper()
            mapping = {
                "PROD": Environment.PROD,
                "PRODUCTION": Environment.PROD,
                "STAGING": Environment.STAGING,
                "STAGE": Environment.STAGING,
                "DEV": Environment.DEV,
                "DEVELOPMENT": Environment.DEV,
            }
            if clean in mapping:
                return mapping[clean]
        raise ValueError(
            f"Invalid environment '{v}'. Expected one of: PROD, STAGING, DEV (or Production, Staging, Development)."
        )

    @field_validator("time_period", mode="before")
    @classmethod
    def normalize_time_period(cls, v: Any) -> TimePeriod:
        if isinstance(v, TimePeriod):
            return v
        if isinstance(v, str):
            clean = v.strip().lower()
            for tp in TimePeriod:
                if tp.value == clean or tp.name.lower() == clean:
                    return tp
        raise ValueError(f"Invalid time_period '{v}'. Supported values: '1h', '24h', '7d', '30d', 'custom'.")

    @model_validator(mode="after")
    def validate_date_range(self) -> Self:
        if self.time_period == TimePeriod.CUSTOM:
            if self.start_time is None or self.end_time is None:
                raise ValueError("Both start_time and end_time are required when time_period is 'custom'.")
        if self.start_time and self.end_time and self.end_time < self.start_time:
            raise ValueError(
                f"end_time ({self.end_time.isoformat()}) cannot be earlier than start_time ({self.start_time.isoformat()})."
            )
        return self


class MetricThresholdConfig(BaseModel):
    """Dynamic alert threshold definition with comparison operator and rule authoring metadata."""

    model_config = ConfigDict(
        populate_by_name=True,
        validate_assignment=True,
        extra="forbid",
        str_strip_whitespace=True,
    )

    metric_name: str = Field(
        ...,
        min_length=1,
        description="Fully-qualified metric identifier (e.g., 'database.cpu_io_percent', 'cloud.uptime_percent')",
    )
    warning_threshold: float = Field(
        ...,
        description="Numerical threshold value that triggers a WARNING state",
    )
    critical_threshold: float = Field(
        ...,
        description="Numerical threshold value that triggers a CRITICAL state",
    )
    operator: ThresholdOperator = Field(
        default=ThresholdOperator.GREATER_THAN,
        description="Comparison evaluation operator (> , >=, <, <=, ==, !=)",
    )
    custom_rule_setter_metadata: Dict[str, Any] = Field(
        default_factory=dict,
        alias="metadata",
        description="Governance metadata recorded by the rule author (e.g. author_id, runbook_url, reason)",
    )

    @field_validator("operator", mode="before")
    @classmethod
    def parse_operator(cls, v: Any) -> ThresholdOperator:
        if isinstance(v, ThresholdOperator):
            return v
        if isinstance(v, str):
            clean = v.strip().lower()
            mapping = {
                ">": ThresholdOperator.GREATER_THAN,
                "gt": ThresholdOperator.GREATER_THAN,
                ">=": ThresholdOperator.GREATER_THAN_OR_EQUAL,
                "gte": ThresholdOperator.GREATER_THAN_OR_EQUAL,
                "<": ThresholdOperator.LESS_THAN,
                "lt": ThresholdOperator.LESS_THAN,
                "<=": ThresholdOperator.LESS_THAN_OR_EQUAL,
                "lte": ThresholdOperator.LESS_THAN_OR_EQUAL,
                "==": ThresholdOperator.EQUAL,
                "=": ThresholdOperator.EQUAL,
                "eq": ThresholdOperator.EQUAL,
                "!=": ThresholdOperator.NOT_EQUAL,
                "ne": ThresholdOperator.NOT_EQUAL,
            }
            if clean in mapping:
                return mapping[clean]
            for op in ThresholdOperator:
                if op.name.lower() == clean or op.value == clean:
                    return op
        raise ValueError(f"Unsupported threshold operator: '{v}'. Supported: >, >=, <, <=, ==, !=")

    def evaluate(self, value: float) -> MetricStatus:
        """Evaluates a raw metric reading against configured warning and critical thresholds."""
        if self.operator in (ThresholdOperator.GREATER_THAN, ThresholdOperator.GREATER_THAN_OR_EQUAL):
            crit_fn = (
                (lambda v, t: v > t)
                if self.operator == ThresholdOperator.GREATER_THAN
                else (lambda v, t: v >= t)
            )
            warn_fn = crit_fn
            if self.critical_threshold >= self.warning_threshold:
                if crit_fn(value, self.critical_threshold):
                    return MetricStatus.CRITICAL
                if warn_fn(value, self.warning_threshold):
                    return MetricStatus.WARNING
            else:
                if crit_fn(value, self.critical_threshold):
                    return MetricStatus.CRITICAL
                if warn_fn(value, self.warning_threshold):
                    return MetricStatus.WARNING
            return MetricStatus.HEALTHY

        if self.operator in (ThresholdOperator.LESS_THAN, ThresholdOperator.LESS_THAN_OR_EQUAL):
            crit_fn = (
                (lambda v, t: v < t)
                if self.operator == ThresholdOperator.LESS_THAN
                else (lambda v, t: v <= t)
            )
            warn_fn = crit_fn
            if self.critical_threshold <= self.warning_threshold:
                if crit_fn(value, self.critical_threshold):
                    return MetricStatus.CRITICAL
                if warn_fn(value, self.warning_threshold):
                    return MetricStatus.WARNING
            else:
                if crit_fn(value, self.critical_threshold):
                    return MetricStatus.CRITICAL
                if warn_fn(value, self.warning_threshold):
                    return MetricStatus.WARNING
            return MetricStatus.HEALTHY

        if self.operator == ThresholdOperator.EQUAL:
            if math.isclose(value, self.critical_threshold, rel_tol=1e-5):
                return MetricStatus.CRITICAL
            if math.isclose(value, self.warning_threshold, rel_tol=1e-5):
                return MetricStatus.WARNING
            return MetricStatus.HEALTHY

        if self.operator == ThresholdOperator.NOT_EQUAL:
            if not math.isclose(value, self.critical_threshold, rel_tol=1e-5):
                return MetricStatus.CRITICAL
            if not math.isclose(value, self.warning_threshold, rel_tol=1e-5):
                return MetricStatus.WARNING
            return MetricStatus.HEALTHY

        return MetricStatus.HEALTHY


class AlertRule(BaseModel):
    """Operational alert rule instance representing an active alert condition with remediation guidance."""

    model_config = ConfigDict(
        populate_by_name=True,
        validate_assignment=True,
        extra="forbid",
        str_strip_whitespace=True,
    )

    metric_id: str = Field(
        ...,
        min_length=1,
        description="Target metric identifier triggering or associated with this alert (e.g. 'cpu-io')",
    )
    current_value: float = Field(
        ...,
        description="Current measured value that triggered the alert condition",
    )
    severity: AlertSeverity = Field(
        ...,
        description="Incident severity level: WARNING or CRITICAL",
    )
    suggested_action: str = Field(
        ...,
        min_length=1,
        description="Actionable, prescriptive remediation guidance text for site reliability/FinOps engineers",
    )
    rule_id: UUID = Field(
        default_factory=uuid4,
        description="Unique alert rule event identifier",
    )
    resource_id: Optional[str] = Field(
        default=None,
        description="Impacted GCP resource name or URI (e.g. 'orders-primary')",
    )
    triggered_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="UTC timestamp when the alert condition was triggered",
    )
    is_acknowledged: bool = Field(
        default=False,
        description="Flag indicating whether an operator has acknowledged this alert",
    )

    @field_validator("severity", mode="before")
    @classmethod
    def normalize_severity(cls, v: Any) -> AlertSeverity:
        if isinstance(v, AlertSeverity):
            return v
        if isinstance(v, str):
            clean = v.strip().upper()
            if clean in AlertSeverity.__members__:
                return AlertSeverity[clean]
        raise ValueError(f"Invalid alert severity: '{v}'. Must be WARNING or CRITICAL.")

    @field_validator("current_value")
    @classmethod
    def validate_finite_value(cls, v: float) -> float:
        if math.isnan(v) or math.isinf(v):
            raise ValueError("AlertRule current_value must be finite (not NaN or Inf).")
        return float(v)


class AuditLogEntry(BaseModel):
    """Immutable audit trail record capturing operational, governance, and threshold mutations."""

    model_config = ConfigDict(
        populate_by_name=True,
        frozen=True,
        extra="forbid",
        str_strip_whitespace=True,
    )

    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="UTC timestamp when the auditable event occurred",
    )
    user_id: str = Field(
        ...,
        min_length=1,
        description="Principal ID, service account, or user email who executed the action",
    )
    action_type: Union[AuditActionType, str] = Field(
        ...,
        description="Categorical operation type performed on the system",
    )
    targeted_metric: str = Field(
        ...,
        min_length=1,
        description="Specific metric, rule, or configuration path targeted by this operation",
    )
    previous_value: Optional[Any] = Field(
        default=None,
        description="Target entity value prior to mutation",
    )
    new_value: Optional[Any] = Field(
        default=None,
        description="Target entity value following mutation",
    )
    log_id: UUID = Field(
        default_factory=uuid4,
        description="Unique cryptographic audit event record UUID",
    )
    reason: Optional[str] = Field(
        default=None,
        description="Business justification, incident ticket reference, or change summary",
    )

    @field_validator("timestamp", mode="before")
    @classmethod
    def ensure_utc(cls, v: Any) -> datetime:
        if isinstance(v, str):
            dt = datetime.fromisoformat(v.replace("Z", "+00:00"))
        elif isinstance(v, datetime):
            dt = v
        else:
            raise ValueError(f"Invalid timestamp format: {v}")
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)


class UserRBACContext(BaseModel):
    """Role-Based Access Control context defining identity, authorization role, and permission grants."""

    model_config = ConfigDict(
        populate_by_name=True,
        validate_assignment=True,
        extra="forbid",
        str_strip_whitespace=True,
    )

    user_id: str = Field(
        ...,
        min_length=1,
        description="Unique user or service account identifier",
    )
    role: UserRole = Field(
        ...,
        description="Assigned role: INFRA_ADMIN (full management) or VIEW_ONLY (read-only telemetry)",
    )
    permissions: List[Union[Permission, str]] = Field(
        default_factory=list,
        description="Explicit granular permissions granted to this operational context",
    )
    email: Optional[str] = Field(
        default=None,
        description="User email address for notification delivery and audit tracking",
    )

    @field_validator("role", mode="before")
    @classmethod
    def normalize_role(cls, v: Any) -> UserRole:
        if isinstance(v, UserRole):
            return v
        if isinstance(v, str):
            clean = v.strip().upper().replace(" ", "_")
            if clean in UserRole.__members__:
                return UserRole[clean]
        raise ValueError(f"Invalid user role: '{v}'. Must be INFRA_ADMIN or VIEW_ONLY.")

    @model_validator(mode="after")
    def populate_default_role_permissions(self) -> Self:
        """Automatically assigns standard role permissions if not explicitly populated."""
        if not self.permissions:
            defaults = DEFAULT_ROLE_PERMISSIONS.get(self.role, [])
            self.permissions = list(defaults)
        return self

    def has_permission(self, permission: Union[Permission, str]) -> bool:
        """Determines if the active context is authorized for a specific permission."""
        perm_str = permission.value if isinstance(permission, Permission) else str(permission)
        user_perms: Set[str] = {
            p.value if isinstance(p, Permission) else str(p) for p in self.permissions
        }
        return (
            perm_str in user_perms
            or "*" in user_perms
            or (self.role == UserRole.INFRA_ADMIN)
        )

    @property
    def is_admin(self) -> bool:
        """Returns True if the active context carries INFRA_ADMIN rights."""
        return self.role == UserRole.INFRA_ADMIN


# ============================================================================
# 6. COMPOSITE DASHBOARD AGGREGATE PAYLOAD
# ============================================================================


class GcpResourceMetadata(BaseModel):
    """Catalog representation of an inventoried GCP resource."""

    model_config = ConfigDict(
        populate_by_name=True,
        validate_assignment=True,
        extra="allow",
        str_strip_whitespace=True,
    )

    name: str = Field(..., description="Unique resource name (e.g. 'orders-primary')")
    env: Environment = Field(..., description="Deployment environment tier")
    service: Union[GCPService, str] = Field(..., description="GCP managed service")
    region: str = Field(..., description="GCP Region (e.g. 'us-central1', 'europe-west1')")
    resource_type: str = Field(
        ...,
        description="Functional category: Database, Cloud, Storage, Processing, Token Usage, SLA",
    )
    labels: Dict[str, str] = Field(
        default_factory=dict,
        description="Key-value resource labels extracted from GCP time-series",
    )
    metric_count: int = Field(
        default=0,
        description="Number of metric series associated with this resource",
    )


class DashboardMetricsPayload(BaseModel):
    """Root composite model encapsulating the full GCP FinOps & Observability dashboard payload."""

    model_config = ConfigDict(
        populate_by_name=True,
        validate_assignment=True,
        extra="forbid",
        str_strip_whitespace=True,
    )

    filter_params: DashboardFilterParams = Field(
        default_factory=DashboardFilterParams,
        description="Filtering parameters applied to this telemetry payload",
    )
    database: DatabaseMetrics = Field(
        ...,
        description="Database telemetry and instance pressure metrics",
    )
    cloud: CloudMetrics = Field(
        ...,
        description="Compute fleet utilization and FinOps infrastructure cost metrics",
    )
    storage: StorageMetrics = Field(
        ...,
        description="Storage usage, throughput, IOPS, and latency metrics",
    )
    processing: ProcessingMetrics = Field(
        ...,
        description="Batch workflow and queue processing health metrics",
    )
    tokens: TokenUsageMetrics = Field(
        ...,
        description="LLM inference volume, model spend, and rate-limiting metrics",
    )
    sla: SlaMetrics = Field(
        ...,
        description="Platform availability, error counts, and workload growth metrics",
    )
    active_alerts: List[AlertRule] = Field(
        default_factory=list,
        description="Active alerts requiring engineering or FinOps team attention",
    )
    data_source: str = Field(
        default="gcp",
        description="Data provenance source ('gcp', 'cache', 'demo', 'unavailable', 'estimated')",
    )
    generated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="UTC timestamp when the payload was generated",
    )
    bucket_seconds: int = Field(
        default=60,
        description="Bucket alignment period in seconds used across telemetry series",
    )
    environment_scope: Optional[str] = Field(
        default=None,
        description="Environment scoping mechanism: 'single-project', 'project-mapped', or 'label-filtered'",
    )
    warnings: List[str] = Field(
        default_factory=list,
        description="Operational notices or degraded state reasons",
    )

    @property
    def aggregate_status(self) -> MetricStatus:
        """Computes aggregate system status across all metric categories and active alerts."""
        category_statuses = [
            self.database.overall_status,
            self.cloud.overall_status,
            self.storage.overall_status,
            self.processing.overall_status,
            self.tokens.overall_status,
            self.sla.overall_status,
        ]
        has_critical_alerts = any(a.severity == AlertSeverity.CRITICAL for a in self.active_alerts)
        if MetricStatus.CRITICAL in category_statuses or has_critical_alerts:
            return MetricStatus.CRITICAL
        has_warning_alerts = any(a.severity == AlertSeverity.WARNING for a in self.active_alerts)
        if MetricStatus.WARNING in category_statuses or has_warning_alerts:
            return MetricStatus.WARNING
        return MetricStatus.HEALTHY


# ============================================================================
# 7. SELF-TEST & VERIFICATION EXECUTION BLOCK
# ============================================================================

if __name__ == "__main__":
    from datetime import timedelta

    print("==================================================================")
    print("GCP FinOps & Observability Pydantic v2 Schemas Verification")
    print("==================================================================")

    now = datetime.now(timezone.utc)
    demo_series = [
        TimeSeriesPoint(timestamp=now - timedelta(hours=i), value=round(100.0 + (12 - i) * 3.5, 2))
        for i in range(12, -1, -1)
    ]

    # 1. Instantiate DatabaseMetrics
    db_metrics = DatabaseMetrics(
        resource_id="orders-primary",
        environment=Environment.PROD,
        qps=MetricReading(
            current_value=2418.0,
            unit=MetricUnit.QPS,
            status=MetricStatus.HEALTHY,
            time_series=demo_series,
        ),
        active_connections=MetricReading(
            current_value=684.0,
            unit=MetricUnit.COUNT,
            status=MetricStatus.WARNING,
        ),
        locks=MetricReading(
            current_value=14.0,
            unit=MetricUnit.COUNT,
            status=MetricStatus.HEALTHY,
        ),
        slow_queries_count=MetricReading(
            current_value=27.0,
            unit=MetricUnit.COUNT,
            status=MetricStatus.WARNING,
        ),
        avg_response_time_ms=MetricReading(
            current_value=42.0,
            unit=MetricUnit.MILLISECONDS,
            status=MetricStatus.HEALTHY,
        ),
        cpu_io_percent=MetricReading(
            current_value=71.0,
            unit=MetricUnit.PERCENT,
            status=MetricStatus.CRITICAL,
        ),
        replication_lag_seconds=MetricReading(
            current_value=1.8,
            unit=MetricUnit.SECONDS,
            status=MetricStatus.WARNING,
        ),
    )

    # 2. Instantiate CloudMetrics
    cloud_metrics = CloudMetrics(
        resource_id="api-workers",
        environment=Environment.PROD,
        cpu_percent=MetricReading(current_value=68.4, unit=MetricUnit.PERCENT, status=MetricStatus.WARNING),
        memory_percent=MetricReading(current_value=72.1, unit=MetricUnit.PERCENT, status=MetricStatus.WARNING),
        disk_percent=MetricReading(current_value=61.8, unit=MetricUnit.PERCENT, status=MetricStatus.WARNING),
        estimated_cost_usd=MetricReading(current_value=18426.0, unit=MetricUnit.USD, status=MetricStatus.HEALTHY),
        uptime_percent=MetricReading(current_value=99.97, unit=MetricUnit.PERCENT, status=MetricStatus.HEALTHY),
    )

    # 3. Instantiate StorageMetrics
    storage_metrics = StorageMetrics(
        resource_id="media-archive",
        environment=Environment.PROD,
        total_usage=MetricReading(current_value=428.6, unit=MetricUnit.TERABYTES, status=MetricStatus.WARNING),
        bucket_volume_usage_percent=MetricReading(current_value=74.2, unit=MetricUnit.PERCENT, status=MetricStatus.CRITICAL),
        iops=MetricReading(current_value=18400.0, unit=MetricUnit.IOPS, status=MetricStatus.HEALTHY),
        read_write_throughput_mb_s=MetricReading(current_value=2800.0, unit=MetricUnit.MB_PER_SEC, status=MetricStatus.HEALTHY),
        latency_ms=MetricReading(current_value=18.6, unit=MetricUnit.MILLISECONDS, status=MetricStatus.HEALTHY),
    )

    # 4. Instantiate ProcessingMetrics
    processing_metrics = ProcessingMetrics(
        resource_id="analytics-warehouse",
        environment=Environment.PROD,
        queued_jobs=MetricReading(current_value=1284.0, unit=MetricUnit.COUNT, status=MetricStatus.WARNING),
        running_jobs=MetricReading(current_value=342.0, unit=MetricUnit.COUNT, status=MetricStatus.HEALTHY),
        avg_processing_time_seconds=MetricReading(current_value=222.0, unit=MetricUnit.SECONDS, status=MetricStatus.HEALTHY),
        failure_counts=MetricReading(current_value=23.0, unit=MetricUnit.COUNT, status=MetricStatus.CRITICAL),
    )

    # 5. Instantiate TokenUsageMetrics
    token_metrics = TokenUsageMetrics(
        resource_id="model-inference",
        environment=Environment.PROD,
        daily_token_count=MetricReading(current_value=8420000.0, unit=MetricUnit.TOKENS, status=MetricStatus.HEALTHY),
        weekly_token_count=MetricReading(current_value=58940000.0, unit=MetricUnit.TOKENS, status=MetricStatus.HEALTHY),
        cost_per_model=MetricReading(
            current_value=1284.0,
            unit=MetricUnit.USD,
            status=MetricStatus.HEALTHY,
            metadata={"Gemini 1.5 Pro": 642.0, "Gemini Flash": 318.0, "Claude 3.5": 204.0},
        ),
        error_rate_percent=MetricReading(current_value=0.84, unit=MetricUnit.PERCENT, status=MetricStatus.WARNING),
        rate_limit_breaches=MetricReading(current_value=128.0, unit=MetricUnit.COUNT, status=MetricStatus.HEALTHY),
    )

    # 6. Instantiate SlaMetrics
    sla_metrics = SlaMetrics(
        environment=Environment.PROD,
        availability_percent=MetricReading(current_value=99.96, unit=MetricUnit.PERCENT, status=MetricStatus.HEALTHY),
        error_counts_4xx_5xx=MetricReading(current_value=1240.0, unit=MetricUnit.COUNT, status=MetricStatus.WARNING),
        peak_usage_percent=MetricReading(current_value=82.4, unit=MetricUnit.PERCENT, status=MetricStatus.CRITICAL),
        growth_trend_percent=MetricReading(current_value=12.8, unit=MetricUnit.PERCENT, status=MetricStatus.HEALTHY),
    )

    # 7. Instantiate System & Operations Models
    filters = DashboardFilterParams(
        period="24h",
        environment=Environment.PROD,
        service="Cloud SQL",
        resource_id="orders-primary",
    )

    thresh_config = MetricThresholdConfig(
        metric_name="database.cpu_io_percent",
        warning_threshold=70.0,
        critical_threshold=85.0,
        operator=ThresholdOperator.GREATER_THAN,
        custom_rule_setter_metadata={"author": "lead-data-engineer@company.com", "ticket": "FINOPS-402"},
    )

    alert_rule = AlertRule(
        metric_id="cpu-io",
        current_value=71.0,
        severity=AlertSeverity.CRITICAL,
        suggested_action="Scale database tier or optimize hot queries",
        resource_id="orders-primary",
    )

    audit_entry = AuditLogEntry(
        user_id="lead-data-engineer@company.com",
        action_type=AuditActionType.THRESHOLD_UPDATE,
        targeted_metric="database.cpu_io_percent",
        previous_value={"warning": 65.0, "critical": 80.0},
        new_value={"warning": 70.0, "critical": 85.0},
        reason="Workload peak adjustment",
    )

    admin_rbac = UserRBACContext(
        user_id="usr-infra-lead-99",
        role=UserRole.INFRA_ADMIN,
    )
    viewer_rbac = UserRBACContext(
        user_id="usr-viewer-12",
        role=UserRole.VIEW_ONLY,
    )

    # 8. Instantiate Composite Payload
    root_payload = DashboardMetricsPayload(
        filter_params=filters,
        database=db_metrics,
        cloud=cloud_metrics,
        storage=storage_metrics,
        processing=processing_metrics,
        tokens=token_metrics,
        sla=sla_metrics,
        active_alerts=[alert_rule],
    )

    print(f"✓ All 11 Pydantic v2 models validated successfully.")
    print(f"✓ Root Dashboard Status: {root_payload.aggregate_status.value}")
    print(f"✓ Threshold Evaluation (value=75.0, warn=70, crit=85): {thresh_config.evaluate(75.0).value}")
    print(f"✓ RBAC Infra Admin permission check: {admin_rbac.has_permission(Permission.INFRA_REMEDIATE)}")
    print(f"✓ RBAC View Only permission check: {viewer_rbac.has_permission(Permission.INFRA_REMEDIATE)}")
    print(f"✓ JSON serialization length: {len(root_payload.model_dump_json())} bytes.")
    print("==================================================================")
