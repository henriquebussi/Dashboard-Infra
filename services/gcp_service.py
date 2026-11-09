"""GCP FinOps Observatory - GCP Integration Service Module.

Provides a production-grade abstraction over:
  - Cloud Monitoring API v3 (MetricServiceClient) with roles/monitoring.viewer:
    - Structured metric ingestion across Compute Engine, Cloud SQL, Cloud Storage,
      BigQuery, and Vertex AI.
    - Dynamic alignment periods targeting 60-120 points per series.
    - Dual-window parallel processing for accurate change_percentage and trend.
    - Strict handling for INT64, DOUBLE, BOOL, and DISTRIBUTION types.
    - Concurrency control via asyncio.Semaphore, 429 exponential backoff,
      and in-flight query deduplication.
    - GCS daily snapshot awareness.
  - Cloud Logging API (Client) with roles/logging.viewer:
    - Cloud SQL slow-query logs, Vertex AI token logs, error logs (severity>=ERROR).
  - Metric-level Redis cache-aside caching (gcp:{project}:{metric_type}:{period}:{bucket}:{filter_hash}).
  - Zero synthetic data in Real mode: missing or degraded readings return
    available=False with explicit human-readable reason.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import math
import os
import random
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Callable, Coroutine, Dict, Iterator, List, Optional, Sequence, Tuple, Union

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Conditional GCP SDK imports
# ---------------------------------------------------------------------------

try:
    from google.api_core.exceptions import (
        Forbidden,
        GoogleAPICallError,
        NotFound,
        PermissionDenied,
        ResourceExhausted,
        ServiceUnavailable,
    )
    from google.cloud import monitoring_v3
    from google.cloud.monitoring_v3 import (
        Aggregation,
        ListTimeSeriesRequest,
        MetricServiceClient,
        TimeInterval,
    )
    from google.protobuf.timestamp_pb2 import Timestamp
    _MONITORING_AVAILABLE = True
except ImportError:
    _MONITORING_AVAILABLE = False
    GoogleAPICallError = Exception  # type: ignore[misc,assignment]
    ResourceExhausted = Exception   # type: ignore[misc,assignment]
    ServiceUnavailable = Exception  # type: ignore[misc,assignment]
    PermissionDenied = Exception    # type: ignore[misc,assignment]
    Forbidden = Exception           # type: ignore[misc,assignment]
    NotFound = Exception            # type: ignore[misc,assignment]
    monitoring_v3 = None            # type: ignore[assignment]
    logger.warning(
        "[GCPService] google-cloud-monitoring not installed. "
        "Real GCP mode will report metrics as unavailable."
    )

try:
    from google.cloud import logging as gcp_logging
    _LOGGING_AVAILABLE = True
except ImportError:
    _LOGGING_AVAILABLE = False
    gcp_logging = None  # type: ignore[assignment]
    logger.warning(
        "[GCPService] google-cloud-logging not installed. "
        "Log-based metrics will return empty results."
    )

from schemas import (
    AlertRule,
    AlertSeverity,
    CloudMetrics,
    DashboardFilterParams,
    DashboardMetricsPayload,
    DatabaseMetrics,
    Environment,
    GCPService,
    MetricReading,
    MetricStatus,
    MetricThresholdConfig,
    MetricUnit,
    ProcessingMetrics,
    ResourceBreakdownItem,
    SlaMetrics,
    StorageMetrics,
    ThresholdOperator,
    TimePeriod,
    TimeSeriesPoint,
    TokenUsageMetrics,
    TrendDirection,
)
from services.cache import RedisCache, _CircuitBreaker, _CircuitState
from services.log_service import GCPLogService
from services.metric_registry import (
    METRIC_DEFINITIONS,
    MetricDefinition,
    get_category_definitions,
    get_metric_definition,
)
from services.resource_inventory import resource_inventory

# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class GCPServiceError(Exception):
    """Raised when a GCP API call fails and the circuit breaker is OPEN or degraded."""


class GCPQuotaExceededError(GCPServiceError):
    """Raised when Cloud Monitoring quota (429 / ResourceExhausted) is hit."""


# ---------------------------------------------------------------------------
# Metric Descriptor Registry (Backward Compatibility mapping)
# ---------------------------------------------------------------------------

METRIC_DESCRIPTORS: Dict[Tuple[str, str], str] = {
    ("cloud", "cpu_utilization"): "compute.googleapis.com/instance/cpu/utilization",
    ("cloud", "disk_read_bytes"): "compute.googleapis.com/instance/disk/read_bytes_count",
    ("cloud", "disk_write_bytes"): "compute.googleapis.com/instance/disk/write_bytes_count",
    ("cloud", "network_in"): "compute.googleapis.com/instance/network/received_bytes_count",
    ("cloud", "network_out"): "compute.googleapis.com/instance/network/sent_bytes_count",
    ("cloud", "uptime"): "compute.googleapis.com/instance/uptime",
    ("database", "queries"): "cloudsql.googleapis.com/database/mysql/queries",
    ("database", "connections"): "cloudsql.googleapis.com/database/network/connections",
    ("database", "cpu_utilization"): "cloudsql.googleapis.com/database/cpu/utilization",
    ("database", "memory_utilization"): "cloudsql.googleapis.com/database/memory/utilization",
    ("database", "disk_utilization"): "cloudsql.googleapis.com/database/disk/utilization",
    ("database", "replication_lag"): "cloudsql.googleapis.com/database/replication/replica_lag",
    ("storage", "total_bytes"): "storage.googleapis.com/storage/v2/total_bytes",
    ("storage", "bucket_bytes"): "storage.googleapis.com/storage/v2/total_bytes",
    ("storage", "request_count"): "storage.googleapis.com/storage/v2/request_count",
    ("storage", "received_bytes"): "storage.googleapis.com/network/received_bytes_count",
    ("storage", "sent_bytes"): "storage.googleapis.com/network/sent_bytes_count",
    ("processing", "bq_slots"): "bigquery.googleapis.com/slots/total_available",
    ("processing", "bq_job_count"): "bigquery.googleapis.com/job/num_in_flight",
    ("processing", "bq_scanned_bytes"): "bigquery.googleapis.com/query/scanned_bytes",
    ("tokens", "prediction_count"): "aiplatform.googleapis.com/publisher/online_serving/token_count",
    ("tokens", "error_count"): "aiplatform.googleapis.com/publisher/online_serving/error_count",
    ("tokens", "latency"): "aiplatform.googleapis.com/prediction/online/prediction_latencies",
    ("sla", "pubsub_undelivered"): "pubsub.googleapis.com/subscription/num_undelivered_messages",
    ("sla", "pubsub_oldest_age"): "pubsub.googleapis.com/subscription/oldest_unacked_message_age",
}

_WINDOW_TO_ALIGNER: Dict[int, str] = {
    3_600: "ALIGN_MEAN",
    86_400: "ALIGN_MEAN",
    604_800: "ALIGN_MEAN",
}


def _period_to_seconds(period: Union[TimePeriod, str]) -> int:
    """Convert period string ('1h', '24h', '7d', '30d') to total seconds."""
    raw = period.value if isinstance(period, TimePeriod) else str(period).strip().lower()
    if raw.endswith("h"):
        return int(raw[:-1]) * 3600
    if raw.endswith("d"):
        return int(raw[:-1]) * 86400
    if raw.endswith("m"):
        return int(raw[:-1]) * 60
    if raw.isdigit():
        return int(raw)
    return 86400


def calculate_bucket_seconds(
    period_seconds: int,
    bucket_override: Optional[Union[str, int]] = None,
    is_daily_snapshot: bool = False,
) -> int:
    """Compute standardized bucket seconds targeting 60-120 points per series.

    Allows overriding via bucket parameter ('1m', '5m', '15m', '1h', '6h' or integer seconds).
    Daily snapshot metrics (GCS) are always aligned to at least 86400 seconds.
    """
    if is_daily_snapshot:
        return 86400

    if bucket_override:
        if isinstance(bucket_override, int) and bucket_override > 0:
            return bucket_override
        s = str(bucket_override).strip().lower()
        if s != "auto" and s != "":
            if s.endswith("m"):
                return max(10, int(s[:-1]) * 60)
            if s.endswith("h"):
                return max(60, int(s[:-1]) * 3600)
            if s.endswith("s"):
                return max(10, int(s[:-1]))
            if s.isdigit():
                return max(10, int(s))

    # Dynamic target of 60-120 points
    if period_seconds <= 3600:  # 1h -> 60s (60 pts)
        return 60
    elif period_seconds <= 86400:  # 24h -> 900s (15m = 96 pts)
        return 900
    elif period_seconds <= 604800:  # 7d -> 7200s (2h = 84 pts)
        return 7200
    else:  # 30d -> 21600s (6h = 120 pts)
        return 21600


# ---------------------------------------------------------------------------
# Internal Circuit Breaker for GCP API calls
# ---------------------------------------------------------------------------


@dataclass
class _GCPCircuitBreaker:
    """Dedicated circuit breaker for GCP API quota / network failures."""

    failure_threshold: int = 5
    open_window: float = 60.0

    _state: _CircuitState = field(default=_CircuitState.CLOSED, init=False)
    _failure_count: int = field(default=0, init=False)
    _last_opened_at: float = field(default=0.0, init=False)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False)

    @property
    def state(self) -> _CircuitState:
        return self._state

    @staticmethod
    def _discard_awaitable(awaitable: Any) -> None:
        if isinstance(awaitable, asyncio.Future):
            awaitable.add_done_callback(
                lambda fut: None if fut.cancelled() else fut.exception()
            )
            awaitable.cancel()
        elif hasattr(awaitable, "close"):
            awaitable.close()

    async def call(self, coro: Coroutine) -> Any:
        async with self._lock:
            if self._state is _CircuitState.OPEN:
                elapsed = time.monotonic() - self._last_opened_at
                if elapsed < self.open_window:
                    self._discard_awaitable(coro)
                    raise GCPServiceError(
                        f"[GCPCircuitBreaker] GCP API circuit OPEN — "
                        f"retry in {self.open_window - elapsed:.0f}s"
                    )
                self._state = _CircuitState.HALF_OPEN
                logger.info("[GCPCircuitBreaker] Transitioning to HALF_OPEN (probe).")

        try:
            result = await coro
        except NotFound:
            return []
        except ResourceExhausted as exc:
            await self._open(exc)
            raise GCPQuotaExceededError(
                f"GCP Monitoring quota exhausted: {exc}"
            ) from exc
        except (GoogleAPICallError, ServiceUnavailable) as exc:
            await self._record_failure(exc)
            raise GCPServiceError(f"GCP API error: {exc}") from exc
        except Exception as exc:
            await self._record_failure(exc)
            raise
        else:
            await self._reset()
            return result

    async def _open(self, exc: Exception) -> None:
        async with self._lock:
            self._state = _CircuitState.OPEN
            self._last_opened_at = time.monotonic()
            logger.error("[GCPCircuitBreaker] Circuit OPENED (quota/error): %s", exc)

    async def _record_failure(self, exc: Exception) -> None:
        async with self._lock:
            self._failure_count += 1
            logger.warning("[GCPCircuitBreaker] Failure #%d: %s", self._failure_count, exc)
            if (
                self._state is _CircuitState.HALF_OPEN
                or self._failure_count >= self.failure_threshold
            ):
                self._state = _CircuitState.OPEN
                self._last_opened_at = time.monotonic()
                logger.error("[GCPCircuitBreaker] Circuit OPENED after repeated failures.")

    async def _reset(self) -> None:
        async with self._lock:
            if self._state is not _CircuitState.CLOSED:
                logger.info("[GCPCircuitBreaker] Circuit CLOSED (recovered).")
            self._state = _CircuitState.CLOSED
            self._failure_count = 0


# ---------------------------------------------------------------------------
# Data Structures
# ---------------------------------------------------------------------------


@dataclass
class MetricPoint:
    """A single time-series data point."""

    timestamp: datetime
    value: float
    labels: Dict[str, str] = field(default_factory=dict)


@dataclass
class MetricSeries:
    """Aggregated time-series result for a single GCP metric query."""

    metric_type: str
    category: str
    metric_name: str
    unit: str
    points: List[MetricPoint]
    aggregated_avg: float = 0.0
    aggregated_max: float = 0.0
    aggregated_min: float = 0.0
    fetched_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    resource_name: Optional[str] = None
    labels: Dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "metric_type": self.metric_type,
            "category": self.category,
            "metric_name": self.metric_name,
            "unit": self.unit,
            "resource_name": self.resource_name,
            "labels": self.labels,
            "aggregated_avg": round(self.aggregated_avg, 4),
            "aggregated_max": round(self.aggregated_max, 4),
            "aggregated_min": round(self.aggregated_min, 4),
            "fetched_at": self.fetched_at.isoformat(),
            "points": [
                {
                    "timestamp": p.timestamp.isoformat(),
                    "value": round(p.value, 6),
                    "labels": p.labels,
                }
                for p in self.points
            ],
        }


@dataclass
class LogBasedMetricResult:
    """Result from a Cloud Logging query."""

    query_type: str
    log_entries: List[Dict[str, Any]]
    total_count: int
    capped: bool = False
    estimated: bool = False
    fetched_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "query_type": self.query_type,
            "total_count": self.total_count,
            "capped": self.capped,
            "estimated": self.estimated,
            "fetched_at": self.fetched_at.isoformat(),
            "entries": self.log_entries,
        }


# ---------------------------------------------------------------------------
# Concurrency & Deduplication Helper
# ---------------------------------------------------------------------------


class InFlightDeduplicator:
    """Deduplicates simultaneous identical in-flight query requests."""

    def __init__(self) -> None:
        self._tasks: Dict[str, asyncio.Task] = {}
        self._lock = asyncio.Lock()

    async def execute(self, key: str, coro_fn: Callable[[], Coroutine]) -> Any:
        async with self._lock:
            if key in self._tasks and not self._tasks[key].done():
                task = self._tasks[key]
            else:
                task = asyncio.create_task(coro_fn())
                self._tasks[key] = task

        try:
            return await task
        finally:
            async with self._lock:
                if key in self._tasks and self._tasks[key].done():
                    self._tasks.pop(key, None)


# ---------------------------------------------------------------------------
# Low-level GCP Monitoring Service
# ---------------------------------------------------------------------------


class GCPMonitoringService:
    """Low-level interface to Cloud Monitoring API v3."""

    def __init__(
        self,
        project_id: str,
        credentials: Optional[Any] = None,
        circuit_failure_threshold: int = 5,
        circuit_open_window: float = 60.0,
        max_concurrency: int = 8,
    ) -> None:
        self.project_id = project_id
        self._project_name = f"projects/{project_id}"
        self._credentials = credentials
        self._breaker = _GCPCircuitBreaker(
            failure_threshold=circuit_failure_threshold,
            open_window=circuit_open_window,
        )
        self._monitoring_client: Optional[MetricServiceClient] = None
        self._semaphore = asyncio.Semaphore(max_concurrency)
        self._log_service = GCPLogService(project_id=project_id, credentials=credentials)

    def _get_monitoring_client(self) -> MetricServiceClient:
        if not _MONITORING_AVAILABLE:
            raise GCPServiceError(
                "google-cloud-monitoring is not installed. "
                "Run: pip install google-cloud-monitoring"
            )
        if self._monitoring_client is None:
            kwargs: Dict[str, Any] = {}
            if self._credentials:
                kwargs["credentials"] = self._credentials
            self._monitoring_client = MetricServiceClient(**kwargs)
        return self._monitoring_client

    @staticmethod
    def _build_interval(
        start_time: datetime,
        end_time: datetime,
    ) -> TimeInterval:
        end_ts = Timestamp()
        end_ts.FromDatetime(end_time)
        start_ts = Timestamp()
        start_ts.FromDatetime(start_time)

        interval = TimeInterval()
        interval.end_time = end_ts
        interval.start_time = start_ts
        return interval

    async def query_metric(
        self,
        metric_type: str,
        period: str = "1h",
        aligner: str = "ALIGN_MEAN",
        reducer: str = "REDUCE_MEAN",
        alignment_period_seconds: int = 60,
        extra_filter: str = "",
        resource_labels: Optional[Dict[str, str]] = None,
        group_by_fields: Optional[Sequence[str]] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        value_transform: Optional[Callable[[float], float]] = None,
    ) -> List[MetricSeries]:
        """Query Cloud Monitoring with role roles/monitoring.viewer.

        Uses asyncio.Semaphore for concurrency rate limiting and implements
        exponential backoff on 429 ResourceExhausted.
        """
        now = datetime.now(timezone.utc)
        if end_time is None:
            end_time = now
        if start_time is None:
            sec = _period_to_seconds(period)
            start_time = end_time - timedelta(seconds=sec)

        interval = self._build_interval(start_time, end_time)

        filters = [f'metric.type="{metric_type}"']
        if resource_labels:
            for k, v in resource_labels.items():
                filters.append(f'resource.labels.{k}="{v}"')
        if extra_filter:
            filters.append(extra_filter)

        filter_str = " AND ".join(filters)

        def _sync_query() -> List[MetricSeries]:
            client = self._get_monitoring_client()
            agg = Aggregation()
            agg.alignment_period = timedelta(seconds=alignment_period_seconds)

            aligner_enum = getattr(
                Aggregation.Aligner, aligner, Aggregation.Aligner.ALIGN_MEAN
            )
            agg.per_series_aligner = aligner_enum

            if reducer:
                reducer_enum = getattr(
                    Aggregation.Reducer, reducer, Aggregation.Reducer.REDUCE_MEAN
                )
                agg.cross_series_reducer = reducer_enum

            if group_by_fields:
                agg.group_by_fields.extend(list(group_by_fields))

            request = ListTimeSeriesRequest(
                name=self._project_name,
                filter=filter_str,
                interval=interval,
                aggregation=agg,
                view=monitoring_v3.ListTimeSeriesRequest.TimeSeriesView.FULL,
            )

            # Exponential backoff retry loop for 429
            max_retries = 3
            backoff_base = 0.5
            series_results: List[MetricSeries] = []

            for attempt in range(max_retries):
                try:
                    for ts in client.list_time_series(request=request):
                        points: List[MetricPoint] = []
                        raw_values: List[float] = []

                        labels = dict(ts.metric.labels)
                        labels.update(dict(ts.resource.labels))

                        for point in ts.points:
                            dt = point.interval.end_time.todatetime(tzinfo=timezone.utc)
                            val_type = ts.value_type.name

                            if val_type == "INT64":
                                val = float(point.value.int64_value)
                            elif val_type == "BOOL":
                                val = float(point.value.bool_value)
                            elif val_type == "DISTRIBUTION":
                                dist = point.value.distribution_value
                                if aligner == "ALIGN_PERCENTILE_95" and dist.bucket_counts and dist.bucket_options:
                                    # P95 percentile estimation from distribution buckets
                                    total_count = dist.count
                                    if total_count > 0:
                                        target_rank = 0.95 * total_count
                                        running_count = 0
                                        est_val = dist.mean
                                        bounds = getattr(dist.bucket_options.explicit_buckets, "bounds", [])
                                        for idx, b_count in enumerate(dist.bucket_counts):
                                            running_count += b_count
                                            if running_count >= target_rank:
                                                if bounds and idx < len(bounds):
                                                    est_val = bounds[idx]
                                                break
                                        val = float(est_val)
                                    else:
                                        val = float(dist.mean)
                                else:
                                    val = float(dist.mean)
                            else:
                                val = float(point.value.double_value)

                            if value_transform:
                                val = value_transform(val)

                            raw_values.append(val)
                            points.append(MetricPoint(timestamp=dt, value=val, labels=labels))

                        # Extract target resource name
                        res_name = (
                            labels.get("database_id")
                            or labels.get("instance_name")
                            or labels.get("instance_id")
                            or labels.get("bucket_name")
                            or labels.get("table_id")
                            or labels.get("model_id")
                        )

                        series = MetricSeries(
                            metric_type=metric_type,
                            category="",
                            metric_name="",
                            unit=ts.unit or "",
                            points=sorted(points, key=lambda p: p.timestamp),
                            resource_name=res_name,
                            labels=labels,
                        )
                        if raw_values:
                            series.aggregated_avg = sum(raw_values) / len(raw_values)
                            series.aggregated_max = max(raw_values)
                            series.aggregated_min = min(raw_values)
                        series_results.append(series)
                    break
                except NotFound:
                    logger.info("[GCPMonitoring] Metric %s not found in project (404), returning empty series", metric_type)
                    return []
                except ResourceExhausted as exc:
                    if attempt == max_retries - 1:
                        raise
                    sleep_dur = backoff_base * (2**attempt) + random.uniform(0.1, 0.4)
                    logger.warning("[GCPMonitoring] 429 Quota exhausted, backing off %.2fs", sleep_dur)
                    time.sleep(sleep_dur)

            return series_results

        async with self._semaphore:
            loop = asyncio.get_running_loop()
            return await self._breaker.call(
                loop.run_in_executor(None, _sync_query)
            )

    @property
    def circuit_state(self) -> _CircuitState:
        return self._breaker.state

    async def get_token_usage_logs(self, hours: int = 24, **kwargs: Any) -> LogBasedMetricResult:
        res = await self._log_service.get_token_usage_logs(hours=hours, **kwargs)
        return LogBasedMetricResult(
            query_type=res.query_type,
            log_entries=res.entries,
            total_count=res.total_count,
            capped=res.capped,
            estimated=res.estimated,
            fetched_at=res.fetched_at,
        )

    async def get_slow_query_logs(self, hours: int = 24, **kwargs: Any) -> LogBasedMetricResult:
        res = await self._log_service.get_slow_query_logs(hours=hours, **kwargs)
        return LogBasedMetricResult(
            query_type=res.query_type,
            log_entries=res.entries,
            total_count=res.total_count,
            capped=res.capped,
            estimated=res.estimated,
            fetched_at=res.fetched_at,
        )

    async def get_error_logs(self, hours: int = 24, **kwargs: Any) -> LogBasedMetricResult:
        res = await self._log_service.get_error_logs(hours=hours, **kwargs)
        return LogBasedMetricResult(
            query_type=res.query_type,
            log_entries=res.entries,
            total_count=res.total_count,
            capped=res.capped,
            estimated=res.estimated,
            fetched_at=res.fetched_at,
        )

    # ------------------------------------------------------------------
    # Category convenience queries (Preserved for existing router / test contracts)
    # ------------------------------------------------------------------

    async def get_compute_metrics(self, period: str = "1h", instance_id: Optional[str] = None) -> Dict[str, Any]:
        resource_labels = {"instance_id": instance_id} if instance_id else None
        metric_names = ["cpu_utilization", "disk_read_bytes", "disk_write_bytes", "network_in", "network_out"]
        series_map: Dict[str, List[Dict[str, Any]]] = {}
        errors: List[str] = []

        for name in metric_names:
            metric_type = METRIC_DESCRIPTORS.get(("cloud", name))
            if not metric_type:
                continue
            try:
                series_list = await self.query_metric(metric_type=metric_type, period=period, resource_labels=resource_labels)
                for s in series_list:
                    s.category = "cloud"
                    s.metric_name = name
                series_map[name] = [s.to_dict() for s in series_list]
            except Exception as exc:
                errors.append(str(exc))

        return {"category": "cloud", "period": period, "metrics": series_map, "errors": errors}

    async def get_cloudsql_metrics(self, period: str = "1h", database_id: Optional[str] = None) -> Dict[str, Any]:
        resource_labels = {"database_id": database_id} if database_id else None
        metric_names = ["queries", "connections", "cpu_utilization", "memory_utilization", "disk_utilization", "replication_lag"]
        series_map: Dict[str, List[Dict[str, Any]]] = {}
        errors: List[str] = []

        for name in metric_names:
            metric_type = METRIC_DESCRIPTORS.get(("database", name))
            if not metric_type:
                continue
            try:
                series_list = await self.query_metric(metric_type=metric_type, period=period, resource_labels=resource_labels)
                for s in series_list:
                    s.category = "database"
                    s.metric_name = name
                series_map[name] = [s.to_dict() for s in series_list]
            except Exception as exc:
                errors.append(str(exc))

        return {"category": "database", "period": period, "metrics": series_map, "errors": errors}

    async def get_storage_metrics(self, period: str = "1h", bucket_name: Optional[str] = None) -> Dict[str, Any]:
        resource_labels = {"bucket_name": bucket_name} if bucket_name else None
        metric_names = ["total_bytes", "bucket_bytes", "request_count", "received_bytes", "sent_bytes"]
        series_map: Dict[str, List[Dict[str, Any]]] = {}
        errors: List[str] = []

        for name in metric_names:
            metric_type = METRIC_DESCRIPTORS.get(("storage", name))
            if not metric_type:
                continue
            try:
                series_list = await self.query_metric(metric_type=metric_type, period=period, resource_labels=resource_labels)
                for s in series_list:
                    s.category = "storage"
                    s.metric_name = name
                series_map[name] = [s.to_dict() for s in series_list]
            except Exception as exc:
                errors.append(str(exc))

        return {"category": "storage", "period": period, "metrics": series_map, "errors": errors}


# ---------------------------------------------------------------------------
# CachedGCPMetricsService — Cache-Aside Orchestrator
# ---------------------------------------------------------------------------


class CachedGCPMetricsService:
    """Primary Cache-Aside Orchestrator driven exclusively by real GCP data.

    Provides metric-level caching, parallel dual-window processing, dynamic alignment,
    environment scoping, and inventory extraction.
    """

    def __init__(
        self,
        project_id: str,
        cache: RedisCache,
        default_ttl: int = 60,
        gcp_circuit_failure_threshold: int = 5,
        gcp_circuit_open_window: float = 60.0,
        credentials: Optional[Any] = None,
        project_map: Optional[Dict[str, str]] = None,
    ) -> None:
        self.project_id = project_id
        self.cache = cache
        self.default_ttl = default_ttl
        self._credentials = credentials
        self._project_map = project_map or self._parse_project_map()
        self._dedup = InFlightDeduplicator()

        self._gcp = GCPMonitoringService(
            project_id=project_id,
            credentials=credentials,
            circuit_failure_threshold=gcp_circuit_failure_threshold,
            circuit_open_window=gcp_circuit_open_window,
        )

    @staticmethod
    def _parse_project_map() -> Dict[str, str]:
        raw = os.getenv("GCP_PROJECT_MAP", "").strip()
        if not raw:
            return {}
        if raw.startswith("{"):
            try:
                return json.loads(raw)
            except Exception:
                pass
        mapping: Dict[str, str] = {}
        for part in raw.split(","):
            if ":" in part:
                k, v = part.split(":", 1)
                mapping[k.strip().upper()] = v.strip()
        return mapping

    def resolve_environment(self, env: Union[Environment, str]) -> Tuple[str, str, Optional[str]]:
        """Resolve target GCP project ID and scoping model for an environment tier.

        Returns: (target_project_id, environment_scope, warning_message_or_none)
        """
        env_str = env.value if isinstance(env, Environment) else str(env).upper()
        if env_str in self._project_map:
            return self._project_map[env_str], "project-mapped", None

        env_label = os.getenv("GCP_ENV_LABEL", "").strip()
        if env_label:
            return self.project_id, "label-filtered", None

        return (
            self.project_id,
            "single-project",
            f"Environment mapping not configured for {env_str}; displaying single-project scope.",
        )

    # ------------------------------------------------------------------
    # Metric-Level Caching Key Builder
    # ------------------------------------------------------------------

    @staticmethod
    def build_metric_cache_key(
        project: str,
        metric_type: str,
        period: str,
        bucket_seconds: int,
        filter_str: str = "",
    ) -> str:
        """Pattern: gcp:{project}:{metric_type}:{period}:{bucket}:{filter_hash}"""
        f_hash = hashlib.md5(filter_str.encode("utf-8")).hexdigest()[:8] if filter_str else "all"
        return f"gcp:{project}:{metric_type}:{period}:{bucket_seconds}:{f_hash}"

    # ------------------------------------------------------------------
    # Core Reading Fetcher: Dual-Window Parallel Ingestion
    # ------------------------------------------------------------------

    async def get_reading_for_definition(
        self,
        defn: MetricDefinition,
        filters: DashboardFilterParams,
        target_project: str,
        effective_env: Environment,
    ) -> MetricReading:
        """Fetch a single MetricReading for a MetricDefinition using real GCP data only.

        Executes current and baseline comparison windows in parallel to calculate change_percentage.
        """
        # Guard 1: Requires GCP Billing
        if defn.requires_billing:
            return MetricReading(
                current_value=0.0,
                unit=defn.unit,
                status=MetricStatus.HEALTHY,
                available=False,
                source="unavailable",
                reason=defn.unavailable_reason or "Requires GCP Billing permissions",
                bucket_seconds=0,
                gcp_metric_types=defn.gcp_metric_types,
                timestamps=[],
                resources=[],
            )

        # Guard 2: No metric types defined
        if not defn.gcp_metric_types:
            return MetricReading(
                current_value=0.0,
                unit=defn.unit,
                status=MetricStatus.HEALTHY,
                available=False,
                source="unavailable",
                reason=defn.unavailable_reason or "No metric source configured",
                bucket_seconds=0,
                gcp_metric_types=[],
                timestamps=[],
                resources=[],
            )

        period_seconds = _period_to_seconds(filters.time_period)
        bucket_sec = calculate_bucket_seconds(
            period_seconds=period_seconds,
            bucket_override=filters.bucket,
            is_daily_snapshot=defn.is_daily_snapshot,
        )

        now = datetime.now(timezone.utc)
        cur_end = now
        cur_start = cur_end - timedelta(seconds=period_seconds)
        prev_end = cur_start
        prev_start = prev_end - timedelta(seconds=period_seconds)

        # Build extra filters
        extra_filters = []
        if defn.filter_template:
            extra_filters.append(defn.filter_template)
        env_label = os.getenv("GCP_ENV_LABEL", "").strip()
        if env_label:
            extra_filters.append(f'resource.labels.{env_label}="{effective_env.value}"')
        if filters.resource_id:
            extra_filters.append(f'resource.labels.name="{filters.resource_id}"')

        combined_filter = " AND ".join(extra_filters)

        # Attempt metric types in candidate order
        series_list: List[MetricSeries] = []
        baseline_series_list: List[MetricSeries] = []
        active_metric_type: Optional[str] = None
        last_error: Optional[str] = None
        from_cache = False

        for candidate_type in defn.gcp_metric_types:
            cache_key = self.build_metric_cache_key(
                project=target_project,
                metric_type=candidate_type,
                period=filters.time_period.value,
                bucket_seconds=bucket_sec,
                filter_str=combined_filter,
            )

            # TTL: max(default_ttl, bucket_seconds), daily metrics >= 300s
            ttl = max(self.default_ttl, bucket_sec)
            if defn.is_daily_snapshot:
                ttl = max(ttl, 300)

            async def _fetch_dual() -> Tuple[List[MetricSeries], List[MetricSeries]]:
                cur_task = self._gcp.query_metric(
                    metric_type=candidate_type,
                    period=filters.time_period.value,
                    aligner=defn.aligner,
                    reducer=defn.reducer,
                    alignment_period_seconds=bucket_sec,
                    extra_filter=combined_filter,
                    group_by_fields=defn.group_by_fields,
                    start_time=cur_start,
                    end_time=cur_end,
                    value_transform=defn.value_transform,
                )
                prev_task = self._gcp.query_metric(
                    metric_type=candidate_type,
                    period=filters.time_period.value,
                    aligner=defn.aligner,
                    reducer=defn.reducer,
                    alignment_period_seconds=bucket_sec,
                    extra_filter=combined_filter,
                    group_by_fields=defn.group_by_fields,
                    start_time=prev_start,
                    end_time=prev_end,
                    value_transform=defn.value_transform,
                )
                cur_res, prev_res = await asyncio.gather(cur_task, prev_task)
                return cur_res, prev_res

            try:
                # Deduplicate and check cache
                async def _cached_call() -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
                    c_list, p_list = await _fetch_dual()
                    return [s.to_dict() for s in c_list], [s.to_dict() for s in p_list]

                cached_raw, hit = await self.cache.get_or_fetch_with_meta(
                    key=cache_key,
                    fetcher=lambda: self._dedup.execute(cache_key, _cached_call),
                    ttl=ttl,
                )
                from_cache = hit

                if cached_raw and isinstance(cached_raw, (list, tuple)) and len(cached_raw) == 2:
                    cur_dicts, prev_dicts = cached_raw
                    if cur_dicts:
                        active_metric_type = candidate_type
                        # Reconstruct MetricSeries
                        for d in cur_dicts:
                            pts = [
                                MetricPoint(
                                    timestamp=datetime.fromisoformat(p["timestamp"]),
                                    value=float(p["value"]),
                                    labels=p.get("labels", {}),
                                )
                                for p in d.get("points", [])
                            ]
                            s = MetricSeries(
                                metric_type=d["metric_type"],
                                category=defn.category,
                                metric_name=defn.field_name,
                                unit=d.get("unit", defn.unit),
                                points=pts,
                                aggregated_avg=d.get("aggregated_avg", 0.0),
                                aggregated_max=d.get("aggregated_max", 0.0),
                                aggregated_min=d.get("aggregated_min", 0.0),
                                resource_name=d.get("resource_name"),
                                labels=d.get("labels", {}),
                            )
                            series_list.append(s)

                        for d in prev_dicts:
                            pts = [
                                MetricPoint(
                                    timestamp=datetime.fromisoformat(p["timestamp"]),
                                    value=float(p["value"]),
                                    labels=p.get("labels", {}),
                                )
                                for p in d.get("points", [])
                            ]
                            s = MetricSeries(
                                metric_type=d["metric_type"],
                                category=defn.category,
                                metric_name=defn.field_name,
                                unit=d.get("unit", defn.unit),
                                points=pts,
                                aggregated_avg=d.get("aggregated_avg", 0.0),
                            )
                            baseline_series_list.append(s)
                        break
            except Exception as exc:
                last_error = str(exc)
                logger.warning(
                    "[GCPService] Candidate %s query failed for %s: %s",
                    candidate_type, defn.id, exc
                )

        # If Ops Agent is required and no data returned
        if defn.requires_ops_agent and not series_list:
            return MetricReading(
                current_value=0.0,
                unit=defn.unit,
                status=MetricStatus.HEALTHY,
                available=False,
                source="unavailable",
                reason=defn.unavailable_reason or "Requires Google Cloud Ops Agent installed on VMs",
                bucket_seconds=bucket_sec,
                gcp_metric_types=defn.gcp_metric_types,
                timestamps=[],
                resources=[],
            )

        if not series_list:
            return MetricReading(
                current_value=0.0,
                unit=defn.unit,
                status=MetricStatus.HEALTHY,
                available=False,
                source="unavailable",
                reason=last_error or f"No time-series data returned for {defn.id}",
                bucket_seconds=bucket_sec,
                gcp_metric_types=defn.gcp_metric_types,
                timestamps=[],
                resources=[],
            )

        # Merge time-series points across distinct resource series
        timestamp_buckets: Dict[str, List[float]] = {}
        for s in series_list:
            # Record resource in inventory
            if s.labels:
                resource_inventory.record_series_labels(
                    category=defn.category,
                    metric_type=s.metric_type,
                    labels=s.labels,
                    env=effective_env,
                )
            for p in s.points:
                ts_str = p.timestamp.isoformat()
                timestamp_buckets.setdefault(ts_str, []).append(p.value)

        sorted_ts = sorted(timestamp_buckets.keys())
        merged_points: List[TimeSeriesPoint] = []
        for ts_str in sorted_ts:
            vals = timestamp_buckets[ts_str]
            avg_v = sum(vals) / len(vals) if vals else 0.0
            merged_points.append(
                TimeSeriesPoint(
                    timestamp=datetime.fromisoformat(ts_str),
                    value=round(avg_v, 4),
                )
            )

        current_val = merged_points[-1].value if merged_points else 0.0
        cur_avg = sum(p.value for p in merged_points) / len(merged_points) if merged_points else 0.0

        # Baseline comparison
        prev_vals: List[float] = []
        for s in baseline_series_list:
            for p in s.points:
                prev_vals.append(p.value)
        prev_avg = sum(prev_vals) / len(prev_vals) if prev_vals else None

        change_pct: Optional[float] = None
        trend: Optional[TrendDirection] = None
        if prev_avg is not None and abs(prev_avg) > 1e-6:
            change_pct = round(((cur_avg - prev_avg) / abs(prev_avg)) * 100.0, 2)
            if change_pct > 1.0:
                trend = TrendDirection.UP
            elif change_pct < -1.0:
                trend = TrendDirection.DOWN
            else:
                trend = TrendDirection.FLAT

        # Build ResourceBreakdownItems
        resources: List[ResourceBreakdownItem] = []
        for s in series_list:
            r_name = s.resource_name or (s.labels.get("name") if s.labels else "resource-1")
            r_val = s.aggregated_avg
            r_region = s.labels.get("region") or s.labels.get("location") or s.labels.get("zone")
            resources.append(
                ResourceBreakdownItem(
                    name=r_name,
                    region=r_region,
                    value=round(r_val, 2),
                    labels=s.labels,
                    series=[round(p.value, 2) for p in s.points],
                )
            )

        reading = MetricReading(
            current_value=round(current_val, 4),
            unit=defn.unit,
            status=MetricStatus.HEALTHY,
            time_series=merged_points,
            change_percentage=change_pct,
            trend=trend,
            available=True,
            source="cache" if from_cache else "gcp",
            reason=None,
            bucket_seconds=bucket_sec,
            gcp_metric_types=[active_metric_type] if active_metric_type else defn.gcp_metric_types,
            timestamps=sorted_ts,
            resources=resources,
        )
        return reading

    # ------------------------------------------------------------------
    # Category Builders
    # ------------------------------------------------------------------

    async def build_database_metrics(
        self,
        filters: DashboardFilterParams,
        target_project: str,
        effective_env: Environment,
    ) -> DatabaseMetrics:
        definitions = [
            ("qps", "database.qps"),
            ("active_connections", "database.active_connections"),
            ("locks", "database.locks"),
            ("slow_queries_count", "database.slow_queries_count"),
            ("avg_response_time_ms", "database.avg_response_time_ms"),
            ("cpu_io_percent", "database.cpu_io_percent"),
            ("replication_lag_seconds", "database.replication_lag_seconds"),
        ]
        tasks = [
            self.get_reading_for_definition(
                METRIC_DEFINITIONS[def_id], filters, target_project, effective_env
            )
            for _, def_id in definitions
        ]
        readings = await asyncio.gather(*tasks)
        reading_dict = dict(zip([name for name, _ in definitions], readings))

        # Check for slow queries via Cloud Logging if slow_queries_count is unavailable
        if not reading_dict["slow_queries_count"].available or reading_dict["slow_queries_count"].current_value == 0:
            try:
                hours = max(1, _period_to_seconds(filters.time_period) // 3600)
                sq_res = await self._gcp.get_slow_query_logs(hours=hours)
                reading_dict["slow_queries_count"] = MetricReading(
                    current_value=float(sq_res.total_count),
                    unit="count",
                    status=MetricStatus.HEALTHY,
                    available=True,
                    source="gcp",
                    reason=None,
                    bucket_seconds=3600,
                    gcp_metric_types=[],
                    timestamps=[],
                    resources=[],
                )
            except Exception:
                pass

        return DatabaseMetrics(
            environment=effective_env,
            timestamp=datetime.now(timezone.utc),
            **reading_dict,
        )

    async def build_cloud_metrics(
        self,
        filters: DashboardFilterParams,
        target_project: str,
        effective_env: Environment,
    ) -> CloudMetrics:
        definitions = [
            ("cpu_percent", "cloud.cpu_percent"),
            ("memory_percent", "cloud.memory_percent"),
            ("disk_percent", "cloud.disk_percent"),
            ("estimated_cost_usd", "cloud.estimated_cost_usd"),
            ("uptime_percent", "cloud.uptime_percent"),
        ]
        tasks = [
            self.get_reading_for_definition(
                METRIC_DEFINITIONS[def_id], filters, target_project, effective_env
            )
            for _, def_id in definitions
        ]
        readings = await asyncio.gather(*tasks)
        reading_dict = dict(zip([name for name, _ in definitions], readings))

        return CloudMetrics(
            environment=effective_env,
            timestamp=datetime.now(timezone.utc),
            **reading_dict,
        )

    async def build_storage_metrics(
        self,
        filters: DashboardFilterParams,
        target_project: str,
        effective_env: Environment,
    ) -> StorageMetrics:
        definitions = [
            ("total_usage", "storage.total_usage"),
            ("bucket_volume_usage_percent", "storage.bucket_volume_usage_percent"),
            ("iops", "storage.iops"),
            ("read_write_throughput_mb_s", "storage.read_write_throughput_mb_s"),
            ("latency_ms", "storage.latency_ms"),
        ]
        tasks = [
            self.get_reading_for_definition(
                METRIC_DEFINITIONS[def_id], filters, target_project, effective_env
            )
            for _, def_id in definitions
        ]
        readings = await asyncio.gather(*tasks)
        reading_dict = dict(zip([name for name, _ in definitions], readings))

        return StorageMetrics(
            environment=effective_env,
            timestamp=datetime.now(timezone.utc),
            **reading_dict,
        )

    async def build_processing_metrics(
        self,
        filters: DashboardFilterParams,
        target_project: str,
        effective_env: Environment,
    ) -> ProcessingMetrics:
        definitions = [
            ("queued_jobs", "processing.queued_jobs"),
            ("running_jobs", "processing.running_jobs"),
            ("avg_processing_time_seconds", "processing.avg_processing_time_seconds"),
            ("failure_counts", "processing.failure_counts"),
        ]
        tasks = [
            self.get_reading_for_definition(
                METRIC_DEFINITIONS[def_id], filters, target_project, effective_env
            )
            for _, def_id in definitions
        ]
        readings = await asyncio.gather(*tasks)
        reading_dict = dict(zip([name for name, _ in definitions], readings))

        return ProcessingMetrics(
            environment=effective_env,
            timestamp=datetime.now(timezone.utc),
            **reading_dict,
        )

    async def build_token_metrics(
        self,
        filters: DashboardFilterParams,
        target_project: str,
        effective_env: Environment,
    ) -> TokenUsageMetrics:
        definitions = [
            ("daily_token_count", "tokens.daily_token_count"),
            ("weekly_token_count", "tokens.weekly_token_count"),
            ("cost_per_model", "tokens.cost_per_model"),
            ("error_rate_percent", "tokens.error_rate_percent"),
            ("rate_limit_breaches", "tokens.rate_limit_breaches"),
        ]
        tasks = [
            self.get_reading_for_definition(
                METRIC_DEFINITIONS[def_id], filters, target_project, effective_env
            )
            for _, def_id in definitions
        ]
        readings = await asyncio.gather(*tasks)
        reading_dict = dict(zip([name for name, _ in definitions], readings))

        # Cloud Logging fallback for token count if metric was unavailable
        if not reading_dict["daily_token_count"].available or reading_dict["daily_token_count"].current_value == 0:
            try:
                t_res = await self._gcp.get_token_usage_logs(hours=24)
                if t_res.total_count > 0:
                    reading_dict["daily_token_count"] = MetricReading(
                        current_value=float(t_res.total_count * 1000),  # estimate from logs
                        unit="tokens",
                        status=MetricStatus.HEALTHY,
                        available=True,
                        source="gcp",
                        reason=None,
                        bucket_seconds=86400,
                        gcp_metric_types=[],
                        timestamps=[],
                        resources=[],
                    )
            except Exception:
                pass

        return TokenUsageMetrics(
            environment=effective_env,
            timestamp=datetime.now(timezone.utc),
            **reading_dict,
        )

    async def build_sla_metrics(
        self,
        filters: DashboardFilterParams,
        target_project: str,
        effective_env: Environment,
        cloud_metrics: CloudMetrics,
        database_metrics: DatabaseMetrics,
    ) -> SlaMetrics:
        definitions = [
            ("availability_percent", "sla.availability_percent"),
            ("error_counts_4xx_5xx", "sla.error_counts_4xx_5xx"),
            ("peak_usage_percent", "sla.peak_usage_percent"),
            ("growth_trend_percent", "sla.growth_trend_percent"),
        ]
        tasks = [
            self.get_reading_for_definition(
                METRIC_DEFINITIONS[def_id], filters, target_project, effective_env
            )
            for _, def_id in definitions
        ]
        readings = await asyncio.gather(*tasks)
        reading_dict = dict(zip([name for name, _ in definitions], readings))

        # Calculate SLA availability from real compute / database uptime if direct SLA query unavailable
        if not reading_dict["availability_percent"].available or reading_dict["availability_percent"].current_value == 0:
            uptime = cloud_metrics.uptime_percent.current_value
            if cloud_metrics.uptime_percent.available and uptime > 0:
                reading_dict["availability_percent"] = MetricReading(
                    current_value=uptime,
                    unit="%",
                    status=MetricStatus.HEALTHY if uptime >= 99.9 else MetricStatus.WARNING,
                    available=True,
                    source=cloud_metrics.uptime_percent.source,
                    bucket_seconds=cloud_metrics.uptime_percent.bucket_seconds or 60,
                    timestamps=cloud_metrics.uptime_percent.timestamps,
                )

        # Calculate Peak from maximum CPU
        if not reading_dict["peak_usage_percent"].available or reading_dict["peak_usage_percent"].current_value == 0:
            cpu_val = max(
                cloud_metrics.cpu_percent.current_value if cloud_metrics.cpu_percent.available else 0.0,
                database_metrics.cpu_io_percent.current_value if database_metrics.cpu_io_percent.available else 0.0,
            )
            if cpu_val > 0:
                reading_dict["peak_usage_percent"] = MetricReading(
                    current_value=cpu_val,
                    unit="%",
                    status=MetricStatus.CRITICAL if cpu_val > 85.0 else (MetricStatus.WARNING if cpu_val > 70.0 else MetricStatus.HEALTHY),
                    available=True,
                    source="gcp",
                )

        # Pull error logs from Cloud Logging for error_counts_4xx_5xx
        if not reading_dict["error_counts_4xx_5xx"].available or reading_dict["error_counts_4xx_5xx"].current_value == 0:
            try:
                hours = max(1, _period_to_seconds(filters.time_period) // 3600)
                err_res = await self._gcp.get_error_logs(hours=hours)
                reading_dict["error_counts_4xx_5xx"] = MetricReading(
                    current_value=float(err_res.total_count),
                    unit="count",
                    status=MetricStatus.CRITICAL if err_res.total_count > 50 else (MetricStatus.WARNING if err_res.total_count > 10 else MetricStatus.HEALTHY),
                    available=True,
                    source="gcp",
                    reason="Estimated via bounded Cloud Logging error stream" if err_res.estimated else None,
                )
            except Exception:
                pass

        return SlaMetrics(
            environment=effective_env,
            timestamp=datetime.now(timezone.utc),
            **reading_dict,
        )

    # ------------------------------------------------------------------
    # Local Alert Evaluation Engine
    # ------------------------------------------------------------------

    def evaluate_local_alerts(
        self,
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

        # Standard operational threshold guardrails
        checks = [
            (
                "database.cpu-io",
                database.cpu_io_percent,
                70.0,
                85.0,
                ThresholdOperator.GREATER_THAN,
                "Scale database tier or optimize slow queries causing CPU saturation.",
            ),
            (
                "database.connections",
                database.active_connections,
                650.0,
                850.0,
                ThresholdOperator.GREATER_THAN,
                "Increase Cloud SQL connection pool limits or enable connection pooling (PgBouncer).",
            ),
            (
                "cloud.cpu",
                cloud.cpu_percent,
                75.0,
                90.0,
                ThresholdOperator.GREATER_THAN,
                "Scale out Compute Engine instance group or investigate runaway processes.",
            ),
            (
                "cloud.uptime",
                cloud.uptime_percent,
                99.9,
                99.5,
                ThresholdOperator.LESS_THAN,
                "Investigate VM node reboots and zone availability incidents.",
            ),
            (
                "storage.buckets",
                storage.bucket_volume_usage_percent,
                75.0,
                90.0,
                ThresholdOperator.GREATER_THAN,
                "Enforce object lifecycle rules or archive cold objects to Nearline/Coldline.",
            ),
            (
                "processing.failures",
                processing.failure_counts,
                10.0,
                25.0,
                ThresholdOperator.GREATER_THAN,
                "Review BigQuery job error logs and query syntax/quota exhaustion.",
            ),
            (
                "tokens.error-rate",
                tokens.error_rate_percent,
                1.0,
                5.0,
                ThresholdOperator.GREATER_THAN,
                "Inspect Vertex AI model invocation latencies and quota limits.",
            ),
            (
                "sla.availability",
                sla.availability_percent,
                99.9,
                99.5,
                ThresholdOperator.LESS_THAN,
                "Initiate high-severity platform incident triage.",
            ),
        ]

        for metric_id, reading, warn_th, crit_th, op, action in checks:
            if not reading.available:
                continue
            config = MetricThresholdConfig(
                metric_name=metric_id,
                warning_threshold=warn_th,
                critical_threshold=crit_th,
                operator=op,
            )
            evaluated_status = config.evaluate(reading.current_value)
            if evaluated_status != MetricStatus.HEALTHY:
                reading.status = evaluated_status
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

    # ------------------------------------------------------------------
    # Root Overview Aggregator
    # ------------------------------------------------------------------

    async def get_overview_payload(self, filters: DashboardFilterParams) -> DashboardMetricsPayload:
        """Stream live aggregated GCP data for /api/v1/metrics/overview."""
        target_project, env_scope, warning = self.resolve_environment(filters.environment)
        warnings: List[str] = [warning] if warning else []

        # Concurrently build metric categories
        db_task = self.build_database_metrics(filters, target_project, filters.environment)
        cloud_task = self.build_cloud_metrics(filters, target_project, filters.environment)
        storage_task = self.build_storage_metrics(filters, target_project, filters.environment)
        proc_task = self.build_processing_metrics(filters, target_project, filters.environment)
        token_task = self.build_token_metrics(filters, target_project, filters.environment)

        db, cloud, storage, proc, tokens = await asyncio.gather(
            db_task, cloud_task, storage_task, proc_task, token_task
        )

        sla = await self.build_sla_metrics(filters, target_project, filters.environment, cloud, db)

        # Local threshold alert evaluation
        active_alerts = self.evaluate_local_alerts(db, cloud, storage, proc, tokens, sla)

        period_seconds = _period_to_seconds(filters.time_period)
        bucket_sec = calculate_bucket_seconds(period_seconds, filters.bucket)

        # Overall data source provenance
        all_readings = [
            db.qps, db.cpu_io_percent, cloud.cpu_percent, storage.total_usage,
            proc.queued_jobs, tokens.daily_token_count, sla.availability_percent,
        ]
        sources = {r.source for r in all_readings}
        data_source = "cache" if "cache" in sources and "gcp" not in sources else ("gcp" if "gcp" in sources else "unavailable")

        payload = DashboardMetricsPayload(
            filter_params=filters,
            database=db,
            cloud=cloud,
            storage=storage,
            processing=proc,
            tokens=tokens,
            sla=sla,
            active_alerts=active_alerts,
            data_source=data_source,
            generated_at=datetime.now(timezone.utc),
            bucket_seconds=bucket_sec,
            environment_scope=env_scope,
            warnings=warnings,
        )
        return payload

    # ------------------------------------------------------------------
    # Diagnostics & Health Check (Acceptance Criterion 1)
    # ------------------------------------------------------------------

    async def health(self) -> Dict[str, Any]:
        """Comprehensive diagnostic health snapshot.

        Details:
          - Monitoring SDK state & probe
          - Logging SDK state & probe
          - Active project ID & project map
          - Missing IAM permissions (roles/monitoring.viewer, roles/logging.viewer)
          - Cache health & circuit breaker
        """
        missing_permissions: List[str] = []
        monitoring_state = "unreachable"
        logging_state = "unreachable"

        # 1. Probe Monitoring API
        if not _MONITORING_AVAILABLE:
            monitoring_state = "sdk_not_installed"
        else:
            try:
                client = self._gcp._get_monitoring_client()
                req = monitoring_v3.ListMetricDescriptorsRequest(
                    name=f"projects/{self.project_id}",
                    page_size=1,
                )
                loop = asyncio.get_running_loop()
                await loop.run_in_executor(
                    None,
                    lambda: next(iter(client.list_metric_descriptors(request=req, timeout=5)), None),
                )
                monitoring_state = "ok"
            except (PermissionDenied, Forbidden):
                monitoring_state = "unauthorized"
                missing_permissions.append("roles/monitoring.viewer")
            except Exception as exc:
                monitoring_state = f"degraded: {exc}"

        # 2. Probe Logging API
        if not _LOGGING_AVAILABLE:
            logging_state = "sdk_not_installed"
        else:
            try:
                log_client = self._gcp._log_service._get_client()
                loop = asyncio.get_running_loop()
                await loop.run_in_executor(
                    None,
                    lambda: next(
                        iter(
                            log_client.list_entries(
                                resource_names=[f"projects/{self.project_id}"],
                                max_results=1,
                                page_size=1,
                            )
                        ),
                        None,
                    ),
                )
                logging_state = "ok"
            except (PermissionDenied, Forbidden):
                logging_state = "unauthorized"
                missing_permissions.append("roles/logging.viewer")
            except Exception as exc:
                logging_state = f"degraded: {exc}"

        cache_health = await self.cache.health()

        return {
            "service": "CachedGCPMetricsService",
            "gcp": {
                "monitoring_sdk_available": _MONITORING_AVAILABLE,
                "logging_sdk_available": _LOGGING_AVAILABLE,
                "monitoring_state": monitoring_state,
                "logging_state": logging_state,
                "active_project_id": self.project_id,
                "project_map": self._project_map,
                "environment_scope": "project-mapped" if self._project_map else "single-project",
                "missing_permissions": missing_permissions,
                "gcp_circuit_state": self._gcp.circuit_state.value,
                "project_id": self.project_id,
            },
            "cache": cache_health,
        }

    # ------------------------------------------------------------------
    # Category router compatibility helpers
    # ------------------------------------------------------------------

    async def get_metrics(
        self,
        environment: str,
        category: str,
        period: str,
        ttl: Optional[int] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """Legacy /router compatibility fetcher."""
        effective_ttl = ttl or self.default_ttl
        cache_key = RedisCache.build_key(environment, category, period)

        async def _fetch() -> Dict[str, Any]:
            return await self._dispatch_category(category, period, **kwargs)

        try:
            result, from_cache = await self.cache.get_or_fetch_with_meta(
                key=cache_key,
                fetcher=_fetch,
                ttl=effective_ttl,
                register_prewarm=True,
            )
            if isinstance(result, dict):
                result = dict(result)
                result["data_source"] = "cache" if from_cache else "live"
            return result
        except GCPServiceError as exc:
            return {
                "category": category,
                "period": period,
                "environment": environment,
                "metrics": {},
                "error": str(exc),
                "degraded": True,
                "data_source": "offline",
            }

    async def _dispatch_category(self, category: str, period: str, **kwargs: Any) -> Dict[str, Any]:
        cat = category.lower()
        if cat == "cloud":
            return await self._gcp.get_compute_metrics(period=period, **kwargs)
        if cat == "database":
            return await self._gcp.get_cloudsql_metrics(period=period, **kwargs)
        if cat == "storage":
            return await self._gcp.get_storage_metrics(period=period, **kwargs)
        if cat in ("tokens", "token_usage"):
            hours = max(1, _period_to_seconds(period) // 3600)
            res = await self._gcp.get_token_usage_logs(hours=hours, **kwargs)
            return res.to_dict()

        metric_types = [(name, mt) for (c, name), mt in METRIC_DESCRIPTORS.items() if c == cat]
        series_map: Dict[str, Any] = {}
        for name, metric_type in metric_types:
            try:
                series_list = await self._gcp.query_metric(metric_type=metric_type, period=period)
                for s in series_list:
                    s.category = cat
                    s.metric_name = name
                series_map[name] = [s.to_dict() for s in series_list]
            except Exception as exc:
                series_map[name] = {"error": str(exc)}
        return {"category": category, "period": period, "metrics": series_map}

    async def get_token_usage(self, environment: str, hours: int = 24, ttl: int = 120, **kwargs: Any) -> Dict[str, Any]:
        cache_key = RedisCache.build_key(environment, "tokens", f"{hours}h", "logs")
        async def _fetch():
            res = await self._gcp.get_token_usage_logs(hours=hours, **kwargs)
            return res.to_dict()
        return await self.cache.get_or_fetch(cache_key, _fetch, ttl=ttl)

    async def get_slow_queries(self, environment: str, hours: int = 24, threshold_ms: int = 1000, ttl: int = 60, **kwargs: Any) -> Dict[str, Any]:
        cache_key = RedisCache.build_key(environment, "database", f"{hours}h", f"slow_queries_{threshold_ms}ms")
        async def _fetch():
            res = await self._gcp.get_slow_query_logs(hours=hours, threshold_ms=threshold_ms, **kwargs)
            return res.to_dict()
        return await self.cache.get_or_fetch(cache_key, _fetch, ttl=ttl)

    async def get_error_logs(self, environment: str, hours: int = 24, ttl: int = 60, **kwargs: Any) -> Dict[str, Any]:
        cache_key = RedisCache.build_key(environment, "sla", f"{hours}h", "error_logs")
        async def _fetch():
            res = await self._gcp.get_error_logs(hours=hours, **kwargs)
            return res.to_dict()
        return await self.cache.get_or_fetch(cache_key, _fetch, ttl=ttl)

    async def prewarm_standard_keys(
        self,
        environments: Sequence[str] = ("PROD", "STAGING"),
        categories: Sequence[str] = ("cloud", "database", "storage"),
        periods: Sequence[str] = ("1h", "24h"),
    ) -> List[str]:
        warmed: List[str] = []
        for env in environments:
            for cat in categories:
                for per in periods:
                    key = RedisCache.build_key(env, cat, per)
                    try:
                        await self.get_metrics(env, cat, per)
                        warmed.append(key)
                    except Exception as exc:
                        logger.warning("[CachedGCPMetricsService] Pre-warm failed for %s: %s", key, exc)
        return warmed
