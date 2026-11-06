import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';

/**
 * Where the value rendered by a statistic comes from.
 *
 * - `live`    fresh GCP Monitoring call (green)
 * - `api`     backend overview API (green — real backend data)
 * - `cache`   Redis cache hit (amber)
 * - `mock`    local demo dataset (red)
 * - `offline` no usable data (red)
 */
export type DataSource = 'live' | 'api' | 'cache' | 'mock' | 'offline';

const SOURCE_META: Record<
  DataSource,
  { dot: string; label: string; detail: string }
> = {
  live: {
    dot: 'bg-[#4a9867] shadow-[0_0_0_3px_rgba(74,152,103,.14)]',
    label: 'GCP ao vivo',
    detail: 'A seção ativa está sendo consultada agora no GCP Cloud Monitoring.',
  },
  api: {
    dot: 'bg-[#4a9867] shadow-[0_0_0_3px_rgba(74,152,103,.14)]',
    label: 'API do backend',
    detail: 'Valores atuais do endpoint /metrics/overview.',
  },
  cache: {
    dot: 'bg-[#c2832b] shadow-[0_0_0_3px_rgba(194,131,43,.16)]',
    label: 'Cache Redis',
    detail: 'A seção ativa foi servida pelo cache Redis; pode ter alguns minutos.',
  },
  mock: {
    dot: 'bg-[#bd493c] shadow-[0_0_0_3px_rgba(189,73,60,.14)]',
    label: 'Dados de demonstração',
    detail: 'Mock local — não representa a infraestrutura real.',
  },
  offline: {
    dot: 'bg-[#bd493c] shadow-[0_0_0_3px_rgba(189,73,60,.14)]',
    label: 'Sem dados',
    detail: 'Nenhuma fonte real disponível para esta estatística.',
  },
};

type Props = {
  source: DataSource;
  className?: string;
};

/** Small coloured dot + tooltip describing the origin of a statistic. */
export function SourceDot({ source, className }: Props) {
  const meta = SOURCE_META[source];
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span
          role="img"
          tabIndex={0}
          aria-label={`${meta.label}: ${meta.detail}`}
          data-testid={`source-dot-${source}`}
          data-source={source}
          className={`inline-flex h-2 w-2 shrink-0 cursor-help rounded-full outline-none focus-visible:ring-2 focus-visible:ring-[#286b4c]/40 ${meta.dot} ${className ?? ''}`}
        />
      </TooltipTrigger>
      <TooltipContent side="top" className="max-w-56 text-xs">
        <span className="block font-semibold">{meta.label}</span>
        <span className="mt-0.5 block text-[11px] opacity-80">{meta.detail}</span>
      </TooltipContent>
    </Tooltip>
  );
}
