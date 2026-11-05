"""GCP Infrastructure & FinOps Observatory - FastAPI Application.

Production-grade FastAPI application integrating:
  - OpenAPI Router Structure (/api/v1)
  - RBAC Security Dependencies & Granular Permission Checks
  - RBAC Audit Middleware tracking mutations to threshold configs
  - Telemetry endpoints supporting 30-day retention historical queries
  - Multi-format file export streaming handlers (CSV, XLSX, PDF)
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict

from fastapi import FastAPI, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from routers.exports import router as exports_router
from routers.metrics import router as metrics_router
from security import AuditLoggingMiddleware

# ============================================================================
# Application Factory & OpenAPI Metadata
# ============================================================================

app = FastAPI(
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
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Adjust for production domains
    allow_credentials=True,
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
        },
    }


# ============================================================================
# Execution Entry Point
# ============================================================================

if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
