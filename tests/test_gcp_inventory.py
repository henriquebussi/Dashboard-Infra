"""Inventory evidence must distinguish samples, empty results and failed reads."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from google.api_core.exceptions import PermissionDenied, ServiceUnavailable

from scripts.gcp_inventory import collect_descriptors, configured_scopes, probe_series, service_for


def test_inventory_accepts_protobuf_integer_enums():
    from google.api import metric_pb2
    from google.cloud import monitoring_v3
    client = Mock()
    client.list_metric_descriptors.return_value.pages = [
        monitoring_v3.ListMetricDescriptorsResponse(metric_descriptors=[
            metric_pb2.MetricDescriptor(
                type='compute.googleapis.com/instance/cpu/utilization',
                metric_kind=metric_pb2.MetricDescriptor.GAUGE,
                value_type=metric_pb2.MetricDescriptor.DOUBLE, unit='10^2.%',
            )
        ])
    ]
    result = collect_descriptors(client, 'project', 1)
    assert result['status'] == 'ok'
    assert result['complete']
    assert result['descriptors'][0]['metric_kind'] == 'GAUGE'
    assert result['descriptors'][0]['value_type'] == 'DOUBLE'


@pytest.mark.parametrize('mapping', ['prod:prod-project,DEV:dev-project', '{"prod":"prod-project","DEV":"dev-project"}'])
def test_configured_projects_and_environment_scope(mapping):
    scopes = {s['environment']: s for s in configured_scopes({
        'GCP_PROJECT_ID': 'fallback-project', 'GCP_PROJECT_MAP': mapping,
        'GCP_ENV_LABEL': 'deployment',
    })}
    assert scopes['PROD'] == dict(environment='PROD', project='prod-project', scope='project-mapped', label='')
    assert scopes['DEV']['project'] == 'dev-project'
    assert scopes['STAGING']['project'] == 'fallback-project'
    assert scopes['STAGING']['scope'] == 'label-filtered'
    assert scopes['STAGING']['label'] == 'deployment'


def test_default_environments_do_not_claim_separate_projects():
    scopes = configured_scopes({'GCP_PROJECT_ID': 'one-project'})
    assert {s['environment'] for s in scopes} == {'PROD', 'STAGING', 'DEV'}
    assert all(s['scope'] == 'single-project' and s['project'] == 'one-project' for s in scopes)


@pytest.mark.parametrize('prefix,service', [
    ('compute', 'Compute Engine'), ('cloudsql', 'Cloud SQL'), ('storage', 'Cloud Storage'),
    ('bigquery', 'BigQuery'), ('aiplatform', 'Vertex AI'), ('custom', 'Other/custom'),
])
def test_service_classification(prefix, service):
    assert service_for(prefix + '.googleapis.com/example') == service


def page(points=0, token='', errors=()):
    series = [SimpleNamespace(points=[object() for _ in range(points)])] if points else []
    return SimpleNamespace(time_series=series, next_page_token=token, execution_errors=errors)


def run_probe(client, **kwargs):
    end = datetime(2026, 11, 18, tzinfo=timezone.utc)
    return probe_series(client, 'project', 'compute.googleapis.com/instance/cpu/utilization',
                        end - timedelta(hours=25), end, **kwargs)


def test_empty_response_confirms_no_samples_only():
    client = Mock()
    client.list_time_series.return_value.pages = [page()]
    result = run_probe(client)
    assert result['status'] == 'empty'
    assert result['points'] == 0
    assert result['pages'] == 1
    assert not result['truncated']


def test_reads_pages_with_explicit_budget_and_sanitizes_values():
    client = Mock()
    client.list_time_series.side_effect = [SimpleNamespace(pages=[page(2, 'private-page-token')]),
                                           SimpleNamespace(pages=[page(1)])]
    result = run_probe(client)
    assert result['status'] == 'samples_read'
    assert result['points'] == 3
    assert result['pages'] == 2
    assert not result['truncated']
    assert 'private-page-token' not in str(result)
    calls = client.list_time_series.call_args_list
    assert calls[1].kwargs['request']['page_token'] == 'private-page-token'
    assert all(c.kwargs['retry'] is None and c.kwargs['timeout'] == 10 for c in calls)
    assert all(c.kwargs['request']['page_size'] == 100 for c in calls)


def test_page_budget_marks_incomplete_read():
    client = Mock()
    client.list_time_series.return_value.pages = [page(1, 'more')]
    result = run_probe(client, max_pages=1)
    assert result['status'] == 'samples_read'
    assert result['truncated']
    assert client.list_time_series.call_count == 1


@pytest.mark.parametrize('error,status', [
    (PermissionDenied('Bearer secret'), 'forbidden'),
    (ServiceUnavailable('Could not contact DNS servers'), 'technical_failure'),
])
def test_failed_read_does_not_claim_empty_or_access(error, status):
    client = Mock()
    client.list_time_series.side_effect = error
    result = run_probe(client)
    assert result['status'] == status
    assert 'Bearer secret' not in str(result)


def test_partial_execution_errors_are_not_clean_success():
    client = Mock()
    client.list_time_series.return_value.pages = [page(1, errors=[object()])]
    assert run_probe(client)['status'] == 'technical_failure'


def test_descriptor_pagination_records_truncation_without_tokens():
    from scripts.gcp_inventory import collect_descriptors
    client = Mock()
    descriptor = SimpleNamespace(type='custom.googleapis.com/private', unit='1',
                                 metric_kind=1,
                                 value_type=3)
    client.list_metric_descriptors.return_value.pages = [SimpleNamespace(
        metric_descriptors=[descriptor], next_page_token='secret-token')]
    result = collect_descriptors(client, 'project', 1)
    assert not result['complete']
    assert result['pages'] == 1
    assert result['descriptors'][0]['service'] == 'Other/custom'
    assert 'secret-token' not in str(result)


def test_series_filter_preserves_project_environment_and_period():
    client = Mock()
    client.list_time_series.return_value.pages = [page()]
    run_probe(client, label='deployment', environment='PROD')
    request = client.list_time_series.call_args.kwargs['request']
    assert 'project="project"' in request['filter']
    assert 'resource.labels.deployment="PROD"' in request['filter']
    assert request['interval']['end_time'] - request['interval']['start_time'] == timedelta(hours=25)
    assert request['view'] == 'FULL'
