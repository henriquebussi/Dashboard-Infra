"""Financial readings require a billing source; operational SDKs cannot supply it."""
import asyncio
from unittest.mock import Mock

import pytest

from schemas import DashboardFilterParams, Environment
from services.gcp_service import CachedGCPMetricsService
from services.metric_registry import METRIC_DEFINITIONS


@pytest.mark.parametrize('metric_id', ['cloud.estimated_cost_usd', 'tokens.cost_per_model'])
@pytest.mark.parametrize('environment', list(Environment))
def test_missing_billing_is_unavailable_without_external_calls(metric_id, environment):
    cache = Mock()
    service = CachedGCPMetricsService('configured-project', cache)
    client_factory = Mock(side_effect=AssertionError('No operational query may estimate billing'))
    service._client_for_project = client_factory
    definition = METRIC_DEFINITIONS[metric_id]
    reading = asyncio.run(service.get_reading_for_definition(
        definition, DashboardFilterParams(environment=environment, period='24h'),
        'configured-project', environment,
    ))
    assert definition.requires_billing
    assert definition.gcp_metric_types == []
    assert not reading.available
    assert reading.source == 'unavailable'
    assert reading.unit == 'USD'
    assert 'não configurada' in reading.reason
    assert 'não implementada' in reading.reason
    assert not reading.time_series
    assert not reading.timestamps
    assert not reading.resources
    client_factory.assert_not_called()
    assert not cache.mock_calls
