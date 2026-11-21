"""Cache provenance tests for the dashboard data-source indicators."""

from __future__ import annotations

import asyncio
from typing import Any, Dict

from services.cache import RedisCache
from services.gcp_service import CachedGCPMetricsService
from services.gcp_service import MetricPoint, MetricSeries
from services.metric_registry import METRIC_DEFINITIONS
from schemas import DashboardFilterParams, Environment, TimePeriod
from datetime import datetime, timezone


class MemoryCache:
    get_or_fetch = RedisCache.get_or_fetch
    """Minimal async cache implementing the RedisCache methods used here."""

    def __init__(self) -> None:
        self.store: Dict[str, Any] = {}
        self.default_ttl = 60

    async def get(self, key: str) -> Any:
        return self.store.get(key)

    async def set(self, key: str, value: Any, ttl: int | None = None) -> None:
        self.store[key] = value

    def _register_prewarm(self, *args: Any, **kwargs: Any) -> None:
        return None

    async def get_or_fetch_with_meta(self, **kwargs: Any) -> tuple[Any, bool]:
        return await RedisCache.get_or_fetch_with_meta(self, **kwargs)  # type: ignore[arg-type]


def test_get_or_fetch_with_meta_reports_cache_hits() -> None:
    cache = MemoryCache()
    calls = 0

    async def fetcher() -> Dict[str, int]:
        nonlocal calls
        calls += 1
        return {"value": calls}

    value, from_cache = asyncio.run(
        RedisCache.get_or_fetch_with_meta(cache, "key", fetcher, ttl=60)  # type: ignore[arg-type]
    )
    assert value == {"value": 1}
    assert from_cache is False

    value, from_cache = asyncio.run(
        RedisCache.get_or_fetch_with_meta(cache, "key", fetcher, ttl=60)  # type: ignore[arg-type]
    )
    assert value == {"value": 1}
    assert from_cache is True
    assert calls == 1


def test_gcp_metrics_reports_live_then_cache(monkeypatch) -> None:
    cache = MemoryCache()
    service = CachedGCPMetricsService(project_id="test-project", cache=cache)  # type: ignore[arg-type]
    calls = 0

    async def fake_dispatch(category: str, period: str, **kwargs: Any) -> Dict[str, Any]:
        nonlocal calls
        calls += 1
        return {
            "category": category,
            "period": period,
            "metrics": {"queries": [{"points": [{"timestamp": "t", "value": 1.0}]}]},
        }

    monkeypatch.setattr(service, "_dispatch_category", fake_dispatch)

    live = asyncio.run(service.get_metrics("PROD", "database", "1h"))
    assert live["data_source"] == "live"

    cached = asyncio.run(service.get_metrics("PROD", "database", "1h"))
    assert cached["data_source"] == "cache"
    assert calls == 1


def test_gcp_metrics_cache_is_scoped_by_project_and_resource(monkeypatch) -> None:
    cache = MemoryCache()
    service = CachedGCPMetricsService(
        project_id="default-project",
        project_map={"PROD": "production-project", "STAGING": "staging-project"},
        cache=cache,  # type: ignore[arg-type]
    )
    calls: list[tuple[str, str | None]] = []

    async def fake_dispatch(category: str, period: str, **kwargs: Any) -> Dict[str, Any]:
        calls.append((kwargs["project_id"], kwargs.get("database_id")))
        return {"category": category, "period": period, "metrics": {}}

    monkeypatch.setattr(service, "_dispatch_category", fake_dispatch)
    asyncio.run(service.get_metrics("PROD", "database", "1h", database_id="one"))
    asyncio.run(service.get_metrics("PROD", "database", "1h", database_id="two"))
    asyncio.run(service.get_metrics("STAGING", "database", "1h", database_id="one"))
    asyncio.run(service.get_metrics("PROD", "database", "1h", database_id="one"))

    assert calls == [
        ("production-project", "one"),
        ("production-project", "two"),
        ("staging-project", "one"),
    ]


def test_daily_storage_metric_uses_full_day_for_one_hour_filter(monkeypatch) -> None:
    cache = MemoryCache()
    service = CachedGCPMetricsService(project_id="test-project", cache=cache)  # type: ignore[arg-type]
    intervals: list[float] = []

    async def fake_query(**kwargs: Any) -> list[MetricSeries]:
        intervals.append((kwargs["end_time"] - kwargs["start_time"]).total_seconds())
        return [MetricSeries(
            metric_type=kwargs["metric_type"], category="storage", metric_name="total_usage",
            unit="By", points=[MetricPoint(datetime.now(timezone.utc), 1024 ** 3)],
        )]

    monkeypatch.setattr(service._gcp, "query_metric", fake_query)
    filters = DashboardFilterParams(time_period=TimePeriod.ONE_HOUR, environment=Environment.PROD)
    reading = asyncio.run(service.get_reading_for_definition(
        METRIC_DEFINITIONS["storage.total_usage"], filters, "test-project", Environment.PROD,
    ))
    assert reading.available
    assert intervals == [86400.0, 86400.0]


def test_token_count_sums_aligned_buckets_across_models(monkeypatch) -> None:
    cache = MemoryCache()
    service = CachedGCPMetricsService(project_id="test-project", cache=cache)  # type: ignore[arg-type]

    async def fake_query(**kwargs: Any) -> list[MetricSeries]:
        base = kwargs["start_time"]
        return [MetricSeries(
            metric_type=kwargs["metric_type"], category="tokens", metric_name="daily_token_count",
            unit="1", points=[
                MetricPoint(base, 10.0),
                MetricPoint(base.replace(hour=(base.hour + 1) % 24), 20.0),
            ],
        )]

    monkeypatch.setattr(service._gcp, "query_metric", fake_query)
    filters = DashboardFilterParams(time_period=TimePeriod.ONE_HOUR, environment=Environment.PROD)
    reading = asyncio.run(service.get_reading_for_definition(
        METRIC_DEFINITIONS["tokens.daily_token_count"], filters, "test-project", Environment.PROD,
    ))
    assert reading.available
    assert reading.current_value == 30.0
    assert reading.change_percentage == 0.0


def test_error_logs_do_not_reuse_another_filters_cache(monkeypatch):
    from types import SimpleNamespace
    service = CachedGCPMetricsService("project", MemoryCache())
    async def query(**kwargs):
        return SimpleNamespace(to_dict=lambda: kwargs)
    monkeypatch.setattr(service._gcp, "get_error_logs", query)
    for limit, name in [(5, "first"), (5, "second"), (10, "second")]:
        data = asyncio.run(service.get_error_logs("PROD", max_entries=limit, service_filter=name))
        assert (data["max_entries"], data["service_filter"]) == (limit, name)


def test_same_named_resource_in_two_projects_is_discovered_separately():
    from services.resource_inventory import ResourceInventoryService
    inventory = ResourceInventoryService()
    for project, env in [("one", Environment.PROD), ("two", Environment.DEV)]:
        inventory.record_series_labels("cloud", "cpu", {"instance_name": "worker"}, env, project)
    assert len(inventory.get_resources()) == 2
    assert len(inventory.get_resources(env=Environment.DEV)) == 1
