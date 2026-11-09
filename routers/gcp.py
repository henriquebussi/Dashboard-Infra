"""GCP Live Metrics Router — Cloud Monitoring & Logging Integration.

Endpoints (prefix: /api/v1/gcp):
  GET  /gcp/metrics/{category}            — Live GCP time-series (cache-aside)
  GET  /gcp/metrics/tokens/usage          — Vertex AI token-usage log entries
  GET  /gcp/metrics/database/slow-queries — Cloud SQL slow-query log entries
  GET  /gcp/health                        — Cache + GCP API circuit-breaker status
  POST /gcp/cache/flush                   — Flush Redis namespace (INFRA_ADMIN only)
  POST /gcp/cache/prewarm                 — Trigger manual pre-warm (INFRA_ADMIN only)

All metric endpoints apply the same RBAC dependency used by the existing
metrics router (get_current_user), and honour the same environment/period
query parameters already established in the dashboard schema.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from schemas import Environment, GcpResourceMetadata, TimePeriod, UserRBACContext, UserRole
from security import get_current_user, require_role
from services.resource_inventory import resource_inventory

logger = logging.getLogger("gcp_observatory.gcp_router")

router = APIRouter()


# ---------------------------------------------------------------------------
# Service accessor helpers
# ---------------------------------------------------------------------------

def _get_gcp_service(request: Request):
    """Retrieve the CachedGCPMetricsService instance from app state."""
    svc = getattr(request.app.state, "gcp_service", None)
    if svc is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "GCP Integration Service is not initialised. "
                "Ensure GCP_PROJECT_ID is set and the app lifespan completed."
            ),
        )
    return svc


def _get_cache(request: Request):
    """Retrieve the RedisCache instance from app state."""
    cache = getattr(request.app.state, "redis_cache", None)
    if cache is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Redis cache is not initialised.",
        )
    return cache


# ---------------------------------------------------------------------------
# 1. Live GCP Metrics (Cache-Aside)
# ---------------------------------------------------------------------------


@router.get(
    "/gcp/metrics/{category}",
    summary="Live GCP Metrics — Cache-Aside",
    description=(
        "Returns live GCP Cloud Monitoring time-series for the specified category "
        "(cloud, database, storage, processing, tokens, sla). "
        "Results are served from Redis when cached (TTL configurable, default 60 s); "
        "on cache miss, the Cloud Monitoring API v3 is queried, the result is stored, "
        "and the key is registered for background pre-warming."
    ),
    response_description="Metric time-series payload with aggregation statistics.",
    tags=["GCP Live Metrics"],
)
async def get_live_gcp_metrics(
    category: str,
    request: Request,
    period: TimePeriod = Query(
        default=TimePeriod.TWENTY_FOUR_HOURS,
        description="Observation window: '1h', '24h', '7d', '30d'.",
    ),
    env: Environment = Query(
        default=Environment.PROD,
        description="Deployment environment tier: PROD, STAGING, DEV.",
    ),
    ttl: Optional[int] = Query(
        default=None,
        ge=10,
        le=3600,
        description="Override Redis TTL in seconds (10–3600). Defaults to service default (60 s).",
    ),
    instance_id: Optional[str] = Query(
        default=None,
        description="Compute Engine instance ID filter (category=cloud only).",
    ),
    database_id: Optional[str] = Query(
        default=None,
        description="Cloud SQL instance ID filter (category=database only).",
    ),
    bucket_name: Optional[str] = Query(
        default=None,
        description="Cloud Storage bucket name filter (category=storage only).",
    ),
    user: UserRBACContext = Depends(get_current_user),
) -> Dict[str, Any]:
    """Return live GCP metrics for *category*, served from Redis cache when hot."""
    gcp = _get_gcp_service(request)

    # Build optional resource-label kwargs.
    kwargs: Dict[str, Any] = {}
    if instance_id:
        kwargs["instance_id"] = instance_id
    if database_id:
        kwargs["database_id"] = database_id
    if bucket_name:
        kwargs["bucket_name"] = bucket_name

    try:
        return await gcp.get_metrics(
            environment=env.value,
            category=category,
            period=period.value,
            ttl=ttl,
            **kwargs,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc


# ---------------------------------------------------------------------------
# 2. Token Usage Log Entries (Vertex AI)
# ---------------------------------------------------------------------------


@router.get(
    "/gcp/metrics/tokens/usage",
    summary="Vertex AI Token Usage — Cloud Logging",
    description=(
        "Pulls Vertex AI token-usage events from Cloud Logging sinks "
        "(``aiplatform.googleapis.com/Endpoint`` resource type). "
        "Results are cached with a 120-second TTL."
    ),
    response_description="Token usage log entries with count and timestamps.",
    tags=["GCP Live Metrics"],
)
async def get_token_usage(
    request: Request,
    hours: int = Query(
        default=24,
        ge=1,
        le=168,
        description="Look-back window in hours (1–168).",
    ),
    env: Environment = Query(
        default=Environment.PROD,
        description="Deployment environment tier.",
    ),
    ttl: int = Query(
        default=120,
        ge=10,
        le=3600,
        description="Redis TTL override in seconds.",
    ),
    user: UserRBACContext = Depends(get_current_user),
) -> Dict[str, Any]:
    """Return Vertex AI token-usage log entries, served from cache when hot."""
    gcp = _get_gcp_service(request)
    return await gcp.get_token_usage(environment=env.value, hours=hours, ttl=ttl)


# ---------------------------------------------------------------------------
# 3. Cloud SQL Slow Queries — Log-Based
# ---------------------------------------------------------------------------


@router.get(
    "/gcp/metrics/database/slow-queries",
    summary="Cloud SQL Slow Queries — Cloud Logging",
    description=(
        "Pulls Cloud SQL slow-query log entries from Cloud Logging "
        "(``cloudsql_database`` resource type). "
        "Only entries with ``duration >= threshold_ms`` are returned."
    ),
    response_description="Slow-query log entries with parsed duration and query text.",
    tags=["GCP Live Metrics"],
)
async def get_slow_queries(
    request: Request,
    hours: int = Query(default=24, ge=1, le=168, description="Look-back window in hours."),
    threshold_ms: int = Query(
        default=1000,
        ge=100,
        le=60000,
        description="Minimum query duration in milliseconds to include (100–60000).",
    ),
    database_id: Optional[str] = Query(
        default=None,
        description="Cloud SQL instance ID label filter.",
    ),
    env: Environment = Query(default=Environment.PROD, description="Environment tier."),
    ttl: int = Query(default=60, ge=10, le=3600, description="Redis TTL override."),
    user: UserRBACContext = Depends(get_current_user),
) -> Dict[str, Any]:
    """Return Cloud SQL slow-query log entries, served from cache when hot."""
    gcp = _get_gcp_service(request)
    kwargs: Dict[str, Any] = {}
    if database_id:
        kwargs["database_id"] = database_id
    return await gcp.get_slow_queries(
        environment=env.value,
        hours=hours,
        threshold_ms=threshold_ms,
        ttl=ttl,
        **kwargs,
    )


# ---------------------------------------------------------------------------
# 3b. Platform Error Logs — Cloud Logging
# ---------------------------------------------------------------------------


@router.get(
    "/gcp/logs/errors",
    summary="Platform Error Logs — Cloud Logging",
    description=(
        "Pulls error log records (severity>=ERROR) from Cloud Logging. "
        "Queries are strictly bounded with time-windows and max_results."
    ),
    response_description="Bounded error log entries with capping and estimation indicators.",
    tags=["GCP Live Metrics"],
)
async def get_error_logs(
    request: Request,
    hours: int = Query(default=24, ge=1, le=168, description="Look-back window in hours."),
    max_entries: int = Query(default=200, ge=1, le=1000, description="Maximum entries to return."),
    service_filter: Optional[str] = Query(default=None, description="Optional resource filter."),
    env: Environment = Query(default=Environment.PROD, description="Environment tier."),
    ttl: int = Query(default=60, ge=10, le=3600, description="Redis TTL override."),
    user: UserRBACContext = Depends(get_current_user),
) -> Dict[str, Any]:
    """Return bounded error log entries, served from cache when hot."""
    gcp = _get_gcp_service(request)
    return await gcp.get_error_logs(
        environment=env.value,
        hours=hours,
        ttl=ttl,
        max_entries=max_entries,
        service_filter=service_filter,
    )


# ---------------------------------------------------------------------------
# 3c. Discovered GCP Resources Catalog
# ---------------------------------------------------------------------------


@router.get(
    "/gcp/resources",
    response_model=List[GcpResourceMetadata],
    summary="Discovered GCP Resources Catalog",
    description=(
        "Returns active GCP resources (Cloud SQL, Compute VMs, GCS Buckets, BigQuery, Vertex AI) "
        "derived purely from Cloud Monitoring time-series metric labels. Zero admin APIs called."
    ),
    response_description="List of inventoried GCP resources with metadata.",
    tags=["GCP Live Metrics"],
)
async def get_discovered_resources(
    env: Optional[Environment] = Query(default=None, description="Environment tier filter."),
    service: Optional[str] = Query(default=None, description="GCP Service filter."),
    search: Optional[str] = Query(default=None, description="Search query across resource name/region."),
    user: UserRBACContext = Depends(get_current_user),
) -> List[GcpResourceMetadata]:
    """Return list of discovered GCP resources derived dynamically from metric labels."""
    return resource_inventory.get_resources(env=env, service=service, search=search)


# ---------------------------------------------------------------------------
# 4. GCP + Cache Health
# ---------------------------------------------------------------------------


@router.get(
    "/gcp/health",
    summary="GCP Integration Service Health",
    description=(
        "Returns the health of both the Redis cache layer (ping latency, circuit state, "
        "pre-warm registry) and the GCP API integration (SDK availability, project, "
        "circuit state)."
    ),
    response_description="Diagnostic health snapshot for cache and GCP API.",
    tags=["Diagnostics"],
)
async def gcp_health(
    request: Request,
    user: UserRBACContext = Depends(get_current_user),
) -> Dict[str, Any]:
    """Return combined GCP + Redis cache health snapshot."""
    gcp = _get_gcp_service(request)
    return await gcp.health()


# ---------------------------------------------------------------------------
# 5. Cache Management (INFRA_ADMIN only)
# ---------------------------------------------------------------------------


@router.post(
    "/gcp/cache/flush",
    summary="Flush Redis Metric Cache (Infra Admin Only)",
    description=(
        "Deletes all keys matching the ``metrics:*`` namespace from Redis. "
        "Use with caution — subsequent requests will trigger live GCP API calls "
        "until the cache re-warms."
    ),
    response_description="Number of keys flushed and namespace pattern used.",
    tags=["GCP Live Metrics"],
    status_code=status.HTTP_200_OK,
)
async def flush_cache(
    request: Request,
    pattern: str = Query(
        default="metrics:*",
        description="Redis key pattern to flush (default: all metric keys).",
    ),
    admin: UserRBACContext = Depends(require_role(UserRole.INFRA_ADMIN)),
) -> Dict[str, Any]:
    """Flush the Redis metric cache namespace (restricted to INFRA_ADMIN)."""
    cache = _get_cache(request)
    deleted = await cache.flush_namespace(pattern=pattern)
    logger.warning(
        "[GCPRouter] Cache flushed by %s — %d keys deleted (pattern=%s)",
        admin.user_id,
        deleted,
        pattern,
    )
    return {
        "flushed": True,
        "keys_deleted": deleted,
        "pattern": pattern,
        "flushed_by": admin.user_id,
    }


@router.post(
    "/gcp/cache/prewarm",
    summary="Trigger Manual Cache Pre-Warm (Infra Admin Only)",
    description=(
        "Eagerly populates Redis with standard GCP metric keys across the specified "
        "environments, categories, and periods. Useful after a flush or cold start."
    ),
    response_description="List of successfully pre-warmed cache keys.",
    tags=["GCP Live Metrics"],
    status_code=status.HTTP_200_OK,
)
async def prewarm_cache(
    request: Request,
    environments: List[str] = Query(
        default=["PROD", "STAGING"],
        description="Environment tiers to pre-warm.",
    ),
    categories: List[str] = Query(
        default=["cloud", "database", "storage"],
        description="Metric categories to pre-warm.",
    ),
    periods: List[str] = Query(
        default=["1h", "24h"],
        description="Time periods to pre-warm.",
    ),
    admin: UserRBACContext = Depends(require_role(UserRole.INFRA_ADMIN)),
) -> Dict[str, Any]:
    """Manually trigger cache pre-warming (restricted to INFRA_ADMIN)."""
    gcp = _get_gcp_service(request)
    warmed = await gcp.prewarm_standard_keys(
        environments=environments,
        categories=categories,
        periods=periods,
    )
    logger.info(
        "[GCPRouter] Manual pre-warm by %s — %d keys warmed.",
        admin.user_id,
        len(warmed),
    )
    return {
        "prewarmed": True,
        "keys_warmed": len(warmed),
        "cache_keys": warmed,
        "triggered_by": admin.user_id,
    }
