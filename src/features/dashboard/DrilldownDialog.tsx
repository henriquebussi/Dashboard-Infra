import { useState } from 'react';
import {
  AlertTriangle,
  ArrowUpRight,
  BrainCircuit,
  Check,
  CircleAlert,
  Clock,
  Cloud,
  Database,
  FileText,
  HardDrive,
  Layers,
  Lightbulb,
  ShieldCheck,
  Workflow,
} from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { SourceBadge } from './SourceDot';
import type { Environment, Metric, Period } from './mock-data';
import {
  envToBackend,
  useGcpErrors,
  useGcpResources,
  useSlowQueries,
  useTokenUsage,
} from '@/lib/useMetrics';

type Props = {
  metric: Metric | null;
  category?: string;
  environment?: Environment;
  period?: Period;
  realMode?: boolean;
  onClose: () => void;
};

const categoryIcons: Record<string, typeof Database> = {
  database: Database,
  cloud: Cloud,
  storage: HardDrive,
  processing: Workflow,
  tokens: BrainCircuit,
  sla: ShieldCheck,
};

function periodToHours(period?: Period): number {
  switch (period) {
    case '1h':
      return 1;
    case '24h':
      return 24;
    case '7d':
      return 168;
    case '30d':
      return 720;
    default:
      return 24;
  }
}

function formatLogTimestamp(ts: string | null): string {
  if (!ts) return '—';
  try {
    const dt = new Date(ts);
    if (Number.isNaN(dt.getTime())) return ts;
    return dt.toLocaleString('pt-BR', {
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
      day: '2-digit',
      month: '2-digit',
    });
  } catch {
    return ts;
  }
}

export function DrilldownDialog({
  metric,
  category = 'database',
  environment = 'Produção',
  period = '24h',
  realMode = true,
  onClose,
}: Props) {
  const [activeTab, setActiveTab] = useState<string>('resources');

  const backendEnv = envToBackend(environment);
  const hours = periodToHours(period);

  const isDatabase = category === 'database' || (metric?.id ? ['qps', 'connections', 'locks', 'slow-queries', 'response-time', 'replication'].includes(metric.id) : false);
  const isTokens = category === 'tokens' || (metric?.id ? ['tokens-day', 'model-cost', 'error-rate', 'rate-limits'].includes(metric.id) : false);
  const isSla = category === 'sla' || (metric?.id ? ['availability', 'errors', 'peak', 'growth'].includes(metric.id) : false);

  // Queries for drill-down panels
  const gcpResourcesResult = useGcpResources({ env: backendEnv }, Boolean(metric) && realMode);
  const slowQueriesResult = useSlowQueries(backendEnv, { hours, thresholdMs: 500 }, Boolean(metric) && realMode && isDatabase);
  const tokenUsageResult = useTokenUsage(backendEnv, hours, 120, Boolean(metric) && realMode && isTokens);
  const gcpErrorsResult = useGcpErrors(backendEnv, { hours, maxEntries: 50 }, Boolean(metric) && realMode && isSla);

  if (!metric) return null;

  const IconComponent = categoryIcons[category] ?? Database;
  const severityLabel = metric.severity === 'critical' ? 'crítico' : 'atenção';
  const isAvailable = metric.available !== false;

  return (
    <Dialog open={Boolean(metric)} onOpenChange={(open) => !open && onClose()}>
      <DialogContent data-testid="dialog-metric-detail" className="max-h-[92dvh] overflow-y-auto rounded-xl border-[#dce6df] p-0 sm:max-w-[760px]">
        {/* Header */}
        <div className="border-b border-[#e8eeea] bg-[#fbfdfb] px-6 pb-5 pt-6">
          <DialogHeader>
            <div className="mb-3 flex items-center gap-2">
              <span className="flex h-8 w-8 items-center justify-center rounded-md bg-[#eaf3ed] text-[#286b4c]">
                <IconComponent className="h-4 w-4" />
              </span>
              <span className="text-[10px] font-bold uppercase tracking-[.16em] text-[#718078]">
                Detalhamento Operacional · {category.toUpperCase()}
              </span>
              <div className="ml-auto flex items-center gap-2">
                <SourceBadge source={metric.source ?? (realMode ? 'gcp' : 'demo')} />
                {metric.severity && (
                  <Badge className={metric.severity === 'critical' ? 'rounded-sm border border-[#f1c6c0] bg-[#fff1ef] text-[#a83c30]' : 'rounded-sm border border-[#efd8a8] bg-[#fff8e8] text-[#916315]'}>
                    {severityLabel}
                  </Badge>
                )}
              </div>
            </div>
            <DialogTitle className="font-display text-[23px] font-bold tracking-[-.035em] text-[#203329]">
              {metric.label}
            </DialogTitle>
            <DialogDescription className="text-sm leading-relaxed text-[#6f7d75]">
              {metric.description}
            </DialogDescription>
          </DialogHeader>

          <div className="mt-5 flex items-end justify-between">
            <div>
              <span className="font-display text-[38px] font-bold leading-none tracking-[-.05em] text-[#1c3328]">
                {metric.value}
              </span>
              <span className="ml-3 font-mono text-xs text-[#78857d]">
                {metric.change} vs. período anterior ({period})
              </span>
            </div>
            {!isAvailable && metric.reason && (
              <div className="max-w-xs text-right text-[11px] font-medium text-[#ad5442]">
                Motivo: {metric.reason}
              </div>
            )}
          </div>
        </div>

        {/* Navigation Tabs */}
        <div className="px-6 pt-4">
          <Tabs value={activeTab} onValueChange={setActiveTab}>
            <TabsList className="h-9 w-full justify-start rounded-md border border-[#e5ebe7] bg-[#f5f8f6] p-0.5">
              <TabsTrigger value="resources" className="gap-1.5 text-xs font-semibold data-[state=active]:bg-white data-[state=active]:text-[#224e37] data-[state=active]:shadow-sm">
                <Layers className="h-3.5 w-3.5" />
                Recursos & Breakdown
              </TabsTrigger>
              {isDatabase && (
                <TabsTrigger value="slow_queries" className="gap-1.5 text-xs font-semibold data-[state=active]:bg-white data-[state=active]:text-[#224e37] data-[state=active]:shadow-sm">
                  <Database className="h-3.5 w-3.5" />
                  Consultas Lentas
                </TabsTrigger>
              )}
              {isTokens && (
                <TabsTrigger value="token_usage" className="gap-1.5 text-xs font-semibold data-[state=active]:bg-white data-[state=active]:text-[#224e37] data-[state=active]:shadow-sm">
                  <BrainCircuit className="h-3.5 w-3.5" />
                  Uso de Tokens
                </TabsTrigger>
              )}
              {isSla && (
                <TabsTrigger value="error_logs" className="gap-1.5 text-xs font-semibold data-[state=active]:bg-white data-[state=active]:text-[#224e37] data-[state=active]:shadow-sm">
                  <FileText className="h-3.5 w-3.5" />
                  Logs de Erro (Cloud Logging)
                </TabsTrigger>
              )}
            </TabsList>

            {/* TAB: Resources */}
            <TabsContent value="resources" className="mt-4 focus-visible:outline-none">
              <div className="mb-3 flex items-center justify-between">
                <h3 className="text-[11px] font-bold uppercase tracking-[.12em] text-[#707d75]">
                  Recursos Monitorados
                </h3>
                <span className="font-mono text-[10px] text-[#95a099]">
                  {metric.resources.length} instâncias
                </span>
              </div>

              {metric.resources.length > 0 ? (
                <div className="divide-y divide-[#edf1ee] rounded-lg border border-[#e6ece8]">
                  {metric.resources.map((resource, index) => (
                    <div
                      key={resource.name}
                      data-testid={`row-resource-${metric.id}-${index}`}
                      className="flex items-center justify-between gap-3 px-3.5 py-3 transition-colors hover:bg-[#fafcfb]"
                    >
                      <div className="min-w-0">
                        <div className="flex items-center gap-2 text-[13px] font-semibold text-[#293a31]">
                          <span
                            className={`h-1.5 w-1.5 shrink-0 rounded-full ${
                              resource.severity === 'critical'
                                ? 'bg-[#bd493c]'
                                : resource.severity === 'warning'
                                  ? 'bg-[#bd8b2c]'
                                  : 'bg-[#5d9b78]'
                            }`}
                          />
                          <span className="truncate">{resource.name}</span>
                        </div>
                        {resource.detail && (
                          <div className="ml-3.5 mt-0.5 text-[10px] text-[#8a968f]">{resource.detail}</div>
                        )}
                      </div>
                      <div className="flex shrink-0 items-center gap-2">
                        {resource.severity && <CircleAlert className="h-3.5 w-3.5 text-[#b68124]" />}
                        <span className="font-mono text-xs font-medium text-[#34493c]">{resource.value}</span>
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="rounded-lg border border-dashed border-[#dce6df] bg-[#f9fbf9] p-6 text-center text-xs text-[#738279]">
                  Nenhum detalhamento individual de recurso disponível para esta métrica no escopo atual.
                </div>
              )}

              {/* Discovered GCP Resources inventory */}
              {realMode && gcpResourcesResult.data && gcpResourcesResult.data.length > 0 && (
                <div className="mt-5">
                  <div className="mb-2 flex items-center justify-between">
                    <span className="text-[11px] font-bold uppercase tracking-[.12em] text-[#707d75]">
                      Inventário Descoberto via Labels GCP ({gcpResourcesResult.data.length})
                    </span>
                  </div>
                  <div className="max-h-40 overflow-y-auto rounded-lg border border-[#e6ece8] bg-[#fbfdfb] p-2 text-xs">
                    <div className="grid grid-cols-1 gap-1.5 sm:grid-cols-2">
                      {gcpResourcesResult.data.slice(0, 8).map((res) => (
                        <div key={res.name} className="flex items-center justify-between rounded border border-[#eaf0ec] bg-white px-2.5 py-1.5">
                          <div className="min-w-0">
                            <div className="truncate font-medium text-[#293b31]">{res.name}</div>
                            <div className="text-[9px] text-[#809087]">{res.service} · {res.region}</div>
                          </div>
                          <span className="ml-2 font-mono text-[10px] text-[#4b7a60]">{res.resource_type}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                </div>
              )}
            </TabsContent>

            {/* TAB: Slow Queries (Cloud SQL) */}
            {isDatabase && (
              <TabsContent value="slow_queries" className="mt-4 focus-visible:outline-none">
                <div className="mb-3 flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <h3 className="text-[11px] font-bold uppercase tracking-[.12em] text-[#707d75]">
                      Consultas Cloud SQL (&gt; 500 ms)
                    </h3>
                    {slowQueriesResult.data?.capped && (
                      <Badge className="border-[#efd8a8] bg-[#fff8e8] text-[9px] font-bold text-[#916315]">
                        Amostra Bounded (50 registros)
                      </Badge>
                    )}
                  </div>
                  <span className="font-mono text-[10px] text-[#95a099]">
                    {slowQueriesResult.data?.entries.length ?? 0} consultas
                  </span>
                </div>

                {slowQueriesResult.loading ? (
                  <div className="py-8 text-center text-xs text-[#708076]">Carregando logs do Cloud SQL…</div>
                ) : slowQueriesResult.error ? (
                  <div className="rounded-lg border border-[#f3d3cf] bg-[#fff6f5] p-4 text-xs text-[#a03d32]">
                    <div className="font-semibold">Não foi possível carregar consultas lentas</div>
                    <div className="mt-1 text-[11px]">{slowQueriesResult.error.message}</div>
                  </div>
                ) : slowQueriesResult.data && slowQueriesResult.data.entries.length > 0 ? (
                  <div className="max-h-[320px] overflow-y-auto rounded-lg border border-[#e6ece8]">
                    <table className="w-full text-left text-xs">
                      <thead className="sticky top-0 border-b border-[#e6ece8] bg-[#f7faf8] text-[10px] uppercase tracking-wider text-[#6b7b71]">
                        <tr>
                          <th className="px-3 py-2">Horário</th>
                          <th className="px-3 py-2">Duração</th>
                          <th className="px-3 py-2">Banco</th>
                          <th className="px-3 py-2">Consulta SQL</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-[#edf1ee] bg-white">
                        {slowQueriesResult.data.entries.map((item, idx) => (
                          <tr key={idx} className="hover:bg-[#f9fbf9]">
                            <td className="whitespace-nowrap px-3 py-2 font-mono text-[11px] text-[#55675c]">
                              {formatLogTimestamp(item.timestamp)}
                            </td>
                            <td className="whitespace-nowrap px-3 py-2 font-mono font-semibold text-[#bd493c]">
                              {item.duration_ms !== null ? `${item.duration_ms} ms` : '—'}
                            </td>
                            <td className="whitespace-nowrap px-3 py-2 font-mono text-[11px] text-[#69796f]">
                              {item.database_id ?? 'default'}
                            </td>
                            <td className="max-w-[340px] truncate px-3 py-2 font-mono text-[11px] text-[#293a31]" title={item.query_text}>
                              <code>{item.query_text}</code>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                ) : (
                  <div className="rounded-lg border border-dashed border-[#dce6df] bg-[#f9fbf9] p-6 text-center text-xs text-[#738279]">
                    Nenhuma consulta lenta identificada nos logs do Cloud SQL na janela selecionada ({period}).
                  </div>
                )}
              </TabsContent>
            )}

            {/* TAB: Token Usage (Vertex AI) */}
            {isTokens && (
              <TabsContent value="token_usage" className="mt-4 focus-visible:outline-none">
                <div className="mb-3 flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <h3 className="text-[11px] font-bold uppercase tracking-[.12em] text-[#707d75]">
                      Consumo de Tokens & Predições
                    </h3>
                    {(tokenUsageResult.data?.capped || tokenUsageResult.data?.estimated) && (
                      <Badge className="border-[#efd8a8] bg-[#fff8e8] text-[9px] font-bold text-[#916315]">
                        Amostra Bounded
                      </Badge>
                    )}
                  </div>
                  <span className="font-mono text-[10px] text-[#95a099]">
                    {tokenUsageResult.data?.entries.length ?? 0} eventos
                  </span>
                </div>

                {tokenUsageResult.loading ? (
                  <div className="py-8 text-center text-xs text-[#708076]">Carregando telemetria de tokens…</div>
                ) : tokenUsageResult.error ? (
                  <div className="rounded-lg border border-[#f3d3cf] bg-[#fff6f5] p-4 text-xs text-[#a03d32]">
                    <div className="font-semibold">Erro ao recuperar logs de tokens</div>
                    <div className="mt-1 text-[11px]">{tokenUsageResult.error.message}</div>
                  </div>
                ) : tokenUsageResult.data && tokenUsageResult.data.entries.length > 0 ? (
                  <div className="max-h-[320px] overflow-y-auto rounded-lg border border-[#e6ece8]">
                    <table className="w-full text-left text-xs">
                      <thead className="sticky top-0 border-b border-[#e6ece8] bg-[#f7faf8] text-[10px] uppercase tracking-wider text-[#6b7b71]">
                        <tr>
                          <th className="px-3 py-2">Horário</th>
                          <th className="px-3 py-2">Modelo / Endpoint</th>
                          <th className="px-3 py-2">Severidade</th>
                          <th className="px-3 py-2">Detalhes</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-[#edf1ee] bg-white">
                        {tokenUsageResult.data.entries.map((item, idx) => (
                          <tr key={idx} className="hover:bg-[#f9fbf9]">
                            <td className="whitespace-nowrap px-3 py-2 font-mono text-[11px] text-[#55675c]">
                              {formatLogTimestamp(item.timestamp)}
                            </td>
                            <td className="whitespace-nowrap px-3 py-2 font-semibold text-[#293a31]">
                              {String(item.labels?.model_id ?? item.payload?.model ?? item.resource_type ?? 'Vertex AI')}
                            </td>
                            <td className="whitespace-nowrap px-3 py-2">
                              <Badge className="border-[#dfe7e2] bg-[#f2f7f4] text-[9px] text-[#346b4c]">
                                {item.severity}
                              </Badge>
                            </td>
                            <td className="max-w-[300px] truncate px-3 py-2 font-mono text-[11px] text-[#69796f]">
                              {JSON.stringify(item.payload ?? item.labels)}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                ) : (
                  <div className="rounded-lg border border-dashed border-[#dce6df] bg-[#f9fbf9] p-6 text-center text-xs text-[#738279]">
                    Nenhum evento detalhado de tokens encontrado no Cloud Logging para este período.
                  </div>
                )}
              </TabsContent>
            )}

            {/* TAB: Error Logs (Cloud Logging) */}
            {isSla && (
              <TabsContent value="error_logs" className="mt-4 focus-visible:outline-none">
                <div className="mb-3 flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <h3 className="text-[11px] font-bold uppercase tracking-[.12em] text-[#707d75]">
                      Stream de Logs de Erro (severity &gt;= ERROR)
                    </h3>
                    {(gcpErrorsResult.data?.capped || gcpErrorsResult.data?.estimated) && (
                      <Badge className="border-[#efd8a8] bg-[#fff8e8] text-[9px] font-bold text-[#916315]">
                        Estimated / Limite de Logs Atingido
                      </Badge>
                    )}
                  </div>
                  <span className="font-mono text-[10px] text-[#95a099]">
                    {gcpErrorsResult.data?.entries.length ?? 0} erros
                  </span>
                </div>

                {gcpErrorsResult.loading ? (
                  <div className="py-8 text-center text-xs text-[#708076]">Buscando logs de erro no Cloud Logging…</div>
                ) : gcpErrorsResult.error ? (
                  <div className="rounded-lg border border-[#f3d3cf] bg-[#fff6f5] p-4 text-xs text-[#a03d32]">
                    <div className="font-semibold">Erro ao consultar Cloud Logging</div>
                    <div className="mt-1 text-[11px]">{gcpErrorsResult.error.message}</div>
                  </div>
                ) : gcpErrorsResult.data && gcpErrorsResult.data.entries.length > 0 ? (
                  <div className="max-h-[320px] overflow-y-auto rounded-lg border border-[#e6ece8]">
                    <div className="divide-y divide-[#edf1ee]">
                      {gcpErrorsResult.data.entries.map((entry, idx) => (
                        <div key={idx} className="p-3 text-xs hover:bg-[#fffdfd]">
                          <div className="flex items-center justify-between gap-2">
                            <div className="flex items-center gap-2">
                              <Badge className="border-[#f1c6c0] bg-[#fff1ef] text-[9px] font-bold uppercase text-[#a83c30]">
                                {entry.severity}
                              </Badge>
                              <span className="font-mono text-[10px] text-[#839188]">
                                {formatLogTimestamp(entry.timestamp)}
                              </span>
                            </div>
                            <span className="font-mono text-[10px] text-[#63756a]">
                              {entry.resource_type ?? 'gcp_resource'}
                            </span>
                          </div>
                          <div className="mt-1.5 font-mono text-[11px] leading-relaxed text-[#304136]">
                            {entry.message}
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                ) : (
                  <div className="rounded-lg border border-dashed border-[#dce6df] bg-[#f9fbf9] p-6 text-center text-xs text-[#738279]">
                    Nenhum log com severidade ERROR ou superior registrado nesta janela ({period}).
                  </div>
                )}
              </TabsContent>
            )}
          </Tabs>

          {/* Action Callout */}
          {metric.action && (
            <div className="mt-4 rounded-lg border border-[#dce9df] bg-[#f3f8f4] p-3.5">
              <div className="flex items-center gap-2 text-xs font-bold text-[#286b4c]">
                <Lightbulb className="h-3.5 w-3.5" /> Ação sugerida
              </div>
              <div className="mt-1.5 pl-[22px] text-[12px] leading-relaxed text-[#52685b]">
                {metric.action} para restaurar uma margem saudável nos recursos afetados.
              </div>
            </div>
          )}

          {/* Footer actions */}
          <div className="mt-5 flex justify-end pb-5">
            <Button
              onClick={onClose}
              data-testid="button-close-detail"
              variant="outline"
              className="h-9 border-[#dce5df] text-xs text-[#45554b]"
            >
              <Check className="mr-2 h-3.5 w-3.5" /> Concluído
            </Button>
            <button
              onClick={onClose}
              data-testid="button-view-resource"
              className="ml-2 inline-flex h-9 items-center rounded-md px-3 text-xs font-semibold text-[#286b4c] hover:bg-[#edf5ef]"
            >
              Ver recurso <ArrowUpRight className="ml-1.5 h-3.5 w-3.5" />
            </button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
