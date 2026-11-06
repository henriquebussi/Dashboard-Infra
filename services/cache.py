"""GCP FinOps Observatory - High-Performance Redis Caching Layer.

Implements a Cache-Aside strategy with:
  - Async Redis client via `redis.asyncio` (drop-in aioredis-compatible).
  - Namespaced key schema: ``metrics:{environment}:{category}:{period}``.
  - Configurable per-key TTL with a sensible 60-second default.
  - Background pre-warming loop to keep hot keys alive before they expire,
    guaranteeing sub-2-second API response times under GCP API rate limits.
  - Circuit-breaker wrapper protecting every Redis I/O call; a degraded Redis
    node degrades gracefully to cache-miss semantics instead of crashing.
  - Decorator ``cached_metric`` for transparently wrapping any coroutine that
    returns a JSON-serialisable payload.
"""

from __future__ import annotations

import asyncio
import functools
import json
import logging
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Coroutine, Dict, List, Optional, Tuple

try:
    import redis.asyncio as aioredis
    from redis.asyncio import Redis
    from redis.exceptions import ConnectionError as RedisConnectionError
    from redis.exceptions import RedisError, TimeoutError as RedisTimeoutError
except ImportError as exc:  # pragma: no cover
    raise ImportError(
        "redis>=4.2.0 is required for the caching layer. "
        "Install it with: pip install 'redis[asyncio]>=4.2.0'"
    ) from exc

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_DEFAULT_TTL_SECONDS: int = 60
"""Default cache TTL in seconds (1 minute)."""

_PREWARM_THRESHOLD_RATIO: float = 0.30
"""Fraction of TTL remaining below which background pre-warming triggers."""

_CIRCUIT_OPEN_WINDOW_SECONDS: float = 30.0
"""Seconds that the circuit-breaker stays OPEN before attempting a probe."""

_CIRCUIT_FAILURE_THRESHOLD: int = 5
"""Consecutive Redis errors required to OPEN the circuit breaker."""

_KEY_PREFIX: str = "metrics"
"""Top-level namespace prefix for all cache keys."""


# ---------------------------------------------------------------------------
# Circuit-Breaker State Machine
# ---------------------------------------------------------------------------


class _CircuitState(str, Enum):
    CLOSED = "CLOSED"      # Normal operation — requests pass through.
    OPEN = "OPEN"          # Faulted — requests are rejected immediately.
    HALF_OPEN = "HALF_OPEN"  # Probe phase — single request to test recovery.


@dataclass
class _CircuitBreaker:
    """Lightweight asyncio-compatible circuit breaker for Redis I/O."""

    failure_threshold: int = _CIRCUIT_FAILURE_THRESHOLD
    open_window: float = _CIRCUIT_OPEN_WINDOW_SECONDS

    _state: _CircuitState = field(default=_CircuitState.CLOSED, init=False)
    _failure_count: int = field(default=0, init=False)
    _last_opened_at: float = field(default=0.0, init=False)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False)

    @property
    def state(self) -> _CircuitState:
        return self._state

    async def call(self, coro: Coroutine) -> Any:
        """Execute *coro* through the circuit breaker.

        Raises ``RuntimeError`` if the breaker is OPEN and the probe window
        has not elapsed yet. Otherwise propagates exceptions from *coro*.
        """
        async with self._lock:
            if self._state is _CircuitState.OPEN:
                elapsed = time.monotonic() - self._last_opened_at
                if elapsed < self.open_window:
                    raise RuntimeError(
                        f"[CircuitBreaker] Redis circuit is OPEN — "
                        f"retry in {self.open_window - elapsed:.1f}s"
                    )
                # Probe window elapsed → allow a single half-open attempt.
                self._state = _CircuitState.HALF_OPEN
                logger.info("[CircuitBreaker] Transitioning to HALF_OPEN (probe).")

        try:
            result = await coro
        except (RedisConnectionError, RedisTimeoutError, RedisError) as exc:
            await self._record_failure(exc)
            raise
        else:
            await self._record_success()
            return result

    async def _record_failure(self, exc: Exception) -> None:
        async with self._lock:
            self._failure_count += 1
            # Log the first failure and state transitions loudly; repeated
            # failures while the circuit is open stay at debug level.
            if self._failure_count == 1 or self._failure_count >= self.failure_threshold:
                logger.warning(
                    "[CircuitBreaker] Redis failure #%d: %s", self._failure_count, exc
                )
            else:
                logger.debug(
                    "[CircuitBreaker] Redis failure #%d: %s", self._failure_count, exc
                )
            if (
                self._state is _CircuitState.HALF_OPEN
                or self._failure_count >= self.failure_threshold
            ):
                self._state = _CircuitState.OPEN
                self._last_opened_at = time.monotonic()
                logger.error(
                    "[CircuitBreaker] Circuit OPENED after %d failures.",
                    self._failure_count,
                )

    async def _record_success(self) -> None:
        async with self._lock:
            if self._state is not _CircuitState.CLOSED:
                logger.info(
                    "[CircuitBreaker] Redis recovered — circuit CLOSED."
                )
            self._state = _CircuitState.CLOSED
            self._failure_count = 0


# ---------------------------------------------------------------------------
# Pre-Warming Registry
# ---------------------------------------------------------------------------


@dataclass
class _PrewarmEntry:
    """Tracks metadata for a hot cache key to enable background refresh."""

    cache_key: str
    ttl: int
    fetcher: Callable[[], Coroutine]  # zero-arg coroutine factory
    last_refreshed_at: float = field(default_factory=time.monotonic)


# ---------------------------------------------------------------------------
# Redis Cache Manager
# ---------------------------------------------------------------------------


class RedisCache:
    """Async Redis cache manager with Cache-Aside, TTL control, circuit breaker,
    and background pre-warming for GCP FinOps Observatory.

    Usage::

        cache = RedisCache(url="redis://localhost:6379/0")
        await cache.connect()

        # Manual cache-aside
        value = await cache.get("metrics:PROD:database:24h")
        if value is None:
            value = expensive_gcp_call()
            await cache.set("metrics:PROD:database:24h", value, ttl=60)

        # Decorator-based (see `cached_metric`)
        await cache.close()
    """

    def __init__(
        self,
        url: str = "redis://localhost:6379/0",
        default_ttl: int = _DEFAULT_TTL_SECONDS,
        circuit_failure_threshold: int = _CIRCUIT_FAILURE_THRESHOLD,
        circuit_open_window: float = _CIRCUIT_OPEN_WINDOW_SECONDS,
        prewarm_interval: float = 15.0,
        max_connections: int = 20,
        enabled: bool = True,
    ) -> None:
        self._url = url
        self._enabled = enabled
        self._available = False
        self.default_ttl = default_ttl
        self._prewarm_interval = prewarm_interval
        self._max_connections = max_connections

        self._redis: Optional[Redis] = None
        self._breaker = _CircuitBreaker(
            failure_threshold=circuit_failure_threshold,
            open_window=circuit_open_window,
        )
        self._prewarm_registry: Dict[str, _PrewarmEntry] = {}
        self._prewarm_task: Optional[asyncio.Task] = None
        self._closed = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def connect(self) -> None:
        """Open a connection pool to Redis and start the pre-warm loop.

        Redis is optional: when ``enabled=False`` or the initial ping fails,
        the cache runs in cache-miss mode without raising or spamming retries.
        """
        self._closed = False

        if not self._enabled:
            logger.info(
                "[RedisCache] Disabled (REDIS_ENABLED=false) — running in cache-miss mode."
            )
            return

        self._redis = aioredis.from_url(
            self._url,
            max_connections=self._max_connections,
            decode_responses=False,  # We handle encoding ourselves.
            socket_timeout=2.0,
            socket_connect_timeout=2.0,
            retry_on_timeout=True,
        )
        # Verify connectivity immediately.
        try:
            await self._breaker.call(self._redis.ping())
            self._available = True
            logger.info("[RedisCache] Connected to %s", self._url)
        except Exception as exc:
            logger.warning(
                "[RedisCache] Redis unavailable at %s (%s). "
                "Running in cache-miss mode; set REDIS_ENABLED=false to silence this warning.",
                self._url,
                exc,
            )
            # Do not start the pre-warm loop while Redis is unreachable.
            return

        self._prewarm_task = asyncio.create_task(
            self._prewarm_loop(), name="redis-prewarm"
        )

    async def close(self) -> None:
        """Cancel the pre-warm loop and close all Redis connections."""
        self._closed = True
        if self._prewarm_task and not self._prewarm_task.done():
            self._prewarm_task.cancel()
            try:
                await self._prewarm_task
            except asyncio.CancelledError:
                pass
        if self._redis:
            await self._redis.aclose()
            logger.info("[RedisCache] Connection closed.")

    @asynccontextmanager
    async def lifespan(self):
        """Async context manager for FastAPI lifespan integration."""
        await self.connect()
        try:
            yield self
        finally:
            await self.close()

    # ------------------------------------------------------------------
    # Key Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def build_key(
        environment: str,
        category: str,
        period: str,
        *extra: str,
    ) -> str:
        """Build a canonical cache key.

        Pattern: ``metrics:{environment}:{category}:{period}[:{extra}...]``
        """
        parts = [_KEY_PREFIX, environment.upper(), category.lower(), period.lower()]
        parts.extend(str(e) for e in extra)
        return ":".join(parts)

    # ------------------------------------------------------------------
    # Core Cache Operations
    # ------------------------------------------------------------------

    async def get(self, key: str) -> Optional[Any]:
        """Return the cached value for *key*, or ``None`` on miss/error."""
        if self._redis is None:
            return None
        try:
            raw: Optional[bytes] = await self._breaker.call(self._redis.get(key))
        except Exception as exc:
            logger.debug("[RedisCache] get(%s) bypassed — %s", key, exc)
            return None

        if raw is None:
            logger.debug("[RedisCache] MISS %s", key)
            return None

        try:
            value = json.loads(raw)
            logger.debug("[RedisCache] HIT  %s", key)
            return value
        except json.JSONDecodeError as exc:
            logger.warning("[RedisCache] JSON decode error for %s: %s", key, exc)
            return None

    async def set(
        self,
        key: str,
        value: Any,
        ttl: Optional[int] = None,
    ) -> bool:
        """Serialise *value* as JSON and store under *key* with *ttl* seconds.

        Returns ``True`` on success, ``False`` on circuit-open or Redis error.
        """
        if self._redis is None:
            return False
        effective_ttl = ttl if ttl is not None else self.default_ttl
        try:
            payload = json.dumps(value, default=str)
        except (TypeError, ValueError) as exc:
            logger.warning("[RedisCache] Serialisation error for %s: %s", key, exc)
            return False

        try:
            await self._breaker.call(
                self._redis.setex(key, effective_ttl, payload)
            )
            logger.debug("[RedisCache] SET  %s (TTL=%ds)", key, effective_ttl)
            return True
        except Exception as exc:
            logger.debug("[RedisCache] set(%s) failed — %s", key, exc)
            return False

    async def delete(self, key: str) -> bool:
        """Remove a key from the cache."""
        if self._redis is None:
            return False
        try:
            await self._breaker.call(self._redis.delete(key))
            return True
        except Exception:
            return False

    async def flush_namespace(self, pattern: str = f"{_KEY_PREFIX}:*") -> int:
        """Delete all keys matching *pattern* (use sparingly in production)."""
        if self._redis is None:
            return 0
        try:
            keys: List[bytes] = await self._breaker.call(self._redis.keys(pattern))
            if keys:
                deleted: int = await self._breaker.call(self._redis.delete(*keys))
                logger.info(
                    "[RedisCache] Flushed %d keys matching '%s'", deleted, pattern
                )
                return deleted
        except Exception as exc:
            logger.warning("[RedisCache] flush_namespace failed: %s", exc)
        return 0

    async def ttl_remaining(self, key: str) -> int:
        """Return the remaining TTL (seconds) for *key*, or -2 if absent."""
        if self._redis is None:
            return -2
        try:
            return await self._breaker.call(self._redis.ttl(key))
        except Exception:
            return -2

    # ------------------------------------------------------------------
    # Cache-Aside Convenience
    # ------------------------------------------------------------------

    async def get_or_fetch(
        self,
        key: str,
        fetcher: Callable[[], Coroutine],
        ttl: Optional[int] = None,
        register_prewarm: bool = True,
    ) -> Any:
        """Cache-Aside: return cached value or call *fetcher* on miss."""
        value, _ = await self.get_or_fetch_with_meta(
            key=key,
            fetcher=fetcher,
            ttl=ttl,
            register_prewarm=register_prewarm,
        )
        return value

    async def get_or_fetch_with_meta(
        self,
        key: str,
        fetcher: Callable[[], Coroutine],
        ttl: Optional[int] = None,
        register_prewarm: bool = True,
    ) -> Tuple[Any, bool]:
        """Cache-Aside with metadata.

        Returns ``(value, from_cache)`` so callers can report whether the
        payload came from Redis (``True``) or was fetched from the origin
        (``False``).
        """
        cached = await self.get(key)
        if cached is not None:
            return cached, True

        # Cache miss — call origin.
        fresh = await fetcher()
        await self.set(key, fresh, ttl=ttl)

        if register_prewarm:
            self._register_prewarm(key, ttl or self.default_ttl, fetcher)

        return fresh, False

    # ------------------------------------------------------------------
    # Background Pre-Warming
    # ------------------------------------------------------------------

    def _register_prewarm(
        self,
        key: str,
        ttl: int,
        fetcher: Callable[[], Coroutine],
    ) -> None:
        """Register (or update) a hot key for background pre-warming."""
        self._prewarm_registry[key] = _PrewarmEntry(
            cache_key=key,
            ttl=ttl,
            fetcher=fetcher,
            last_refreshed_at=time.monotonic(),
        )
        logger.debug("[RedisCache] Registered pre-warm entry: %s", key)

    async def _prewarm_loop(self) -> None:
        """Coroutine: periodically refresh hot keys before they expire.

        A key is refreshed when its remaining TTL drops below
        ``_PREWARM_THRESHOLD_RATIO * ttl`` seconds.
        """
        logger.info(
            "[RedisCache] Pre-warm loop started (interval=%ss).",
            self._prewarm_interval,
        )
        while not self._closed:
            await asyncio.sleep(self._prewarm_interval)
            if not self._prewarm_registry:
                continue

            snapshot = list(self._prewarm_registry.values())
            for entry in snapshot:
                remaining = await self.ttl_remaining(entry.cache_key)
                threshold = int(entry.ttl * _PREWARM_THRESHOLD_RATIO)
                if remaining < 0 or remaining <= threshold:
                    await self._refresh_entry(entry)

    async def _refresh_entry(self, entry: _PrewarmEntry) -> None:
        """Silently refresh a single pre-warm entry."""
        try:
            fresh = await entry.fetcher()
            await self.set(entry.cache_key, fresh, ttl=entry.ttl)
            entry.last_refreshed_at = time.monotonic()
            logger.info(
                "[RedisCache] Pre-warmed key: %s (TTL=%ds)",
                entry.cache_key,
                entry.ttl,
            )
        except Exception as exc:
            logger.warning(
                "[RedisCache] Pre-warm refresh failed for %s: %s",
                entry.cache_key,
                exc,
            )

    # ------------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------------

    @property
    def circuit_state(self) -> _CircuitState:
        """Expose circuit-breaker state for health-check endpoints."""
        return self._breaker.state

    async def health(self) -> Dict[str, Any]:
        """Return a diagnostic health snapshot."""
        is_alive = False
        latency_ms: Optional[float] = None
        if self._redis is not None:
            try:
                t0 = time.perf_counter()
                await self._breaker.call(self._redis.ping())
                latency_ms = round((time.perf_counter() - t0) * 1000, 2)
                is_alive = True
            except Exception:
                pass

        return {
            "redis_alive": is_alive,
            "circuit_state": self.circuit_state.value,
            "ping_latency_ms": latency_ms,
            "prewarm_registered_keys": len(self._prewarm_registry),
            "prewarm_keys": list(self._prewarm_registry.keys()),
        }


# ---------------------------------------------------------------------------
# ``cached_metric`` Decorator
# ---------------------------------------------------------------------------


def cached_metric(
    environment: str,
    category: str,
    period: str,
    ttl: int = _DEFAULT_TTL_SECONDS,
    *extra_key_parts: str,
):
    """Decorator: wraps an async function with Cache-Aside for GCP metrics.

    The decorated function must receive a :class:`RedisCache` instance as its
    first positional argument (or as keyword argument ``cache``).

    Example::

        @cached_metric("PROD", "database", "24h", ttl=60)
        async def fetch_db_metrics(cache: RedisCache, project_id: str) -> dict:
            ...  # calls GCP Monitoring API
            return payload

        result = await fetch_db_metrics(cache, project_id="my-proj")
    """

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(*args, **kwargs) -> Any:
            # Resolve cache instance: first positional arg or kwarg.
            cache_instance: Optional[RedisCache] = None
            if args and isinstance(args[0], RedisCache):
                cache_instance = args[0]
            elif "cache" in kwargs and isinstance(kwargs["cache"], RedisCache):
                cache_instance = kwargs["cache"]

            key = RedisCache.build_key(environment, category, period, *extra_key_parts)

            if cache_instance is None:
                # No cache available — call origin directly.
                logger.debug("[cached_metric] No cache instance; calling origin.")
                return await func(*args, **kwargs)

            async def fetcher() -> Any:
                return await func(*args, **kwargs)

            return await cache_instance.get_or_fetch(key, fetcher, ttl=ttl)

        return wrapper

    return decorator


# ---------------------------------------------------------------------------
# Module-level singleton (populated by application startup)
# ---------------------------------------------------------------------------

#: Global cache instance. Initialise in your FastAPI lifespan handler:
#:
#:     redis_cache = RedisCache(url=settings.REDIS_URL)
#:     await redis_cache.connect()
redis_cache: Optional[RedisCache] = None
