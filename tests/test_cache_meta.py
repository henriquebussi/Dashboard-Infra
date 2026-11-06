"""Cache provenance tests for the dashboard data-source indicators."""

from __future__ import annotations

import asyncio
from typing import Any, Dict

from services.cache import RedisCache
from services.gcp_service import CachedGCPMetricsService


class MemoryCache:
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
