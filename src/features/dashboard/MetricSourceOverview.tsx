import { metricSources } from '@/lib/metricSources';

/** Inventory of implemented sources; this is not a live availability check. */
export function MetricSourceOverview() {
  return <details className="mx-4 my-3 rounded border p-3 text-sm md:mx-7">
    <summary className="cursor-pointer font-medium">Métricas por fonte</summary>
    <p className="my-2 text-xs text-muted-foreground">Inventário da integração: não confirma amostras ou permissões. Demo, cache e estimativa indicam proveniência, não uma nova fonte.</p>
    <div className="grid gap-3 md:grid-cols-2">
      {metricSources.map(source => <section key={source.id} aria-label={source.name} className="rounded border p-3">
        <h3 className="font-semibold">{source.name}</h3>
        <p className="text-xs font-medium">{source.status}</p>
        <p className="mt-1 text-xs text-muted-foreground">{source.description}</p>
        {source.metrics.length > 0 && <details className="mt-2">
          <summary className="cursor-pointer text-xs">{source.metrics.length} indicadores mapeados (não implica disponibilidade)</summary>
          <ul className="mt-1 max-h-48 overflow-auto text-xs">{source.metrics.map(metric => <li key={metric} className="break-all font-mono">{metric}</li>)}</ul>
        </details>}
      </section>)}
    </div>
  </details>;
}
