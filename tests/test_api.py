"""Comprehensive Integration & Unit Tests for GCP FinOps Observatory API.

Verifies:
  - All 6 OpenAPI endpoints (/api/v1)
  - Security RBAC dependency (INFRA_ADMIN vs VIEW_ONLY)
  - Audit logging middleware and change tracking
  - 30-day retention time-series querying
  - Export handlers for CSV, XLSX (multi-tab openpyxl), and PDF (ReportLab)
"""

from __future__ import annotations

import io
from datetime import datetime, timezone
from typing import Any, Dict

import openpyxl
import pytest
from fastapi.testclient import TestClient

from main import app
from schemas import (
    AlertSeverity,
    DashboardMetricsPayload,
    Environment,
    MetricThresholdConfig,
    ThresholdOperator,
    TimePeriod,
    UserRole,
)
from services.audit_service import audit_service
from services.metrics_store import metrics_store


@pytest.fixture
def client() -> TestClient:
    """Fixture providing a FastAPI TestClient."""
    return TestClient(app)


# ============================================================================
# 1. Health & Root Diagnostics Tests
# ============================================================================


def test_health_check(client: TestClient) -> None:
    """Verify system health endpoint returns operational status."""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert "utc_time" in data


def test_api_v1_health_check(client: TestClient) -> None:
    """Verify v1 health check endpoint."""
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"


def test_root_navigation(client: TestClient) -> None:
    """Verify root discovery endpoint lists API documentation and routes."""
    response = client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert "/api/v1/metrics/overview" in data["endpoints"].values()


# ============================================================================
# 2. Metrics Overview Telemetry Tests
# ============================================================================


def test_metrics_overview_default(client: TestClient) -> None:
    """Verify default overview endpoint returns a valid DashboardMetricsPayload."""
    response = client.get("/api/v1/metrics/overview")
    assert response.status_code == 200
    data = response.json()

    # Validate against Pydantic schema
    payload = DashboardMetricsPayload.model_validate(data)
    assert payload.filter_params.environment == Environment.PROD
    assert payload.filter_params.time_period == TimePeriod.TWENTY_FOUR_HOURS
    assert payload.database.qps.current_value > 0
    assert payload.cloud.estimated_cost_usd.current_value > 0
    assert payload.storage.total_usage.current_value > 0
    assert payload.processing.queued_jobs.current_value > 0
    assert payload.tokens.daily_token_count.current_value > 0
    assert payload.sla.availability_percent.current_value > 90.0


def test_metrics_overview_with_filters(client: TestClient) -> None:
    """Verify overview with customized environment and time period filters."""
    response = client.get(
        "/api/v1/metrics/overview",
        params={
            "env": "STAGING",
            "period": "7d",
            "resource": "staging-replica",
        },
    )
    assert response.status_code == 200
    data = response.json()
    payload = DashboardMetricsPayload.model_validate(data)
    assert payload.filter_params.environment == Environment.STAGING
    assert payload.filter_params.time_period == TimePeriod.SEVEN_DAYS
    assert payload.filter_params.resource_id == "staging-replica"


# ============================================================================
# 3. Historical Time-Series (30-day retention query test)
# ============================================================================


def test_timeseries_30_day_retention_query(client: TestClient) -> None:
    """Verify 30-day retention historical query across metric categories."""
    response = client.get(
        "/api/v1/metrics/database/timeseries",
        params={"period": "30d", "metric_name": "cpu_io_percent"},
    )
    assert response.status_code == 200
    data = response.json()

    assert data["category"] == "database"
    assert data["period"] == "30d"
    assert "cpu_io_percent" in data["series"]
    points = data["series"]["cpu_io_percent"]

    # Ensure 30-day retention points span roughly 30 days
    assert len(points) >= 30
    first_pt = datetime.fromisoformat(points[0]["timestamp"].replace("Z", "+00:00"))
    last_pt = datetime.fromisoformat(points[-1]["timestamp"].replace("Z", "+00:00"))
    delta_days = (last_pt - first_pt).total_seconds() / 86400.0
    assert 28.0 <= delta_days <= 32.0


def test_timeseries_all_categories(client: TestClient) -> None:
    """Verify all 6 categories support timeseries queries."""
    categories = ["database", "cloud", "storage", "processing", "tokens", "sla"]
    for cat in categories:
        resp = client.get(f"/api/v1/metrics/{cat}/timeseries", params={"period": "24h"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["category"] == cat
        assert len(data["series"]) > 0


def test_timeseries_invalid_category(client: TestClient) -> None:
    """Verify 400 error when querying a non-existent category."""
    response = client.get("/api/v1/metrics/nonexistent/timeseries")
    assert response.status_code == 400
    assert "Unknown metric category" in response.json()["detail"]


# ============================================================================
# 4. Active Alerts Tests
# ============================================================================


def test_active_alerts_retrieval(client: TestClient) -> None:
    """Verify active alerts contain severity and prescriptive action items."""
    response = client.get("/api/v1/alerts/active")
    assert response.status_code == 200
    alerts = response.json()
    assert isinstance(alerts, list)
    assert len(alerts) > 0

    first_alert = alerts[0]
    assert "rule_id" in first_alert
    assert "severity" in first_alert
    assert "suggested_action" in first_alert
    assert len(first_alert["suggested_action"]) > 10


def test_active_alerts_filtering(client: TestClient) -> None:
    """Verify active alerts filtered by severity."""
    response = client.get("/api/v1/alerts/active", params={"severity": "CRITICAL"})
    assert response.status_code == 200
    alerts = response.json()
    for a in alerts:
        assert a["severity"] == "CRITICAL"


# ============================================================================
# 5. Security & RBAC Enforcement Tests
# ============================================================================


def test_threshold_update_forbidden_for_view_only(client: TestClient) -> None:
    """Verify that VIEW_ONLY users are blocked from mutating metric thresholds (403 Forbidden)."""
    payload = {
        "metric_name": "database.cpu_io_percent",
        "warning_threshold": 65.0,
        "critical_threshold": 80.0,
        "operator": ">",
        "metadata": {"reason": "Unauthorized test update"},
    }

    # Case A: Default anonymous request (resolves to VIEW_ONLY)
    response_anon = client.post("/api/v1/thresholds", json=payload)
    assert response_anon.status_code == 403
    assert "Forbidden" in response_anon.text

    # Case B: Explicit VIEW_ONLY role header
    response_viewer = client.post(
        "/api/v1/thresholds",
        json=payload,
        headers={"X-User-Role": "VIEW_ONLY", "X-User-Id": "analyst-viewer"},
    )
    assert response_viewer.status_code == 403
    data = response_viewer.json()
    assert data["detail"]["required_role"] == UserRole.INFRA_ADMIN.value


def test_threshold_update_allowed_for_infra_admin(client: TestClient) -> None:
    """Verify that INFRA_ADMIN users can mutate thresholds, with audit recording."""
    initial_audit_count = audit_service.count()

    payload = {
        "metric_name": "cloud.cpu_percent",
        "warning_threshold": 72.0,
        "critical_threshold": 88.0,
        "operator": ">",
        "metadata": {
            "reason": "Production autoscaler adjustment",
            "author": "lead-infra-admin@gcp-corp.internal",
        },
    }

    response = client.post(
        "/api/v1/thresholds",
        json=payload,
        headers={
            "X-User-Role": "INFRA_ADMIN",
            "X-User-Id": "lead-infra-admin@gcp-corp.internal",
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["metric_name"] == "cloud.cpu_percent"
    assert data["warning_threshold"] == 72.0
    assert data["critical_threshold"] == 88.0

    # Verify audit middleware headers
    assert response.headers.get("X-Audit-Recorded") == "true"
    assert "X-Audit-Log-Id" in response.headers

    # Verify audit service recorded the change
    assert audit_service.count() == initial_audit_count + 1


def test_threshold_update_allowed_with_bearer_token(client: TestClient) -> None:
    """Verify INFRA_ADMIN authorization via Bearer token."""
    payload = {
        "metric_name": "storage.bucket_volume_usage_percent",
        "warning_threshold": 78.0,
        "critical_threshold": 92.0,
        "operator": ">",
        "metadata": {"reason": "Token-based automation"},
    }

    response = client.post(
        "/api/v1/thresholds",
        json=payload,
        headers={"Authorization": "Bearer infra-admin-token"},
    )
    assert response.status_code == 200
    assert response.headers.get("X-Audit-Recorded") == "true"


# ============================================================================
# 6. Audit Logging Retrieval & Trail Tests
# ============================================================================


def test_audit_logs_query(client: TestClient) -> None:
    """Verify audit logs retrieval and filtering."""
    response = client.get("/api/v1/audit-logs")
    assert response.status_code == 200
    logs = response.json()
    assert isinstance(logs, list)
    assert len(logs) > 0

    first = logs[0]
    assert "log_id" in first
    assert "user_id" in first
    assert "action_type" in first
    assert "targeted_metric" in first
    assert "timestamp" in first


def test_audit_logs_filter_by_metric(client: TestClient) -> None:
    """Verify audit logs filtered by targeted metric."""
    response = client.get(
        "/api/v1/audit-logs",
        params={"targeted_metric": "database.cpu_io_percent"},
    )
    assert response.status_code == 200
    logs = response.json()
    for entry in logs:
        assert "database.cpu_io_percent" in entry["targeted_metric"]


# ============================================================================
# 7. Export Handlers Tests (CSV, XLSX, PDF)
# ============================================================================


def test_export_csv(client: TestClient) -> None:
    """Verify streaming CSV export handler."""
    response = client.get(
        "/api/v1/export",
        params={"format": "csv", "env": "PROD", "period": "24h"},
    )
    assert response.status_code == 200
    assert "text/csv" in response.headers["Content-Type"]
    assert "attachment;" in response.headers["Content-Disposition"]
    assert ".csv" in response.headers["Content-Disposition"]

    content = response.text
    assert "# GCP FINOPS & INFRASTRUCTURE OBSERVATORY REPORT" in content
    assert "--- METRIC READINGS SUMMARY ---" in content
    assert "Database" in content
    assert "Cloud & Compute" in content


def test_export_xlsx_multi_tab(client: TestClient) -> None:
    """Verify streaming Excel (XLSX) multi-tab export handler."""
    response = client.get(
        "/api/v1/export",
        params={"format": "xlsx", "env": "PROD", "period": "24h"},
    )
    assert response.status_code == 200
    assert (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        in response.headers["Content-Type"]
    )
    assert ".xlsx" in response.headers["Content-Disposition"]

    # Verify openpyxl can load and inspect multi-tab sheets
    excel_bytes = io.BytesIO(response.content)
    wb = openpyxl.load_workbook(excel_bytes)
    sheet_names = wb.sheetnames

    expected_sheets = [
        "Executive Overview",
        "Database",
        "Cloud & Compute",
        "Storage & IOPS",
        "Processing & Jobs",
        "Token & AI FinOps",
        "Platform SLA",
        "Active Alerts",
    ]
    for expected in expected_sheets:
        assert expected in sheet_names, f"Expected sheet '{expected}' in workbook"


def test_export_pdf(client: TestClient) -> None:
    """Verify streaming PDF report generation via ReportLab."""
    response = client.get(
        "/api/v1/export",
        params={"format": "pdf", "env": "PROD", "period": "24h"},
    )
    assert response.status_code == 200
    assert "application/pdf" in response.headers["Content-Type"]
    assert ".pdf" in response.headers["Content-Disposition"]

    pdf_bytes = response.content
    # PDF files start with %PDF- header magic bytes
    assert pdf_bytes.startswith(b"%PDF-")
    assert len(pdf_bytes) > 1000
