"""FastAPI Router for Report Exports.

Endpoint:
  - GET /api/v1/export: Generates and streams report downloads in CSV, XLSX, or PDF formats.
"""

from __future__ import annotations

import io
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse

from schemas import DashboardFilterParams, Environment, TimePeriod, UserRBACContext
from security import get_current_user
from services.export_service import ExportFormat, export_metrics_report
from services.metrics_store import metrics_store

router = APIRouter()


@router.get(
    "/export",
    summary="Export Metrics Report",
    description=(
        "Generates and streams high-fidelity report file downloads in CSV, multi-tab Excel (XLSX), "
        "or executive PDF summary formats, scoped by target environment and time window. "
        "Produces exact same live GCP data and provenance attributes as the dashboard UI."
    ),
    responses={
        200: {
            "description": "Streamed binary or text file download.",
            "content": {
                "text/csv": {},
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": {},
                "application/pdf": {},
            },
        },
        422: {"description": "Validation error in filter parameters or format."},
    },
)
async def export_dashboard_report(
    request: Request,
    format: ExportFormat = Query(
        default=ExportFormat.CSV,
        description="Target export file format: 'csv', 'xlsx', or 'pdf'",
    ),
    period: TimePeriod = Query(
        default=TimePeriod.TWENTY_FOUR_HOURS,
        alias="period",
        description="Temporal aggregation scope ('1h', '24h', '7d', '30d', 'custom')",
    ),
    env: Environment = Query(
        default=Environment.PROD,
        alias="env",
        description="Target deployment tier: PROD, STAGING, or DEV",
    ),
    service: Optional[str] = Query(
        default=None,
        description="GCP Service filter (e.g. 'Cloud SQL', 'Compute Engine', 'BigQuery')",
    ),
    resource_id: Optional[str] = Query(
        default=None,
        alias="resource",
        description="Specific GCP resource identifier filter",
    ),
    start_time: Optional[datetime] = Query(
        default=None,
        description="Explicit UTC window start (required for 'custom' period)",
    ),
    end_time: Optional[datetime] = Query(
        default=None,
        description="Explicit UTC window end (required for 'custom' period)",
    ),
    bucket: Optional[str] = Query(
        default=None,
        description="Alignment bucket override ('auto', '1m', '5m', '15m', '1h', '6h' or seconds)",
    ),
    source: Optional[str] = Query(
        default=None,
        description="Data mode: 'demo' for mock mode, 'gcp' or omitted for live GCP",
    ),
    user: UserRBACContext = Depends(get_current_user),
) -> StreamingResponse:
    """Generate and stream file download in CSV, XLSX, or PDF format."""
    try:
        filters = DashboardFilterParams(
            period=period,
            environment=env,
            service=service,
            resource_id=resource_id,
            start_time=start_time,
            end_time=end_time,
            bucket=bucket,
            source=source,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid filter parameters: {exc}",
        ) from exc

    gcp_service = getattr(request.app.state, "gcp_service", None)
    if source == "demo" or gcp_service is None:
        payload = metrics_store.get_overview_payload(filters)
        if source == "demo":
            payload.data_source = "demo"
    else:
        payload = await gcp_service.get_overview_payload(filters)

    try:
        file_bytes, media_type, filename = export_metrics_report(payload, format)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Report generation error: {exc}",
        ) from exc

    # Return streaming response with appropriate headers
    return StreamingResponse(
        io.BytesIO(file_bytes),
        media_type=media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Length": str(len(file_bytes)),
            "Access-Control-Expose-Headers": "Content-Disposition",
        },
    )
