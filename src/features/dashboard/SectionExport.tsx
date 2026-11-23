import { Download } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { Dialog, DialogContent, DialogDescription, DialogTitle } from '@/components/ui/dialog';
import { ApexChart } from './ApexChart';
import { downloadSnapshot } from '@/lib/api';
import { generateHourlySeries, type Metric, type Period, type SectionData } from './mock-data';

type Props = {
  section: SectionData; metric?: Metric; scope: string; period: Period; demo: boolean; multiplier: number;
  labels: string[]; series: {name: string; source?: string; unit?: string; values: (number | null)[]}[];
};

type Snapshot = Parameters<typeof downloadSnapshot>[1];
type Preview = {
  format: string;
  filename: string;
  snapshot: Snapshot;
  file: Blob;
  csv: string;
};

export function SectionExport({ section, metric, scope, period, demo, multiplier, labels, series }: Props) {
  const disclosure = useRef<HTMLDetailsElement>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [preview, setPreview] = useState<Preview | null>(null);
  const [fileUrl, setFileUrl] = useState('');
  const [sheet, setSheet] = useState(0);

  useEffect(() => {
    if (!preview) {
      setFileUrl('');
      return;
    }
    const url = URL.createObjectURL(preview.file);
    setFileUrl(url);
    return () => URL.revokeObjectURL(url);
  }, [preview]);

  async function openPreview(format: string) {
    setBusy(true);
    setError('');
    try {
      const metrics = metric ? [metric] : section.metrics;
      const statistics: Snapshot['statistics'] = metrics.map(m => {
        const live = m.isLive;
        const chart = m.available === false || !m.series.length ? {labels: [], values: []}
          : live ? {labels: m.timestamps ?? [], values: m.series}
          : generateHourlySeries(period, m.series.map(v => v * multiplier));
        return { name: m.label, value: m.available === false ? 'Indisponível' : m.value,
          unit: m.unit ?? '', source: demo ? 'demo' : m.source ?? 'unavailable',
          points: chart.values.map((value, i) => ({value, label: chart.labels[i] ?? String(i + 1)})) };
      });
      if (!metric) {
        for (const line of series) {
          statistics.push({name: line.name, value: '', unit: line.unit ?? '', source: demo ? 'demo' : line.source ?? 'unavailable',
            points: line.values.flatMap((value, i) => value === null ? [] : [{value, label: labels[i] ?? String(i + 1)}])});
        }
      }
      const title = metric?.label ?? section.title;
      const snapshot = {title, scope, statistics};
      const file = await downloadSnapshot(format, snapshot);
      const csv = format === 'csv' ? await file.text() : '';
      setSheet(0);
      setPreview({format, filename: `${title}-${period}.${format}`, snapshot, file, csv});
    } catch {
      setError('Falha ao gerar a prévia. Tente novamente.');
    } finally {
      setBusy(false);
    }
  }
  const statistic = preview?.snapshot.statistics[sheet];
  return <div className="text-sm">
    <details ref={disclosure} className="w-fit">
      <summary className="flex cursor-pointer list-none items-center gap-2 rounded-md border border-[#cbdcd1] bg-white px-3 py-1.5 font-medium text-[#286b4c] hover:bg-[#eef6f0]">
        <Download size={15} aria-hidden="true" />
        {busy ? 'Gerando prévia…' : metric ? 'Exportar estatística' : 'Exportar área'}
      </summary>
      <div className="mt-1 flex gap-1">
        {['csv', 'pdf', 'xlsx'].map(format => (
          <button key={format} type="button" disabled={busy} onClick={() => openPreview(format)}
            className="rounded border bg-white px-2 py-1 text-xs font-medium hover:bg-[#eef6f0]">
            {format.toUpperCase()}
          </button>
        ))}
      </div>
    </details>
    <Dialog open={preview !== null} onOpenChange={open => { if (!open) setPreview(null); }}>
      {preview && <DialogContent className="gap-0 overflow-x-hidden border-[#dce6df] bg-[#f5f8f6] p-0 sm:max-w-3xl" onCloseAutoFocus={event => {
        event.preventDefault();
        disclosure.current?.querySelector('summary')?.focus();
      }}>
        <header className="border-b border-[#dce6df] bg-white px-6 py-4 pr-12">
          <span className="inline-flex rounded bg-[#eaf3ed] px-2 py-1 text-xs font-semibold text-[#286b4c]">
            Prévia {preview.format.toUpperCase()}
          </span>
          <DialogTitle className="mt-2 break-words font-display text-2xl text-[#203329]">
            {preview.snapshot.title}
          </DialogTitle>
          <DialogDescription className="mt-1 break-words text-[#52665a]">{preview.snapshot.scope}</DialogDescription>
        </header>
        <div className="min-w-0 space-y-3 p-4 sm:px-6">
        {preview.format === 'pdf' && fileUrl &&
          <iframe title="Prévia do PDF" src={fileUrl} className="h-[55dvh] w-full rounded-lg border border-[#cfddd3] bg-white" />}
        {preview.format === 'csv' &&
          <div className="overflow-hidden rounded-lg border border-[#cfddd3] bg-white">
            <div className="border-b border-[#cfddd3] bg-[#eaf3ed] px-4 py-2 text-sm font-semibold text-[#286b4c]">
              Conteúdo do arquivo
            </div>
            <pre className="max-h-[55dvh] overflow-auto p-4 font-mono text-xs leading-relaxed text-[#314c3b]"
              aria-label="Conteúdo do CSV" tabIndex={0}>{preview.csv}</pre>
          </div>}
        {preview.format === 'xlsx' && statistic && <>
          <label className="flex flex-wrap items-center gap-2 text-sm font-medium text-[#286b4c]">
            Aba
            <select value={sheet} onChange={event => setSheet(Number(event.target.value))}
              className="min-w-0 max-w-full rounded-md border border-[#cfddd3] bg-white px-2 py-1.5">
              {preview.snapshot.statistics.map((item, index) =>
                <option key={index} value={index}>{index + 1} · {item.name}</option>)}
            </select>
          </label>
          <p className="rounded-md bg-[#eaf3ed] px-3 py-2 text-sm font-medium text-[#314c3b]">{[statistic.value, statistic.unit, statistic.source].filter(Boolean).join(' · ')}</p>
          {statistic.points.length > 0 ? <>
            <div className="rounded-lg border border-[#dce6df] bg-white p-3">
              <ApexChart labels={statistic.points.map(point => point.label)}
              series={[{name: statistic.name, values: statistic.points.map(point => point.value), color: '#286b4c'}]} />
            </div>
            <div className="max-h-48 overflow-auto rounded-lg border border-[#dce6df] bg-white" tabIndex={0}>
              <table className="w-full text-left text-sm">
                <thead className="sticky top-0 bg-[#eaf3ed] text-[#286b4c]"><tr>
                  <th className="px-3 py-1">Amostra</th><th className="px-3 py-1">Valor</th>
                </tr></thead>
                <tbody>{statistic.points.map((point, index) => <tr key={index} className="border-t border-[#e8eeea] even:bg-[#f5f8f6]">
                  <td className="px-3 py-1">{point.label}</td><td className="px-3 py-1">{point.value}</td>
                </tr>)}</tbody>
              </table>
            </div>
          </> : <p>Sem amostras para esta estatística.</p>}
        </>}
        </div>
        <footer className="flex justify-end border-t border-[#dce6df] bg-white px-6 py-3">
        {fileUrl && <a href={fileUrl} download={preview.filename}
          className="inline-flex w-fit items-center gap-2 rounded-md bg-[#286b4c] px-3 py-2 font-medium text-white hover:bg-[#20573e]">
          <Download size={15} aria-hidden="true" /> Baixar {preview.format.toUpperCase()}
        </a>}
        </footer>
      </DialogContent>}
    </Dialog>
    {error && <span role="alert">{error}</span>}
  </div>;
}
