import { useEffect, useState } from 'react';
import { ApiError, getMetricCatalog, getCatalogSeries, type CatalogPage, type Environment, type Period } from '@/lib/api';
import { ApexChart } from './ApexChart';

type Props = { env: Environment; period: Period };
type Catalog = Awaited<ReturnType<typeof getMetricCatalog>>;

function message(error: unknown) {
  if (error instanceof ApiError && error.status === 403) return 'Sem permissão para consultar esta métrica.';
  return error instanceof Error ? error.message : 'Falha ao consultar o Cloud Monitoring.';
}

export function ProjectTelemetry({env, period}: Props) {
  const [catalog, setCatalog] = useState<Catalog>();
  const [selected, setSelected] = useState('');
  const [error, setError] = useState('');
  useEffect(() => {
    const controller = new AbortController();
    getMetricCatalog(env, true, controller.signal).then(result => {
      if (controller.signal.aborted) return;
      const saved = localStorage.getItem('gcp.pin.' + result.project + '.' + env);
      const preferred = result.metrics.find(m => m.type === 'serviceruntime.googleapis.com/api/request_count')
        ?? result.metrics[0];
      setCatalog(result);
      setSelected(saved || preferred?.type || '');
    }).catch(e => { if (!controller.signal.aborted) setError(message(e)); });
    return () => controller.abort();
  }, [env]);
  useEffect(() => {
    function pin(event: Event) {
      const detail = (event as CustomEvent).detail;
      if (!catalog || detail.project !== catalog.project || detail.env !== env) return;
      localStorage.setItem('gcp.pin.' + catalog.project + '.' + env, detail.metric);
      setSelected(detail.metric);
    }
    window.addEventListener('gcp-pin', pin);
    return () => window.removeEventListener('gcp-pin', pin);
  }, [catalog, env]);
  return <section className="mx-4 my-4 rounded-lg border p-4 md:mx-7">
    <p className="text-xs text-muted-foreground">Fonte · GCP Cloud Monitoring</p>
    <h2 className="font-semibold">Telemetria do projeto {catalog?.project}</h2>
    {error && <p role="alert">{error}</p>}
    {!catalog && !error && <p>Consultando projeto…</p>}
    {catalog && (catalog.metrics.length ? <label>Métrica em destaque
      <select className="my-2 block w-full rounded border p-2" value={selected} onChange={e => {
        setSelected(e.target.value);
        localStorage.setItem('gcp.pin.' + catalog.project + '.' + env, e.target.value);
      }}>{selected && !catalog.metrics.some(m => m.type === selected) && <option>{selected}</option>}{catalog.metrics.map(m => <option key={m.type} value={m.type}>{m.name || m.type}</option>)}</select>
    </label> : <p>Nenhum descritor ativo nesta página do catálogo.</p>)}
    {selected && <Reading key={JSON.stringify([env, selected, period])} env={env} period={period} metric={selected} />}
  </section>;
}

function Reading({env, period, metric}: Props & {metric: string}) {
  const [page, setPage] = useState<CatalogPage>();
  const [error, setError] = useState('');
  useEffect(() => {
    const controller = new AbortController();
    const read = async () => {
      try {
        const result = await getCatalogSeries(env, period, metric, null, controller.signal);
        if (!controller.signal.aborted) { setPage(result); setError(''); }
      } catch (e) { if (!controller.signal.aborted) setError(message(e)); }
    };
    void read();
    const timer = setInterval(read, 60000);
    return () => { clearInterval(timer); controller.abort(); };
  }, [env, period, metric]);
  if (error) return <p role="alert">{error}</p>;
  if (!page) return <p>Carregando amostras…</p>;
  const series = page.series.find(s => s.points.length);
  const points = [...(series?.points ?? [])].sort((a,b) => a.interval.end_time.localeCompare(b.interval.end_time));
  const last = points.at(-1);
  const values = points.map(p => Number(p.value.double_value ?? p.value.int64_value));
  return <div className="text-sm">
    <p>{metric} · {env} · {period}</p>
    {page.warnings.map((w,i) => <p key={i} role="alert">{w}</p>)}
    {last ? <><p>Última amostra da série exibida · {last.interval.end_time} · {JSON.stringify(Object.values(last.value)[0])} {series?.unit}</p>
      <p className="break-all">{JSON.stringify({...series?.resource.labels, ...series?.metric.labels})}</p>
      {values.every(Number.isFinite) && <ApexChart labels={points.map(p => p.interval.end_time)} series={[{name: metric, values}]} />}
    </> : <p>Sem amostras nesta página para o período selecionado.</p>}
  </div>;
}
