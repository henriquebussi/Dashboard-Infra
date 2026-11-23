import type { UseOverviewResult } from '@/lib/useMetrics';
import { SourceBadge } from './SourceDot';
import type { Environment, Metric, Period } from './mock-data';

type Props = {
  environment: Environment;
  period: Period;
  readings: Metric[];
  metricCount: number;
  overviewResult: UseOverviewResult;
};

export function ReadingsTable({ environment, period, readings, metricCount, overviewResult }: Props) {
  return (
    <section className="overflow-x-auto px-4 py-4 md:px-7">
      <h2 className="font-semibold">Leituras no período · {environment} · {period}</h2>
      <p role="status" className="mb-3 text-sm text-[#52665a]">
        {overviewResult.loading && !overviewResult.stale ? 'Carregando leituras…'
          : overviewResult.error ? 'Falha ao carregar as leituras.'
          : !metricCount ? 'Nenhum indicador corresponde aos filtros.'
          : !readings.length ? 'Sem amostras no período.'
          : `${readings.length} de ${metricCount} indicadores medidos`}
      </p>
      {readings.length > 0 && (
        <div tabIndex={0} role="region" aria-label="Tabela de leituras" className="overflow-x-auto rounded-lg border border-[#e5ebe7] focus-visible:outline-2 focus-visible:outline-primary">
          <table className="w-full text-left text-sm">
            <thead className="bg-[#f2f6f3] text-[#41564a]">
              <tr>
                {['Indicador', 'Valor', 'Unidade', 'Última amostra (UTC)', 'Fonte'].map(label => (
                  <th key={label} scope="col" className="px-3 py-2">{label}</th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-[#e5ebe7]">
              {readings.map(metric => {
                const times = (metric.timestamps ?? []).map(Date.parse).filter(Number.isFinite);
                const latest = times.length ? new Date(Math.max(...times)) : null;
                return (
                  <tr key={metric.id}>
                    <th scope="row" className="px-3 py-2 font-medium">{metric.label}</th>
                    <td className="whitespace-nowrap px-3 py-2 font-mono tabular-nums">{metric.value}</td>
                    <td className="px-3 py-2">{metric.unit || '—'}</td>
                    <td className="whitespace-nowrap px-3 py-2">
                      {latest ? <time dateTime={latest.toISOString()}>{latest.toLocaleString('pt-BR', { timeZone: 'UTC' })}</time> : 'Sem horário informado'}
                    </td>
                    <td className="px-3 py-2"><SourceBadge source={metric.source ?? 'api'} /></td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
