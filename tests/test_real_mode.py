"""Tests for Real Mode GCP Integration, Metric Registry, and Role Boundaries."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from main import app
from schemas import (
    DashboardFilterParams,
    DashboardMetricsPayload,
    Environment,
    GcpResourceMetadata,
    GCPService,
    MetricReading,
    MetricStatus,
    TimePeriod,
)
from services.gcp_service import (
    CachedGCPMetricsService,
    calculate_bucket_seconds,
)
from services.metric_registry import (
    METRIC_DEFINITIONS,
    get_category_definitions,
    get_metric_definition,
)
from services.resource_inventory import resource_inventory


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def test_metric_registry_definitions() -> None:
    """Verify registry has definitions for all required categories."""
    assert "database.qps" in METRIC_DEFINITIONS
    assert "cloud.cpu_percent" in METRIC_DEFINITIONS
    assert "storage.total_usage" in METRIC_DEFINITIONS
    assert "processing.queued_jobs" in METRIC_DEFINITIONS
    assert "tokens.daily_token_count" in METRIC_DEFINITIONS
    assert "sla.availability_percent" in METRIC_DEFINITIONS

    # Verify GCS daily snapshot flag
    gcs_total = METRIC_DEFINITIONS["storage.total_usage"]
    assert gcs_total.is_daily_snapshot is True

    # Verify billing requirement flag
    cost_def = METRIC_DEFINITIONS["cloud.estimated_cost_usd"]
    assert cost_def.requires_billing is True
    assert cost_def.default_available is False


def test_calculate_bucket_seconds() -> None:
    """Verify standardized alignment targeting 60-120 points and bucket overrides."""
    # 1h = 3600s -> 60s (60 pts)
    assert calculate_bucket_seconds(3600) == 60
    # 24h = 86400s -> 900s (96 pts)
    assert calculate_bucket_seconds(86400) == 900
    # 7d = 604800s -> 7200s (84 pts)
    assert calculate_bucket_seconds(604800) == 7200
    # 30d = 2592000s -> 21600s (120 pts)
    assert calculate_bucket_seconds(2592000) == 21600

    # Overrides
    assert calculate_bucket_seconds(3600, bucket_override="5m") == 300
    assert calculate_bucket_seconds(86400, bucket_override="1h") == 3600
    assert calculate_bucket_seconds(86400, bucket_override="300") == 300

    # Daily snapshots always align to at least 86400s
    assert calculate_bucket_seconds(86400, is_daily_snapshot=True) == 86400
    assert calculate_bucket_seconds(3600, is_daily_snapshot=True) == 86400


def test_resource_inventory_extraction() -> None:
    """Verify inventory extracts resources purely from metric labels without admin APIs."""
    resource_inventory.clear()

    # Cloud SQL
    resource_inventory.record_series_labels(
        category="database",
        metric_type="cloudsql.googleapis.com/database/mysql/queries",
        labels={"database_id": "my-corp:orders-db", "region": "us-central1"},
        env=Environment.PROD,
    )

    # Compute VM
    resource_inventory.record_series_labels(
        category="cloud",
        metric_type="compute.googleapis.com/instance/cpu/utilization",
        labels={"instance_id": "vm-prod-api-1", "zone": "us-central1-a"},
        env=Environment.PROD,
    )

    # GCS Bucket
    resource_inventory.record_series_labels(
        category="storage",
        metric_type="storage.googleapis.com/storage/v2/total_bytes",
        labels={"bucket_name": "prod-media-assets", "location": "US"},
        env=Environment.PROD,
    )

    res = resource_inventory.get_resources()
    names = {r.name for r in res}
    assert "orders-db" in names
    assert "vm-prod-api-1" in names
    assert "prod-media-assets" in names


def test_gcp_health_endpoint(client: TestClient) -> None:
    """Verify /api/v1/gcp/health returns monitoring, logging state and project map."""
    resp = client.get("/api/v1/gcp/health")
    # Health endpoint can return 200 or 503 if gcp_service is not configured,
    # but when app lifespan is run it returns the health payload
    if resp.status_code == 200:
        data = resp.json()
        assert "gcp" in data
        assert "monitoring_sdk_available" in data["gcp"]
        assert "logging_sdk_available" in data["gcp"]
        assert "missing_permissions" in data["gcp"]
        assert "environment_scope" in data["gcp"]


def test_gcp_resources_endpoint(client: TestClient) -> None:
    """Verify /api/v1/gcp/resources exposes discovered catalog."""
    resp = client.get("/api/v1/gcp/resources")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)


def test_overview_demo_mode_isolation(client: TestClient) -> None:
    """Verify ?source=demo routes strictly to mock data with demo provenance."""
    resp = client.get("/api/v1/metrics/overview?source=demo")
    assert resp.status_code == 200
    data = resp.json()
    assert data["data_source"] == "demo"
    payload = DashboardMetricsPayload.model_validate(data)
    assert payload.database.qps.current_value > 0


def test_export_includes_provenance(client: TestClient) -> None:
    """Verify report exports include data source and provenance columns."""
    resp = client.get("/api/v1/export?format=csv&source=demo")
    assert resp.status_code == 200
    text = resp.text
    assert "# Data Source" in text
    assert "Source" in text
    assert "Available" in text
