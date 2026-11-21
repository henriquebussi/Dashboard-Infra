"""Read-only, sanitized GCP diagnostics. Run via check_gcp.py --diagnose."""
from __future__ import annotations

import json
import os
import socket
import ssl
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse


class PartialReadError(Exception):
    """The server reported incomplete time-series results."""


def classify_error(exc):
    """Classify evidence without emitting server messages, tokens or payloads."""
    from google.api_core import exceptions as g
    from google.auth.exceptions import RefreshError, TransportError

    message = str(exc).lower()  # Used locally only; never included in output.
    reasons = []
    for error in getattr(exc, 'errors', ()) or ():
        if isinstance(error, dict):
            reasons.append(error.get('reason', ''))
    reason = getattr(exc, 'reason', None)
    if reason:
        reasons.append(reason)
    if any(s in message for s in ('could not contact dns servers', 'name resolution', 'hostname lookup', 'errors resolving', 'name or service not known')):
        status = 'dns_error'
    elif any(r in ('SERVICE_DISABLED', 'accessNotConfigured', 'API_DISABLED') for r in reasons):
        status = 'api_disabled'
    elif isinstance(exc, (g.Unauthenticated, RefreshError)):
        status = 'authentication_failed'
    elif isinstance(exc, (g.Forbidden, g.PermissionDenied)):
        status = 'authorization_denied'
    elif isinstance(exc, g.NotFound):
        status = 'not_found'
    elif isinstance(exc, g.ResourceExhausted):
        status = 'quota_exceeded'
    elif isinstance(exc, g.ServiceUnavailable):
        status = 'api_unavailable'
    elif isinstance(exc, (g.DeadlineExceeded, TransportError, OSError)):
        status = 'connectivity_error'
    elif isinstance(exc, PartialReadError):
        status = 'partial_read'
    else:
        status = 'unclassified_error'
    return {'status': status, 'exception': type(exc).__name__}


def network_probe(host):
    result = {'host': host}
    try:
        socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
        result['dns'] = 'ok'
    except socket.gaierror as exc:
        return {**result, 'dns': 'blocked', 'errno': exc.errno, 'tls': 'not_tested'}
    try:
        with socket.create_connection((host, 443), timeout=5) as conn:
            with ssl.create_default_context().wrap_socket(conn, server_hostname=host):
                result['tls'] = 'ok'
    except Exception as exc:
        result.update(tls='blocked', exception=type(exc).__name__)
    return result


def remote_probe(operation):
    try:
        operation()
        return {'status': 'ok'}
    except Exception as exc:
        return classify_error(exc)


def run():
    import google.auth
    from google.auth.transport.requests import Request
    from google.cloud import monitoring_v3
    from google.cloud.logging_v2.services.logging_service_v2 import LoggingServiceV2Client

    report = {'timestamp_utc': datetime.now(timezone.utc).isoformat(), 'transport': 'grpc',
              'notes': ['No IAM or API configuration changes.',
                        'DNS/TLS probes use direct egress; SDK proxy routing may differ.',
                        'Only successful remote reads confirm the tested permissions; no role inference.',
                        '503 alone does not prove a Google service outage; 404 does not prove API disabled.']}
    projects = [os.getenv('GCP_PROJECT_ID', '').strip()]
    for entry in os.getenv('GCP_PROJECT_MAP', '').split(','):
        if ':' in entry:
            projects.append(entry.split(':', 1)[1].strip())
    projects = list(dict.fromkeys(p for p in projects if p))
    if not projects:
        report['configuration'] = {'status': 'missing_project'}
        print(json.dumps(report, indent=2))
        return 1
    try:
        credentials, detected = google.auth.default(scopes=['https://www.googleapis.com/auth/cloud-platform'])
        report['credentials'] = {'status': 'loaded', 'type': type(credentials).__name__,
                                 'detected_project': detected, 'quota_project': getattr(credentials, 'quota_project_id', None)}
    except Exception as exc:
        report['credentials'] = classify_error(exc)
        print(json.dumps(report, indent=2))
        return 1
    hosts = ['monitoring.googleapis.com', 'logging.googleapis.com']
    token_host = urlparse(getattr(credentials, '_token_uri', '') or '').hostname
    if token_host:
        hosts.append(token_host)
    report['network'] = [network_probe(h) for h in dict.fromkeys(hosts)]
    class BoundedRequest:
        def __call__(self, *args, **kwargs):
            kwargs['timeout'] = 10
            return Request()(*args, **kwargs)
    report['authentication'] = remote_probe(lambda: credentials.refresh(BoundedRequest()))
    report['projects'] = {}
    for project in projects:
        results = {}
        def descriptors():
            with monitoring_v3.MetricServiceClient(credentials=credentials) as client:
                next(iter(client.list_metric_descriptors(request={'name': f'projects/{project}', 'page_size': 1}, retry=None, timeout=10).pages))
        def series():
            end = datetime.now(timezone.utc)
            with monitoring_v3.MetricServiceClient(credentials=credentials) as client:
                page = next(iter(client.list_time_series(request={
                    'name': f'projects/{project}',
                    'filter': 'metric.type="compute.googleapis.com/instance/cpu/utilization"',
                    'interval': {'start_time': end-timedelta(hours=1), 'end_time': end},
                    'view': 'FULL', 'page_size': 1}, retry=None, timeout=10).pages))
                if page.execution_errors:
                    raise PartialReadError()
        def logs():
            with LoggingServiceV2Client(credentials=credentials) as client:
                next(iter(client.list_log_entries(request={
                    'resource_names': [f'projects/{project}'], 'page_size': 1,
                    'filter': 'timestamp >= "'+(datetime.now(timezone.utc)-timedelta(hours=1)).isoformat()+'"'}, retry=None, timeout=10).pages))
        results['Monitoring'] = {'metricDescriptors.list': remote_probe(descriptors), 'timeSeries.list': remote_probe(series)}
        results['Logging'] = {'logEntries.list': remote_probe(logs)}
        report['projects'][project] = results
    print(json.dumps(report, indent=2))
    return 0 if all(probe['status'] == 'ok' for result in report['projects'].values() for service in result.values() for probe in service.values()) and report['authentication']['status'] == 'ok' else 1
