"""FastAPI Router for GCP Infrastructure & FinOps Metrics, Alerts, Thresholds, and Audit Logs.

Endpoints:
  - GET  /api/v1/metrics/overview
  - GET  /api/v1/metrics/{category}/timeseries
  - GET  /api/v1/alerts/active
  - POST /api/v1/thresholds
  - GET  /api/v1/thresholds
  - GET  /api/v1/audit-logs
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status

from schemas import (
    AlertRule,
    AlertSeverity,
    AuditLogEntry,
    DashboardFilterParams,
    DashboardMetricsPayload,
    Environment,
    MetricThresholdConfig,
    TimePeriod,
    UserRBACContext,
    UserRole,
)
from security import get_current_user, require_role
from services.audit_service import audit_service
from services.metrics_store import metrics_store

router = APIRouter()


# ----------------------------------------------------------------------------
# 1. Overview Telemetry
# ----------------------------------------------------------------------------


@router.get(
    "/metrics/overview",
    response_model=DashboardMetricsPayload,
    summary="Get Aggregated Dashboard Metrics Overview",
    description=(
        "Retrieves the comprehensive, aggregated GCP telemetry and FinOps metrics payload "
        "scoped by target environment, temporal window, service, or resource identifier."
    ),
    response_description="Composite dashboard metrics and health payload.",
)
async def get_metrics_overview(
    period: TimePeriod = Query(
        default=TimePeriod.TWENTY_FOUR_HOURS,
        alias="period",
        description="Temporal scope for metrics aggregation ('1h', '24h', '7d', '30d', 'custom')",
    ),
    env: Environment = Query(
        default=Environment.PROD,
        alias="env",
        description="Target deployment environment tier: PROD, STAGING, or DEV",
    ),
    service: Optional[str] = Query(
        default=None,
        description="GCP Service filter (e.g. 'Cloud SQL', 'Compute Engine', 'BigQuery')",
    ),
    resource_id: Optional[str] = Query(
        default=None,
        alias="resource",
        description="Specific GCP resource identifier (e.g. 'orders-primary')",
    ),
    start_time: Optional[datetime] = Query(
        default=None,
        description="UTC window start timestamp (required if period is 'custom')",
    ),
    end_time: Optional[datetime] = Query(
        default=None,
        description="UTC window end timestamp (required if period is 'custom')",
    ),
    user: UserRBACContext = Depends(get_current_user),
) -> DashboardMetricsPayload:
    """Return composite GCP FinOps overview metrics matching filter criteria."""
    try:
        filter_params = DashboardFilterParams(
            period=period,
            environment=env,
            service=service,
            resource_id=resource_id,
            start_time=start_time,
            end_time=end_time,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Filter parameter validation error: {exc}",
        ) from exc

    return metrics_store.get_overview_payload(filter_params)


# ----------------------------------------------------------------------------
# 2. Historical Time-Series (supports 30-day retention queries)
# ----------------------------------------------------------------------------


@router.get(
    "/metrics/{category}/timeseries",
    summary="Get Historical Time-Series Chart Data",
    description=(
        "Returns historical time-series observation points for a given metric category "
        "(database, cloud, storage, processing, tokens, sla). Fully supports 30-day retention "
        "and custom temporal windows for charting."
    ),
    response_description="Historical time-series chart telemetry dataset.",
)
async def get_category_timeseries(
    category: str,
    period: TimePeriod = Query(
        default=TimePeriod.TWENTY_FOUR_HOURS,
        alias="period",
        description="Temporal retention scope: '1h', '24h', '7d', '30d' (30-day retention), '90d'",
    ),
    metric_name: Optional[str] = Query(
        default=None,
        description="Specific metric name within category (e.g. 'cpu_io_percent', 'qps')",
    ),
    start_time: Optional[datetime] = Query(
        default=None,
        description="Explicit UTC window start timestamp",
    ),
    end_time: Optional[datetime] = Query(
        default=None,
        description="Explicit UTC window end timestamp",
    ),
    user: UserRBACContext = Depends(get_current_user),
) -> Dict[str, Any]:
    """Retrieve historical time-series datapoints supporting up to 30-day and 90-day retention."""
    try:
        return metrics_store.get_category_timeseries(
            category=category,
            period=period,
            metric_name=metric_name,
            start_time=start_time,
            end_time=end_time,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


# ----------------------------------------------------------------------------
# 3. Active Incident Alerts
# ----------------------------------------------------------------------------


@router.get(
    "/alerts/active",
    response_model=List[AlertRule],
    summary="Get Active Infrastructure Alerts",
    description=(
        "Returns all currently triggered alerts across GCP infrastructure resources, "
        "including current reading values, severity classification, and prescriptive "
        "rule-based remediation actions."
    ),
    response_description="List of active AlertRule instances.",
)
async def get_active_alerts(
    severity: Optional[AlertSeverity] = Query(
        default=None,
        description="Filter by alert severity (WARNING or CRITICAL)",
    ),
    resource_id: Optional[str] = Query(
        default=None,
        alias="resource",
        description="Filter by affected GCP resource ID",
    ),
    is_acknowledged: Optional[bool] = Query(
        default=None,
        description="Filter by operator acknowledgment flag",
    ),
    user: UserRBACContext = Depends(get_current_user),
) -> List[AlertRule]:
    """Retrieve active alerts requiring engineering or FinOps attention."""
    return metrics_store.get_active_alerts(
        severity=severity,
        resource_id=resource_id,
        is_acknowledged=is_acknowledged,
    )


# ----------------------------------------------------------------------------
# 4. Custom Metric Threshold Configurations (RBAC Protected: INFRA_ADMIN)
# ----------------------------------------------------------------------------


@router.post(
    "/thresholds",
    response_model=MetricThresholdConfig,
    status_code=status.HTTP_200_OK,
    summary="Update Custom Metric Threshold (Infra Admin Restricted)",
    description=(
        "Registers or updates custom warning and critical metric evaluation thresholds. "
        "Strictly restricted to users with the 'INFRA_ADMIN' role. Changes are automatically "
        "intercepted and logged by the RBAC Audit Middleware."
    ),
    response_description="The updated MetricThresholdConfig definition.",
)
async def update_metric_threshold(
    config: MetricThresholdConfig,
    current_admin: UserRBACContext = Depends(require_role(UserRole.INFRA_ADMIN)),
) -> MetricThresholdConfig:
    """Update custom alert threshold configuration (restricted to Infrastructure Admin)."""
    updated, _ = metrics_store.update_threshold(config)
    return updated


@router.get(
    "/thresholds",
    response_model=List[MetricThresholdConfig],
    summary="List Metric Threshold Configurations",
    description="Retrieves all currently registered metric threshold rules.",
    response_description="List of MetricThresholdConfig items.",
)
async def list_metric_thresholds(
    user: UserRBACContext = Depends(get_current_user),
) -> List[MetricThresholdConfig]:
    """List all registered threshold configurations."""
    return metrics_store.list_thresholds()


# ----------------------------------------------------------------------------
# 5. Audit Logging Trail
# ----------------------------------------------------------------------------


@router.get(
    "/audit-logs",
    response_model=List[AuditLogEntry],
    summary="Retrieve Audit Trails for Configuration Changes",
    description=(
        "Retrieves immutable audit records documenting threshold mutations, configuration "
        "changes, and administrative actions, including principal ID, previous/new values, "
        "and timestamps."
    ),
    response_description="List of immutable AuditLogEntry records in reverse chronological order.",
)
async def get_audit_logs(
    user_id: Optional[str] = Query(
        default=None,
        description="Filter audit records by actor user ID or service account",
    ),
    action_type: Optional[str] = Query(
        default=None,
        description="Filter by action category (e.g. 'THRESHOLD_UPDATE', 'THRESHOLD_CREATE')",
    ),
    targeted_metric: Optional[str] = Query(
        default=None,
        description="Filter by targeted metric identifier (e.g. 'database.cpu_io_percent')",
    ),
    start_time: Optional[datetime] = Query(
        default=None,
        description="Filter records starting from this UTC timestamp",
    ),
    end_time: Optional[datetime] = Query(
        default=None,
        description="Filter records up to this UTC timestamp",
    ),
    limit: int = Query(
        default=50,
        ge=1,
        le=500,
        description="Pagination limit",
    ),
    offset: int = Query(
        default=0,
        ge=0,
        description="Pagination offset",
    ),
    user: UserRBACContext = Depends(get_current_user),
) -> List[AuditLogEntry]:
    """Query audit log records for governance and change tracking."""
    return audit_service.query(
        user_id=user_id,
        action_type=action_type,
        targeted_metric=targeted_metric,
        start_time=start_time,
        end_time=end_time,
        limit=limit,
        offset=offset,
    )
