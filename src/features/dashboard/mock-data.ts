export type Period = '24h' | '7d' | '30d';
export type Environment = 'Production' | 'Staging' | 'Development';

export type Metric = {
  id: string;
  label: string;
  value: string;
  unit?: string;
  change: string;
  trend: 'up' | 'down' | 'flat';
  severity?: 'warning' | 'critical';
  action?: string;
  description: string;
  resources: { name: string; value: string; detail: string; severity?: 'warning' | 'critical' }[];
  series: number[];
};

export type SectionData = {
  id: string;
  title: string;
  eyebrow: string;
  summary: string;
  metrics: Metric[];
  series: { name: string; values: number[]; color?: string }[];
};

const resourceNames = ['orders-primary', 'ledger-replica', 'analytics-warehouse', 'identity-store', 'events-stream'];

function resourceBreakdown(values: string[], unit: string, severityAt = -1) {
  return resourceNames.slice(0, values.length).map((name, index) => ({
    name,
    value: values[index],
    detail: `${['us-central1', 'europe-west1', 'asia-east1'][index % 3]} · ${unit}`,
    ...(index === severityAt ? { severity: 'warning' as const } : {}),
  }));
}

function metric(
  id: string,
  label: string,
  value: string,
  change: string,
  trend: Metric['trend'],
  description: string,
  resources: Metric['resources'],
  severity?: Metric['severity'],
  action?: string,
): Metric {
  const match = value.replace(/,/g, '').match(/[0-9]+(?:\.[0-9]+)?/);
  const rawBase = match ? Number(match[0]) : 1;
  const lowerValue = value.toLowerCase();
  const duration = lowerValue.match(/(\d+)m\s+(\d+)s/);
  const base = duration
    ? Number(duration[1]) * 60 + Number(duration[2])
    : rawBase * (lowerValue.includes('m') && !lowerValue.includes('ms') ? 1_000_000 : lowerValue.includes('k') ? 1_000 : 1);
  const seed = [...id].reduce((sum, character) => sum + character.charCodeAt(0), 0);
  const series = Array.from({ length: 24 }, (_, hour) => {
    const dailyCycle = Math.sin((hour / 24) * Math.PI * 2 - 1.3 + seed * 0.04) * 0.075;
    const shortCycle = Math.cos(hour * 0.61 + seed) * 0.028;
    const deterministicVariation = Math.sin(hour * 12.9898 + seed * 78.233) * 0.018;
    return Number(Math.max(0, base * (1 + dailyCycle + shortCycle + deterministicVariation)).toFixed(2));
  });
  return { id, label, value, change, trend, description, resources, severity, action, series };
}

export const sections: SectionData[] = [
  {
    id: 'database', title: 'Database', eyebrow: 'DATA PLANE', summary: 'Query performance and connection pressure',
    metrics: [
      metric('qps', 'Queries / sec', '2,418', '+8.4%', 'up', 'Queries served per second across managed database instances.', resourceBreakdown(['1,204 q/s', '612 q/s', '388 q/s', '142 q/s'], 'queries/sec')),
      metric('connections', 'Active connections', '684', '+12.1%', 'up', 'Current open client connections compared with provisioned capacity.', resourceBreakdown(['284 / 400', '176 / 300', '142 / 250', '82 / 150'], 'connections', 0), 'warning', 'Review connection pooling'),
      metric('locks', 'Lock waits', '14', '+3', 'up', 'Sessions currently waiting on row or table locks.', resourceBreakdown(['8 waits', '4 waits', '2 waits'], 'lock waits')),
      metric('slow-queries', 'Slow queries', '27', '−6.2%', 'down', 'Queries exceeding the 500 ms latency threshold in this window.', resourceBreakdown(['12 queries', '8 queries', '5 queries', '2 queries'], 'slow queries', 0), 'warning', 'Optimize query'),
      metric('response-time', 'Avg. response', '42 ms', '−4.8%', 'down', 'Mean database response time across all monitored instances.', resourceBreakdown(['31 ms', '48 ms', '56 ms', '34 ms'], 'milliseconds')),
      metric('cpu-io', 'CPU / IO pressure', '71%', '+9.3%', 'up', 'Combined compute and storage pressure on the busiest instance.', resourceBreakdown(['84% CPU', '71% CPU', '59% CPU', '44% CPU'], 'utilization', 0), 'critical', 'Scale database tier'),
      metric('replication', 'Replication lag', '1.8 s', '+0.4 s', 'up', 'Time behind primary for cross-region read replicas.', resourceBreakdown(['0.8 s', '1.8 s', '0.4 s'], 'seconds', 1), 'warning', 'Inspect replica health'),
    ],
    series: [
      { name: 'Queries / sec', values: [1680, 1540, 1490, 1460, 1530, 1780, 2120, 2380, 2490, 2310, 2160, 2280, 2410, 2580, 2460, 2330, 2510, 2670, 2520, 2380, 2240, 2110, 1940, 1810] },
      { name: 'Avg response (ms)', values: [39, 37, 38, 36, 38, 40, 44, 49, 53, 48, 43, 42, 45, 51, 47, 42, 46, 50, 45, 43, 41, 40, 39, 42], color: '#72a897' },
    ],
  },
  {
    id: 'cloud', title: 'Cloud', eyebrow: 'COMPUTE FLEET', summary: 'Capacity, reliability and spend',
    metrics: [
      metric('cpu', 'CPU consumed', '68.4%', '+5.2%', 'up', 'Average vCPU utilization across compute instances.', resourceBreakdown(['82%', '74%', '61%', '57%'], 'CPU', 0), 'warning', 'Right-size compute'),
      metric('ram', 'Memory consumed', '72.1%', '+2.8%', 'up', 'Working set utilization across active virtual machines.', resourceBreakdown(['86%', '75%', '63%', '59%'], 'memory', 0), 'warning', 'Review memory headroom'),
      metric('disk', 'Disk consumed', '61.8%', '+1.2%', 'up', 'Provisioned disk capacity currently in use.', resourceBreakdown(['79%', '65%', '58%', '45%'], 'disk', 0), 'warning', 'Review disk growth'),
      metric('cost', 'Estimated cost', '$18,426', '+3.7%', 'up', 'Projected cloud infrastructure charges for the selected period.', resourceBreakdown(['$6,820', '$4,216', '$3,990', '$1,842'], 'USD')),
      metric('uptime', 'Service uptime', '99.97%', '+0.02%', 'up', 'Availability measured across monitored cloud services.', resourceBreakdown(['99.99%', '99.96%', '99.94%', '99.99%'], 'uptime')),
    ],
    series: [
      { name: 'CPU utilization', values: [48, 45, 43, 44, 46, 52, 61, 69, 73, 70, 66, 68, 72, 75, 72, 69, 74, 78, 76, 71, 68, 62, 56, 51] },
      { name: 'Memory utilization', values: [62, 61, 60, 60, 61, 63, 66, 69, 73, 72, 71, 72, 74, 76, 74, 72, 74, 77, 75, 73, 72, 69, 66, 64], color: '#72a897' },
    ],
  },
  {
    id: 'storage', title: 'Storage', eyebrow: 'OBJECT & BLOCK', summary: 'Usage, throughput and latency',
    metrics: [
      metric('usage', 'Total usage', '428.6 TB', '+6.4%', 'up', 'Total object and block storage currently in use.', resourceBreakdown(['184.2 TB', '96.4 TB', '84.8 TB', '63.2 TB'], 'storage', 0), 'warning', 'Increase storage capacity'),
      metric('buckets', 'Bucket utilization', '74.2%', '+4.1%', 'up', 'Average capacity consumed across monitored storage buckets.', resourceBreakdown(['91%', '78%', '67%', '61%'], 'bucket usage', 0), 'critical', 'Increase storage capacity'),
      metric('iops', 'IOPS', '18.4k', '+11.8%', 'up', 'Read and write operations per second across storage volumes.', resourceBreakdown(['8.2k IOPS', '4.8k IOPS', '3.1k IOPS', '2.3k IOPS'], 'IOPS')),
      metric('throughput', 'Throughput', '2.8 GB/s', '+7.2%', 'up', 'Aggregate read/write throughput for this environment.', resourceBreakdown(['1.1 GB/s', '0.7 GB/s', '0.6 GB/s', '0.4 GB/s'], 'throughput')),
      metric('latency', 'Avg. latency', '18.6 ms', '−2.4%', 'down', 'Mean request latency for storage operations.', resourceBreakdown(['14 ms', '19 ms', '24 ms', '17 ms'], 'milliseconds')),
    ],
    series: [
      { name: 'Hot data', color: '#216b4e', values: [146, 145, 144, 144, 145, 147, 150, 153, 156, 158, 160, 162, 164, 166, 168, 169, 171, 173, 175, 177, 179, 181, 183, 184] },
      { name: 'Nearline', color: '#72a897', values: [112, 112, 113, 113, 114, 115, 116, 116, 117, 118, 119, 120, 120, 121, 122, 123, 124, 124, 125, 126, 127, 128, 129, 130] },
      { name: 'Archive', color: '#bfd8ca', values: [86, 86, 86, 87, 87, 88, 88, 89, 89, 90, 90, 91, 91, 92, 92, 93, 93, 94, 95, 95, 96, 96, 97, 98] },
    ],
  },
  {
    id: 'processing', title: 'Processing', eyebrow: 'JOB ORCHESTRATION', summary: 'Queue depth and execution health',
    metrics: [
      metric('queued', 'Queued jobs', '1,284', '+14.2%', 'up', 'Jobs waiting for a worker to become available.', resourceBreakdown(['482 jobs', '338 jobs', '276 jobs', '188 jobs'], 'queued', 0), 'warning', 'Add worker capacity'),
      metric('running', 'Running jobs', '342', '+4.8%', 'up', 'Jobs actively executing across processing pools.', resourceBreakdown(['128 jobs', '94 jobs', '72 jobs', '48 jobs'], 'running')),
      metric('processing-time', 'Avg. processing', '3m 42s', '−8.1%', 'down', 'Average wall-clock time from start to successful completion.', resourceBreakdown(['2m 48s', '3m 16s', '4m 22s', '4m 01s'], 'duration')),
      metric('failures', 'Job failures', '23', '+9', 'up', 'Failed or timed-out jobs in the current reporting window.', resourceBreakdown(['12 failures', '6 failures', '3 failures', '2 failures'], 'failures', 0), 'critical', 'Inspect failed job runs'),
    ],
    series: [{ name: 'Jobs completed / hr', values: [486, 422, 390, 372, 401, 518, 642, 718, 746, 702, 664, 691, 724, 768, 741, 710, 756, 784, 762, 721, 682, 638, 590, 534] }],
  },
  {
    id: 'tokens', title: 'Token Usage', eyebrow: 'MODEL OPERATIONS', summary: 'Inference volume, spend and limits',
    metrics: [
      metric('tokens-day', 'Tokens / day', '8.42M', '+18.6%', 'up', 'Tokens processed by managed model endpoints in this window.', resourceBreakdown(['3.82M', '2.16M', '1.42M', '1.02M'], 'tokens')),
      metric('model-cost', 'Cost / model', '$1,284', '+7.4%', 'up', 'Estimated inference spend grouped by model family.', resourceBreakdown(['$642 · Gemini 1.5 Pro', '$318 · Gemini Flash', '$204 · Claude 3.5', '$120 · Embeddings'], 'USD')),
      metric('error-rate', 'Error rate', '0.84%', '+0.21%', 'up', 'Failed inference requests as a share of all requests.', resourceBreakdown(['1.2%', '0.8%', '0.4%', '0.3%'], 'error rate', 0), 'warning', 'Review endpoint errors'),
      metric('rate-limits', 'Rate limited', '128', '−12.4%', 'down', 'Requests throttled after reaching configured quota limits.', resourceBreakdown(['62 requests', '34 requests', '21 requests', '11 requests'], 'requests')),
    ],
    series: [{ name: 'Tokens (millions)', values: [4.1, 3.8, 3.6, 3.5, 3.8, 4.4, 5.1, 6.2, 7.1, 6.8, 6.4, 6.9, 7.4, 8.2, 7.8, 7.6, 8.1, 8.6, 8.3, 7.9, 7.3, 6.8, 5.9, 5.0] }],
  },
  {
    id: 'sla', title: 'General / SLA', eyebrow: 'SERVICE RELIABILITY', summary: 'Availability, errors and growth',
    metrics: [
      metric('availability', 'Availability', '99.96%', '+0.03%', 'up', 'Rolling service availability across the monitored platform.', resourceBreakdown(['99.99%', '99.96%', '99.92%', '99.98%'], 'availability')),
      metric('errors', '4xx / 5xx errors', '1.24k', '+6.8%', 'up', 'Client and server-side response errors during this period.', resourceBreakdown(['842 4xx', '214 5xx', '126 4xx', '58 5xx'], 'errors', 1), 'warning', 'Investigate server errors'),
      metric('peak', 'Peak usage', '82.4%', '+3.2%', 'up', 'Highest observed resource saturation in selected time window.', resourceBreakdown(['91%', '82%', '76%', '68%'], 'peak', 0), 'critical', 'Review capacity plan'),
      metric('growth', 'Growth trend', '+12.8%', '+1.6 pts', 'up', 'Change in aggregate workload volume versus prior period.', resourceBreakdown(['+16.4%', '+12.8%', '+9.1%', '+7.6%'], 'growth')),
    ],
    series: [{ name: 'Availability (%)', values: [99.98, 99.99, 100, 99.98, 99.97, 99.96, 99.95, 99.94, 99.96, 99.98, 99.99, 99.97, 99.95, 99.94, 99.97, 99.98, 99.99, 99.97, 99.96, 99.98, 99.99, 100, 99.98, 99.97] }],
  },
];

export const resources = [
  { name: 'orders-primary', env: 'Production', service: 'Cloud SQL', region: 'us-central1', type: 'Database' },
  { name: 'ledger-replica', env: 'Production', service: 'Cloud SQL', region: 'europe-west1', type: 'Database' },
  { name: 'analytics-warehouse', env: 'Staging', service: 'BigQuery', region: 'us-central1', type: 'Processing' },
  { name: 'identity-store', env: 'Production', service: 'Memorystore', region: 'asia-east1', type: 'Database' },
  { name: 'events-stream', env: 'Development', service: 'Pub/Sub', region: 'us-central1', type: 'Processing' },
  { name: 'media-archive', env: 'Production', service: 'Cloud Storage', region: 'europe-west1', type: 'Storage' },
  { name: 'api-workers', env: 'Staging', service: 'Compute Engine', region: 'us-central1', type: 'Cloud' },
  { name: 'model-inference', env: 'Production', service: 'Vertex AI', region: 'us-central1', type: 'Token Usage' },
] as const;

export const generateHourlySeries = (period: Period, points: number[]) => {
  const count = period === '24h' ? 24 : period === '7d' ? 28 : 30;
  const labels = period === '24h'
    ? Array.from({ length: 24 }, (_, i) => `${String((i + 1) % 24).padStart(2, '0')}:00`)
    : Array.from({ length: count }, (_, i) => period === '7d' ? `D${Math.floor(i / 4) + 1}` : `D${i + 1}`);
  const values = period === '24h'
    ? points
    : Array.from({ length: count }, (_, i) => {
      const start = Math.floor(i * points.length / count);
      const end = Math.max(start + 1, Math.floor((i + 1) * points.length / count));
      const slice = points.slice(start, end);
      return Number((slice.reduce((a, b) => a + b, 0) / slice.length).toFixed(2));
    });
  return { labels, values };
};
