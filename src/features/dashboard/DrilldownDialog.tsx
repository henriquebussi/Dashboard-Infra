import { ArrowUpRight, Check, CircleAlert, Database, Lightbulb } from 'lucide-react';
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import type { Metric } from './mock-data';

type Props = { metric: Metric | null; onClose: () => void };

export function DrilldownDialog({ metric, onClose }: Props) {
  if (!metric) return null;
  const severityLabel = metric.severity === 'critical' ? 'crítico' : 'atenção';
  return (
    <Dialog open={Boolean(metric)} onOpenChange={(open) => !open && onClose()}>
      <DialogContent data-testid="dialog-metric-detail" className="max-h-[90dvh] overflow-y-auto rounded-xl border-[#dce6df] p-0 sm:max-w-[560px]">
        <div className="border-b border-[#e8eeea] bg-[#fbfdfb] px-6 pb-5 pt-6">
          <DialogHeader>
            <div className="mb-3 flex items-center gap-2">
              <span className="flex h-8 w-8 items-center justify-center rounded-md bg-[#eaf3ed] text-[#286b4c]"><Database className="h-4 w-4" /></span>
              <span className="text-[10px] font-bold uppercase tracking-[.16em] text-[#718078]">Detalhamento por recurso</span>
              {metric.severity && <Badge className={metric.severity === 'critical' ? 'ml-auto rounded-sm border border-[#f1c6c0] bg-[#fff1ef] text-[#a83c30]' : 'ml-auto rounded-sm border border-[#efd8a8] bg-[#fff8e8] text-[#916315]'}>{severityLabel}</Badge>}
            </div>
            <DialogTitle className="font-display text-[23px] font-bold tracking-[-.035em] text-[#203329]">{metric.label}</DialogTitle>
            <DialogDescription className="text-sm leading-relaxed text-[#6f7d75]">{metric.description}</DialogDescription>
          </DialogHeader>
          <div className="mt-5 flex items-end gap-3">
            <span className="font-display text-[38px] font-bold leading-none tracking-[-.05em] text-[#1c3328]">{metric.value}</span>
            <span className="mb-1 font-mono text-xs text-[#78857d]">{metric.change} vs. período anterior</span>
          </div>
        </div>
        <div className="px-6 py-5">
          <div className="mb-3 flex items-center justify-between">
            <h3 className="text-[11px] font-bold uppercase tracking-[.12em] text-[#707d75]">Recursos</h3>
            <span className="font-mono text-[10px] text-[#95a099]">{metric.resources.length} monitorados</span>
          </div>
          <div className="divide-y divide-[#edf1ee] rounded-lg border border-[#e6ece8]">
            {metric.resources.map((resource, index) => (
              <div key={resource.name} data-testid={`row-resource-${metric.id}-${index}`} className="flex items-center justify-between gap-3 px-3.5 py-3">
                <div className="min-w-0">
                  <div className="flex items-center gap-2 text-[13px] font-semibold text-[#293a31]">
                    <span className={`h-1.5 w-1.5 shrink-0 rounded-full ${resource.severity === 'critical' ? 'bg-[#bd493c]' : resource.severity === 'warning' ? 'bg-[#bd8b2c]' : 'bg-[#5d9b78]'}`} />
                    <span className="truncate">{resource.name}</span>
                  </div>
                  <div className="ml-3.5 mt-1 text-[10px] text-[#8a968f]">{resource.detail}</div>
                </div>
                <div className="flex shrink-0 items-center gap-2">
                  {resource.severity && <CircleAlert className="h-3.5 w-3.5 text-[#b68124]" />}
                  <span className="font-mono text-xs font-medium text-[#34493c]">{resource.value}</span>
                </div>
              </div>
            ))}
          </div>
          {metric.action && (
            <div className="mt-4 rounded-lg border border-[#dce9df] bg-[#f3f8f4] p-3.5">
              <div className="flex items-center gap-2 text-xs font-bold text-[#286b4c]"><Lightbulb className="h-3.5 w-3.5" /> Ação sugerida</div>
              <div className="mt-1.5 pl-[22px] text-[12px] leading-relaxed text-[#52685b]">{metric.action} para restaurar uma margem saudável nos recursos afetados.</div>
            </div>
          )}
          <div className="mt-5 flex justify-end">
            <Button onClick={onClose} data-testid="button-close-detail" variant="outline" className="h-9 border-[#dce5df] text-xs text-[#45554b]"><Check className="mr-2 h-3.5 w-3.5" /> Concluído</Button>
            <button onClick={onClose} data-testid="button-view-resource" className="ml-2 inline-flex h-9 items-center rounded-md px-3 text-xs font-semibold text-[#286b4c] hover:bg-[#edf5ef]">Ver recurso <ArrowUpRight className="ml-1.5 h-3.5 w-3.5" /></button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
