#!/usr/bin/env python3
"""Bounded read-only metric inventory; emits no labels, values or raw errors."""
from __future__ import annotations

import argparse
import json
import os
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv

try:
    from .gcp_diagnostics import classify_error
except ImportError:
    from gcp_diagnostics import classify_error

SERVICES = {'compute': 'Compute Engine', 'cloudsql': 'Cloud SQL',
            'storage': 'Cloud Storage', 'bigquery': 'BigQuery', 'aiplatform': 'Vertex AI'}


def service_for(metric_type):
    return next((name for prefix, name in SERVICES.items()
                 if metric_type.startswith(prefix + '.googleapis.com/')), 'Other/custom')


def configured_scopes(environ):
    default = environ.get('GCP_PROJECT_ID', '').strip()
    raw = environ.get('GCP_PROJECT_MAP', '').strip()
    if raw.startswith('{'):
        mapping = json.loads(raw)
    else:
        mapping = dict(part.split(':', 1) for part in raw.split(',') if ':' in part)
    mapping = {k.strip().upper(): v.strip() for k, v in mapping.items()}
    label = environ.get('GCP_ENV_LABEL', '').strip()
    if label and not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', label):
        raise ValueError('Invalid environment label')
    scopes = []
    for env in dict.fromkeys(['PROD', 'STAGING', 'DEV', *mapping]):
        project = mapping.get(env, default)
        if project:
            scopes.append({'environment': env, 'project': project,
                           'scope': 'project-mapped' if env in mapping else 'label-filtered' if label else 'single-project',
                           'label': label if env not in mapping else ''})
    return scopes


def failure(exc):
    evidence = classify_error(exc)
    return {'status': 'forbidden' if evidence['status'] == 'authorization_denied' else 'technical_failure',
            'evidence': evidence}


def probe_series(client, project, metric_type, start, end, label='', environment='', max_pages=2):
    result = {'status': 'not_verified', 'pages': 0, 'points': 0, 'truncated': False}
    filters = [f'metric.type={json.dumps(metric_type)}', f'project={json.dumps(project)}']
    if label:
        filters.append(f'resource.labels.{label}={json.dumps(environment)}')
    token = ''
    try:
        for _ in range(max_pages):
            page = next(iter(client.list_time_series(request={
                'name': f'projects/{project}', 'filter': ' AND '.join(filters),
                'interval': {'start_time': start, 'end_time': end}, 'view': 'FULL',
                'page_size': 100, 'page_token': token}, retry=None, timeout=10).pages))
            result['pages'] += 1
            result['points'] += sum(len(s.points) for s in page.time_series)
            if page.execution_errors:
                return {**result, 'status': 'technical_failure', 'evidence': {'status': 'partial_read'}}
            token = page.next_page_token
            result['truncated'] = bool(token)
            if not token:
                break
            time.sleep(0.2)
        result['status'] = 'samples_read' if result['points'] else 'not_verified' if token else 'empty'
    except Exception as exc:
        result.update(failure(exc))
    return result


def collect_descriptors(client, project, max_pages):
    from google.api import metric_pb2
    rows, token, pages = [], '', 0
    try:
        for _ in range(max_pages):
            page = next(iter(client.list_metric_descriptors(request={
                'name': f'projects/{project}', 'page_size': 100, 'page_token': token},
                retry=None, timeout=10).pages))
            pages += 1
            rows.extend({'type': d.type, 'service': service_for(d.type), 'unit': d.unit,
                         'metric_kind': metric_pb2.MetricDescriptor.MetricKind.Name(int(d.metric_kind)),
                         'value_type': metric_pb2.MetricDescriptor.ValueType.Name(int(d.value_type))}
                        for d in page.metric_descriptors)
            token = page.next_page_token
            if not token:
                break
            time.sleep(0.2)
        return {'status': 'ok', 'pages': pages, 'complete': not bool(token), 'descriptors': rows}
    except Exception as exc:
        return {**failure(exc), 'pages': pages, 'complete': False, 'descriptors': rows}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--hours', type=int, default=25, choices=range(1, 169), metavar='1..168')
    parser.add_argument('--descriptor-pages', type=int, default=10, choices=range(1, 101), metavar='1..100')
    parser.add_argument('--series-pages', type=int, default=2, choices=range(1, 11), metavar='1..10')
    parser.add_argument('--metrics-per-service', type=int, default=5, choices=range(1, 101), metavar='1..100')
    args = parser.parse_args()
    load_dotenv(Path(__file__).resolve().parent.parent / '.env')
    end = datetime.now(timezone.utc)
    start = end - timedelta(hours=args.hours)
    report = {'start_utc': start.isoformat(), 'end_utc': end.isoformat(),
              'limits': vars(args), 'scopes': [], 'projects': {}}
    try:
        scopes = configured_scopes(os.environ)
        if not scopes:
            raise ValueError('Missing configured project')
        import google.auth
        from google.cloud import monitoring_v3
        credentials, _ = google.auth.default(scopes=['https://www.googleapis.com/auth/cloud-platform'])
        with monitoring_v3.MetricServiceClient(credentials=credentials) as client:
            for project in dict.fromkeys(s['project'] for s in scopes):
                report['projects'][project] = collect_descriptors(client, project, args.descriptor_pages)
            cache = {}
            for scope in scopes:
                catalog = report['projects'][scope['project']]
                counts, rows = {}, []
                stop = catalog['status'] != 'ok'
                for d in sorted(catalog['descriptors'], key=lambda d: d['type']):
                    service = d['service']
                    result = {'status': 'not_verified', 'reason': 'outside_target_services'}
                    if service in SERVICES.values():
                        count = counts.get(service, 0)
                        if stop:
                            result = {'status': 'not_verified', 'reason': 'collection_blocked'}
                        elif count >= args.metrics_per_service:
                            result = {'status': 'not_verified', 'reason': 'metric_budget'}
                        else:
                            key = (scope['project'], scope['label'], scope['environment'] if scope['label'] else '', d['type'])
                            if key not in cache:
                                time.sleep(0.2)
                                cache[key] = probe_series(client, scope['project'], d['type'], start, end,
                                                          scope['label'], scope['environment'], args.series_pages)
                            result = cache[key]
                            counts[service] = count + 1
                            if result.get('evidence', {}).get('status') in ('dns_error', 'quota_exceeded', 'authentication_failed', 'api_disabled', 'api_unavailable', 'connectivity_error'):
                                stop = True
                    rows.append({'type': d['type'], 'service': service, **result})
                report['scopes'].append({**scope, 'metrics': rows, 'services': {
                    name: 'descriptors_listed' if any(d['service'] == name for d in catalog['descriptors'])
                    else 'not_observed' if catalog['complete'] else 'not_verified'
                    for name in SERVICES.values()}})
    except Exception as exc:
        report['collection'] = failure(exc)
    print(json.dumps(report, indent=2))
    incomplete = (not report['scopes'] or any(not p['complete'] for p in report['projects'].values())
                  or any(r['status'] not in ('samples_read', 'empty') for s in report['scopes']
                         for r in s['metrics'] if r['service'] in SERVICES.values()))
    return 1 if incomplete else 0


if __name__ == '__main__':
    raise SystemExit(main())
