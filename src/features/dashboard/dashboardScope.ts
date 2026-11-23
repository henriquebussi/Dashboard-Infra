import { resources, type Environment, type Metric, type SectionData } from './mock-data';

export const ALL_SERVICES = 'Todos os serviços';

export const serviceSection: Record<string, string> = {
  'Cloud SQL': 'database',
  BigQuery: 'processing',
  'Cloud Storage': 'storage',
  'Compute Engine': 'cloud',
  'Vertex AI': 'tokens',
  'Pub/Sub': 'processing',
  Memorystore: 'database',
};

export function getScopedResources(environment: Environment, service: string, search: string) {
  const term = search.trim().toLowerCase();
  return resources.filter(
    (resource) =>
      resource.env === environment &&
      (service === ALL_SERVICES || resource.service === service) &&
      (!term || `${resource.name} ${resource.service} ${resource.region} ${resource.type}`.toLowerCase().includes(term)),
  );
}

export function getScopedSection(section: SectionData, service: string, scoped: (typeof resources)[number][]) {
  if (service !== ALL_SERVICES && serviceSection[service] !== section.id) return null;
  if (scoped.length === 0) return null;
  const scopeNames = new Set<string>(scoped.map((resource) => resource.name));
  const metrics = section.metrics.map((item) => {
    const matches = item.resources.filter((resource) => scopeNames.has(resource.name));
    const relevant =
      matches.length > 0 ? matches : item.resources.slice(0, Math.min(scoped.length, item.resources.length));
    if (item.isLive) {
      return { ...item, resources: relevant };
    }
    const ratio = relevant.length / Math.max(item.resources.length, 1);
    const numeric = Number(item.value.replace(/[^0-9.]/g, ''));
    const dynamicValue =
      Number.isFinite(numeric) && numeric > 0 && relevant.length > 0
        ? item.value.replace(/[\d,.]+/, (raw) => {
            const computed = numeric * (0.56 + ratio * 0.44);
            const decimals = raw.includes('.') ? (raw.split('.')[1]?.length ?? 0) : 0;
            return computed.toLocaleString('pt-BR', { minimumFractionDigits: decimals, maximumFractionDigits: decimals });
          })
        : item.value;
    return { ...item, value: dynamicValue, resources: relevant };
  });
  return { ...section, metrics };
}

// ---------------------------------------------------------------------------
// Real-mode sanitisation — never render demo numbers as if they were real
// ---------------------------------------------------------------------------

export const UNAVAILABLE = 'Indisponível';

function unavailableMetric(metric: Metric): Metric {
  return {
    ...metric,
    value: UNAVAILABLE,
    change: '—',
    trend: 'flat',
    severity: undefined,
    action: undefined,
    resources: [],
    series: [],
    isLive: false,
    available: false,
    source: 'unavailable',
  };
}

export function sanitizeRealSections(input: SectionData[]): SectionData[] {
  return input.map((section) => ({
    ...section,
    metrics: section.metrics.map((metric) => (metric.isLive && metric.source !== 'demo' ? metric : unavailableMetric(metric))),
  }));
}

export function getRealScopedSection(section: SectionData, service: string, search: string): SectionData | null {
  if (service !== ALL_SERVICES && serviceSection[service] !== section.id) return null;
  const term = search.trim().toLowerCase();
  if (!term) return section;

  const metrics = section.metrics.filter((metric) =>
    `${metric.label} ${metric.description} ${metric.resources.map((resource) => resource.name).join(' ')}`
      .toLowerCase()
      .includes(term),
  );
  return metrics.length > 0 ? { ...section, metrics } : null;
}
