import { METRIC_KEYS } from './overview';

/** Technical origin, separate from provenance (gcp/cache/demo/estimated). */
export const metricSources = [
  {
    id: 'qdrant', name: 'Qdrant',
    status: 'Integração de leitura disponível',
    description: 'Contagem atual das coleções visíveis à credencial do ambiente.',
    metrics: ["database.qdrant.collections"],
  },
  {
    id: 'gcp', name: 'Google Cloud Platform (GCP)',
    status: 'Integração implementada; acesso real não confirmado',
    description: 'Cloud SQL, Compute Engine, Storage, BigQuery, Vertex AI e SLA. Custos dependem de billing ainda não integrado.',
    metrics: Object.entries(METRIC_KEYS).flatMap(([section, fields]) =>
      Object.values(fields).map(field => `${section}.${field}`)),
  },
  {
    id: 'internal-server', name: 'Servidor Interno',
    status: 'Telemetria do host não implementada',
    description: 'Health da API e diagnóstico do cache existem; não medem CPU, RAM ou disco do servidor interno.',
    metrics: [] as string[],
  },
  {
    id: 'local-tokens', name: 'Tokens Locais',
    status: 'Coletor não implementado',
    description: 'Tokens de Vertex AI pertencem ao GCP. Não há coleta de consumo de modelos ou agentes locais.',
    metrics: [] as string[],
  },
] as const;
