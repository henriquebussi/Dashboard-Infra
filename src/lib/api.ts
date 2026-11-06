/**
 * GCP FinOps Observatory — Typed API Client
 *
 * Thin fetch wrapper that:
 *  - Reads VITE_API_BASE_URL from env (empty = same-origin, Vite proxies /api in dev)
 *  - Injects X-User-Role header from VITE_USER_ROLE
 *  - Maps all HTTP 4xx/5xx responses to typed ApiError exceptions
 *  - Provides typed helpers for every backend endpoint
 */

// ---------------------------------------------------------------------------
// Config
// ---------------------------------------------------------------------------

const BASE_URL = (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? '';
const USER_ROLE = (import.meta.env.VITE_USER_ROLE as string | undefined) ?? 'VIEW_ONLY';

// ---------------------------------------------------------------------------
// Error type
// ---------------------------------------------------------------------------

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly detail: string,
  ) {
    super(`API ${status}: ${detail}`);
    this.name = 'ApiError';
  }
}

// ---------------------------------------------------------------------------
// Core fetch wrapper
// ---------------------------------------------------------------------------

async function apiFetch<T>(path: string, init: RequestInit = {}): Promise<T> {
  const url = `${BASE_URL}/api/v1${path}`;
  const res = await fetch(url, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      'X-User-Role': USER_ROLE,
      ...(init.headers ?? {}),
    },
  });

  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = (await res.json()) as { detail?: string };
      if (body.detail) detail = body.detail;
    } catch {
      // ignore parse failure — keep statusText
    }
    throw new ApiError(res.status, detail);
  }

  return res.json() as Promise<T>;
}

// ---------------------------------------------------------------------------
// Response types (mirrors backend Pydantic schemas)
// ---------------------------------------------------------------------------

export type Environment = 'PROD' | 'STAGING' | 'DEV';
export type Period = '1h' | '24h' | '7d' | '30d';
export type MetricCategory = 'cloud' | 'database' | 'storage' | 'processing' | 'tokens' | 'sla';

export interface TimeSeriesPoint {
  timestamp: string;
  value: number;
  labels: Record<string, string>;
}

/** Metric reading returned by the aggregated overview endpoint. */
export interface MetricReadingDto {
  current_value: number;
  unit: string;
  status: 'HEALTHY' | 'WARNING' | 'CRITICAL';
  time_series: Array<{ timestamp: string; value: number }>;
  change_percentage?: number | null;
  trend?: 'up' | 'down' | 'flat' | null;
  min_value?: number | null;
  max_value?: number | null;
  avg_value?: number | null;
  resources: Array<{
    name: string;
    value: string | number;
    detail?: string;
    severity?: 'warning' | 'critical' | null;
  }>;
  metadata: Record<string, unknown>;
}

export interface MetricSeriesDto {
  metric_type: string;
  category: string;
  metric_name: string;
  unit: string;
  aggregated_avg: number;
  aggregated_max: number;
  aggregated_min: number;
  fetched_at: string;
  points: TimeSeriesPoint[];
}

export interface GcpMetricsResponse {
  category: string;
  period: string;
  metrics: Record<string, MetricSeriesDto[] | { error: string }>;
  errors?: string[];
  /** Present only when the GCP circuit breaker is open */
  degraded?: boolean;
  error?: string;
  /** Where the payload came from: fresh GCP call, Redis cache, or failure. */
  data_source?: 'live' | 'cache' | 'offline';
}

export interface TokenUsageEntry {
  timestamp: string | null;
  severity: string;
  resource_type: string | null;
  labels: Record<string, string>;
  payload: Record<string, unknown>;
}

export interface TokenUsageResponse {
  query_type: 'token_usage';
  total_count: number;
  fetched_at: string;
  entries: TokenUsageEntry[];
}

export interface SlowQueryEntry {
  timestamp: string | null;
  severity: string;
  database_id: string | null;
  duration_ms: number | null;
  query_text: string;
  labels: Record<string, string>;
}

export interface SlowQueryResponse {
  query_type: 'slow_queries';
  total_count: number;
  fetched_at: string;
  entries: SlowQueryEntry[];
}

export interface GcpHealthResponse {
  service: string;
  gcp: {
    monitoring_sdk_available: boolean;
    logging_sdk_available: boolean;
    gcp_circuit_state: 'CLOSED' | 'OPEN' | 'HALF_OPEN';
    project_id: string;
  };
  cache: {
    redis_alive: boolean;
    circuit_state: 'CLOSED' | 'OPEN' | 'HALF_OPEN';
    ping_latency_ms: number | null;
    prewarm_registered_keys: number;
    prewarm_keys: string[];
  };
}

export interface OverviewAlert {
  metric_id: string;
  current_value: number;
  severity: 'WARNING' | 'CRITICAL';
  suggested_action: string;
  rule_id: string;
  resource_id: string;
  triggered_at: string;
  is_acknowledged: boolean;
}

export interface OverviewCategory {
  resource_id: string;
  environment: string;
  timestamp: string;
  [metricName: string]: unknown;
}

export interface OverviewResponse {
  filter_params: {
    period: string;
    env: string;
    service: string | null;
    resource: string | null;
    start_time: string | null;
    end_time: string | null;
  };
  database: OverviewCategory;
  cloud: OverviewCategory;
  storage: OverviewCategory;
  processing: OverviewCategory;
  tokens: OverviewCategory;
  sla: OverviewCategory;
  active_alerts: OverviewAlert[];
}

export interface CacheFlushResponse {
  flushed: boolean;
  keys_deleted: number;
  pattern: string;
  flushed_by: string;
}

export interface PrewarmResponse {
  prewarmed: boolean;
  keys_warmed: number;
  cache_keys: string[];
  triggered_by: string;
}

// ---------------------------------------------------------------------------
// API helpers
// ---------------------------------------------------------------------------

/** GET /api/v1/metrics/overview */
export function fetchOverview(
  env: Environment,
  period: Period,
  options: { service?: string; resourceId?: string } = {},
): Promise<OverviewResponse> {
  const params = new URLSearchParams({ env, period });
  if (options.service) params.set('service', options.service);
  if (options.resourceId) params.set('resource', options.resourceId);
  return apiFetch(`/metrics/overview?${params}`);
}

/** GET /api/v1/alerts/active */
export function fetchActiveAlerts(
  options: {
    severity?: 'WARNING' | 'CRITICAL';
    resourceId?: string;
    isAcknowledged?: boolean;
  } = {},
): Promise<OverviewAlert[]> {
  const params = new URLSearchParams();
  if (options.severity) params.set('severity', options.severity);
  if (options.resourceId) params.set('resource', options.resourceId);
  if (options.isAcknowledged !== undefined) {
    params.set('is_acknowledged', String(options.isAcknowledged));
  }
  const query = params.toString();
  return apiFetch(`/alerts/active${query ? `?${query}` : ''}`);
}

/** GET /api/v1/gcp/metrics/{category} */
export function fetchGcpMetrics(
  category: MetricCategory,
  env: Environment,
  period: Period,
  options: {
    ttl?: number;
    instanceId?: string;
    databaseId?: string;
    bucketName?: string;
  } = {},
): Promise<GcpMetricsResponse> {
  const params = new URLSearchParams({ env, period });
  if (options.ttl !== undefined) params.set('ttl', String(options.ttl));
  if (options.instanceId) params.set('instance_id', options.instanceId);
  if (options.databaseId) params.set('database_id', options.databaseId);
  if (options.bucketName) params.set('bucket_name', options.bucketName);
  return apiFetch(`/gcp/metrics/${category}?${params}`);
}

/** GET /api/v1/gcp/metrics/tokens/usage */
export function fetchTokenUsage(
  env: Environment,
  hours = 24,
  ttl = 120,
): Promise<TokenUsageResponse> {
  return apiFetch(`/gcp/metrics/tokens/usage?env=${env}&hours=${hours}&ttl=${ttl}`);
}

/** GET /api/v1/gcp/metrics/database/slow-queries */
export function fetchSlowQueries(
  env: Environment,
  options: { hours?: number; thresholdMs?: number; databaseId?: string; ttl?: number } = {},
): Promise<SlowQueryResponse> {
  const params = new URLSearchParams({ env });
  if (options.hours) params.set('hours', String(options.hours));
  if (options.thresholdMs) params.set('threshold_ms', String(options.thresholdMs));
  if (options.databaseId) params.set('database_id', options.databaseId);
  if (options.ttl) params.set('ttl', String(options.ttl));
  return apiFetch(`/gcp/metrics/database/slow-queries?${params}`);
}

/** GET /api/v1/gcp/health */
export function fetchGcpHealth(): Promise<GcpHealthResponse> {
  return apiFetch('/gcp/health');
}

/** POST /api/v1/gcp/cache/flush */
export function flushCache(pattern = 'metrics:*'): Promise<CacheFlushResponse> {
  return apiFetch(`/gcp/cache/flush?pattern=${encodeURIComponent(pattern)}`, { method: 'POST' });
}

/** POST /api/v1/gcp/cache/prewarm */
export function prewarmCache(options: {
  environments?: string[];
  categories?: string[];
  periods?: string[];
} = {}): Promise<PrewarmResponse> {
  const params = new URLSearchParams();
  (options.environments ?? ['PROD', 'STAGING']).forEach((e) => params.append('environments', e));
  (options.categories ?? ['cloud', 'database', 'storage']).forEach((c) =>
    params.append('categories', c),
  );
  (options.periods ?? ['1h', '24h']).forEach((p) => params.append('periods', p));
  return apiFetch(`/gcp/cache/prewarm?${params}`, { method: 'POST' });
}
