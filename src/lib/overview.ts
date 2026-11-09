/**
 * Mapping helpers that project the backend `/metrics/overview` payload onto the
 * dashboard's view models. This keeps the UI fully functional with the REST API
 * even when live GCP Monitoring credentials are not configured.
 */

import type { MetricReadingDto, OverviewResponse } from '@/lib/api';
import type { Metric, SectionData } from '@/features/dashboard/mock-data';

type MetricKeyMap = Record<string, string>;

/**
 * Frontend metric id → backend metric field name, per dashboard section.
 * Keep this in sync with schemas.py (DatabaseMetrics, CloudMetrics, …).
 */
export const METRIC_KEYS: Record<string, MetricKeyMap> = {
  database: {
    qps: 'qps',
    connections: 'active_connections',
    locks: 'locks',
    'slow-queries': 'slow_queries_count',
    'response-time': 'avg_response_time_ms',
    'cpu-io': 'cpu_io_percent',
    replication: 'replication_lag_seconds',
  },
  cloud: {
    cpu: 'cpu_percent',
    ram: 'memory_percent',
    disk: 'disk_percent',
    cost: 'estimated_cost_usd',
    uptime: 'uptime_percent',
  },
  storage: {
    usage: 'total_usage',
    buckets: 'bucket_volume_usage_percent',
    iops: 'iops',
    throughput: 'read_write_throughput_mb_s',
    latency: 'latency_ms',
  },
  processing: {
    queued: 'queued_jobs',
    running: 'running_jobs',
    'processing-time': 'avg_processing_time_seconds',
    failures: 'failure_counts',
  },
  tokens: {
    'tokens-day': 'daily_token_count',
    'model-cost': 'cost_per_model',
    'error-rate': 'error_rate_percent',
    'rate-limits': 'rate_limit_breaches',
  },
  sla: {
    availability: 'availability_percent',
    errors: 'error_counts_4xx_5xx',
    peak: 'peak_usage_percent',
    growth: 'growth_trend_percent',
  },
};

/** Backend metric fields used for the section-level trend chart. */
const SERIES_KEYS: Record<string, string[]> = {
  database: ['qps', 'avg_response_time_ms'],
  cloud: ['cpu_percent', 'memory_percent'],
  storage: ['total_usage', 'bucket_volume_usage_percent', 'iops'],
  processing: ['queued_jobs', 'running_jobs'],
  tokens: ['daily_token_count'],
  sla: ['availability_percent', 'error_counts_4xx_5xx'],
};

const ptNumber = (value: number, digits = 0) =>
  value.toLocaleString('pt-BR', {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });

function compactNumber(value: number): string {
  const abs = Math.abs(value);
  if (abs >= 1_000_000) return `${ptNumber(value / 1_000_000, 2)}M`;
  if (abs >= 10_000) return `${ptNumber(value / 1_000, 1)}k`;
  if (abs >= 1_000) return ptNumber(value, 0);
  if (!Number.isInteger(value)) return ptNumber(value, 2);
  return ptNumber(value, 0);
}

function formatSeconds(value: number): string {
  if (Math.abs(value) >= 60) {
    const minutes = Math.floor(value / 60);
    const seconds = Math.round(value % 60);
    return `${minutes}m ${seconds}s`;
  }
  return `${ptNumber(value, 1)} s`;
}

/** Format a backend reading using its engineering/financial unit. */
export function formatMetricValue(reading: MetricReadingDto): string {
  if (reading.available === false) return 'Indisponível';
  const value = reading.current_value;
  switch (reading.unit) {
    case '%': {
      const digits = Number.isInteger(value) ? 0 : Math.abs(value) < 10 ? 2 : 1;
      return `${ptNumber(value, digits)}%`;
    }
    case 'USD':
      return `$${ptNumber(value, 0)}`;
    case 'ms': {
      const digits = Number.isInteger(value) ? 0 : Math.abs(value) < 100 ? 1 : 0;
      return `${ptNumber(value, digits)} ms`;
    }
    case 's':
      return formatSeconds(value);
    case 'm':
      return `${ptNumber(value, 1)} min`;
    case 'TB':
      return `${ptNumber(value, 1)} TB`;
    case 'GB':
      return `${ptNumber(value, 1)} GB`;
    case 'MB':
      return `${ptNumber(value, 1)} MB`;
    case 'MB/s':
      return value >= 1000
        ? `${ptNumber(value / 1000, 1)} GB/s`
        : `${ptNumber(value, 1)} MB/s`;
    case 'GB/s':
      return `${ptNumber(value, 1)} GB/s`;
    case 'IOPS':
    case 'tokens':
    case 'requests':
    case 'count':
      return compactNumber(value);
    case 'queries/sec':
      return ptNumber(value, 0);
    default:
      return reading.unit
        ? `${compactNumber(value)} ${reading.unit}`
        : compactNumber(value);
  }
}

export function formatChange(reading: MetricReadingDto): string {
  if (reading.available === false) return '—';
  const change = reading.change_percentage;
  if (change === null || change === undefined || Number.isNaN(change)) return '0%';
  const sign = change > 0 ? '+' : change < 0 ? '−' : '';
  const digits = Math.abs(change) < 1 ? 2 : 1;
  return `${sign}${ptNumber(Math.abs(change), digits)}%`;
}

function trendOf(reading: MetricReadingDto): Metric['trend'] {
  if (reading.trend === 'up' || reading.trend === 'down' || reading.trend === 'flat') {
    return reading.trend;
  }
  const change = reading.change_percentage ?? 0;
  if (change > 0) return 'up';
  if (change < 0) return 'down';
  return 'flat';
}

function severityOf(reading: MetricReadingDto): Metric['severity'] {
  if (reading.status === 'CRITICAL') return 'critical';
  if (reading.status === 'WARNING') return 'warning';
  return undefined;
}

function normalizeReading(raw: unknown): MetricReadingDto | null {
  if (!raw || typeof raw !== 'object') return null;
  const candidate = raw as Partial<MetricReadingDto>;
  if (typeof candidate.current_value !== 'number') return null;

  return {
    current_value: candidate.current_value,
    unit: typeof candidate.unit === 'string' ? candidate.unit : '',
    status:
      candidate.status === 'CRITICAL'
        ? 'CRITICAL'
        : candidate.status === 'WARNING'
          ? 'WARNING'
          : 'HEALTHY',
    time_series: Array.isArray(candidate.time_series) ? candidate.time_series : [],
    change_percentage:
      typeof candidate.change_percentage === 'number' ? candidate.change_percentage : null,
    trend: candidate.trend ?? null,
    min_value: typeof candidate.min_value === 'number' ? candidate.min_value : null,
    max_value: typeof candidate.max_value === 'number' ? candidate.max_value : null,
    avg_value: typeof candidate.avg_value === 'number' ? candidate.avg_value : null,
    available: candidate.available !== false,
    source: candidate.source ?? 'gcp',
    reason: candidate.reason ?? null,
    bucket_seconds: candidate.bucket_seconds ?? null,
    gcp_metric_types: Array.isArray(candidate.gcp_metric_types) ? candidate.gcp_metric_types : [],
    timestamps: Array.isArray(candidate.timestamps) ? candidate.timestamps : [],
    resources: Array.isArray(candidate.resources) ? candidate.resources : [],
    metadata:
      candidate.metadata && typeof candidate.metadata === 'object'
        ? (candidate.metadata as Record<string, unknown>)
        : {},
  };
}

/** Format an ISO UTC timestamp for chart axes (e.g. '14:30' or '08/11 14:30'). */
export function formatTimestampLabel(isoString: string): string {
  try {
    const dt = new Date(isoString);
    if (Number.isNaN(dt.getTime())) return isoString;
    const hours = String(dt.getUTCHours()).padStart(2, '0');
    const minutes = String(dt.getUTCMinutes()).padStart(2, '0');
    return `${hours}:${minutes}`;
  } catch {
    return isoString;
  }
}

/** Read a metric field from the overview payload by section + backend field name. */
export function getCategoryReading(
  overview: OverviewResponse | null,
  sectionId: string,
  metricKey: string,
): MetricReadingDto | null {
  if (!overview) return null;
  const category = overview[sectionId as keyof OverviewResponse];
  if (!category || typeof category !== 'object') return null;
  return normalizeReading((category as Record<string, unknown>)[metricKey]);
}

export function getMetricReading(
  overview: OverviewResponse | null,
  sectionId: string,
  metricId: string,
): MetricReadingDto | null {
  const key = METRIC_KEYS[sectionId]?.[metricId];
  if (!key) return null;
  return getCategoryReading(overview, sectionId, key);
}

/**
 * Build the section-level chart series and exact timestamp labels from backend readings.
 */
export function buildOverviewChart(
  section: SectionData,
  overview: OverviewResponse | null,
): { labels: string[]; series: SectionData['series'] } | null {
  if (!overview) return null;

  let commonTimestamps: string[] = [];

  const series = (SERIES_KEYS[section.id] ?? [])
    .map((key, index) => {
      const reading = getCategoryReading(overview, section.id, key);
      if (!reading || reading.time_series.length === 0) return null;

      if (commonTimestamps.length === 0 && reading.timestamps && reading.timestamps.length > 0) {
        commonTimestamps = reading.timestamps;
      } else if (commonTimestamps.length === 0 && reading.time_series.length > 0) {
        commonTimestamps = reading.time_series.map((p) => p.timestamp);
      }

      const mockEntry = section.series[index];
      return {
        name: mockEntry?.name ?? key,
        values: reading.time_series.map((point) => point.value),
        color: mockEntry?.color,
      };
    })
    .filter((entry): entry is NonNullable<typeof entry> => entry !== null);

  if (series.length === 0) return null;

  const labels = commonTimestamps.map(formatTimestampLabel);
  return { labels, series };
}

/**
 * Build the section-level chart series from real backend readings.
 * Returns ``null`` when the overview has no usable time-series for the section.
 */
export function buildOverviewSeries(
  section: SectionData,
  overview: OverviewResponse | null,
): SectionData['series'] | null {
  const chart = buildOverviewChart(section, overview);
  return chart?.series ?? null;
}

/**
 * Return a copy of the dashboard sections with live backend readings applied.
 * Any metric without a matching backend field keeps its demo value.
 */
export function applyOverviewToSections(
  sections: SectionData[],
  overview: OverviewResponse | null,
): SectionData[] {
  if (!overview) return sections;

  return sections.map((section) => {
    const metrics = section.metrics.map((metric) => {
      const reading = getMetricReading(overview, section.id, metric.id);
      if (!reading) return metric;

      const alert = overview.active_alerts.find(
        (item) => item.metric_id === `${section.id}.${METRIC_KEYS[section.id]?.[metric.id]}`,
      );

      const isAvailable = reading.available !== false;

      return {
        ...metric,
        value: isAvailable ? formatMetricValue(reading) : 'Indisponível',
        change: isAvailable ? formatChange(reading) : '—',
        trend: isAvailable ? trendOf(reading) : 'flat',
        severity: isAvailable ? severityOf(reading) : undefined,
        action: alert?.suggested_action ?? (isAvailable ? metric.action : undefined),
        isLive: true,
        available: isAvailable,
        source: reading.source ?? 'gcp',
        reason: reading.reason ?? null,
        timestamps: reading.timestamps,
        series:
          reading.time_series.length > 0
            ? reading.time_series.map((point) => point.value)
            : (isAvailable ? metric.series : metric.series.map(() => 0)),
        resources:
          reading.resources.length > 0
            ? reading.resources.map((resource) => ({
                name: resource.name,
                value: String(resource.value),
                detail: resource.detail ?? (resource.region ? `${resource.region}` : ''),
                severity: resource.severity ?? undefined,
              }))
            : [],
      } satisfies Metric;
    });

    return {
      ...section,
      metrics,
      series: buildOverviewSeries(section, overview) ?? section.series,
    };
  });
}

/** Convenience accessor for the platform availability KPI. */
export function getOverviewAvailability(overview: OverviewResponse | null): string | null {
  const reading = getCategoryReading(overview, 'sla', 'availability_percent');
  return reading ? formatMetricValue(reading) : null;
}

/** Convenience accessor for the platform availability change KPI. */
export function getOverviewAvailabilityChange(overview: OverviewResponse | null): string | null {
  const reading = getCategoryReading(overview, 'sla', 'availability_percent');
  return reading ? formatChange(reading) : null;
}
