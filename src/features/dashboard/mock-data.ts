export type Period = '24h' | '7d' | '30d';
export type Environment = 'Produção' | 'Homologação' | 'Desenvolvimento';

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
  /** True when the metric was populated by the backend API. */
  isLive?: boolean;
};

export type SectionData = {
  id: string;
  title: string;
  eyebrow: string;
  summary: string;
  metrics: Metric[];
  series: { name: string; values: number[]; color?: string }[];
};

const resourceNames = ['solo-primary', 'clima-replica', 'imagens-drone', 'sensores-store', 'telemetria-stream'];

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
    id: 'database', title: 'Banco de dados', eyebrow: 'PLANO DE DADOS', summary: 'Desempenho de consultas e pressão de conexões',
    metrics: [
      metric('qps', 'Consultas / s', '2,418', '+8.4%', 'up', 'Consultas atendidas por segundo nas instâncias gerenciadas do banco de dados.', resourceBreakdown(['1,204 q/s', '612 q/s', '388 q/s', '142 q/s'], 'consultas/s')),
      metric('connections', 'Conexões ativas', '684', '+12.1%', 'up', 'Conexões de clientes abertas no momento, comparadas à capacidade provisionada.', resourceBreakdown(['284 / 400', '176 / 300', '142 / 250', '82 / 150'], 'conexões', 0), 'warning', 'Revisar o pool de conexões'),
      metric('locks', 'Esperas de bloqueio', '14', '+3', 'up', 'Sessões aguardando bloqueios de linha ou de tabela.', resourceBreakdown(['8 esperas', '4 esperas', '2 esperas'], 'esperas de bloqueio')),
      metric('slow-queries', 'Consultas lentas', '27', '−6.2%', 'down', 'Consultas que excedem o limite de latência de 500 ms nesta janela.', resourceBreakdown(['12 consultas', '8 consultas', '5 consultas', '2 consultas'], 'consultas lentas', 0), 'warning', 'Otimizar a consulta'),
      metric('response-time', 'Tempo médio de resposta', '42 ms', '−4.8%', 'down', 'Tempo médio de resposta do banco em todas as instâncias monitoradas.', resourceBreakdown(['31 ms', '48 ms', '56 ms', '34 ms'], 'milissegundos')),
      metric('cpu-io', 'Pressão de CPU / IO', '71%', '+9.3%', 'up', 'Pressão combinada de computação e armazenamento na instância mais movimentada.', resourceBreakdown(['84% CPU', '71% CPU', '59% CPU', '44% CPU'], 'utilização', 0), 'critical', 'Escalar a camada do banco'),
      metric('replication', 'Atraso de replicação', '1.8 s', '+0.4 s', 'up', 'Atraso em relação ao primário nas réplicas de leitura entre regiões.', resourceBreakdown(['0.8 s', '1.8 s', '0.4 s'], 'segundos', 1), 'warning', 'Inspecionar a saúde das réplicas'),
    ],
    series: [
      { name: 'Consultas / s', values: [1680, 1540, 1490, 1460, 1530, 1780, 2120, 2380, 2490, 2310, 2160, 2280, 2410, 2580, 2460, 2330, 2510, 2670, 2520, 2380, 2240, 2110, 1940, 1810] },
      { name: 'Tempo médio de resposta (ms)', values: [39, 37, 38, 36, 38, 40, 44, 49, 53, 48, 43, 42, 45, 51, 47, 42, 46, 50, 45, 43, 41, 40, 39, 42], color: '#72a897' },
    ],
  },
  {
    id: 'cloud', title: 'Nuvem', eyebrow: 'FROTA DE COMPUTAÇÃO', summary: 'Capacidade, confiabilidade e custos',
    metrics: [
      metric('cpu', 'CPU consumida', '68.4%', '+5.2%', 'up', 'Utilização média de vCPU nas instâncias de computação.', resourceBreakdown(['82%', '74%', '61%', '57%'], 'CPU', 0), 'warning', 'Redimensionar a computação'),
      metric('ram', 'Memória consumida', '72.1%', '+2.8%', 'up', 'Utilização do conjunto de trabalho nas máquinas virtuais ativas.', resourceBreakdown(['86%', '75%', '63%', '59%'], 'memória', 0), 'warning', 'Revisar a folga de memória'),
      metric('disk', 'Disco consumido', '61.8%', '+1.2%', 'up', 'Capacidade de disco provisionada atualmente em uso.', resourceBreakdown(['79%', '65%', '58%', '45%'], 'disco', 0), 'warning', 'Revisar o crescimento do disco'),
      metric('cost', 'Custo estimado', '$18,426', '+3.7%', 'up', 'Cobranças projetadas de infraestrutura em nuvem para o período selecionado.', resourceBreakdown(['$6,820', '$4,216', '$3,990', '$1,842'], 'USD')),
      metric('uptime', 'Disponibilidade do serviço', '99.97%', '+0.02%', 'up', 'Disponibilidade medida nos serviços de nuvem monitorados.', resourceBreakdown(['99.99%', '99.96%', '99.94%', '99.99%'], 'disponibilidade')),
    ],
    series: [
      { name: 'Utilização de CPU', values: [48, 45, 43, 44, 46, 52, 61, 69, 73, 70, 66, 68, 72, 75, 72, 69, 74, 78, 76, 71, 68, 62, 56, 51] },
      { name: 'Utilização de memória', values: [62, 61, 60, 60, 61, 63, 66, 69, 73, 72, 71, 72, 74, 76, 74, 72, 74, 77, 75, 73, 72, 69, 66, 64], color: '#72a897' },
    ],
  },
  {
    id: 'storage', title: 'Armazenamento', eyebrow: 'OBJETOS E BLOCOS', summary: 'Uso, vazão e latência',
    metrics: [
      metric('usage', 'Uso total', '428.6 TB', '+6.4%', 'up', 'Total de armazenamento de objetos e blocos atualmente em uso.', resourceBreakdown(['184.2 TB', '96.4 TB', '84.8 TB', '63.2 TB'], 'armazenamento', 0), 'warning', 'Aumentar a capacidade de armazenamento'),
      metric('buckets', 'Utilização dos buckets', '74.2%', '+4.1%', 'up', 'Capacidade média consumida nos buckets de armazenamento monitorados.', resourceBreakdown(['91%', '78%', '67%', '61%'], 'uso do bucket', 0), 'critical', 'Aumentar a capacidade de armazenamento'),
      metric('iops', 'IOPS', '18.4k', '+11.8%', 'up', 'Operações de leitura e escrita por segundo nos volumes de armazenamento.', resourceBreakdown(['8.2k IOPS', '4.8k IOPS', '3.1k IOPS', '2.3k IOPS'], 'IOPS')),
      metric('throughput', 'Vazão', '2.8 GB/s', '+7.2%', 'up', 'Vazão agregada de leitura e escrita para este ambiente.', resourceBreakdown(['1.1 GB/s', '0.7 GB/s', '0.6 GB/s', '0.4 GB/s'], 'vazão')),
      metric('latency', 'Latência média', '18.6 ms', '−2.4%', 'down', 'Latência média das requisições de armazenamento.', resourceBreakdown(['14 ms', '19 ms', '24 ms', '17 ms'], 'milissegundos')),
    ],
    series: [
      { name: 'Dados quentes', color: '#216b4e', values: [146, 145, 144, 144, 145, 147, 150, 153, 156, 158, 160, 162, 164, 166, 168, 169, 171, 173, 175, 177, 179, 181, 183, 184] },
      { name: 'Nearline', color: '#72a897', values: [112, 112, 113, 113, 114, 115, 116, 116, 117, 118, 119, 120, 120, 121, 122, 123, 124, 124, 125, 126, 127, 128, 129, 130] },
      { name: 'Arquivo', color: '#bfd8ca', values: [86, 86, 86, 87, 87, 88, 88, 89, 89, 90, 90, 91, 91, 92, 92, 93, 93, 94, 95, 95, 96, 96, 97, 98] },
    ],
  },
  {
    id: 'processing', title: 'Processamento', eyebrow: 'ORQUESTRAÇÃO DE JOBS', summary: 'Profundidade da fila e saúde da execução',
    metrics: [
      metric('queued', 'Jobs na fila', '1,284', '+14.2%', 'up', 'Jobs aguardando um worker ficar disponível.', resourceBreakdown(['482 jobs', '338 jobs', '276 jobs', '188 jobs'], 'na fila', 0), 'warning', 'Adicionar capacidade de workers'),
      metric('running', 'Jobs em execução', '342', '+4.8%', 'up', 'Jobs em execução ativa nos pools de processamento.', resourceBreakdown(['128 jobs', '94 jobs', '72 jobs', '48 jobs'], 'em execução')),
      metric('processing-time', 'Tempo médio de processamento', '3m 42s', '−8.1%', 'down', 'Tempo médio, em tempo real, do início até a conclusão com sucesso.', resourceBreakdown(['2m 48s', '3m 16s', '4m 22s', '4m 01s'], 'duração')),
      metric('failures', 'Falhas de jobs', '23', '+9', 'up', 'Jobs com falha ou tempo esgotado na janela de análise atual.', resourceBreakdown(['12 falhas', '6 falhas', '3 falhas', '2 falhas'], 'falhas', 0), 'critical', 'Inspecionar execuções com falha'),
    ],
    series: [
      { name: 'Jobs concluídos / h', values: [486, 422, 390, 372, 401, 518, 642, 718, 746, 702, 664, 691, 724, 768, 741, 710, 756, 784, 762, 721, 682, 638, 590, 534], color: '#216b4e' },
      { name: 'Pools de processamento ativos', values: [242, 218, 204, 196, 214, 276, 332, 368, 384, 358, 336, 350, 368, 394, 380, 362, 386, 404, 390, 368, 346, 324, 298, 270], color: '#72a897' },
    ],
  },
  {
    id: 'tokens', title: 'Uso de tokens', eyebrow: 'OPERAÇÕES DE MODELO', summary: 'Volume de inferência, custos e limites',
    metrics: [
      metric('tokens-day', 'Tokens / dia', '8.42M', '+18.6%', 'up', 'Tokens processados pelos endpoints de modelo gerenciados nesta janela.', resourceBreakdown(['3.82M', '2.16M', '1.42M', '1.02M'], 'tokens')),
      metric('model-cost', 'Custo / modelo', '$1,284', '+7.4%', 'up', 'Custo estimado de inferência agrupado por família de modelos.', resourceBreakdown(['$642 · Gemini 1.5 Pro', '$318 · Gemini Flash', '$204 · Claude 3.5', '$120 · Embeddings'], 'USD')),
      metric('error-rate', 'Taxa de erro', '0.84%', '+0.21%', 'up', 'Requisições de inferência com falha em relação ao total de requisições.', resourceBreakdown(['1.2%', '0.8%', '0.4%', '0.3%'], 'taxa de erro', 0), 'warning', 'Revisar erros do endpoint'),
      metric('rate-limits', 'Requisições limitadas', '128', '−12.4%', 'down', 'Requisições limitadas após atingir as cotas configuradas.', resourceBreakdown(['62 requisições', '34 requisições', '21 requisições', '11 requisições'], 'requisições')),
    ],
    series: [{ name: 'Tokens (milhões)', values: [4.1, 3.8, 3.6, 3.5, 3.8, 4.4, 5.1, 6.2, 7.1, 6.8, 6.4, 6.9, 7.4, 8.2, 7.8, 7.6, 8.1, 8.6, 8.3, 7.9, 7.3, 6.8, 5.9, 5.0], color: '#216b4e' }],
  },
  {
    id: 'sla', title: 'Geral / SLA', eyebrow: 'CONFIABILIDADE DO SERVIÇO', summary: 'Disponibilidade, erros e crescimento',
    metrics: [
      metric('availability', 'Disponibilidade', '99.96%', '+0.03%', 'up', 'Disponibilidade contínua do serviço em toda a plataforma monitorada.', resourceBreakdown(['99.99%', '99.96%', '99.92%', '99.98%'], 'disponibilidade')),
      metric('errors', 'Erros 4xx / 5xx', '1.24k', '+6.8%', 'up', 'Erros de resposta do cliente e do servidor durante este período.', resourceBreakdown(['842 4xx', '214 5xx', '126 4xx', '58 5xx'], 'erros', 1), 'warning', 'Investigar erros do servidor'),
      metric('peak', 'Pico de uso', '82.4%', '+3.2%', 'up', 'Maior saturação de recursos observada na janela selecionada.', resourceBreakdown(['91%', '82%', '76%', '68%'], 'pico', 0), 'critical', 'Revisar o plano de capacidade'),
      metric('growth', 'Tendência de crescimento', '+12.8%', '+1,6 p.p.', 'up', 'Variação do volume agregado de carga em relação ao período anterior.', resourceBreakdown(['+16.4%', '+12.8%', '+9.1%', '+7.6%'], 'crescimento')),
    ],
    series: [
      { name: 'Disponibilidade (%)', values: [99.98, 99.99, 100, 99.98, 99.97, 99.96, 99.95, 99.94, 99.96, 99.98, 99.99, 99.97, 99.95, 99.94, 99.97, 99.98, 99.99, 99.97, 99.96, 99.98, 99.99, 100, 99.98, 99.97], color: '#216b4e' },
      { name: 'Índice de saúde da plataforma', values: [98.2, 98.4, 98.8, 98.5, 98.1, 97.8, 97.5, 97.2, 97.6, 98.1, 98.5, 98.2, 97.9, 97.6, 98.0, 98.3, 98.6, 98.2, 98.0, 98.3, 98.5, 98.8, 98.4, 98.1], color: '#72a897' },
    ],
  },
];

export const resources = [
  { name: 'solo-primary', env: 'Produção', service: 'Cloud SQL', region: 'us-central1', type: 'Banco de dados' },
  { name: 'clima-replica', env: 'Produção', service: 'Cloud SQL', region: 'europe-west1', type: 'Banco de dados' },
  { name: 'imagens-drone', env: 'Homologação', service: 'BigQuery', region: 'us-central1', type: 'Processamento' },
  { name: 'sensores-store', env: 'Produção', service: 'Memorystore', region: 'asia-east1', type: 'Banco de dados' },
  { name: 'telemetria-stream', env: 'Desenvolvimento', service: 'Pub/Sub', region: 'us-central1', type: 'Processamento' },
  { name: 'arquivo-imagens', env: 'Produção', service: 'Cloud Storage', region: 'europe-west1', type: 'Armazenamento' },
  { name: 'workers-clima', env: 'Homologação', service: 'Compute Engine', region: 'us-central1', type: 'Nuvem' },
  { name: 'inferencia-ia', env: 'Produção', service: 'Vertex AI', region: 'us-central1', type: 'Uso de tokens' },
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
