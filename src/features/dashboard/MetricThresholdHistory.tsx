import { useEffect, useId, useState } from 'react';
import { History } from 'lucide-react';
import { getThresholdHistory, type ConfigurationAuditEntry } from '@/lib/api';

const pageSize = 50;

function describeRule(rule: ConfigurationAuditEntry['previous_value']) {
  return rule ? `Atenção ${rule.operator} ${rule.warning_threshold} · Crítico ${rule.operator} ${rule.critical_threshold}` : 'Sem regra anterior';
}

export function MetricThresholdHistory({metricName, revision}: {metricName: string; revision: number}) {
  const panelId = useId();
  const [open, setOpen] = useState(false);
  const [offset, setOffset] = useState(0);
  const [entries, setEntries] = useState<ConfigurationAuditEntry[]>([]);
  const [status, setStatus] = useState<'loading' | 'ready' | 'error'>('loading');

  useEffect(() => {
    if (!open) return;
    const controller = new AbortController();
    setStatus('loading');
    getThresholdHistory(metricName, offset, controller.signal).then(result => {
      if (controller.signal.aborted) return;
      setEntries(result);
      setStatus('ready');
    }).catch(() => {
      if (!controller.signal.aborted) setStatus('error');
    });
    return () => controller.abort();
  }, [metricName, offset, open, revision]);

  return <>
    <button type="button" aria-expanded={open} aria-controls={panelId} onClick={() => setOpen(value => !value)}
      className="inline-flex items-center gap-2 rounded-md border border-[#cbdcd1] bg-white px-3 py-1.5 text-sm font-medium text-[#286b4c]">
      <History size={15} aria-hidden="true" /> Histórico de alterações
    </button>
    <div id={panelId} hidden={!open}
      className="order-last w-full rounded-md border border-[#cfddd3] bg-white px-3 py-2 text-sm">
      {status === 'loading' && <p role="status">Carregando histórico…</p>}
      {status === 'error' && <p role="alert">Não foi possível carregar o histórico. Feche e abra para tentar novamente.</p>}
      {status === 'ready' && <>
        {!entries.length && <p>Nenhuma alteração registrada nesta página.</p>}
        <ul className="divide-y divide-[#e8eeea]">
          {entries.map(entry => <li key={entry.log_id} className="py-2">
            <p className="font-medium">{entry.user_id} · {entry.action_type === 'THRESHOLD_CREATE' ? 'Criou a regra' : 'Atualizou a regra'}</p>
            <time className="text-xs text-[#52665a]" dateTime={entry.timestamp}>{new Date(entry.timestamp).toLocaleString('pt-BR')}</time>
            <p>Antes · {describeRule(entry.previous_value)}</p>
            <p>Depois · {describeRule(entry.new_value)}</p>
          </li>)}
        </ul>
        <div className="flex gap-3">
          {offset > 0 && <button type="button" className="underline" onClick={() => setOffset(offset - pageSize)}>Anterior</button>}
          {entries.length === pageSize && <button type="button" className="underline" onClick={() => setOffset(offset + pageSize)}>Próxima</button>}
        </div>
      </>}
    </div>
  </>;
}
