"""GCP Infrastructure & FinOps Observatory - FastAPI Application.

Production-grade FastAPI application integrating:
  - OpenAPI Router Structure (/api/v1)
  - RBAC Security Dependencies & Granular Permission Checks
  - RBAC Audit Middleware tracking mutations to threshold configs
  - Telemetry endpoints supporting 30-day retention historical queries
  - Multi-format file export streaming handlers (CSV, XLSX, PDF)
  - GCP Integration Service with Redis Cache-Aside Layer (< 2 s SLA)
"""

from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

# Load environment variables from .env as early as possible so every module
# (routers, services, security) sees the same configuration.
try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - optional during minimal installs
    def load_dotenv(*_args: Any, **_kwargs: Any) -> bool:
        return False

# Resolve the file next to main.py so the app works from any CWD.
load_dotenv(Path(__file__).with_name(".env"))

from fastapi import FastAPI, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from routers.exports import router as exports_router
from routers.gcp import router as gcp_router
from routers.metrics import router as metrics_router
from security import AuditLoggingMiddleware
from services.cache import RedisCache
from services.gcp_service import CachedGCPMetricsService

logger = logging.getLogger("gcp_observatory.main")

# ============================================================================
# GCP Integration Service — Lifespan (startup / shutdown)
# ============================================================================


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage the lifecycle of the Redis cache and GCP integration service."""
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    redis_enabled = os.getenv("REDIS_ENABLED", "true").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    project_id = os.getenv("GCP_PROJECT_ID", "")
    project_id_was_set = bool(project_id)

    # Guard against the most common misconfiguration: pasting an OAuth Client ID,
    # API key, or email into GCP_PROJECT_ID instead of the GCP project ID.
    if project_id and (
        project_id.lower().endswith(".apps.googleusercontent.com")
        or project_id.lower().startswith("aiza")
        or "@" in project_id
        or " " in project_id
    ):
        logger.error(
            "[Lifespan] GCP_PROJECT_ID=%r is not a valid GCP project ID. "
            "Use the Project ID from Google Cloud Console → project selector "
            "(not an OAuth Client ID or API key). Live GCP metrics disabled.",
            project_id,
        )
        project_id = ""

    default_ttl = int(os.getenv("GCP_CACHE_TTL_SECONDS", "60"))

    # --- Startup ---
    redis_cache = RedisCache(
        url=redis_url,
        default_ttl=default_ttl,
        prewarm_interval=float(os.getenv("GCP_PREWARM_INTERVAL_SECONDS", "15")),
        max_connections=int(os.getenv("REDIS_MAX_CONNECTIONS", "20")),
        enabled=redis_enabled,
    )
    await redis_cache.connect()

    gcp_service: CachedGCPMetricsService | None = None
    if project_id:
        gcp_service = CachedGCPMetricsService(
            project_id=project_id,
            cache=redis_cache,
            default_ttl=default_ttl,
            gcp_circuit_failure_threshold=int(
                os.getenv("GCP_CIRCUIT_FAILURE_THRESHOLD", "5")
            ),
            gcp_circuit_open_window=float(
                os.getenv("GCP_CIRCUIT_OPEN_WINDOW_SECONDS", "60")
            ),
        )
        # Eagerly seed standard metric keys.
        prewarm_envs = os.getenv("GCP_PREWARM_ENVIRONMENTS", "PROD,STAGING").split(",")
        prewarm_cats = os.getenv(
            "GCP_PREWARM_CATEGORIES", "cloud,database,storage"
        ).split(",")
        prewarm_periods = os.getenv("GCP_PREWARM_PERIODS", "1h,24h").split(",")
        prewarm_timeout = float(os.getenv("GCP_PREWARM_TIMEOUT_SECONDS", "10"))
        try:
            await asyncio.wait_for(
                gcp_service.prewarm_standard_keys(
                    environments=prewarm_envs,
                    categories=prewarm_cats,
                    periods=prewarm_periods,
                ),
                timeout=prewarm_timeout,
            )
        except asyncio.TimeoutError:
            logger.warning(
                "[Lifespan] Pre-warm timed out after %.0fs — continuing without it.",
                prewarm_timeout,
            )
        except Exception as exc:
            logger.warning("[Lifespan] Pre-warm failed/skipped (non-fatal): %s", exc)
    else:
        if not project_id_was_set:
            logger.warning(
                "[Lifespan] GCP_PROJECT_ID not set — GCP Integration Service disabled. "
                "Set the environment variable to enable live GCP metrics."
            )

    # Expose to routers via app.state.
    app.state.redis_cache = redis_cache
    app.state.gcp_service = gcp_service

    logger.info("[Lifespan] Startup complete. Redis=%s | GCP project=%s", redis_url, project_id or "N/A")

    yield  # ← app is running

    # --- Shutdown ---
    await redis_cache.close()
    logger.info("[Lifespan] Shutdown complete.")


# ============================================================================
# Application Factory & OpenAPI Metadata
# ============================================================================

app = FastAPI(
    lifespan=lifespan,
    title="GCP FinOps & Infrastructure Observatory API",
    description="""
Enterprise-grade observability and FinOps REST API designed for Google Cloud Platform.

### Core Capabilities:
* **Aggregated Telemetry (`/api/v1/metrics/overview`)**: Rollups across Cloud SQL, Compute Engine, Cloud Storage, BigQuery, and Vertex AI.
* **Historical Time-Series (`/api/v1/metrics/{category}/timeseries`)**: Long-range retention queries supporting 30-day historical chart telemetry.
* **Active Incidents (`/api/v1/alerts/active`)**: Real-time threshold alerts with prescriptive remediation action guidance.
* **Dynamic Guardrails (`/api/v1/thresholds`)**: Custom metric threshold updates restricted to `INFRA_ADMIN` role.
* **Audit Trail Governance (`/api/v1/audit-logs`)**: Immutable event logging tracking who altered thresholds, what was changed, and timestamps.
* **Multi-Format Report Streaming (`/api/v1/export`)**: Direct downloads in CSV, multi-tab Excel (`.xlsx`), and executive PDF summary formats.
* **Live GCP Metrics (`/api/v1/gcp/metrics/{category}`)**: Real-time Cloud Monitoring API v3 data served via Redis Cache-Aside (< 2 s SLA).
* **Token Usage & Slow Queries (`/api/v1/gcp/metrics/tokens/usage`, `/api/v1/gcp/metrics/database/slow-queries`)**: Log-based metric queries from Cloud Logging sinks.
    """,
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    contact={
        "name": "FinOps & Cloud Infrastructure Architecture Team",
        "email": "finops-eng@gcp-corp.internal",
    },
    license_info={
        "name": "Proprietary / Enterprise Confidential",
    },
)

# ============================================================================
# Middlewares
# ============================================================================

# 1. Cross-Origin Resource Sharing (CORS)
# Comma-separated origins from CORS_ORIGINS (defaults to the Vite dev server).
_cors_origins_raw = os.getenv(
    "CORS_ORIGINS",
    "http://localhost:5173,http://127.0.0.1:5173",
)
_cors_origins = [origin.strip() for origin in _cors_origins_raw.split(",") if origin.strip()]
_allow_all_origins = "*" in _cors_origins

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    # Browsers reject wildcard origins together with credentials.
    allow_credentials=not _allow_all_origins,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition", "X-Audit-Recorded", "X-Audit-Log-Id"],
)

# 2. RBAC Audit Logging Middleware
app.add_middleware(AuditLoggingMiddleware)

# ============================================================================
# Routers Registration (/api/v1)
# ============================================================================

app.include_router(
    metrics_router,
    prefix="/api/v1",
    tags=["Metrics, Alerts & Governance"],
)

app.include_router(
    exports_router,
    prefix="/api/v1",
    tags=["Report Exports"],
)

app.include_router(
    gcp_router,
    prefix="/api/v1",
    tags=["GCP Live Metrics"],
)

# ============================================================================
# Platform Health & Root Diagnostic Endpoints
# ============================================================================


@app.get(
    "/health",
    tags=["Diagnostics"],
    summary="Service Health Check",
    status_code=status.HTTP_200_OK,
)
@app.get(
    "/api/v1/health",
    tags=["Diagnostics"],
    summary="API v1 Health Check",
    status_code=status.HTTP_200_OK,
)
async def health_check() -> Dict[str, Any]:
    """Return runtime service health, timestamp, and version."""
    return {
        "status": "healthy",
        "service": "gcp-finops-observatory-api",
        "version": "1.0.0",
        "utc_time": datetime.now(timezone.utc).isoformat(),
    }


@app.get(
    "/",
    tags=["Diagnostics"],
    summary="API Root Information",
    status_code=status.HTTP_200_OK,
)
async def root() -> Dict[str, Any]:
    """API entry point with navigation links."""
    return {
        "title": "GCP FinOps & Infrastructure Observatory API",
        "version": "1.0.0",
        "documentation": {
            "swagger_ui": "/docs",
            "redoc": "/redoc",
            "openapi_json": "/openapi.json",
        },
        "endpoints": {
            "metrics_overview": "/api/v1/metrics/overview",
            "timeseries": "/api/v1/metrics/{category}/timeseries",
            "active_alerts": "/api/v1/alerts/active",
            "thresholds": "/api/v1/thresholds",
            "audit_logs": "/api/v1/audit-logs",
            "report_export": "/api/v1/export",
            "gcp_live_metrics": "/api/v1/gcp/metrics/{category}",
            "gcp_token_usage": "/api/v1/gcp/metrics/tokens/usage",
            "gcp_slow_queries": "/api/v1/gcp/metrics/database/slow-queries",
            "gcp_health": "/api/v1/gcp/health",
            "gcp_cache_flush": "/api/v1/gcp/cache/flush",
            "gcp_cache_prewarm": "/api/v1/gcp/cache/prewarm",
        },
    }


# ============================================================================
# Execution Entry Point
# ============================================================================

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host=os.getenv("API_HOST", "0.0.0.0"),
        port=int(os.getenv("API_PORT", "8000")),
        reload=True,
    )
