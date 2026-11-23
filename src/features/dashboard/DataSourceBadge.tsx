import type { UseOverviewResult } from '@/lib/useMetrics';

export function DataSourceBadge({
  overviewResult,
  dataMode,
}: {
  overviewResult: UseOverviewResult;
  dataMode: 'real' | 'mock';
}) {
  if (dataMode === 'mock') {
    return (
      <div className="mt-1 flex items-center gap-1.5 text-[11px] font-medium text-[#596a60] md:justify-end">
        <span className="h-1.5 w-1.5 rounded-full bg-[#bd493c]" />
        Modo demonstração · <span className="text-[#9aa49e]">dados mock</span>
      </div>
    );
  }
  if (overviewResult.loading && !overviewResult.stale) {
    return (
      <div className="mt-1 flex items-center gap-1.5 text-[11px] font-medium text-[#596a60] md:justify-end">
        <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-[#c2832b]" />
        Conectando à API…
      </div>
    );
  }
  if (overviewResult.error) {
    return (
      <div className="mt-1 flex items-center gap-1.5 text-[11px] font-medium text-[#596a60] md:justify-end">
        <span className="h-1.5 w-1.5 rounded-full bg-[#bd493c]" />
        Backend indisponível · <span className="text-[#9aa49e]">Sem dados reais</span>
      </div>
    );
  }
  if (overviewResult.data) {
    const liveGcp = overviewResult.data.data_source === 'gcp';
    const liveCached = overviewResult.data.data_source === 'cache';
    return (
      <div className="mt-1 flex items-center gap-1.5 text-[11px] font-medium text-[#596a60] md:justify-end">
        <span
          className={`h-1.5 w-1.5 rounded-full ${overviewResult.stale ? 'animate-pulse' : ''} ${
            liveCached ? 'bg-[#c2832b]' : 'bg-[#4a9867]'
          }`}
        />
        {liveCached ? 'API + GCP em cache' : liveGcp ? 'API + GCP ao vivo' : overviewResult.data.data_source === 'unavailable' ? 'API conectada · sem amostras GCP nesta janela' : 'API conectada · dados do backend'}
        {overviewResult.stale && <span className="text-[#9aa49e]">(atualizando)</span>}
      </div>
    );
  }
  return (
    <div className="mt-1 flex items-center gap-1.5 text-[11px] font-medium text-[#596a60] md:justify-end">
      <span className="h-1.5 w-1.5 rounded-full bg-[#bd493c]" />
      Sem dados reais
    </div>
  );
}
