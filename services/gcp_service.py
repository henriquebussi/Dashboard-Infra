"""GCP FinOps Observatory - GCP Integration Service Module.

Provides a production-grade abstraction over:
  - Cloud Monitoring API v3 (``MetricServiceClient``) for structured metric
    time-series ingestion across Compute Engine, Cloud SQL, Cloud Storage,
    BigQuery, and Vertex AI.
  - Cloud Logging API (``logging_v2.Client``) for custom log-based metrics:
    token usage events (Vertex AI) and slow-query log entries (Cloud SQL).

Architecture:
  ``GCPMonitoringService``  — thin, circuit-breaker-protected GCP API wrapper.
  ``CachedGCPMetricsService`` — Cache-Aside orchestrator built on top,
      injecting a :class:`~services.cache.RedisCache` for all hot paths.

Metric name registry (``METRIC_DESCRIPTORS``) maps internal FinOps
category/name pairs to their canonical GCP Cloud Monitoring metric-type
strings, allowing callers to reference metrics by domain rather than by the
GCP wire format.

Circuit-breaker pattern
  Every GCP API call is wrapped in ``_CircuitBreaker`` (re-exported from
  ``services.cache``).  When the GCP Monitoring quota is exhausted or the
  network is degraded, the breaker opens and returns a ``GCPServiceError``
  instead of letting exceptions cascade into the dashboard backend.

Usage::

    from services.gcp_service import CachedGCPMetricsService
    from services.cache import RedisCache

    cache = RedisCache(url="redis://localhost:6379/0")
    await cache.connect()

    svc = CachedGCPMetricsService(
        project_id="my-gcp-project",
        cache=cache,
        default_ttl=60,
    )
    result = await svc.get_metrics("PROD", "database", "24h")
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Dict, Iterator, List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Conditional GCP SDK imports — allows the module to load in environments
# where the GCP SDK is not installed (e.g., pure CI lint/type-check runs).
# ---------------------------------------------------------------------------

try:
    from google.api_core.exceptions import (
        GoogleAPICallError,
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
    logger.warning(
        "[GCPService] google-cloud-monitoring not installed. "
        "Only mock/stub responses will be returned."
    )

try:
    from google.cloud import logging as gcp_logging
    _LOGGING_AVAILABLE = True
except ImportError:
    _LOGGING_AVAILABLE = False
    logger.warning(
        "[GCPService] google-cloud-logging not installed. "
        "Log-based metric queries will return empty results."
    )

from services.cache import RedisCache, _CircuitBreaker, _CircuitState

# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class GCPServiceError(Exception):
    """Raised when a GCP API call fails and the circuit breaker is OPEN."""


class GCPQuotaExceededError(GCPServiceError):
    """Raised when Cloud Monitoring quota (429 / ResourceExhausted) is hit."""


# ---------------------------------------------------------------------------
# Metric Descriptor Registry
# ---------------------------------------------------------------------------

#: Maps (category, metric_name) → GCP Cloud Monitoring metric-type string.
#: Extend this dict to add new GCP metrics without touching service logic.
METRIC_DESCRIPTORS: Dict[Tuple[str, str], str] = {
    # ── Compute Engine ──────────────────────────────────────────────────────
    ("cloud", "cpu_utilization"):
        "compute.googleapis.com/instance/cpu/utilization",
    ("cloud", "disk_read_bytes"):
        "compute.googleapis.com/instance/disk/read_bytes_count",
    ("cloud", "disk_write_bytes"):
        "compute.googleapis.com/instance/disk/write_bytes_count",
    ("cloud", "network_in"):
        "compute.googleapis.com/instance/network/received_bytes_count",
    ("cloud", "network_out"):
        "compute.googleapis.com/instance/network/sent_bytes_count",
    ("cloud", "uptime"):
        "compute.googleapis.com/instance/uptime",

    # ── Cloud SQL ────────────────────────────────────────────────────────────
    ("database", "queries"):
        "cloudsql.googleapis.com/database/queries",
    ("database", "connections"):
        "cloudsql.googleapis.com/database/connections",
    ("database", "cpu_utilization"):
        "cloudsql.googleapis.com/database/cpu/utilization",
    ("database", "memory_utilization"):
        "cloudsql.googleapis.com/database/memory/utilization",
    ("database", "disk_utilization"):
        "cloudsql.googleapis.com/database/disk/utilization",
    ("database", "replication_lag"):
        "cloudsql.googleapis.com/database/replication/replica_lag",

    # ── Cloud Storage ────────────────────────────────────────────────────────
    ("storage", "total_bytes"):
        "storage.googleapis.com/storage/object_count",
    ("storage", "bucket_bytes"):
        "storage.googleapis.com/storage/total_bytes",
    ("storage", "request_count"):
        "storage.googleapis.com/storage/request_count",
    ("storage", "received_bytes"):
        "storage.googleapis.com/network/received_bytes_count",
    ("storage", "sent_bytes"):
        "storage.googleapis.com/network/sent_bytes_count",

    # ── BigQuery ─────────────────────────────────────────────────────────────
    ("processing", "bq_slots"):
        "bigquery.googleapis.com/slots/total_available",
    ("processing", "bq_job_count"):
        "bigquery.googleapis.com/storage/table_count",
    ("processing", "bq_scanned_bytes"):
        "bigquery.googleapis.com/storage/stored_bytes",

    # ── Vertex AI / AI Platform ──────────────────────────────────────────────
    ("tokens", "prediction_count"):
        "aiplatform.googleapis.com/prediction/online/prediction_count",
    ("tokens", "error_count"):
        "aiplatform.googleapis.com/prediction/online/error_count",
    ("tokens", "latency"):
        "aiplatform.googleapis.com/prediction/online/prediction_latencies",

    # ── SLA / Pub·Sub proxy ──────────────────────────────────────────────────
    ("sla", "pubsub_undelivered"):
        "pubsub.googleapis.com/subscription/num_undelivered_messages",
    ("sla", "pubsub_oldest_age"):
        "pubsub.googleapis.com/subscription/oldest_unacked_message_age",
}

# ---------------------------------------------------------------------------
# Aggregation presets keyed by time-window length in seconds.
# ---------------------------------------------------------------------------

_WINDOW_TO_ALIGNER: Dict[int, str] = {
    3_600:   "ALIGN_MEAN",   # 1 h
    86_400:  "ALIGN_MEAN",   # 24 h
    604_800: "ALIGN_MEAN",   # 7 d
}


def _period_to_seconds(period: str) -> int:
    """Convert a TimePeriod-style string (``'1h'``, ``'24h'``, ``'7d'``, ``'30d'``)
    to seconds."""
    unit = period[-1].lower()
    value = int(period[:-1])
    if unit == "h":
        return value * 3_600
    if unit == "d":
        return value * 86_400
    raise ValueError(f"Unsupported period format: '{period}'. Expected e.g. '1h', '7d'.")


# ---------------------------------------------------------------------------
# Internal Circuit Breaker for GCP API calls
# ---------------------------------------------------------------------------


@dataclass
class _GCPCircuitBreaker:
    """Dedicated circuit breaker for GCP API quota / network failures."""

    failure_threshold: int = 5
    open_window: float = 60.0  # Stay OPEN for 60 s after quota exhaustion.

    _state: _CircuitState = field(default=_CircuitState.CLOSED, init=False)
    _failure_count: int = field(default=0, init=False)
    _last_opened_at: float = field(default=0.0, init=False)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False)

    @property
    def state(self) -> _CircuitState:
        return self._state

    @staticmethod
    def _discard_awaitable(awaitable: Any) -> None:
        """Dispose of an awaitable that will not be awaited.

        Callers often pass ``loop.run_in_executor(...)`` futures. If the
        circuit is open we raise before awaiting them, so their eventual
        exceptions would otherwise surface as
        ``Future exception was never retrieved`` warnings.
        """
        if isinstance(awaitable, asyncio.Future):
            awaitable.add_done_callback(
                lambda fut: None if fut.cancelled() else fut.exception()
            )
            awaitable.cancel()
        elif hasattr(awaitable, "close"):
            awaitable.close()

    async def call(self, coro) -> Any:
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
            logger.error("[GCPCircuitBreaker] Circuit OPENED (quota): %s", exc)

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
# Data structures for returned payloads
# ---------------------------------------------------------------------------


@dataclass
class MetricPoint:
    """A single time-series data point."""

    timestamp: datetime
    value: float
    labels: Dict[str, str] = field(default_factory=dict)


@dataclass
class MetricSeries:
    """Aggregated time-series result for a single GCP metric type."""

    metric_type: str
    category: str
    metric_name: str
    unit: str
    points: List[MetricPoint]
    aggregated_avg: float = 0.0
    aggregated_max: float = 0.0
    aggregated_min: float = 0.0
    fetched_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "metric_type": self.metric_type,
            "category": self.category,
            "metric_name": self.metric_name,
            "unit": self.unit,
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
    """Result from a Cloud Logging sink query (token usage or slow queries)."""

    query_type: str           # "token_usage" | "slow_queries"
    log_entries: List[Dict[str, Any]]
    total_count: int
    fetched_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "query_type": self.query_type,
            "total_count": self.total_count,
            "fetched_at": self.fetched_at.isoformat(),
            "entries": self.log_entries,
        }


# ---------------------------------------------------------------------------
# GCPMonitoringService — thin GCP API wrapper
# ---------------------------------------------------------------------------


class GCPMonitoringService:
    """Low-level GCP Cloud Monitoring API v3 interface.

    All public methods are **async** wrappers that run the synchronous
    ``MetricServiceClient`` gRPC calls in ``asyncio``'s default thread-pool
    executor, keeping the event-loop unblocked.

    Parameters
    ----------
    project_id:
        GCP project ID (e.g. ``"my-gcp-project"``).
    credentials:
        Optional explicit ``google.oauth2`` credentials object. When omitted,
        Application Default Credentials (ADC) are used.
    circuit_failure_threshold:
        Number of consecutive GCP API failures before the circuit opens.
    circuit_open_window:
        Seconds to wait before probing recovery after the circuit opens.
    """

    def __init__(
        self,
        project_id: str,
        credentials: Optional[Any] = None,
        circuit_failure_threshold: int = 5,
        circuit_open_window: float = 60.0,
    ) -> None:
        self.project_id = project_id
        self._project_name = f"projects/{project_id}"
        self._credentials = credentials
        self._breaker = _GCPCircuitBreaker(
            failure_threshold=circuit_failure_threshold,
            open_window=circuit_open_window,
        )
        self._monitoring_client: Optional[MetricServiceClient] = None
        self._logging_client: Optional[Any] = None

    # ------------------------------------------------------------------
    # Client initialisation (lazy, thread-safe via asyncio executor)
    # ------------------------------------------------------------------

    def _get_monitoring_client(self) -> "MetricServiceClient":
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

    def _get_logging_client(self) -> Any:
        if not _LOGGING_AVAILABLE:
            raise GCPServiceError(
                "google-cloud-logging is not installed. "
                "Run: pip install google-cloud-logging"
            )
        if self._logging_client is None:
            kwargs: Dict[str, Any] = {"project": self.project_id}
            if self._credentials:
                kwargs["credentials"] = self._credentials
            self._logging_client = gcp_logging.Client(**kwargs)  # type: ignore[name-defined]
        return self._logging_client

    # ------------------------------------------------------------------
    # Time-interval helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _build_interval(period_seconds: int) -> "TimeInterval":
        """Create a Cloud Monitoring ``TimeInterval`` for the past *period_seconds*."""
        end_dt = datetime.now(timezone.utc)
        start_dt = end_dt - timedelta(seconds=period_seconds)

        end_ts = Timestamp()
        end_ts.FromDatetime(end_dt)
        start_ts = Timestamp()
        start_ts.FromDatetime(start_dt)

        interval = TimeInterval()
        interval.end_time = end_ts
        interval.start_time = start_ts
        return interval

    # ------------------------------------------------------------------
    # Core query: list_time_series
    # ------------------------------------------------------------------

    async def query_metric(
        self,
        metric_type: str,
        period: str = "1h",
        aligner: str = "ALIGN_MEAN",
        alignment_period_seconds: int = 60,
        extra_filter: str = "",
        resource_labels: Optional[Dict[str, str]] = None,
    ) -> List[MetricSeries]:
        """Query a single GCP metric type and return structured time-series data.

        Parameters
        ----------
        metric_type:
            Full GCP metric type string, e.g.
            ``"compute.googleapis.com/instance/cpu/utilization"``.
        period:
            Look-back window (``'1h'``, ``'24h'``, ``'7d'``, ``'30d'``).
        aligner:
            Cloud Monitoring aligner constant (default ``ALIGN_MEAN``).
        alignment_period_seconds:
            Alignment bucket size in seconds.
        extra_filter:
            Additional Cloud Monitoring filter expression (AND-ed with the
            metric type filter).
        resource_labels:
            Optional label selector dict, e.g.
            ``{"instance_id": "my-vm-123"}``.

        Returns
        -------
        List[MetricSeries]
            One ``MetricSeries`` per distinct label-set returned by the API.
        """
        loop = asyncio.get_event_loop()
        period_seconds = _period_to_seconds(period)

        def _sync_query() -> List[MetricSeries]:
            client = self._get_monitoring_client()
            interval = self._build_interval(period_seconds)

            # Build filter string.
            filters = [f'metric.type="{metric_type}"']
            if resource_labels:
                for k, v in resource_labels.items():
                    filters.append(f'resource.labels.{k}="{v}"')
            if extra_filter:
                filters.append(extra_filter)

            # Aggregation. ``alignment_period`` is exposed as a timedelta by
            # the Monitoring client, so assign the duration directly instead
            # of mutating a (read-only) ``.seconds`` attribute.
            agg = Aggregation()
            agg.alignment_period = timedelta(seconds=alignment_period_seconds)
            agg.per_series_aligner = getattr(
                Aggregation.Aligner, aligner, Aggregation.Aligner.ALIGN_MEAN
            )
            agg.cross_series_reducer = Aggregation.Reducer.REDUCE_MEAN

            request = ListTimeSeriesRequest(
                name=self._project_name,
                filter=" AND ".join(filters),
                interval=interval,
                aggregation=agg,
                view=monitoring_v3.ListTimeSeriesRequest.TimeSeriesView.FULL,
            )

            results: List[MetricSeries] = []
            for ts in client.list_time_series(request=request):
                points = []
                raw_values: List[float] = []
                for point in ts.points:
                    dt = point.interval.end_time.todatetime(tzinfo=timezone.utc)
                    val_type = ts.value_type.name  # e.g. "DOUBLE", "INT64"
                    if val_type == "INT64":
                        val = float(point.value.int64_value)
                    elif val_type == "BOOL":
                        val = float(point.value.bool_value)
                    else:
                        val = point.value.double_value
                    raw_values.append(val)
                    labels = dict(ts.metric.labels)
                    labels.update(dict(ts.resource.labels))
                    points.append(MetricPoint(timestamp=dt, value=val, labels=labels))

                series = MetricSeries(
                    metric_type=metric_type,
                    category="",
                    metric_name="",
                    unit=ts.unit or "",
                    points=sorted(points, key=lambda p: p.timestamp),
                )
                if raw_values:
                    series.aggregated_avg = sum(raw_values) / len(raw_values)
                    series.aggregated_max = max(raw_values)
                    series.aggregated_min = min(raw_values)
                results.append(series)

            return results

        return await self._breaker.call(
            loop.run_in_executor(None, _sync_query)
        )

    # ------------------------------------------------------------------
    # Category-level convenience queries
    # ------------------------------------------------------------------

    async def get_compute_metrics(
        self,
        period: str = "1h",
        instance_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Fetch Compute Engine CPU, disk, and network metrics.

        Parameters
        ----------
        period:
            Observation window.
        instance_id:
            Optional VM instance ID filter.
        """
        resource_labels = {"instance_id": instance_id} if instance_id else None
        metric_names = [
            "cpu_utilization", "disk_read_bytes",
            "disk_write_bytes", "network_in", "network_out",
        ]
        series_map: Dict[str, List[Dict[str, Any]]] = {}
        errors: List[str] = []

        for name in metric_names:
            metric_type = METRIC_DESCRIPTORS.get(("cloud", name))
            if not metric_type:
                continue
            try:
                series_list = await self.query_metric(
                    metric_type=metric_type,
                    period=period,
                    resource_labels=resource_labels,
                )
                for s in series_list:
                    s.category = "cloud"
                    s.metric_name = name
                series_map[name] = [s.to_dict() for s in series_list]
            except (GCPServiceError, GCPQuotaExceededError) as exc:
                logger.warning("[GCPMonitoringService] compute metric '%s' failed: %s", name, exc)
                errors.append(str(exc))

        return {
            "category": "cloud",
            "period": period,
            "metrics": series_map,
            "errors": errors,
        }

    async def get_cloudsql_metrics(
        self,
        period: str = "1h",
        database_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Fetch Cloud SQL query rate, connections, and resource metrics."""
        resource_labels = {"database_id": database_id} if database_id else None
        metric_names = [
            "queries", "connections", "cpu_utilization",
            "memory_utilization", "disk_utilization", "replication_lag",
        ]
        series_map: Dict[str, List[Dict[str, Any]]] = {}
        errors: List[str] = []

        for name in metric_names:
            metric_type = METRIC_DESCRIPTORS.get(("database", name))
            if not metric_type:
                continue
            try:
                series_list = await self.query_metric(
                    metric_type=metric_type,
                    period=period,
                    resource_labels=resource_labels,
                )
                for s in series_list:
                    s.category = "database"
                    s.metric_name = name
                series_map[name] = [s.to_dict() for s in series_list]
            except (GCPServiceError, GCPQuotaExceededError) as exc:
                logger.warning("[GCPMonitoringService] cloudsql metric '%s' failed: %s", name, exc)
                errors.append(str(exc))

        return {
            "category": "database",
            "period": period,
            "metrics": series_map,
            "errors": errors,
        }

    async def get_storage_metrics(
        self,
        period: str = "1h",
        bucket_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Fetch Cloud Storage byte counts and request-rate metrics."""
        resource_labels = {"bucket_name": bucket_name} if bucket_name else None
        metric_names = ["total_bytes", "bucket_bytes", "request_count",
                        "received_bytes", "sent_bytes"]
        series_map: Dict[str, List[Dict[str, Any]]] = {}
        errors: List[str] = []

        for name in metric_names:
            metric_type = METRIC_DESCRIPTORS.get(("storage", name))
            if not metric_type:
                continue
            try:
                series_list = await self.query_metric(
                    metric_type=metric_type,
                    period=period,
                    resource_labels=resource_labels,
                )
                for s in series_list:
                    s.category = "storage"
                    s.metric_name = name
                series_map[name] = [s.to_dict() for s in series_list]
            except (GCPServiceError, GCPQuotaExceededError) as exc:
                logger.warning("[GCPMonitoringService] storage metric '%s' failed: %s", name, exc)
                errors.append(str(exc))

        return {
            "category": "storage",
            "period": period,
            "metrics": series_map,
            "errors": errors,
        }

    # ------------------------------------------------------------------
    # Special Handler: Token Usage via Cloud Logging
    # ------------------------------------------------------------------

    async def get_token_usage_logs(
        self,
        hours: int = 24,
        log_filter: Optional[str] = None,
        max_entries: int = 500,
    ) -> LogBasedMetricResult:
        """Pull Vertex AI token-usage events from Cloud Logging sinks.

        The default filter targets ``aiplatform.googleapis.com`` log entries
        that contain token-count payload fields (``inputTokenCount``,
        ``outputTokenCount``).  Pass a custom *log_filter* to override.

        Parameters
        ----------
        hours:
            Look-back window in hours.
        log_filter:
            Custom Cloud Logging advanced filter. Overrides the default
            Vertex AI token-event filter.
        max_entries:
            Maximum log entries to return (pagination hard-stop).
        """
        loop = asyncio.get_event_loop()
        start_dt = datetime.now(timezone.utc) - timedelta(hours=hours)
        ts_str = start_dt.strftime("%Y-%m-%dT%H:%M:%SZ")

        default_filter = (
            'resource.type="aiplatform.googleapis.com/Endpoint" '
            f'AND timestamp>="{ts_str}" '
            'AND jsonPayload.tokenCount.inputTokenCount>0'
        )
        active_filter = log_filter or default_filter

        def _sync_query() -> LogBasedMetricResult:
            client = self._get_logging_client()
            entries: List[Dict[str, Any]] = []
            for entry in client.list_entries(
                filter_=active_filter,
                order_by=gcp_logging.DESCENDING,  # type: ignore[attr-defined]
                max_results=max_entries,
            ):
                payload = {}
                if hasattr(entry, "payload") and isinstance(entry.payload, dict):
                    payload = entry.payload
                entries.append(
                    {
                        "timestamp": entry.timestamp.isoformat()
                        if entry.timestamp
                        else None,
                        "severity": str(entry.severity),
                        "resource_type": entry.resource.type
                        if entry.resource
                        else None,
                        "labels": dict(entry.labels or {}),
                        "payload": payload,
                    }
                )
            return LogBasedMetricResult(
                query_type="token_usage",
                log_entries=entries,
                total_count=len(entries),
            )

        try:
            return await self._breaker.call(
                loop.run_in_executor(None, _sync_query)
            )
        except GCPServiceError:
            raise
        except Exception as exc:
            logger.error("[GCPMonitoringService] token_usage log query failed: %s", exc)
            raise GCPServiceError(f"Token usage log query failed: {exc}") from exc

    # ------------------------------------------------------------------
    # Special Handler: Slow Queries via Cloud Logging
    # ------------------------------------------------------------------

    async def get_slow_query_logs(
        self,
        hours: int = 24,
        threshold_ms: int = 1000,
        database_id: Optional[str] = None,
        max_entries: int = 200,
    ) -> LogBasedMetricResult:
        """Pull Cloud SQL slow-query log entries from Cloud Logging.

        Requires that Cloud SQL slow-query logging is enabled on the instance
        (``log_min_duration_statement`` or equivalent).

        Parameters
        ----------
        hours:
            Look-back window in hours.
        threshold_ms:
            Minimum query duration in milliseconds to include.
        database_id:
            Optional Cloud SQL instance ID label filter.
        max_entries:
            Maximum entries returned.
        """
        loop = asyncio.get_event_loop()
        start_dt = datetime.now(timezone.utc) - timedelta(hours=hours)
        ts_str = start_dt.strftime("%Y-%m-%dT%H:%M:%SZ")

        filters = [
            'resource.type="cloudsql_database"',
            f'timestamp>="{ts_str}"',
            'textPayload:"duration:"',  # PostgreSQL slow query pattern
        ]
        if database_id:
            filters.append(f'resource.labels.database_id="{database_id}"')

        active_filter = " AND ".join(filters)

        def _sync_query() -> LogBasedMetricResult:
            client = self._get_logging_client()
            entries: List[Dict[str, Any]] = []
            for entry in client.list_entries(
                filter_=active_filter,
                order_by=gcp_logging.DESCENDING,  # type: ignore[attr-defined]
                max_results=max_entries,
            ):
                # Basic parsing of ``duration: N.NNN ms`` from textPayload.
                duration_ms: Optional[float] = None
                text = getattr(entry, "payload", "") or ""
                if isinstance(text, str) and "duration:" in text:
                    try:
                        after = text.split("duration:")[1].strip()
                        duration_ms = float(after.split()[0])
                    except (IndexError, ValueError):
                        pass

                if duration_ms is not None and duration_ms < threshold_ms:
                    continue  # Exclude fast queries below threshold.

                entries.append(
                    {
                        "timestamp": entry.timestamp.isoformat()
                        if entry.timestamp
                        else None,
                        "severity": str(entry.severity),
                        "database_id": database_id,
                        "duration_ms": duration_ms,
                        "query_text": text[:500],  # Truncate for safety.
                        "labels": dict(entry.labels or {}),
                    }
                )

            return LogBasedMetricResult(
                query_type="slow_queries",
                log_entries=entries,
                total_count=len(entries),
            )

        try:
            return await self._breaker.call(
                loop.run_in_executor(None, _sync_query)
            )
        except GCPServiceError:
            raise
        except Exception as exc:
            logger.error("[GCPMonitoringService] slow_query log query failed: %s", exc)
            raise GCPServiceError(f"Slow query log query failed: {exc}") from exc

    # ------------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------------

    @property
    def circuit_state(self) -> _CircuitState:
        """Current circuit-breaker state for GCP API calls."""
        return self._breaker.state

    async def health(self) -> Dict[str, Any]:
        """Return GCP service health snapshot."""
        return {
            "monitoring_sdk_available": _MONITORING_AVAILABLE,
            "logging_sdk_available": _LOGGING_AVAILABLE,
            "gcp_circuit_state": self._breaker.state.value,
            "project_id": self.project_id,
        }


# ---------------------------------------------------------------------------
# CachedGCPMetricsService — Cache-Aside orchestrator
# ---------------------------------------------------------------------------


class CachedGCPMetricsService:
    """Cache-Aside orchestrator combining :class:`GCPMonitoringService` with
    :class:`~services.cache.RedisCache`.

    This is the **primary interface** for the FinOps dashboard backend.  It
    intercepts every GCP metric request, checks Redis first, and only reaches
    out to the Cloud Monitoring API on cache miss.  Fetched results are stored
    in Redis for *ttl* seconds and the keys are registered for background
    pre-warming to maintain sub-2-second SLA.

    Parameters
    ----------
    project_id:
        GCP project identifier.
    cache:
        Initialised :class:`~services.cache.RedisCache` instance.
    default_ttl:
        Default Redis TTL in seconds (default 60).
    gcp_circuit_failure_threshold:
        Failures before the GCP circuit breaker opens.
    gcp_circuit_open_window:
        Seconds the GCP circuit remains open.
    credentials:
        Optional explicit GCP credentials.
    """

    def __init__(
        self,
        project_id: str,
        cache: RedisCache,
        default_ttl: int = 60,
        gcp_circuit_failure_threshold: int = 5,
        gcp_circuit_open_window: float = 60.0,
        credentials: Optional[Any] = None,
    ) -> None:
        self.project_id = project_id
        self.cache = cache
        self.default_ttl = default_ttl

        self._gcp = GCPMonitoringService(
            project_id=project_id,
            credentials=credentials,
            circuit_failure_threshold=gcp_circuit_failure_threshold,
            circuit_open_window=gcp_circuit_open_window,
        )

    # ------------------------------------------------------------------
    # Generic metric retrieval
    # ------------------------------------------------------------------

    async def get_metrics(
        self,
        environment: str,
        category: str,
        period: str,
        ttl: Optional[int] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """Return metrics for *category* + *period*, serving from cache when hot.

        Parameters
        ----------
        environment:
            Deployment tier (``"PROD"``, ``"STAGING"``, ``"DEV"``).
        category:
            Metric category (``"cloud"``, ``"database"``, ``"storage"``,
            ``"processing"``, ``"tokens"``, ``"sla"``).
        period:
            Observation window (``"1h"``, ``"24h"``, ``"7d"``, ``"30d"``).
        ttl:
            Redis TTL override in seconds.
        **kwargs:
            Forwarded to the underlying category-specific fetcher
            (e.g. ``instance_id``, ``database_id``, ``bucket_name``).
        """
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
            logger.error(
                "[CachedGCPMetricsService] GCP API error for '%s/%s/%s': %s",
                environment, category, period, exc,
            )
            # Return a graceful degraded payload instead of a 500.
            return {
                "category": category,
                "period": period,
                "environment": environment,
                "metrics": {},
                "error": str(exc),
                "degraded": True,
                "data_source": "offline",
            }

    async def _dispatch_category(
        self,
        category: str,
        period: str,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """Route a category request to the appropriate GCP fetcher."""
        cat = category.lower()
        if cat == "cloud":
            return await self._gcp.get_compute_metrics(period=period, **kwargs)
        if cat == "database":
            return await self._gcp.get_cloudsql_metrics(period=period, **kwargs)
        if cat == "storage":
            return await self._gcp.get_storage_metrics(period=period, **kwargs)
        if cat in ("tokens", "token_usage"):
            hours = _period_to_seconds(period) // 3600
            result = await self._gcp.get_token_usage_logs(hours=hours, **kwargs)
            return result.to_dict()
        # processing / sla: compose from individual metrics
        metric_types = [
            (name, mt)
            for (c, name), mt in METRIC_DESCRIPTORS.items()
            if c == cat
        ]
        if not metric_types:
            raise ValueError(
                f"Unknown metric category '{category}'. "
                f"Supported: cloud, database, storage, tokens, processing, sla."
            )
        series_map: Dict[str, Any] = {}
        for name, metric_type in metric_types:
            try:
                series_list = await self._gcp.query_metric(
                    metric_type=metric_type, period=period
                )
                for s in series_list:
                    s.category = cat
                    s.metric_name = name
                series_map[name] = [s.to_dict() for s in series_list]
            except (GCPServiceError, GCPQuotaExceededError) as exc:
                logger.warning(
                    "[CachedGCPMetricsService] '%s/%s' failed: %s", cat, name, exc
                )
                series_map[name] = {"error": str(exc)}
        return {"category": category, "period": period, "metrics": series_map}

    # ------------------------------------------------------------------
    # Convenience wrappers (passthrough + cache)
    # ------------------------------------------------------------------

    async def get_token_usage(
        self,
        environment: str,
        hours: int = 24,
        ttl: int = 120,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """Cached token-usage log query."""
        cache_key = RedisCache.build_key(environment, "tokens", f"{hours}h", "logs")

        async def _fetch() -> Dict[str, Any]:
            result = await self._gcp.get_token_usage_logs(hours=hours, **kwargs)
            return result.to_dict()

        return await self.cache.get_or_fetch(cache_key, _fetch, ttl=ttl)

    async def get_slow_queries(
        self,
        environment: str,
        hours: int = 24,
        threshold_ms: int = 1000,
        ttl: int = 60,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """Cached slow-query log query."""
        cache_key = RedisCache.build_key(
            environment, "database", f"{hours}h", f"slow_queries_{threshold_ms}ms"
        )

        async def _fetch() -> Dict[str, Any]:
            result = await self._gcp.get_slow_query_logs(
                hours=hours, threshold_ms=threshold_ms, **kwargs
            )
            return result.to_dict()

        return await self.cache.get_or_fetch(cache_key, _fetch, ttl=ttl)

    # ------------------------------------------------------------------
    # Bulk pre-warm: seed all standard keys at startup
    # ------------------------------------------------------------------

    async def prewarm_standard_keys(
        self,
        environments: Sequence[str] = ("PROD", "STAGING"),
        categories: Sequence[str] = ("cloud", "database", "storage"),
        periods: Sequence[str] = ("1h", "24h"),
    ) -> List[str]:
        """Eagerly populate Redis with standard metric keys at app startup.

        Call this during the FastAPI ``lifespan`` startup event.  Returns the
        list of cache keys that were successfully warmed.
        """
        warmed: List[str] = []
        for env in environments:
            for cat in categories:
                for per in periods:
                    key = RedisCache.build_key(env, cat, per)
                    logger.info("[CachedGCPMetricsService] Pre-warming %s", key)
                    try:
                        await self.get_metrics(env, cat, per)
                        warmed.append(key)
                    except Exception as exc:
                        logger.warning(
                            "[CachedGCPMetricsService] Pre-warm failed for %s: %s",
                            key, exc,
                        )
        return warmed

    # ------------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------------

    async def health(self) -> Dict[str, Any]:
        """Return combined cache + GCP API health snapshot."""
        gcp_health = await self._gcp.health()
        cache_health = await self.cache.health()
        return {
            "service": "CachedGCPMetricsService",
            "gcp": gcp_health,
            "cache": cache_health,
        }
