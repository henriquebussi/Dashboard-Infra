import { useEffect, useState } from 'react';
import { ApiError, getCatalogSeries, getMetricCatalog, type CatalogPage, type Environment, type Period } from '@/lib/api';

function readError(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 403) return 'Acesso negado à leitura solicitada no Cloud Monitoring.';
    if (error.status === 503) return 'Falha de conexão ou indisponibilidade do Cloud Monitoring. Tente novamente.';
    if (error.status === 429) return 'Cota de leitura esgotada. Aguarde antes de tentar novamente.';
    return error.detail;
  }
  return 'Falha de conexão ao consultar o Cloud Monitoring. Tente novamente.';
}

export function Series({ env, period, type, unit }: { env: Environment; period: Period; type: string; unit?: string }) {
  const [cursor, setCursor] = useState<{ end: string; token: string } | null>(null);
  const [page, setPage] = useState<CatalogPage>();
  const [error, setError] = useState('');
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    setPage(undefined); setError('');
    getCatalogSeries(env, period, type, cursor, controller.signal)
      .then(data => { if (!controller.signal.aborted) setPage(data); })
      .catch(e => { if (!controller.signal.aborted) setError(readError(e)); });
    return () => controller.abort();
  }, [env, period, type, cursor, attempt]);
  if (error) return <div><p role="alert">{error}</p><button onClick={() => setAttempt(a => a + 1)}>Tentar novamente</button></div>;
  if (!page) return <p role="status">Consultando séries…</p>;
  const hasPoints = page.series.some(series => series.points.length > 0);
  return <div className="space-y-2">
    <p className="break-all font-medium">{type} · Unidade: {unit || 'informada por série, quando disponível'}</p>
    <p>{env} · {page.project} · {page.start} a {page.end} (UTC)</p>
    {page.warning && <p role="status">{page.warning}</p>}
    {page.warnings.map((warning, index) => <p key={index} role="alert">{warning}</p>)}
    {!hasPoints && <p>{page.warnings.length ? 'Leitura parcial: não foi possível confirmar amostras nesta página.' : page.next_page_token ? 'Sem amostras nesta página; há mais páginas disponíveis.' : 'Sem amostras nesta janela e ambiente.'}</p>}
    <div className="max-h-80 overflow-auto">
      {page.series.map((series, index) => <details key={index} className="border-b p-2">
        <summary className="cursor-pointer break-all">{series.resource.type} · {JSON.stringify({
          resource: series.resource.labels, metric: series.metric.labels,
        })} · {series.points.length} amostras · Unidade: {series.unit || unit || 'não informada'}</summary>
        <table className="w-full text-left"><thead><tr><th>Instante (UTC)</th><th>Valor</th></tr></thead>
          <tbody>{series.points.map((point, i) => <tr key={i}>
            <td>{point.interval.end_time}</td><td className="break-all">{JSON.stringify(Object.values(point.value)[0]) ?? 'Valor não informado'}</td>
          </tr>)}</tbody></table>
      </details>)}
    </div>
    {page.next_page_token && <button className="underline" onClick={() => {
      setPage(undefined);
      setCursor({ end: page.end, token: page.next_page_token });
    }}>Próxima página de amostras</button>}
  </div>;
}

export function Catalog({ env, period }: { env: Environment; period: Period }) {
  const [activeOnly, setActiveOnly] = useState(true);
  const [catalog, setCatalog] = useState<Awaited<ReturnType<typeof getMetricCatalog>>>();
  const [pageToken, setPageToken] = useState('');
  const [error, setError] = useState('');
  const [attempt, setAttempt] = useState(0);
  const [input, setInput] = useState('');
  const [selection, setSelection] = useState<{ type: string; unit?: string }>();
  useEffect(() => {
    const controller = new AbortController();
    setCatalog(undefined); setError('');
    getMetricCatalog(env, activeOnly, controller.signal, pageToken)
      .then(data => { if (!controller.signal.aborted) setCatalog(data); })
      .catch(e => { if (!controller.signal.aborted) setError(readError(e)); });
    return () => controller.abort();
  }, [env, activeOnly, pageToken, attempt]);
  return <div className="mt-3 space-y-3">
    <label><input type="checkbox" checked={activeOnly} onChange={e => {
      setActiveOnly(e.target.checked); setPageToken(''); setCatalog(undefined); setError('');
    }} /> Apenas métricas com atividade recente no projeto (cerca de 25 horas)</label>
    {error ? <div><p role="alert">{error}</p><button onClick={() => setAttempt(a => a + 1)}>Tentar novamente</button></div> :
      <p aria-live="polite">{catalog ? `${catalog.metrics.length} tipos nesta página · ${env} · ${catalog.project}` : 'Carregando catálogo…'}</p>}
    {catalog?.warning && <p role="status">{catalog.warning}</p>}
    {catalog && !catalog.metrics.length && <p>Nenhum descritor nesta página. Isso não confirma ausência de recursos.</p>}
    {catalog?.next_page_token && <button className="underline" onClick={() => {
      setPageToken(catalog.next_page_token); setCatalog(undefined);
    }}>Próxima página de métricas</button>}
    {pageToken && <button className="underline" onClick={() => setPageToken('')}>Voltar ao início do catálogo</button>}
    <form className="flex flex-wrap gap-2" onSubmit={e => {
      e.preventDefault();
      const type = input.trim();
      if (type) setSelection({ type, unit: catalog?.metrics.find(m => m.type === type)?.unit });
    }}>
      <input className="min-w-0 flex-1 rounded border px-2" aria-label="Tipo de métrica GCP" required
        list="gcp-metric-types" placeholder="Selecionar ou digitar o tipo de métrica"
        value={input} onChange={e => setInput(e.target.value)} />
      <datalist id="gcp-metric-types">{catalog?.metrics.map(m =>
        <option key={m.type} value={m.type}>{m.name} {m.unit}</option>)}</datalist>
      <button className="rounded border px-3 py-1" type="submit">Consultar séries</button>
    </form>
    {selection && catalog && <button className="underline" onClick={() => {
      window.dispatchEvent(new CustomEvent('gcp-pin', {detail: {project: catalog.project, env, metric: selection.type}}));
    }}>Fixar no painel</button>}
    {selection && <Series key={JSON.stringify([env, selection.type, period])} env={env} period={period} {...selection} />}
  </div>;
}

export function MetricExplorer(props: { env: Environment; period: Period }) {
  const [open, setOpen] = useState(false);
  return <details className="mx-4 my-3 rounded border p-3 text-sm md:mx-7"
    onToggle={e => setOpen(e.currentTarget.open)}>
    <summary className="cursor-pointer font-medium">Explorar métricas do Cloud Monitoring</summary>
    {open && <Catalog key={props.env} {...props} />}
  </details>;
}
