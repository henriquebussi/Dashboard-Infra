import { ArrowDownRight, ArrowRight, ArrowUpRight, HelpCircle, Minus } from 'lucide-react';
import { Card, CardContent } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';
import { ApexChart } from './ApexChart';
import { generateHourlySeries, type Metric, type Period } from './mock-data';
import { SourceBadge, type DataSource } from './SourceDot';

type Props = {
  metric: Metric;
  period: Period;
  multiplier: number;
  onSelect: (metric: Metric) => void;
  dataSource?: DataSource;
};

export function MetricCard({ metric, period, multiplier, onSelect, dataSource }: Props) {
  const isAvailable = metric.available !== false;
  const resolvedSource: DataSource = metric.source ?? dataSource ?? (metric.isLive ? 'gcp' : 'mock');

  const hasHistory = isAvailable && metric.series.length > 0;
  const chart = !hasHistory ? null : metric.isLive
    ? {
        values: metric.series,
        labels: metric.timestamps?.length === metric.series.length
          ? metric.timestamps.map(timestamp => {
              const date = new Date(timestamp);
              return Number.isNaN(date.getTime()) ? timestamp : date.toISOString().slice(11, 16);
            })
          : metric.series.map((_, index) => String(index + 1)),
      }
    : generateHourlySeries(period, metric.series.map(value => value * multiplier));

  const TrendIcon = metric.trend === 'up' ? ArrowUpRight : metric.trend === 'down' ? ArrowDownRight : Minus;
  const severityLabel = metric.severity === 'critical' ? 'crítico' : 'atenção';

  return (
    <Card className="group overflow-hidden rounded-lg border-[#e2e9e4] bg-white shadow-[0_1px_2px_rgba(24,48,35,.025)] transition-all hover:border-[#b8d2c2] hover:shadow-[0_8px_22px_rgba(34,78,53,.065)]">
      <CardContent className="p-0">
        <button
          onClick={() => onSelect(metric)}
          data-testid={`button-metric-${metric.id}`}
          className="w-full text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"
        >
          <div className="flex min-h-[142px] flex-col justify-between p-4 pb-2">
            <p className="mb-1 text-xs text-muted-foreground">Fonte · {dataSource === 'mock' || resolvedSource === 'demo' ? 'Demonstração' : 'GCP'}</p>
            <div className="flex items-start justify-between gap-2">
              <span className="text-[11px] font-semibold uppercase tracking-[.085em] text-[#748078]">
                {metric.label}
              </span>
              <div className="flex shrink-0 items-center gap-1.5">
                {metric.severity && isAvailable && (
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <Badge
                        data-testid={`badge-alert-${metric.id}`}
                        className={
                          metric.severity === 'critical'
                            ? 'h-5 gap-1 rounded-sm border border-[#f1c6c0] bg-[#fff1ef] px-1.5 text-[9px] font-bold uppercase tracking-wide text-[#a83c30] hover:bg-[#fff1ef]'
                            : 'h-5 gap-1 rounded-sm border border-[#efd8a8] bg-[#fff8e8] px-1.5 text-[9px] font-bold uppercase tracking-wide text-[#916315] hover:bg-[#fff8e8]'
                        }
                      >
                        <span
                          className={`h-1.5 w-1.5 rounded-full ${
                            metric.severity === 'critical' ? 'bg-[#bc493d]' : 'bg-[#bd8b2c]'
                          }`}
                        />
                        {severityLabel}
                      </Badge>
                    </TooltipTrigger>
                    <TooltipContent side="top" className="max-w-56 text-xs">
                      {metric.action ?? 'Revise a pressão do recurso e as mudanças recentes.'}
                    </TooltipContent>
                  </Tooltip>
                )}

                {!isAvailable && (
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <Badge
                        data-testid={`badge-unavailable-${metric.id}`}
                        className="h-5 gap-1 rounded-sm border border-[#e5e7eb] bg-[#f9fafb] px-1.5 text-[9px] font-bold uppercase tracking-wide text-[#6b7280] hover:bg-[#f9fafb]"
                      >
                        <HelpCircle className="h-2.5 w-2.5 text-[#9ca3af]" />
                        Indisponível
                      </Badge>
                    </TooltipTrigger>
                    <TooltipContent side="top" className="max-w-64 text-xs">
                      {metric.reason ?? 'Métrica não disponível na infraestrutura GCP ou permissão ausente.'}
                    </TooltipContent>
                  </Tooltip>
                )}

                <SourceBadge source={resolvedSource} />
              </div>
            </div>

            <div className="mt-4 flex items-end justify-between gap-2">
              <div>
                <div
                  className={`font-display text-[27px] font-bold leading-none tracking-[-.045em] ${
                    isAvailable ? 'text-[#1d3027]' : 'text-[#9ca3af]'
                  }`}
                  data-testid={`value-metric-${metric.id}`}
                >
                  {isAvailable ? metric.value : 'Indisponível'}
                </div>

                {isAvailable ? (
                  <div
                    className={`mt-2 inline-flex items-center gap-1 font-mono text-[10px] font-medium ${
                      metric.trend === 'down'
                        ? 'text-[#287553]'
                        : metric.severity
                        ? 'text-[#a56c14]'
                        : 'text-[#738078]'
                    }`}
                  >
                    <TrendIcon className="h-3 w-3" />
                    {metric.change}
                    <span className="font-sans font-normal text-[#9aa49e]">vs. período anterior</span>
                  </div>
                ) : (
                  <div className="mt-2 inline-flex items-center gap-1 font-mono text-[10px] text-[#9ca3af]">
                    <span>—</span>
                    <span className="font-sans font-normal text-[#9aa49e]">sem leitura anterior</span>
                  </div>
                )}
              </div>
              <ArrowRight className="mb-1 h-4 w-4 text-[#a2b1a8] opacity-0 transition-all group-hover:translate-x-0.5 group-hover:opacity-100" />
            </div>
          </div>
          {chart ? <ApexChart
            labels={chart.labels}
            series={[{ name: metric.label, values: chart.values }]}
            compact
          /> : <p className="px-4 pb-3 text-[10px] text-[#96a19b]">{isAvailable ? 'Sem histórico disponível.' : 'Histórico indisponível.'}</p>}
        </button>
        <div className="border-t border-[#f0f3f1] px-4 py-2 text-[10px] text-[#96a19b]">
          {metric.reason && (!isAvailable || resolvedSource === 'estimated') ? metric.reason : metric.description}
        </div>
      </CardContent>
    </Card>
  );
}
