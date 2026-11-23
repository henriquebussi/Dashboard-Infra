import { useEffect, useState, type FormEvent } from 'react';
import { CalendarDays, Download } from 'lucide-react';
import {
  createReportSchedule, deleteReportSchedule, downloadPerformanceReport,
  getSession, listReportSchedules, type ReportSchedule, type ReportScheduleInput,
} from '@/lib/api';

const defaults: ReportScheduleInput = {
  recipient: '', frequency: 'weekly', environment: 'PROD', period: '7d', format: 'pdf',
};
const frequencyLabels = {daily: 'Diário', weekly: 'Semanal', monthly: 'Mensal'};

export function PerformanceReports() {
  const [admin, setAdmin] = useState(false);
  const [open, setOpen] = useState(false);
  const [config, setConfig] = useState(defaults);
  const [schedules, setSchedules] = useState<ReportSchedule[]>([]);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let active = true;
    getSession().then(session => {
      if (active) setAdmin(session.role === 'INFRA_ADMIN');
    }).catch(() => {});
    return () => { active = false; };
  }, []);

  useEffect(() => {
    if (open) listReportSchedules().then(setSchedules).catch(() => setError('Falha ao carregar agendamentos.'));
  }, [open]);

  async function create(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError('');
    try {
      await createReportSchedule(config);
      setSchedules(await listReportSchedules());
    } catch {
      setError('Falha ao salvar agendamento.');
    } finally {
      setBusy(false);
    }
  }

  async function download() {
    setBusy(true);
    setError('');
    try {
      const blob = await downloadPerformanceReport(config.environment, config.period, config.format);
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = `desempenho-${config.environment.toLowerCase()}-${config.period}.${config.format}`;
      link.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch {
      setError('Falha ao gerar relatório.');
    } finally {
      setBusy(false);
    }
  }

  async function remove(id: string) {
    setBusy(true);
    setError('');
    try {
      await deleteReportSchedule(id);
      setSchedules(await listReportSchedules());
    } catch {
      setError('Falha ao excluir agendamento.');
    } finally {
      setBusy(false);
    }
  }

  if (!admin) return null;
  const field = 'w-full rounded-md border border-[#cfddd3] bg-white px-3 py-2 text-sm';
  return <section className="border-b border-[#e5ebe7] bg-[#fbfcfb] px-4 py-3 md:px-7">
    <button type="button" aria-expanded={open} onClick={() => setOpen(value => !value)}
      className="inline-flex items-center gap-2 rounded-md border border-[#cbdcd1] bg-white px-3 py-2 text-sm font-medium text-[#286b4c]">
      <CalendarDays size={16} aria-hidden="true" /> Relatórios de desempenho
    </button>
    {open && <div className="mt-3 rounded-lg border border-[#dce6df] bg-white p-4">
      <form onSubmit={create} className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
        <label className="text-sm">Destinatário
          <input className={field} type="email" required value={config.recipient}
            onChange={event => setConfig({...config, recipient: event.target.value})} />
        </label>
        <label className="text-sm">Frequência
          <select className={field} value={config.frequency}
            onChange={event => setConfig({...config, frequency: event.target.value as ReportScheduleInput['frequency']})}>
            {Object.entries(frequencyLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
          </select>
        </label>
        <label className="text-sm">Ambiente
          <select className={field} value={config.environment}
            onChange={event => setConfig({...config, environment: event.target.value as ReportScheduleInput['environment']})}>
            <option value="PROD">Produção</option><option value="STAGING">Homologação</option><option value="DEV">Desenvolvimento</option>
          </select>
        </label>
        <label className="text-sm">Período
          <select className={field} value={config.period}
            onChange={event => setConfig({...config, period: event.target.value as ReportScheduleInput['period']})}>
            <option value="24h">24 horas</option><option value="7d">7 dias</option><option value="30d">30 dias</option>
          </select>
        </label>
        <label className="text-sm">Formato
          <select className={field} value={config.format}
            onChange={event => setConfig({...config, format: event.target.value as ReportScheduleInput['format']})}>
            <option value="pdf">PDF</option><option value="xlsx">XLSX</option><option value="csv">CSV</option>
          </select>
        </label>
        <div className="flex flex-wrap gap-2 sm:col-span-2 lg:col-span-5">
          <button type="submit" disabled={busy} className="rounded-md bg-[#286b4c] px-3 py-2 text-sm font-medium text-white disabled:opacity-50">Agendar e-mail</button>
          <button type="button" disabled={busy} onClick={download}
            className="inline-flex items-center gap-2 rounded-md border border-[#cbdcd1] px-3 py-2 text-sm font-medium text-[#286b4c]">
            <Download size={15} aria-hidden="true" /> Gerar agora
          </button>
        </div>
      </form>
      {error && <p role="alert" className="mt-2 text-sm text-red-700">{error}</p>}
      <h3 className="mt-5 font-semibold text-[#263a2e]">Agendamentos</h3>
      {!schedules.length && <p className="text-sm text-[#65726c]">Nenhum agendamento cadastrado.</p>}
      <ul className="divide-y divide-[#e5ebe7]">
        {schedules.map(item => <li key={item.id} className="flex flex-wrap items-center justify-between gap-2 py-3 text-sm">
          <span>{item.recipient} · {frequencyLabels[item.frequency]} · {item.environment} · {item.period} · {item.format.toUpperCase()}
            <span className="block text-xs text-[#65726c]">Próximo envio {new Date(item.next_run).toLocaleString('pt-BR')} · Último {item.last_status ?? 'pendente'}</span>
          </span>
          <button type="button" disabled={busy} onClick={() => remove(item.id)} className="text-red-700 underline">Excluir</button>
        </li>)}
      </ul>
    </div>}
  </section>;
}
