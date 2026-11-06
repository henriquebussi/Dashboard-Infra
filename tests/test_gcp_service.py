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
