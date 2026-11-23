import { useEffect, useId, useState, type FormEvent } from 'react';
import { MetricThresholdHistory } from './MetricThresholdHistory';
import { Settings2 } from 'lucide-react';
import { getMetricThresholds, getSession, saveMetricThreshold } from '@/lib/api';

export function MetricThresholdEditor({metricName, unit, onSaved}: {
  metricName: string;
  unit?: string;
  onSaved: () => void;
}) {
  const panelId = useId();
  const [loading, setLoading] = useState(false);
  const [admin, setAdmin] = useState(false);
  const [open, setOpen] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [saving, setSaving] = useState(false);
  const [warning, setWarning] = useState('');
  const [critical, setCritical] = useState('');
  const [operator, setOperator] = useState('>');
  const [error, setError] = useState('');
  const [revision, setRevision] = useState(0);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    let active = true;
    getSession().then(session => {
      if (active) setAdmin(session.role === 'INFRA_ADMIN');
    }).catch(() => {});
    return () => { active = false; };
  }, []);

  async function openEditor() {
    setOpen(true);
    if (loaded || loading) return;
    setLoading(true);
    setError('');
    try {
      const config = (await getMetricThresholds()).find(item => item.metric_name === metricName);
      setWarning(config ? String(config.warning_threshold) : '');
      setCritical(config ? String(config.critical_threshold) : '');
      setOperator(config?.operator ?? '>');
      setLoaded(true);
    } catch {
      setError('Não foi possível carregar os limites.');
    } finally {
      setLoading(false);
    }
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const warn = Number(warning);
    const crit = Number(critical);
    setError('');
    setSaved(false);
    if (!warning || !critical || !Number.isFinite(warn) || !Number.isFinite(crit)) return;
    if ((operator.startsWith('>') && crit < warn) || (operator.startsWith('<') && crit > warn)) {
      setError('O limite crítico deve ser tão restritivo quanto o limite de atenção.');
      return;
    }
    setSaving(true);
    try {
      await saveMetricThreshold({metric_name: metricName, operator, warning_threshold: warn, critical_threshold: crit});
      setSaved(true);
      setRevision(value => value + 1);
      onSaved();
    } catch {
      setError('Não foi possível salvar os limites.');
    } finally {
      setSaving(false);
    }
  }

  if (!admin) return null;
  const field = 'w-full rounded-md border border-[#cfddd3] bg-white p-2';
  return <>
    <button type="button" aria-expanded={open} aria-controls={panelId}
      onClick={() => open ? setOpen(false) : void openEditor()}
      className="inline-flex items-center gap-2 rounded-md border text-sm border-[#cbdcd1] bg-white px-3 py-1.5 font-medium text-[#286b4c]">
      <Settings2 size={15} aria-hidden="true" /> Configurar limites
    </button>
    <MetricThresholdHistory metricName={metricName} revision={revision} />
    <div id={panelId} hidden={!open} className="order-last w-full space-y-2 rounded-lg border border-[#dce6df] bg-[#f5f8f6] p-3 text-sm">
      <h3 className="font-semibold text-[#286b4c]">Limites de alerta</h3>
      <p className="text-xs text-[#52665a]">A regra é aplicada à métrica em todos os ambientes com dados reais.{unit && ` Unidade de avaliação: ${unit}.`}</p>
      {loaded ? <form onSubmit={submit} className="space-y-2" onChange={() => setSaved(false)}>
        <fieldset disabled={saving} className="grid gap-2 sm:grid-cols-3">
          <label>Comparação
            <select className={field} value={operator} onChange={event => setOperator(event.target.value)}>
              {['>', '>=', '<', '<=', '==', '!='].map(op => <option key={op}>{op}</option>)}
            </select>
          </label>
          <label>Atenção
            <input className={field} type="number" step="any" required value={warning} onChange={event => setWarning(event.target.value)} />
          </label>
          <label>Crítico
            <input className={field} type="number" step="any" required value={critical} onChange={event => setCritical(event.target.value)} />
          </label>
        </fieldset>
        <button type="submit" disabled={saving} className="rounded-md bg-[#286b4c] px-3 py-1.5 font-medium text-white disabled:opacity-60">
          {saving ? 'Salvando…' : 'Salvar limites'}
        </button>
      </form> : error ? <button type="button" onClick={openEditor} className="underline">Tentar novamente</button> : <p role="status">Carregando limites…</p>}
      {error && <p role="alert" className="text-red-700">{error}</p>}
      {saved && <p role="status" className="text-[#286b4c]">Limites salvos.</p>}
    </div>
  </>;
}
