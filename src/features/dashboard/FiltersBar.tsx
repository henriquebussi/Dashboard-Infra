import { Search, SlidersHorizontal } from 'lucide-react';
import { Input } from '@/components/ui/input';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import type { Environment, Period } from './mock-data';

type Props = {
  period: Period;
  setPeriod: (value: Period) => void;
  environment: Environment;
  setEnvironment: (value: Environment) => void;
  service: string;
  setService: (value: string) => void;
  search: string;
  setSearch: (value: string) => void;
};

export function FiltersBar({ period, setPeriod, environment, setEnvironment, service, setService, search, setSearch }: Props) {
  return (
    <div className="flex flex-col gap-3 border-y border-[#e5ebe7] bg-[#fbfcfb] px-4 py-3 md:flex-row md:items-center md:justify-between md:px-7">
      <div className="flex items-center gap-2 text-[11px] font-semibold uppercase tracking-[.13em] text-muted-foreground">
        <SlidersHorizontal className="h-3.5 w-3.5 text-primary" />
        <span>Escopo</span>
      </div>
      <div className="flex flex-col gap-2 sm:flex-row sm:flex-wrap sm:items-center">
        <div className="inline-flex h-9 items-center rounded-md border border-[#dce5df] bg-white p-1" data-testid="filter-period">
          {(['24h', '7d', '30d'] as Period[]).map((item) => (
            <button key={item} onClick={() => setPeriod(item)} data-testid={`button-period-${item}`} className={`h-7 rounded px-3 text-xs font-semibold transition-colors ${period === item ? 'bg-[#e8f2ec] text-[#1f694b]' : 'text-[#65726c] hover:bg-[#f2f6f3]'}`}>
              {item}
            </button>
          ))}
        </div>
        <Select value={environment} onValueChange={(value: Environment) => setEnvironment(value)}>
          <SelectTrigger data-testid="select-environment" className="h-9 w-full border-[#dce5df] bg-white text-xs sm:w-[145px]"><SelectValue /></SelectTrigger>
          <SelectContent>
            <SelectItem value="Produção">Produção</SelectItem>
            <SelectItem value="Homologação">Homologação</SelectItem>
            <SelectItem value="Desenvolvimento">Desenvolvimento</SelectItem>
          </SelectContent>
        </Select>
        <Select value={service} onValueChange={setService}>
          <SelectTrigger data-testid="select-service" className="h-9 w-full border-[#dce5df] bg-white text-xs sm:w-[152px]"><SelectValue /></SelectTrigger>
          <SelectContent>
            <SelectItem value="Todos os serviços">Todos os serviços</SelectItem>
            <SelectItem value="Cloud SQL">Cloud SQL</SelectItem>
            <SelectItem value="BigQuery">BigQuery</SelectItem>
            <SelectItem value="Cloud Storage">Cloud Storage</SelectItem>
            <SelectItem value="Compute Engine">Compute Engine</SelectItem>
            <SelectItem value="Vertex AI">Vertex AI</SelectItem>
            <SelectItem value="Pub/Sub">Pub/Sub</SelectItem>
            <SelectItem value="Memorystore">Memorystore</SelectItem>
          </SelectContent>
        </Select>
        <div className="relative w-full sm:w-[210px]">
          <Search className="pointer-events-none absolute left-3 top-2.5 h-4 w-4 text-[#8b9991]" />
          <Input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Buscar um recurso…" data-testid="input-resource-search" className="h-9 border-[#dce5df] bg-white pl-9 text-xs placeholder:text-[#9aa69f]" />
        </div>
      </div>
    </div>
  );
}
