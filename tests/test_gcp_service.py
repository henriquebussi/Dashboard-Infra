"""Regression tests for the GCP Monitoring request builder."""

from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import Any, List

import pytest

from services.gcp_service import (
    GCPServiceError,
    GCPMonitoringService,
    _GCPCircuitBreaker,
)


class _FakeMonitoringClient:
    def __init__(self) -> None:
        self.requests: List[Any] = []

    def list_time_series(self, request: Any) -> List[Any]:
        self.requests.append(request)
        return []


def test_query_metric_assigns_alignment_period(monkeypatch) -> None:
    """The aggregation period must be assigned as a timedelta/Duration.

    Newer Monitoring clients expose ``Aggregation.alignment_period`` as a
    read-only ``timedelta`` property, so mutating ``.seconds`` raises
    ``AttributeError`` inside the executor.
    """
    service = GCPMonitoringService(project_id="test-project")
    client = _FakeMonitoringClient()
    monkeypatch.setattr(service, "_get_monitoring_client", lambda: client)

    result = asyncio.run(
        service.query_metric(
            "compute.googleapis.com/instance/cpu/utilization",
            period="1h",
            alignment_period_seconds=120,
        )
    )

    assert result == []
    assert len(client.requests) == 1
    assert client.requests[0].aggregation.alignment_period == timedelta(seconds=120)


def test_open_circuit_cancels_unawaited_future() -> None:
    """An open circuit must not leak executor futures with unread exceptions."""

    async def scenario() -> None:
        breaker = _GCPCircuitBreaker(failure_threshold=1, open_window=60)
        await breaker._open(RuntimeError("quota exhausted"))

        future = asyncio.get_running_loop().create_future()
        with pytest.raises(GCPServiceError, match="circuit OPEN"):
            await breaker.call(future)

        assert future.cancelled()

    asyncio.run(scenario())


def test_catalog_and_raw_samples_via_dashboard_api(monkeypatch):
    from unittest.mock import Mock
    import httpx
    from google.api import metric_pb2
    from google.api_core.exceptions import PermissionDenied
    from google.cloud import monitoring_v3
    from main import app
    from services.gcp_service import CachedGCPMetricsService

    svc = CachedGCPMetricsService("default-project", Mock(), project_map={"DEV": "dev-project"})
    api = Mock()
    monkeypatch.setattr(svc._client_for_project("dev-project"), "_get_monitoring_client", lambda: api)
    monkeypatch.setattr(app.state, "gcp_service", svc, raising=False)
    class ASGIClient:
        def get(self, url, **kwargs):
            async def read():
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test", headers={"Authorization": "Bearer test-viewer"}) as client:
                    return await client.get(url, **kwargs)
            return asyncio.run(read())
    client = ASGIClient()
    metric = "custom.googleapis.com/test/healthy"
    api.list_metric_descriptors.return_value.pages = [monitoring_v3.ListMetricDescriptorsResponse(
        metric_descriptors=[metric_pb2.MetricDescriptor(type=metric, unit="1")], next_page_token="catalog-next",
    )]
    catalog = client.get("/api/v1/gcp/catalog", params={"env": "DEV", "active_only": False})
    assert catalog.status_code == 200
    assert catalog.json()["metrics"][0]["type"] == metric
    assert catalog.json()["next_page_token"] == "catalog-next"
    assert api.list_metric_descriptors.call_args.kwargs["request"] == {
        "name": "projects/dev-project", "active_only": False, "filter": 'project="dev-project"',
        "page_size": 100, "page_token": "",
    }

    assert client.get("/api/v1/gcp/catalog", params={"env": "DEV", "page_token": "catalog-next"}).status_code == 200
    assert api.list_metric_descriptors.call_args.kwargs["request"]["page_token"] == "catalog-next"
    assert api.list_metric_descriptors.call_args.kwargs["retry"] is None
    assert api.list_metric_descriptors.call_args.kwargs["timeout"] == 15
    api.list_time_series.return_value.pages = [monitoring_v3.ListTimeSeriesResponse(
        time_series=[{"points": [{"value": {"bool_value": False}}]}], next_page_token="more",
    )]
    url = "/api/v1/gcp/catalog/series"
    params = {"env": "DEV", "metric_type": metric, "period": "7d"}
    page = client.get(url, params=params)
    assert page.status_code == 200
    assert page.json()["series"][0]["points"][0]["value"] == {"bool_value": False}
    assert page.json()["project"] == "dev-project"
    assert page.json()["scope"] == "project-mapped"
    first = api.list_time_series.call_args.kwargs["request"]
    assert first["interval"].end_time - first["interval"].start_time == timedelta(days=7)
    assert 'project="dev-project"' in first["filter"]
    params.update(page_token=page.json()["next_page_token"], end=page.json()["end"])
    assert client.get(url, params=params).status_code == 200
    second = api.list_time_series.call_args.kwargs["request"]
    assert second["page_token"] == "more"
    assert second["interval"] == first["interval"]
    api.list_time_series.side_effect = PermissionDenied("excluded")
    assert client.get(url, params=params).status_code == 403

    api.list_time_series.side_effect = None
    api.list_time_series.return_value.pages = [monitoring_v3.ListTimeSeriesResponse()]
    assert client.get(url, params=params).json()["series"] == []
    from google.api_core.exceptions import ServiceUnavailable
    api.list_time_series.side_effect = ServiceUnavailable("private DNS details")
    failed = client.get(url, params=params)
    assert failed.status_code == 503
    assert "private DNS details" not in failed.text
    api.list_time_series.side_effect = None
    values = [{"bool_value": False}, {"int64_value": "0"}, {"double_value": 0.0},
              {"string_value": ""}, {"distribution_value": {"count": "2", "mean": 4.0}}]
    api.list_time_series.return_value.pages = [monitoring_v3.ListTimeSeriesResponse(
        time_series=[{"unit": "ms", "points": [{"value": v} for v in
            [{"bool_value": False}, {"int64_value": 0}, {"double_value": 0.0},
             {"string_value": ""}, {"distribution_value": {"count": 2, "mean": 4.0}}]]}])]
    payload = client.get(url, params=params).json()
    assert payload["series"][0]["unit"] == "ms"
    assert [p["value"] for p in payload["series"][0]["points"]] == values
    assert client.get(url, params={"metric_type": metric, "page_token": "more"}).status_code == 422
    assert client.get(url, params={"metric_type": metric, "end": "2026-11-18T12:00:00"}).status_code == 422
    default_api = Mock()
    default_api.list_time_series.return_value.pages = [monitoring_v3.ListTimeSeriesResponse()]
    monkeypatch.setattr(svc._client_for_project("default-project"), "_get_monitoring_client", lambda: default_api)
    monkeypatch.setenv("GCP_ENV_LABEL", "deployment")
    assert client.get(url, params={"env": "PROD", "metric_type": metric, "period": "1h"}).status_code == 200
    default_request = default_api.list_time_series.call_args.kwargs["request"]
    assert default_request["name"] == "projects/default-project"
    assert 'project="default-project"' in default_request["filter"]
    assert 'resource.labels.deployment="PROD"' in default_request["filter"]
    assert default_request["interval"].end_time - default_request["interval"].start_time == timedelta(hours=1)
    assert client.get("/api/v1/gcp/catalog", params={"env": "DEV", "page_token": "catalog-next"}).status_code == 200
    assert api.list_metric_descriptors.call_args.kwargs["request"]["page_token"] == "catalog-next"
    calls_before_demo = api.list_time_series.call_count + default_api.list_time_series.call_count
    demo = client.get("/api/v1/metrics/overview", params={"source": "demo"})
    assert demo.status_code == 200
    assert demo.json()["data_source"] == "demo"
    assert api.list_time_series.call_count + default_api.list_time_series.call_count == calls_before_demo
    calls_before = default_api.list_time_series.call_count + api.list_time_series.call_count
    demo = client.get('/api/v1/metrics/overview', params={'source': 'demo', 'env': 'PROD'})
    assert demo.status_code == 200
    assert demo.json()['data_source'] == 'demo'
    assert default_api.list_time_series.call_count + api.list_time_series.call_count == calls_before


@pytest.mark.parametrize("outcome,status", [("empty", 200), ("dns", 503), ("denied", 403)])
def test_series_empty_dns_and_denial_are_distinct(monkeypatch, outcome, status):
    """A transport failure must never become a successful empty metric read."""
    from unittest.mock import Mock

    import httpx
    from google.api_core.exceptions import PermissionDenied, ServiceUnavailable
    from google.cloud import monitoring_v3

    from main import app
    from services.gcp_service import CachedGCPMetricsService

    project = "configured-dev-project"
    metric_type = "custom.googleapis.com/test/readability"
    sdk = Mock()
    if outcome == "empty":
        sdk.list_time_series.return_value.pages = [monitoring_v3.ListTimeSeriesResponse()]
    elif outcome == "dns":
        sdk.list_time_series.side_effect = ServiceUnavailable(
            "errors resolving monitoring.googleapis.com:443: Could not contact DNS servers; private-detail"
        )
    else:
        sdk.list_time_series.side_effect = PermissionDenied("private-detail")
    service = CachedGCPMetricsService("configured-default-project", Mock(), project_map={"DEV": project})
    monkeypatch.setattr(service._client_for_project(project), "_get_monitoring_client", lambda: sdk)
    monkeypatch.setattr(app.state, "gcp_service", service, raising=False)

    async def request():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test", headers={"Authorization": "Bearer test-viewer"}) as client:
            return await client.get("/api/v1/gcp/catalog/series", params={
                "env": "DEV", "metric_type": metric_type, "period": "1h",
                "end": "2026-11-18T12:00:00Z",
            })

    response = asyncio.run(request())
    assert response.status_code == status
    assert "private-detail" not in response.text
    if outcome == "empty":
        assert response.json()["series"] == []
        assert response.json()["project"] == project
        assert response.json()["warnings"] == []
    else:
        assert "series" not in response.json()
        assert "detail" in response.json()
    call = sdk.list_time_series.call_args.kwargs
    assert call["retry"] is None
    assert call["timeout"] == 15
    assert call["request"]["name"] == f"projects/{project}"
    assert f'project="{project}"' in call["request"]["filter"]
    assert f'metric.type="{metric_type}"' in call["request"]["filter"]
    interval = call["request"]["interval"]
    assert interval.end_time - interval.start_time == timedelta(hours=1)
