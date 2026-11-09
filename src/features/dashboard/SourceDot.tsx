import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';

/**
 * Where the value rendered by a statistic comes from.
 *
 * - `gcp` / `live`      fresh GCP Monitoring call (green)
 * - `cache`             Redis cache hit (amber)
 * - `estimated`         Estimated calculation or bounded log stream (indigo)
 * - `unavailable`       Data missing, degraded, or unauthorized (gray)
 * - `demo` / `mock`     Local mock / demo dataset (red)
 */
export type DataSource =
  | 'gcp'
  | 'live'
  | 'api'
  | 'cache'
  | 'estimated'
  | 'unavailable'
  | 'offline'
  | 'demo'
  | 'mock';

interface SourceMetadata {
  dot: string;
  dotBg: string;
  badgeBg: string;
  badgeText: string;
  badgeLabel: string;
  label: string;
  detail: string;
}

const SOURCE_META: Record<DataSource, SourceMetadata> = {
  gcp: {
    dot: 'bg-[#4a9867] shadow-[0_0_0_3px_rgba(74,152,103,.14)]',
    dotBg: 'bg-[#4a9867]',
    badgeBg: 'bg-[#eaf4ee]',
    badgeText: 'text-[#286b4c]',
    badgeLabel: 'GCP Live',
    label: 'GCP Live',
    detail: 'Telemetria obtida em tempo real via GCP Cloud Monitoring.',
  },
  live: {
    dot: 'bg-[#4a9867] shadow-[0_0_0_3px_rgba(74,152,103,.14)]',
    dotBg: 'bg-[#4a9867]',
    badgeBg: 'bg-[#eaf4ee]',
    badgeText: 'text-[#286b4c]',
    badgeLabel: 'GCP Live',
    label: 'GCP Live',
    detail: 'Telemetria obtida em tempo real via GCP Cloud Monitoring.',
  },
  api: {
    dot: 'bg-[#4a9867] shadow-[0_0_0_3px_rgba(74,152,103,.14)]',
    dotBg: 'bg-[#4a9867]',
    badgeBg: 'bg-[#eaf4ee]',
    badgeText: 'text-[#286b4c]',
    badgeLabel: 'GCP Live',
    label: 'GCP Live',
    detail: 'Valores reais do backend GCP.',
  },
  cache: {
    dot: 'bg-[#c2832b] shadow-[0_0_0_3px_rgba(194,131,43,.16)]',
    dotBg: 'bg-[#c2832b]',
    badgeBg: 'bg-[#fef7ea]',
    badgeText: 'text-[#9a651a]',
    badgeLabel: 'Cache Redis',
    label: 'Cache Redis',
    detail: 'Servido pelo cache Redis acelerado (<2s SLA).',
  },
  estimated: {
    dot: 'bg-[#6366f1] shadow-[0_0_0_3px_rgba(99,102,241,.16)]',
    dotBg: 'bg-[#6366f1]',
    badgeBg: 'bg-[#eef2ff]',
    badgeText: 'text-[#4338ca]',
    badgeLabel: 'Estimated',
    label: 'Estimated',
    detail: 'Métrica estimada por amostragem limitada ou cálculo local.',
  },
  unavailable: {
    dot: 'bg-[#9ca3af] shadow-[0_0_0_3px_rgba(156,163,175,.14)]',
    dotBg: 'bg-[#9ca3af]',
    badgeBg: 'bg-[#f3f4f6]',
    badgeText: 'text-[#4b5563]',
    badgeLabel: 'Unavailable',
    label: 'Unavailable',
    detail: 'Métrica indisponível na infraestrutura GCP ou permissão ausente.',
  },
  offline: {
    dot: 'bg-[#9ca3af] shadow-[0_0_0_3px_rgba(156,163,175,.14)]',
    dotBg: 'bg-[#9ca3af]',
    badgeBg: 'bg-[#f3f4f6]',
    badgeText: 'text-[#4b5563]',
    badgeLabel: 'Unavailable',
    label: 'Unavailable',
    detail: 'Nenhuma fonte real disponível para esta estatística.',
  },
  demo: {
    dot: 'bg-[#bd493c] shadow-[0_0_0_3px_rgba(189,73,60,.14)]',
    dotBg: 'bg-[#bd493c]',
    badgeBg: 'bg-[#fef2f2]',
    badgeText: 'text-[#b91c1c]',
    badgeLabel: 'Demo',
    label: 'Demo',
    detail: 'Dados sintéticos de demonstração.',
  },
  mock: {
    dot: 'bg-[#bd493c] shadow-[0_0_0_3px_rgba(189,73,60,.14)]',
    dotBg: 'bg-[#bd493c]',
    badgeBg: 'bg-[#fef2f2]',
    badgeText: 'text-[#b91c1c]',
    badgeLabel: 'Demo',
    label: 'Demo',
    detail: 'Dados sintéticos de demonstração.',
  },
};

type Props = {
  source: DataSource;
  className?: string;
};

/** Small coloured dot + tooltip describing the origin of a statistic. */
export function SourceDot({ source, className }: Props) {
  const meta = SOURCE_META[source] ?? SOURCE_META.offline;
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

/** Explicit badge displaying provenance: GCP Live, Cache Redis, Estimated, Unavailable, Demo. */
export function SourceBadge({ source, className }: Props) {
  const meta = SOURCE_META[source] ?? SOURCE_META.offline;
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span
          data-testid={`source-badge-${source}`}
          className={`inline-flex cursor-help items-center gap-1 rounded px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wider ${meta.badgeBg} ${meta.badgeText} ${className ?? ''}`}
        >
          <span className={`h-1.5 w-1.5 rounded-full ${meta.dotBg}`} />
          {meta.badgeLabel}
        </span>
      </TooltipTrigger>
      <TooltipContent side="top" className="max-w-56 text-xs">
        <span className="block font-semibold">{meta.label}</span>
        <span className="mt-0.5 block text-[11px] opacity-80">{meta.detail}</span>
      </TooltipContent>
    </Tooltip>
  );
}
