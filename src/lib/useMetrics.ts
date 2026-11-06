/**
 * GCP FinOps Observatory — Live Metrics React Hook
 *
 * useGcpMetrics(category, env, period)
 *   - Fetches live GCP data from the backend on mount.
 *   - Auto-polls every VITE_METRICS_POLL_MS milliseconds (default 30 s).
 *   - Falls back to `null` data on error so the dashboard can render mock data.
 *   - Exposes { data, loading, error, stale, refetch }.
 *
 * useGcpHealth()
 *   - Fetches the combined cache + GCP circuit-breaker health snapshot.
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import {
  fetchGcpHealth,
  fetchGcpMetrics,
  fetchOverview,
  type Environment,
  type GcpHealthResponse,
  type GcpMetricsResponse,
  type MetricCategory,
  type OverviewResponse,
  type Period,
} from '@/lib/api';

// ---------------------------------------------------------------------------
// Config
// ---------------------------------------------------------------------------

const POLL_MS = Number(import.meta.env.VITE_METRICS_POLL_MS ?? 30_000);

// ---------------------------------------------------------------------------
// Generic async-state hook
// ---------------------------------------------------------------------------

interface AsyncState<T> {
  data: T | null;
  loading: boolean;
  /** True when stale data is shown while a background refresh is in-flight */
  stale: boolean;
  error: Error | null;
}

function useAsyncPoll<T>(
  fetcher: () => Promise<T>,
  pollMs: number,
  deps: unknown[],
  enabled = true,
): AsyncState<T> & { refetch: () => void } {
  const [state, setState] = useState<AsyncState<T>>({
    data: null,
    loading: enabled,
    stale: false,
    error: null,
  });

  const abortRef = useRef<AbortController | null>(null);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const mountedRef = useRef(true);

  const execute = useCallback(
    async (isBackground = false) => {
      if (!mountedRef.current || !enabled) return;

      // Cancel any in-flight request.
      abortRef.current?.abort();
      abortRef.current = new AbortController();

      setState((prev) => ({
        ...prev,
        loading: !isBackground,
        stale: isBackground && prev.data !== null,
      }));

      try {
        const data = await fetcher();
        if (!mountedRef.current) return;
        setState({ data, loading: false, stale: false, error: null });
      } catch (err) {
        if (!mountedRef.current) return;
        const error = err instanceof Error ? err : new Error(String(err));
        setState((prev) => ({
          ...prev,
          loading: false,
          stale: false,
          error,
        }));
      }
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [...deps, enabled],
  );

  // Initial fetch + re-fetch when deps change.
  useEffect(() => {
    mountedRef.current = true;

    if (!enabled) {
      setState({ data: null, loading: false, stale: false, error: null });
      return () => {
        mountedRef.current = false;
        abortRef.current?.abort();
        if (timerRef.current) clearInterval(timerRef.current);
      };
    }

    execute(false);

    if (pollMs > 0) {
      timerRef.current = setInterval(() => execute(true), pollMs);
    }

    return () => {
      mountedRef.current = false;
      abortRef.current?.abort();
      if (timerRef.current) clearInterval(timerRef.current);
    };
    // execute changes when deps change, so this is correct.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [execute, pollMs, enabled]);

  return {
    ...state,
    refetch: () => {
      if (enabled) execute(false);
    },
  };
}

// ---------------------------------------------------------------------------
// useGcpMetrics
// ---------------------------------------------------------------------------

export interface UseGcpMetricsResult extends AsyncState<GcpMetricsResponse> {
  refetch: () => void;
  /** True when the GCP payload is degraded/unavailable */
  isMock: boolean;
}

export function useGcpMetrics(
  category: MetricCategory,
  env: Environment,
  period: Period,
  enabled = true,
): UseGcpMetricsResult {
  // Map frontend environment labels to backend enum values.
  const backendEnv = envToBackend(env);

  const result = useAsyncPoll(
    () => fetchGcpMetrics(category, backendEnv, period),
    POLL_MS,
    [category, backendEnv, period],
    enabled,
  );

  const isMock = result.data?.degraded === true;
  return { ...result, isMock };
}

// ---------------------------------------------------------------------------
// useOverview — aggregated backend dashboard payload
// ---------------------------------------------------------------------------

export interface UseOverviewResult extends AsyncState<OverviewResponse> {
  refetch: () => void;
}

/**
 * Fetch `/api/v1/metrics/overview` for the current environment/period.
 * This endpoint is always available (no GCP credentials required), so it is
 * the dashboard's primary backend data source.
 */
export function useOverview(
  env: Environment,
  period: Period,
  enabled = true,
  pollMs = 30_000,
): UseOverviewResult {
  return useAsyncPoll(
    () => fetchOverview(env, period),
    pollMs,
    [env, period],
    enabled,
  );
}

// ---------------------------------------------------------------------------
// useGcpHealth
// ---------------------------------------------------------------------------

export interface UseGcpHealthResult extends AsyncState<GcpHealthResponse> {
  refetch: () => void;
}

export function useGcpHealth(
  pollMs = 60_000,
  enabled = true,
): UseGcpHealthResult {
  return useAsyncPoll(fetchGcpHealth, pollMs, [], enabled);
}

// ---------------------------------------------------------------------------
// Utility
// ---------------------------------------------------------------------------

/** Map the Portuguese UI environment labels to backend Environment enum values. */
export function envToBackend(env: string): Environment {
  if (env === 'Produção' || env === 'PROD') return 'PROD';
  if (env === 'Homologação' || env === 'STAGING') return 'STAGING';
  return 'DEV';
}

/** Map backend Period string to frontend Period type */
export function periodToBackend(period: string): Period {
  if (period === '1h' || period === '24h' || period === '7d' || period === '30d') return period;
  return '24h';
}

/**
 * Extract a flat array of { timestamp, value } points from a GcpMetricsResponse
 * for a specific metric name, averaging across all label-sets (instances).
 */
export function extractSeries(
  data: GcpMetricsResponse | null,
  metricName: string,
): Array<{ timestamp: string; value: number }> {
  if (!data) return [];
  const raw = data.metrics[metricName];
  if (!raw || 'error' in raw) return [];
  const seriesList = raw as import('@/lib/api').MetricSeriesDto[];
  if (seriesList.length === 0) return [];

  // Build a map of timestamp → averaged value across all label-sets.
  const buckets = new Map<string, { sum: number; count: number }>();
  for (const s of seriesList) {
    for (const pt of s.points) {
      const bucket = buckets.get(pt.timestamp) ?? { sum: 0, count: 0 };
      bucket.sum += pt.value;
      bucket.count += 1;
      buckets.set(pt.timestamp, bucket);
    }
  }

  return [...buckets.entries()]
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([timestamp, { sum, count }]) => ({ timestamp, value: sum / count }));
}
