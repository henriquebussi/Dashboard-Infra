import { ArrowDownRight, ArrowRight, ArrowUpRight, Minus } from 'lucide-react';
import { Card, CardContent } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';
import type { Metric } from './mock-data';
import { ApexChart } from './ApexChart';
import { generateHourlySeries, type Period } from './mock-data';
import { SourceDot, type DataSource } from './SourceDot';

type Props = {
  metric: Metric;
  period: Period;
  multiplier: number;
  onSelect: (metric: Metric) => void;
  dataSource?: DataSource;
};

export function MetricCard({ metric, period, multiplier, onSelect, dataSource }: Props) {
  // Backend readings are already scoped to the selected environment.
  const scale = metric.isLive ? 1 : multiplier;
  const chart = generateHourlySeries(period, metric.series.map((value) => value * scale));
  const TrendIcon = metric.trend === 'up' ? ArrowUpRight : metric.trend === 'down' ? ArrowDownRight : Minus;
  const severityLabel = metric.severity === 'critical' ? 'crítico' : 'atenção';
  return (
    <Card className="group overflow-hidden rounded-lg border-[#e2e9e4] bg-white shadow-[0_1px_2px_rgba(24,48,35,.025)] transition-all hover:border-[#b8d2c2] hover:shadow-[0_8px_22px_rgba(34,78,53,.065)]">
      <CardContent className="p-0">
        <button onClick={() => onSelect(metric)} data-testid={`button-metric-${metric.id}`} className="w-full text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary">
          <div className="flex min-h-[142px] flex-col justify-between p-4 pb-2">
            <div className="flex items-start justify-between gap-2">
              <span className="text-[11px] font-semibold uppercase tracking-[.085em] text-[#748078]">{metric.label}</span>
              <div className="flex shrink-0 items-center gap-1.5">
                {metric.severity && (
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <Badge data-testid={`badge-alert-${metric.id}`} className={metric.severity === 'critical' ? 'h-5 gap-1 rounded-sm border border-[#f1c6c0] bg-[#fff1ef] px-1.5 text-[9px] font-bold uppercase tracking-wide text-[#a83c30] hover:bg-[#fff1ef]' : 'h-5 gap-1 rounded-sm border border-[#efd8a8] bg-[#fff8e8] px-1.5 text-[9px] font-bold uppercase tracking-wide text-[#916315] hover:bg-[#fff8e8]'}>
                        <span className={`h-1.5 w-1.5 rounded-full ${metric.severity === 'critical' ? 'bg-[#bc493d]' : 'bg-[#bd8b2c]'}`} />{severityLabel}
                      </Badge>
                    </TooltipTrigger>
                    <TooltipContent side="top" className="max-w-56 text-xs">{metric.action ?? 'Revise a pressão do recurso e as mudanças recentes.'}</TooltipContent>
                  </Tooltip>
                )}
                <SourceDot source={dataSource ?? (metric.isLive ? 'api' : 'mock')} />
              </div>
            </div>
            <div className="mt-4 flex items-end justify-between gap-2">
              <div>
                <div className="font-display text-[27px] font-bold leading-none tracking-[-.045em] text-[#1d3027]" data-testid={`value-metric-${metric.id}`}>{metric.value}</div>
                <div className={`mt-2 inline-flex items-center gap-1 font-mono text-[10px] font-medium ${metric.trend === 'down' ? 'text-[#287553]' : metric.severity ? 'text-[#a56c14]' : 'text-[#738078]'}`}>
                  <TrendIcon className="h-3 w-3" />{metric.change}<span className="font-sans font-normal text-[#9aa49e]">vs. período anterior</span>
                </div>
              </div>
              <ArrowRight className="mb-1 h-4 w-4 text-[#a2b1a8] opacity-0 transition-all group-hover:translate-x-0.5 group-hover:opacity-100" />
            </div>
          </div>
          <ApexChart labels={chart.labels} series={[{ name: metric.label, values: chart.values.map((value) => value * scale) }]} compact />
        </button>
        <div className="border-t border-[#f0f3f1] px-4 py-2 text-[10px] text-[#96a19b]">{metric.description}</div>
      </CardContent>
    </Card>
  );
}
