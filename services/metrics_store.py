"""GCP Infrastructure & FinOps Metrics Telemetry and Storage Service.

Generates and stores high-fidelity GCP observability metrics, supports historical
30-day retention time-series telemetry, evaluates dynamic threshold configs,
and generates prescriptive active alerts for operations and FinOps engineers.
"""

from __future__ import annotations

import math
import random
import threading
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple, Union

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


class MetricsStore:
    """Enterprise metrics repository and dynamic telemetry engine for GCP Observatory."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._thresholds: Dict[str, MetricThresholdConfig] = {}
        self._active_alerts: List[AlertRule] = []
        self._seed_default_thresholds()
        self._seed_default_alerts()

    def _seed_default_thresholds(self) -> None:
        """Seed baseline threshold configs for key GCP infrastructure metrics."""
        defaults = [
            MetricThresholdConfig(
                metric_name="database.cpu_io_percent",
                warning_threshold=70.0,
                critical_threshold=85.0,
                operator=ThresholdOperator.GREATER_THAN,
                custom_rule_setter_metadata={
                    "author": "lead-dba@gcp-corp.internal",
                    "description": "Cloud SQL / Spanner CPU I/O saturation threshold",
                    "runbook_url": "https://wiki.corp.internal/runbooks/cloud-sql-cpu",
                },
            ),
            MetricThresholdConfig(
                metric_name="database.active_connections",
                warning_threshold=650.0,
                critical_threshold=850.0,
                operator=ThresholdOperator.GREATER_THAN,
                custom_rule_setter_metadata={
                    "author": "sre-lead@gcp-corp.internal",
                    "description": "Connection pool saturation guardrail",
                },
            ),
            MetricThresholdConfig(
                metric_name="cloud.cpu_percent",
                warning_threshold=75.0,
                critical_threshold=90.0,
                operator=ThresholdOperator.GREATER_THAN,
                custom_rule_setter_metadata={
                    "author": "finops-eng@gcp-corp.internal",
                    "description": "Compute Engine fleet utilization",
                },
            ),
            MetricThresholdConfig(
                metric_name="cloud.uptime_percent",
                warning_threshold=99.9,
                critical_threshold=99.5,
                operator=ThresholdOperator.LESS_THAN,
                custom_rule_setter_metadata={
                    "author": "sre-lead@gcp-corp.internal",
                    "description": "Compute fleet availability SLA limit",
                },
            ),
            MetricThresholdConfig(
                metric_name="storage.bucket_volume_usage_percent",
                warning_threshold=75.0,
                critical_threshold=90.0,
                operator=ThresholdOperator.GREATER_THAN,
                custom_rule_setter_metadata={
                    "author": "storage-admin@gcp-corp.internal",
                    "description": "Cloud Storage bucket capacity limit",
                },
            ),
            MetricThresholdConfig(
                metric_name="processing.failure_counts",
                warning_threshold=15.0,
                critical_threshold=30.0,
                operator=ThresholdOperator.GREATER_THAN,
                custom_rule_setter_metadata={
                    "author": "data-platform@gcp-corp.internal",
                    "description": "Batch workflow failed job count",
                },
            ),
            MetricThresholdConfig(
                metric_name="tokens.error_rate_percent",
                warning_threshold=1.5,
                critical_threshold=3.0,
                operator=ThresholdOperator.GREATER_THAN,
                custom_rule_setter_metadata={
                    "author": "ai-lead@gcp-corp.internal",
                    "description": "Vertex AI LLM gateway failure rate",
                },
            ),
            MetricThresholdConfig(
                metric_name="sla.availability_percent",
                warning_threshold=99.95,
                critical_threshold=99.80,
                operator=ThresholdOperator.LESS_THAN,
                custom_rule_setter_metadata={
                    "author": "finops-lead@gcp-corp.internal",
                    "description": "Corporate Platform SLA compliance limit",
                },
            ),
        ]
        for cfg in defaults:
            self._thresholds[cfg.metric_name] = cfg

    def _seed_default_alerts(self) -> None:
        """Seed realistic active GCP infrastructure alerts with actionable remediation guidance."""
        now = datetime.now(timezone.utc)
        self._active_alerts = [
            AlertRule(
                metric_id="database.cpu_io_percent",
                current_value=74.2,
                severity=AlertSeverity.WARNING,
                suggested_action=(
                    "Scale database tier to db-custom-16-65536 or enable Cloud SQL Query Insights "
                    "to terminate blocking lock queries."
                ),
                resource_id="orders-primary",
                triggered_at=now - timedelta(minutes=42),
            ),
            AlertRule(
                metric_id="processing.failure_counts",
                current_value=23.0,
                severity=AlertSeverity.CRITICAL,
                suggested_action=(
                    "Check BigQuery batch job error logs for schema mismatch; restart worker pool "
                    "and review Pub/Sub dead-letter queue."
                ),
                resource_id="analytics-warehouse",
                triggered_at=now - timedelta(minutes=15),
            ),
            AlertRule(
                metric_id="storage.bucket_volume_usage_percent",
                current_value=76.8,
                severity=AlertSeverity.WARNING,
                suggested_action=(
                    "Configure Object Lifecycle Management to migrate objects >30 days to Coldline Storage."
                ),
                resource_id="media-archive",
                triggered_at=now - timedelta(hours=2),
            ),
        ]

    # ------------------------------------------------------------------------
    # Threshold Management
    # ------------------------------------------------------------------------

    def get_threshold(self, metric_name: str) -> Optional[MetricThresholdConfig]:
        """Fetch custom threshold config for a given metric."""
        with self._lock:
            return self._thresholds.get(metric_name)

    def list_thresholds(self) -> List[MetricThresholdConfig]:
        """List all active metric threshold configs."""
        with self._lock:
            return list(self._thresholds.values())

    def update_threshold(
        self, config: MetricThresholdConfig
    ) -> Tuple[MetricThresholdConfig, Optional[MetricThresholdConfig]]:
        """Update or register a metric threshold config.

        Returns:
            Tuple of (new_config, previous_config).
        """
        with self._lock:
            prev = self._thresholds.get(config.metric_name)
            self._thresholds[config.metric_name] = config
            return config, prev

    # ------------------------------------------------------------------------
    # Time-Series Generator Engine (supports 30-day retention queries)
    # ------------------------------------------------------------------------

    def generate_timeseries(
        self,
        base_value: float,
        period: TimePeriod = TimePeriod.TWENTY_FOUR_HOURS,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        seed_str: str = "gcp-metric",
        points_count: Optional[int] = None,
    ) -> List[TimeSeriesPoint]:
        """Generate high-fidelity, deterministic historical time-series points.

        Supports 1h, 24h, 7d, 30d (30-day retention), 90d, and custom windows.
        """
        now = datetime.now(timezone.utc)
        end = end_time if end_time else now
        if end.tzinfo is None:
            end = end.replace(tzinfo=timezone.utc)

        # Determine start time and point count based on period
        if period == TimePeriod.ONE_HOUR:
            start = end - timedelta(hours=1)
            count = points_count or 60  # 1 point per minute
        elif period == TimePeriod.TWENTY_FOUR_HOURS:
            start = end - timedelta(hours=24)
            count = points_count or 24  # 1 point per hour
        elif period == TimePeriod.SEVEN_DAYS:
            start = end - timedelta(days=7)
            count = points_count or 42  # 6 points per day (every 4 hours)
        elif period == TimePeriod.THIRTY_DAYS:
            # 30-Day Retention Query
            start = end - timedelta(days=30)
            count = points_count or 60  # 2 points per day (every 12 hours) across 30 days
        elif period == TimePeriod.NINETY_DAYS:
            start = end - timedelta(days=90)
            count = points_count or 90  # 1 point per day
        elif period == TimePeriod.CUSTOM and start_time:
            start = start_time
            if start.tzinfo is None:
                start = start.replace(tzinfo=timezone.utc)
            delta_seconds = (end - start).total_seconds()
            count = points_count or max(10, min(100, int(delta_seconds / 3600)))
        else:
            start = end - timedelta(hours=24)
            count = points_count or 24

        if count <= 0:
            count = 24

        time_step = (end - start) / count
        seed_val = sum(ord(c) for c in seed_str)

        points: List[TimeSeriesPoint] = []
        for i in range(count):
            pt_time = start + time_step * i
            # Cyclic diurnal simulation
            hour = pt_time.hour + pt_time.minute / 60.0
            daily_cycle = math.sin((hour / 24.0) * math.pi * 2.0 - 1.2 + seed_val * 0.05) * 0.12
            weekly_cycle = math.cos((pt_time.weekday() / 7.0) * math.pi * 2.0) * 0.08
            jitter = math.sin(i * 1.7 + seed_val) * 0.04

            multiplier = max(0.05, 1.0 + daily_cycle + weekly_cycle + jitter)
            val = round(base_value * multiplier, 2)
            points.append(TimeSeriesPoint(timestamp=pt_time, value=val))

        # Ensure last point matches current reading closely
        points.append(TimeSeriesPoint(timestamp=end, value=round(base_value, 2)))
        return points

    # ------------------------------------------------------------------------
    # Category Metrics Telemetry
    # ------------------------------------------------------------------------

    def get_database_metrics(
        self,
        env: Environment = Environment.PROD,
        period: TimePeriod = TimePeriod.TWENTY_FOUR_HOURS,
        resource_id: Optional[str] = "orders-primary",
    ) -> DatabaseMetrics:
        """Generate Database category metrics."""
        qps_series = self.generate_timeseries(2418.0, period, seed_str="db-qps")
        active_conn_series = self.generate_timeseries(684.0, period, seed_str="db-conn")
        cpu_io_series = self.generate_timeseries(71.0, period, seed_str="db-cpu-io")

        # Evaluate against active thresholds
        cpu_thresh = self.get_threshold("database.cpu_io_percent")
        cpu_status = cpu_thresh.evaluate(71.0) if cpu_thresh else MetricStatus.CRITICAL

        conn_thresh = self.get_threshold("database.active_connections")
        conn_status = conn_thresh.evaluate(684.0) if conn_thresh else MetricStatus.WARNING

        return DatabaseMetrics(
            resource_id=resource_id or "orders-primary",
            environment=env,
            qps=MetricReading(
                current_value=2418.0,
                unit=MetricUnit.QPS,
                status=MetricStatus.HEALTHY,
                time_series=qps_series,
                change_percentage=4.2,
            ),
            active_connections=MetricReading(
                current_value=684.0,
                unit=MetricUnit.COUNT,
                status=conn_status,
                time_series=active_conn_series,
                change_percentage=12.5,
            ),
            locks=MetricReading(
                current_value=14.0,
                unit=MetricUnit.COUNT,
                status=MetricStatus.HEALTHY,
                change_percentage=-8.1,
            ),
            slow_queries_count=MetricReading(
                current_value=27.0,
                unit=MetricUnit.COUNT,
                status=MetricStatus.WARNING,
                change_percentage=18.0,
            ),
            avg_response_time_ms=MetricReading(
                current_value=42.0,
                unit=MetricUnit.MILLISECONDS,
                status=MetricStatus.HEALTHY,
                change_percentage=-2.4,
            ),
            cpu_io_percent=MetricReading(
                current_value=71.0,
                unit=MetricUnit.PERCENT,
                status=cpu_status,
                time_series=cpu_io_series,
                change_percentage=14.8,
            ),
            replication_lag_seconds=MetricReading(
                current_value=1.8,
                unit=MetricUnit.SECONDS,
                status=MetricStatus.WARNING,
                change_percentage=22.0,
            ),
        )

    def get_cloud_metrics(
        self,
        env: Environment = Environment.PROD,
        period: TimePeriod = TimePeriod.TWENTY_FOUR_HOURS,
        resource_id: Optional[str] = "api-workers",
    ) -> CloudMetrics:
        """Generate Cloud & Compute fleet utilization and FinOps cost metrics."""
        cpu_series = self.generate_timeseries(68.4, period, seed_str="cloud-cpu")
        cost_series = self.generate_timeseries(18426.0, period, seed_str="cloud-cost")

        cpu_thresh = self.get_threshold("cloud.cpu_percent")
        cpu_status = cpu_thresh.evaluate(68.4) if cpu_thresh else MetricStatus.WARNING

        return CloudMetrics(
            resource_id=resource_id or "api-workers",
            environment=env,
            cpu_percent=MetricReading(
                current_value=68.4,
                unit=MetricUnit.PERCENT,
                status=cpu_status,
                time_series=cpu_series,
                change_percentage=6.8,
            ),
            memory_percent=MetricReading(
                current_value=72.1,
                unit=MetricUnit.PERCENT,
                status=MetricStatus.WARNING,
                change_percentage=3.1,
            ),
            disk_percent=MetricReading(
                current_value=61.8,
                unit=MetricUnit.PERCENT,
                status=MetricStatus.WARNING,
                change_percentage=1.9,
            ),
            estimated_cost_usd=MetricReading(
                current_value=18426.0,
                unit=MetricUnit.USD,
                status=MetricStatus.HEALTHY,
                time_series=cost_series,
                change_percentage=-3.5,
            ),
            uptime_percent=MetricReading(
                current_value=99.97,
                unit=MetricUnit.PERCENT,
                status=MetricStatus.HEALTHY,
                change_percentage=0.01,
            ),
        )

    def get_storage_metrics(
        self,
        env: Environment = Environment.PROD,
        period: TimePeriod = TimePeriod.TWENTY_FOUR_HOURS,
        resource_id: Optional[str] = "media-archive",
    ) -> StorageMetrics:
        """Generate Cloud Storage and Persistent Disk telemetry."""
        vol_thresh = self.get_threshold("storage.bucket_volume_usage_percent")
        vol_status = vol_thresh.evaluate(74.2) if vol_thresh else MetricStatus.CRITICAL

        usage_series = self.generate_timeseries(428.6, period, seed_str="storage-usage")

        return StorageMetrics(
            resource_id=resource_id or "media-archive",
            environment=env,
            total_usage=MetricReading(
                current_value=428.6,
                unit=MetricUnit.TERABYTES,
                status=MetricStatus.WARNING,
                time_series=usage_series,
                change_percentage=8.4,
            ),
            bucket_volume_usage_percent=MetricReading(
                current_value=74.2,
                unit=MetricUnit.PERCENT,
                status=vol_status,
                change_percentage=5.2,
            ),
            iops=MetricReading(
                current_value=18400.0,
                unit=MetricUnit.IOPS,
                status=MetricStatus.HEALTHY,
                change_percentage=1.2,
            ),
            read_write_throughput_mb_s=MetricReading(
                current_value=2800.0,
                unit=MetricUnit.MB_PER_SEC,
                status=MetricStatus.HEALTHY,
                change_percentage=-0.8,
            ),
            latency_ms=MetricReading(
                current_value=18.6,
                unit=MetricUnit.MILLISECONDS,
                status=MetricStatus.HEALTHY,
                change_percentage=-1.5,
            ),
        )

    def get_processing_metrics(
        self,
        env: Environment = Environment.PROD,
        period: TimePeriod = TimePeriod.TWENTY_FOUR_HOURS,
        resource_id: Optional[str] = "analytics-warehouse",
    ) -> ProcessingMetrics:
        """Generate batch processing, BigQuery & Cloud Run workload metrics."""
        fail_thresh = self.get_threshold("processing.failure_counts")
        fail_status = fail_thresh.evaluate(23.0) if fail_thresh else MetricStatus.CRITICAL

        queue_series = self.generate_timeseries(1284.0, period, seed_str="proc-queue")

        return ProcessingMetrics(
            resource_id=resource_id or "analytics-warehouse",
            environment=env,
            queued_jobs=MetricReading(
                current_value=1284.0,
                unit=MetricUnit.COUNT,
                status=MetricStatus.WARNING,
                time_series=queue_series,
                change_percentage=15.3,
            ),
            running_jobs=MetricReading(
                current_value=342.0,
                unit=MetricUnit.COUNT,
                status=MetricStatus.HEALTHY,
                change_percentage=2.1,
            ),
            avg_processing_time_seconds=MetricReading(
                current_value=222.0,
                unit=MetricUnit.SECONDS,
                status=MetricStatus.HEALTHY,
                change_percentage=-4.7,
            ),
            failure_counts=MetricReading(
                current_value=23.0,
                unit=MetricUnit.COUNT,
                status=fail_status,
                change_percentage=28.0,
            ),
        )

    def get_token_metrics(
        self,
        env: Environment = Environment.PROD,
        period: TimePeriod = TimePeriod.TWENTY_FOUR_HOURS,
        resource_id: Optional[str] = "model-inference",
    ) -> TokenUsageMetrics:
        """Generate Vertex AI LLM inference token and model spend metrics."""
        err_thresh = self.get_threshold("tokens.error_rate_percent")
        err_status = err_thresh.evaluate(0.84) if err_thresh else MetricStatus.WARNING

        token_series = self.generate_timeseries(8420000.0, period, seed_str="token-daily")

        return TokenUsageMetrics(
            resource_id=resource_id or "model-inference",
            environment=env,
            daily_token_count=MetricReading(
                current_value=8420000.0,
                unit=MetricUnit.TOKENS,
                status=MetricStatus.HEALTHY,
                time_series=token_series,
                change_percentage=11.2,
            ),
            weekly_token_count=MetricReading(
                current_value=58940000.0,
                unit=MetricUnit.TOKENS,
                status=MetricStatus.HEALTHY,
                change_percentage=9.4,
            ),
            cost_per_model=MetricReading(
                current_value=1284.0,
                unit=MetricUnit.USD,
                status=MetricStatus.HEALTHY,
                change_percentage=6.0,
            ),
            error_rate_percent=MetricReading(
                current_value=0.84,
                unit=MetricUnit.PERCENT,
                status=err_status,
                change_percentage=-0.12,
            ),
            rate_limit_breaches=MetricReading(
                current_value=128.0,
                unit=MetricUnit.COUNT,
                status=MetricStatus.HEALTHY,
                change_percentage=4.0,
            ),
        )

    def get_sla_metrics(
        self,
        env: Environment = Environment.PROD,
        period: TimePeriod = TimePeriod.TWENTY_FOUR_HOURS,
        resource_id: Optional[str] = None,
    ) -> SlaMetrics:
        """Generate platform SLA, uptime availability and error metrics."""
        sla_thresh = self.get_threshold("sla.availability_percent")
        sla_status = sla_thresh.evaluate(99.96) if sla_thresh else MetricStatus.HEALTHY

        avail_series = self.generate_timeseries(99.96, period, seed_str="sla-avail")

        return SlaMetrics(
            resource_id=resource_id,
            environment=env,
            availability_percent=MetricReading(
                current_value=99.96,
                unit=MetricUnit.PERCENT,
                status=sla_status,
                time_series=avail_series,
                change_percentage=0.02,
            ),
            error_counts_4xx_5xx=MetricReading(
                current_value=1240.0,
                unit=MetricUnit.COUNT,
                status=MetricStatus.WARNING,
                change_percentage=18.4,
            ),
            peak_usage_percent=MetricReading(
                current_value=82.4,
                unit=MetricUnit.PERCENT,
                status=MetricStatus.CRITICAL,
                change_percentage=5.3,
            ),
            growth_trend_percent=MetricReading(
                current_value=12.8,
                unit=MetricUnit.PERCENT,
                status=MetricStatus.HEALTHY,
                change_percentage=1.4,
            ),
        )

    # ------------------------------------------------------------------------
    # Composite Overview & Active Alerts
    # ------------------------------------------------------------------------

    def get_active_alerts(
        self,
        severity: Optional[AlertSeverity] = None,
        resource_id: Optional[str] = None,
        is_acknowledged: Optional[bool] = None,
    ) -> List[AlertRule]:
        """Fetch active alerts with optional filtering."""
        with self._lock:
            alerts = self._active_alerts
            if severity:
                alerts = [a for a in alerts if a.severity == severity]
            if resource_id:
                alerts = [
                    a for a in alerts if a.resource_id and resource_id.lower() in a.resource_id.lower()
                ]
            if is_acknowledged is not None:
                alerts = [a for a in alerts if a.is_acknowledged == is_acknowledged]
            return list(alerts)

    def get_overview_payload(
        self,
        filters: Optional[DashboardFilterParams] = None,
    ) -> DashboardMetricsPayload:
        """Return the composite root telemetry payload for the FinOps Observatory dashboard."""
        filter_params = filters or DashboardFilterParams()
        env = filter_params.environment
        period = filter_params.time_period
        res_id = filter_params.resource_id

        database = self.get_database_metrics(env=env, period=period, resource_id=res_id)
        cloud = self.get_cloud_metrics(env=env, period=period, resource_id=res_id)
        storage = self.get_storage_metrics(env=env, period=period, resource_id=res_id)
        processing = self.get_processing_metrics(env=env, period=period, resource_id=res_id)
        tokens = self.get_token_metrics(env=env, period=period, resource_id=res_id)
        sla = self.get_sla_metrics(env=env, period=period, resource_id=res_id)

        active_alerts = self.get_active_alerts(resource_id=res_id)

        return DashboardMetricsPayload(
            filter_params=filter_params,
            database=database,
            cloud=cloud,
            storage=storage,
            processing=processing,
            tokens=tokens,
            sla=sla,
            active_alerts=active_alerts,
        )

    def get_category_timeseries(
        self,
        category: str,
        period: TimePeriod = TimePeriod.TWENTY_FOUR_HOURS,
        metric_name: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        """Generate timeseries data for a specific category and support 30-day retention."""
        cat_lower = category.lower().strip()
        series_map: Dict[str, List[TimeSeriesPoint]] = {}

        if cat_lower == "database":
            metrics = self.get_database_metrics(period=period)
            all_metrics = {
                "qps": metrics.qps,
                "active_connections": metrics.active_connections,
                "locks": metrics.locks,
                "slow_queries_count": metrics.slow_queries_count,
                "avg_response_time_ms": metrics.avg_response_time_ms,
                "cpu_io_percent": metrics.cpu_io_percent,
                "replication_lag_seconds": metrics.replication_lag_seconds,
            }
        elif cat_lower == "cloud":
            metrics = self.get_cloud_metrics(period=period)
            all_metrics = {
                "cpu_percent": metrics.cpu_percent,
                "memory_percent": metrics.memory_percent,
                "disk_percent": metrics.disk_percent,
                "estimated_cost_usd": metrics.estimated_cost_usd,
                "uptime_percent": metrics.uptime_percent,
            }
        elif cat_lower == "storage":
            metrics = self.get_storage_metrics(period=period)
            all_metrics = {
                "total_usage": metrics.total_usage,
                "bucket_volume_usage_percent": metrics.bucket_volume_usage_percent,
                "iops": metrics.iops,
                "read_write_throughput_mb_s": metrics.read_write_throughput_mb_s,
                "latency_ms": metrics.latency_ms,
            }
        elif cat_lower == "processing":
            metrics = self.get_processing_metrics(period=period)
            all_metrics = {
                "queued_jobs": metrics.queued_jobs,
                "running_jobs": metrics.running_jobs,
                "avg_processing_time_seconds": metrics.avg_processing_time_seconds,
                "failure_counts": metrics.failure_counts,
            }
        elif cat_lower in ("tokens", "token_usage"):
            metrics = self.get_token_metrics(period=period)
            all_metrics = {
                "daily_token_count": metrics.daily_token_count,
                "weekly_token_count": metrics.weekly_token_count,
                "cost_per_model": metrics.cost_per_model,
                "error_rate_percent": metrics.error_rate_percent,
                "rate_limit_breaches": metrics.rate_limit_breaches,
            }
        elif cat_lower == "sla":
            metrics = self.get_sla_metrics(period=period)
            all_metrics = {
                "availability_percent": metrics.availability_percent,
                "error_counts_4xx_5xx": metrics.error_counts_4xx_5xx,
                "peak_usage_percent": metrics.peak_usage_percent,
                "growth_trend_percent": metrics.growth_trend_percent,
            }
        else:
            raise ValueError(
                f"Unknown metric category '{category}'. Supported: database, cloud, storage, processing, tokens, sla."
            )

        if metric_name:
            if metric_name not in all_metrics:
                raise ValueError(
                    f"Metric '{metric_name}' not found in category '{category}'. Available: {list(all_metrics.keys())}"
                )
            selected = {metric_name: all_metrics[metric_name]}
        else:
            selected = all_metrics

        for name, reading in selected.items():
            if reading.time_series:
                series_map[name] = reading.time_series
            else:
                # Generate on the fly for metrics without pre-computed series
                series_map[name] = self.generate_timeseries(
                    reading.current_value,
                    period=period,
                    start_time=start_time,
                    end_time=end_time,
                    seed_str=f"{category}-{name}",
                )

        return {
            "category": category,
            "period": period.value,
            "metric_count": len(series_map),
            "retention_window": f"{period.value} historical retention query supported",
            "series": {
                name: [pt.model_dump() for pt in points]
                for name, points in series_map.items()
            },
        }


# Global singleton store instance
metrics_store = MetricsStore()
