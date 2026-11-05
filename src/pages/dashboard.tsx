import { useMemo, useState } from 'react';
import { useLocation } from 'wouter';
import { Activity, ArrowRight, ArrowUpRight, Bell, BrainCircuit, CheckCircle2, Cloud, Cpu, Database, HardDrive, LogOut, Search, ShieldCheck, Sparkles, Workflow } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { TooltipProvider } from '@/components/ui/tooltip';
import { useAuth } from '@/lib/auth';
import { ApexChart } from '@/features/dashboard/ApexChart';
import { DrilldownDialog } from '@/features/dashboard/DrilldownDialog';
import { FiltersBar } from '@/features/dashboard/FiltersBar';
import { MetricCard } from '@/features/dashboard/MetricCard';
import { generateHourlySeries, resources, sections, type Environment, type Metric, type Period, type SectionData } from '@/features/dashboard/mock-data';

const logoUrl = `${import.meta.env.BASE_URL}CCDSB100.jpg`;
const ALL_SERVICES = 'Todos os serviços';

const sectionIcons: Record<string, typeof Database> = {
  database: Database, cloud: Cloud, storage: HardDrive, processing: Workflow, tokens: BrainCircuit, sla: ShieldCheck,
};
const serviceSection: Record<string, string> = {
  'Cloud SQL': 'database', BigQuery: 'processing', 'Cloud Storage': 'storage', 'Compute Engine': 'cloud', 'Vertex AI': 'tokens', 'Pub/Sub': 'processing', Memorystore: 'database',
};
function getScopedResources(environment: Environment, service: string, search: string) {
  const term = search.trim().toLowerCase();
  return resources.filter((resource) => (
    resource.env === environment &&
    (service === ALL_SERVICES || resource.service === service) &&
    (!term || `${resource.name} ${resource.service} ${resource.region} ${resource.type}`.toLowerCase().includes(term))
  ));
}

function getScopedSection(section: SectionData, service: string, scoped: typeof resources[number][]) {
  if (service !== ALL_SERVICES && serviceSection[service] !== section.id) return null;
  if (scoped.length === 0) return null;
  const scopeNames = new Set<string>(scoped.map((resource) => resource.name));
  const metrics = section.metrics.map((item) => {
    const matches = item.resources.filter((resource) => scopeNames.has(resource.name));
    const relevant = matches.length > 0 ? matches : item.resources.slice(0, Math.min(scoped.length, item.resources.length));
    const ratio = relevant.length / Math.max(item.resources.length, 1);
    const numeric = Number(item.value.replace(/[^0-9.]/g, ''));
    const dynamicValue = Number.isFinite(numeric) && numeric > 0 && relevant.length > 0
      ? item.value.replace(/[\d,.]+/, (raw) => {
        const computed = numeric * (0.56 + ratio * 0.44);
        const decimals = raw.includes('.') ? (raw.split('.')[1]?.length ?? 0) : 0;
        return computed.toLocaleString('pt-BR', { minimumFractionDigits: decimals, maximumFractionDigits: decimals });
      })
      : item.value;
    return { ...item, value: dynamicValue, resources: relevant };
  });
  return { ...section, metrics };
}

function Dashboard() {
  const { user, signOut } = useAuth();
  const [, navigate] = useLocation();
  const [period, setPeriod] = useState<Period>('24h');
  const [environment, setEnvironment] = useState<Environment>('Produção');
  const [service, setService] = useState(ALL_SERVICES);
  const [search, setSearch] = useState('');
  const [activeSection, setActiveSection] = useState('database');
  const [selectedMetric, setSelectedMetric] = useState<Metric | null>(null);

  const scopedResources = useMemo(() => getScopedResources(environment, service, search), [environment, service, search]);
  const visibleSections = useMemo(
    () => sections.map((section) => getScopedSection(section, service, scopedResources)).filter((section): section is SectionData => section !== null),
    [service, scopedResources],
  );
  const active = visibleSections.find((section) => section.id === activeSection) ?? visibleSections[0];
  const selectedResources = useMemo(() => getScopedResources(environment, service, search), [environment, service, search]);
  const currentSeries = active?.series.map((entry) => {
    const adjusted = entry.values.map((value) => {
      const envScale = environment === 'Produção' ? 1 : environment === 'Homologação' ? 0.58 : 0.31;
      const resourceScale = Math.max(0.42, Math.min(1.2, selectedResources.length / 5));
      return Number((value * envScale * resourceScale).toFixed(2));
    });
    const view = generateHourlySeries(period, adjusted);
    return { name: entry.name, values: view.values, color: entry.color };
  }) ?? [];
  const chartLabels = active ? generateHourlySeries(period, active.series[0].values).labels : [];
  const alertCount = visibleSections.reduce((count, section) => count + section.metrics.filter((metric) => metric.severity).length, 0);
  const highPriority = visibleSections.flatMap((section) => section.metrics.filter((metric) => metric.severity === 'critical').map((item) => ({ ...item, section: section.title }))).slice(0, 2);

  const hasCriticalSignals = visibleSections.some((section) => section.metrics.some((metric) => metric.severity === 'critical'));
  const systemStatus = hasCriticalSignals ? 'Atenção necessária' : alertCount > 0 ? 'Avisos ativos' : 'Sistemas normais';
  const initials = (user?.name ?? 'CC')
    .split(' ')
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part.charAt(0))
    .join('')
    .toUpperCase();

  function handleSignOut() {
    signOut();
    navigate('/login', { replace: true });
  }

  return (
    <TooltipProvider delayDuration={250}>
      <main className="min-h-[100dvh] bg-[#f6f9f7] text-[#203329]">
        <header className="border-b border-[#dfe8e2] bg-white">
          <div className="mx-auto flex max-w-[1480px] items-center justify-between gap-4 px-4 py-3.5 md:px-8">
            <div className="flex min-w-0 items-center gap-3">
              <div className="h-9 w-9 shrink-0 overflow-hidden rounded-lg bg-white ring-1 ring-[#dfe7e1]">
                <img src={logoUrl} alt="Logo do Projeto CCD-SB100" className="h-full w-full object-cover" />
              </div>
              <div className="min-w-0">
                <div className="flex items-center gap-2">
                  <span className="font-display text-[15px] font-extrabold tracking-[-.045em] text-[#203329]">CCD-SB100</span>
                  <span className="h-4 w-px bg-[#dfe7e1]" />
                  <span className="truncate text-[12px] font-medium text-[#69776f]">Dashboard DevOps</span>
                </div>
              </div>
            </div>
            <div className="flex items-center gap-2.5">
              <div className="hidden items-center gap-1.5 rounded-full border border-[#e2e9e4] bg-[#fafcfb] px-2.5 py-1.5 sm:flex">
                <span className={`h-2 w-2 rounded-full ${hasCriticalSignals ? 'bg-[#bd493c]' : alertCount > 0 ? 'bg-[#bd8b2c]' : 'bg-[#4c9467]'}`} />
                <span className={`text-[10px] font-semibold ${hasCriticalSignals ? 'text-[#a83c30]' : alertCount > 0 ? 'text-[#916315]' : 'text-[#5e7165]'}`}>{systemStatus}</span>
              </div>
              <Button variant="ghost" size="icon" data-testid="button-notifications" className="relative h-9 w-9 text-[#69796f] hover:bg-[#f0f5f1]">
                <Bell className="h-[17px] w-[17px]" />
                {alertCount > 0 && <span className="absolute right-[7px] top-[7px] h-1.5 w-1.5 rounded-full bg-[#c2832b] ring-2 ring-white" />}
                <span className="sr-only">Abrir alertas</span>
              </Button>
              <div className="hidden h-7 w-px bg-[#e6ece8] sm:block" />
              <div className="flex h-8 w-8 items-center justify-center rounded-full border border-[#d7e5dc] bg-[#eff6f1] text-[10px] font-bold tracking-wide text-[#326b4d]" data-testid="text-team-avatar" title={user?.email}>{initials}</div>
              <Button variant="ghost" size="icon" onClick={handleSignOut} data-testid="button-sign-out" title="Sair" className="h-9 w-9 text-[#69796f] hover:bg-[#f0f5f1]">
                <LogOut className="h-[16px] w-[16px]" />
                <span className="sr-only">Sair</span>
              </Button>
            </div>
          </div>
        </header>

        <div className="mx-auto max-w-[1480px] px-4 pb-10 md:px-8">
          <section className="flex flex-col gap-5 pb-5 pt-7 md:flex-row md:items-end md:justify-between md:pt-8">
            <div>
              <div className="mb-2 flex items-center gap-2" data-testid="text-overview-environment">
                <span className="inline-flex items-center gap-1.5 rounded-full border border-[#dce8df] bg-[#f1f7f3] px-2.5 py-1 font-mono text-[10px] font-medium uppercase tracking-[.12em] text-[#3d7c59]">
                  <span className="h-1.5 w-1.5 rounded-full bg-[#4a9867]" />
                  {environment}
                </span>
              </div>
              <h1 className="font-display text-[27px] font-extrabold leading-tight tracking-[-.055em] text-[#1d3027] md:text-[32px]">Visão geral da plataforma</h1>
              <p className="mt-1.5 max-w-[560px] text-[13px] leading-relaxed text-[#75827a]">Monitoramento da infraestrutura de IA do Projeto CCD-SB100, uma pesquisa em agricultura apoiada pela FAPESP.</p>
            </div>
            <div className="flex items-center justify-between gap-4 md:justify-end">
              <div className="text-left md:text-right">
                <div className="font-mono text-[10px] uppercase tracking-[.11em] text-[#99a49d]">Fonte de dados</div>
                <div className="mt-1 flex items-center gap-1.5 text-[11px] font-medium text-[#596a60] md:justify-end"><span className="h-1.5 w-1.5 rounded-full bg-[#4a9867]" />Dados de demonstração</div>
              </div>
            </div>
          </section>

          <section className="mb-5 grid grid-cols-1 gap-3 sm:grid-cols-3">
            <Card className="rounded-lg border-[#dce8df] bg-[#f0f7f2] shadow-none">
              <CardContent className="flex items-center justify-between gap-3 p-4">
                <div className="flex items-center gap-3">
                  <span className="flex h-9 w-9 items-center justify-center rounded-md bg-white text-[#347953]"><CheckCircle2 className="h-[17px] w-[17px]" /></span>
                  <div><div className="text-[10px] font-bold uppercase tracking-[.11em] text-[#658071]">Disponibilidade da plataforma</div><div className="mt-1 font-mono text-[20px] font-medium tracking-[-.04em] text-[#244b37]" data-testid="value-fleet-availability">99.96%</div></div>
                </div><span className="font-mono text-[10px] text-[#4b8a66]">+0.03%</span>
              </CardContent>
            </Card>
            <Card className="rounded-lg border-[#e4e9e5] bg-white shadow-none">
              <CardContent className="flex items-center justify-between gap-3 p-4">
                <div className="flex items-center gap-3">
                  <span className="flex h-9 w-9 items-center justify-center rounded-md bg-[#f5f7f5] text-[#62736a]"><Cpu className="h-[17px] w-[17px]" /></span>
                  <div><div className="text-[10px] font-bold uppercase tracking-[.11em] text-[#7e8a82]">Recursos no escopo</div><div className="mt-1 font-mono text-[20px] font-medium tracking-[-.04em] text-[#26382e]" data-testid="value-resource-count">{selectedResources.length}<span className="ml-1.5 text-[11px] text-[#86938b]">de 8</span></div></div>
                </div><span className="text-[10px] text-[#96a19a]">{environment}</span>
              </CardContent>
            </Card>
            <Card className="rounded-lg border-[#e4e9e5] bg-white shadow-none">
              <CardContent className="flex items-center justify-between gap-3 p-4">
                <div className="flex items-center gap-3">
                  <span className="flex h-9 w-9 items-center justify-center rounded-md bg-[#fff7e8] text-[#ad7921]"><Activity className="h-[17px] w-[17px]" /></span>
                  <div><div className="text-[10px] font-bold uppercase tracking-[.11em] text-[#7e8a82]">Sinais ativos</div><div className="mt-1 font-mono text-[20px] font-medium tracking-[-.04em] text-[#26382e]" data-testid="value-active-signals">{alertCount}<span className="ml-1.5 text-[11px] text-[#86938b]">para revisar</span></div></div>
                </div><Badge className="rounded-sm border border-[#f0dfbd] bg-[#fff8e9] px-1.5 text-[9px] font-bold uppercase tracking-wide text-[#966c24] hover:bg-[#fff8e9]">Atenção</Badge>
              </CardContent>
            </Card>
          </section>

          <div className="overflow-hidden rounded-xl border border-[#dfe8e2] bg-white shadow-[0_4px_20px_rgba(33,64,45,.035)]">
            <FiltersBar period={period} setPeriod={setPeriod} environment={environment} setEnvironment={(value) => { setEnvironment(value); setActiveSection('database'); }} service={service} setService={(value) => { setService(value); const target = serviceSection[value]; if (target) setActiveSection(target); }} search={search} setSearch={setSearch} />
            <div className="px-4 pt-4 md:px-7">
              <Tabs value={active?.id ?? ''} onValueChange={setActiveSection}>
                <TabsList data-testid="tabs-dashboard-sections" className="h-auto w-full justify-start gap-1 overflow-x-auto rounded-none border-b border-[#e8eeea] bg-transparent p-0">
                  {sections.map((section) => {
                    const Icon = sectionIcons[section.id];
                    const enabled = visibleSections.some((item) => item.id === section.id);
                    return (
                      <TabsTrigger key={section.id} value={section.id} disabled={!enabled} data-testid={`tab-${section.id}`} className="mb-[-1px] min-w-max gap-2 rounded-none border-b-2 border-transparent px-3 pb-3 pt-1 text-[12px] font-semibold text-[#7c8981] shadow-none data-[state=active]:border-[#286b4c] data-[state=active]:bg-transparent data-[state=active]:text-[#286b4c] data-[state=active]:shadow-none disabled:opacity-35 md:px-4">
                        <Icon className="h-3.5 w-3.5" />{section.title}
                      </TabsTrigger>
                    );
                  })}
                </TabsList>
                {visibleSections.map((section) => (
                  <TabsContent key={section.id} value={section.id} className="mt-0 focus-visible:outline-none">
                    <div className="flex flex-col gap-1 pb-4 pt-5 sm:flex-row sm:items-end sm:justify-between">
                      <div><div className="font-mono text-[9px] font-medium tracking-[.16em] text-[#91a097]">{section.eyebrow}</div><h2 className="mt-1 font-display text-[19px] font-bold tracking-[-.04em] text-[#263a2e]">{section.title} <span className="font-sans text-[13px] font-normal tracking-normal text-[#849188]">/ {section.summary}</span></h2></div>
                      <div className="flex items-center gap-1.5 text-[10px] text-[#86938b]"><span className="h-1.5 w-1.5 rounded-full bg-[#4b9467]" />Janela de análise: <span className="font-mono font-medium text-[#52665a]">{period}</span></div>
                    </div>

                    {section.metrics.length > 0 ? (
                      <div className="grid grid-cols-1 gap-3 pb-5 sm:grid-cols-2 xl:grid-cols-3">
                        {section.metrics.map((item) => (
                          <MetricCard key={item.id} metric={item} period={period} multiplier={environment === 'Produção' ? 1 : environment === 'Homologação' ? 0.64 : 0.37} onSelect={setSelectedMetric} />
                        ))}
                      </div>
                    ) : (
                      <div className="mb-5 rounded-lg border border-dashed border-[#dce6df] bg-[#f9fbf9] px-6 py-12 text-center">
                        <Search className="mx-auto h-5 w-5 text-[#91a097]" />
                        <p className="mt-3 text-sm font-semibold text-[#43564a]">Nenhum recurso corresponde a esta busca</p>
                        <p className="mt-1 text-xs text-[#87938c]">Tente outro nome de recurso, região ou serviço.</p>
                      </div>
                    )}

                    <div className="mb-6 grid grid-cols-1 gap-3 lg:grid-cols-[minmax(0,1.7fr)_minmax(260px,.82fr)]">
                      <Card className="min-w-0 max-w-full overflow-hidden rounded-lg border-[#e2e9e4] shadow-none">
                        <CardContent className="min-w-0 max-w-full overflow-hidden p-4 md:p-5">
                          <div className="mb-2 flex items-start justify-between gap-3">
                            <div><h3 className="text-[12px] font-bold text-[#33473b]">Atividade dos recursos</h3><p className="mt-1 text-[10px] text-[#8a968f]">Sinal por hora · janela de {period}</p></div>
                            <div className="flex flex-wrap justify-end gap-x-3 gap-y-1">
                              {currentSeries.map((line) => <span key={line.name} className="inline-flex items-center gap-1.5 text-[9px] text-[#75827a]"><i className="h-1.5 w-1.5 rounded-full" style={{ backgroundColor: line.color ?? '#216b4e' }} />{line.name}</span>)}
                            </div>
                          </div>
                          <div className="w-full min-w-0 max-w-full overflow-hidden">
                            {active?.id === section.id && (
                              <ApexChart
                                key={`${section.id}-${period}`}
                                labels={chartLabels}
                                series={currentSeries}
                                type={section.id === 'storage' ? 'bar' : 'area'}
                                stacked={section.id === 'storage'}
                              />
                            )}
                          </div>
                        </CardContent>
                      </Card>
                      <Card className="rounded-lg border-[#e2e9e4] shadow-none">
                        <CardContent className="p-4 md:p-5">
                          <div className="flex items-center justify-between">
                            <div><h3 className="text-[12px] font-bold text-[#33473b]">Precisa de atenção</h3><p className="mt-1 text-[10px] text-[#8a968f]">Sinais de maior prioridade</p></div>
                            <Badge className="rounded-sm border border-[#efd8a8] bg-[#fff8e8] px-1.5 text-[9px] font-bold text-[#916315] hover:bg-[#fff8e8]">{highPriority.length} críticos</Badge>
                          </div>
                          <div className="mt-4 space-y-2">
                            {highPriority.length ? highPriority.map((item) => (
                              <button key={item.id} onClick={() => setSelectedMetric(item)} data-testid={`button-alert-${item.id}`} className="flex w-full items-center gap-3 rounded-md border border-[#f0e9dc] bg-[#fffdf9] p-3 text-left transition-colors hover:bg-[#fff9ee]">
                                <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded bg-[#fff2e5] text-[#a96d21]"><ArrowUpRight className="h-3.5 w-3.5" /></span>
                                <span className="min-w-0 flex-1"><span className="block truncate text-[11px] font-semibold text-[#46574b]">{item.label}</span><span className="mt-0.5 block truncate text-[9px] text-[#8e988f]">{item.section} · {item.action}</span></span>
                                <ArrowRight className="h-3.5 w-3.5 shrink-0 text-[#b4b8ac]" />
                              </button>
                            )) : <div className="flex min-h-[114px] flex-col items-center justify-center text-center"><CheckCircle2 className="h-5 w-5 text-[#63a17a]" /><span className="mt-2 text-xs font-semibold text-[#52675a]">Nenhum sinal crítico no escopo</span><span className="mt-1 text-[10px] text-[#8b978f]">Os recursos selecionados estão dentro dos limites.</span></div>}
                          </div>
                          <button onClick={() => { setService(ALL_SERVICES); setSearch(''); }} data-testid="button-reset-scope" className="mt-3 flex w-full items-center justify-between border-t border-[#edf1ee] pt-3 text-[10px] font-semibold text-[#438060] hover:text-[#285d42]">
                            <span>Inspecionar ambiente completo</span><ArrowRight className="h-3 w-3" />
                          </button>
                        </CardContent>
                      </Card>
                    </div>
                  </TabsContent>
                ))}
                {visibleSections.length === 0 && (
                  <div className="flex min-h-[320px] flex-col items-center justify-center text-center">
                    <Sparkles className="h-6 w-6 text-[#8da397]" />
                    <h2 className="mt-4 text-sm font-semibold text-[#41564a]">Nada neste escopo</h2>
                    <p className="mt-1 max-w-xs text-xs leading-relaxed text-[#8a968f]">Nenhum recurso corresponde aos filtros de ambiente, serviço e busca.</p>
                    <Button onClick={() => { setSearch(''); setService(ALL_SERVICES); setEnvironment('Produção'); }} data-testid="button-clear-filters" variant="outline" className="mt-4 h-8 border-[#dce5df] text-xs">Limpar filtros</Button>
                  </div>
                )}
              </Tabs>
            </div>
            <div className="flex flex-col gap-2 border-t border-[#edf1ee] bg-[#fbfcfb] px-4 py-3 text-[9px] text-[#89958d] sm:flex-row sm:items-center sm:justify-between md:px-7">
              <div className="flex items-center gap-2"><span className="font-mono font-medium tracking-wide text-[#718077]">CCD-SB100</span><span className="h-3 w-px bg-[#dce5df]" /><span>Métricas são amostras operacionais de demonstração</span></div>
              <div className="flex items-center gap-2"><span>{selectedResources.length} recursos no escopo</span><span className="h-1 w-1 rounded-full bg-[#b8c2bb]" /><span className="font-mono">Amostra de {period}</span></div>
            </div>
          </div>
        </div>
        <DrilldownDialog metric={selectedMetric} onClose={() => setSelectedMetric(null)} />
      </main>
    </TooltipProvider>
  );
}

export default Dashboard;
