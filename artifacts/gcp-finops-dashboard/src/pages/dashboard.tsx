import { useMemo, useState } from 'react';
import { Activity, ArrowRight, ArrowUpRight, Bell, BrainCircuit, CheckCircle2, ChevronRight, Cloud, Cpu, Database, HardDrive, Search, ShieldCheck, Sparkles, Workflow } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { TooltipProvider } from '@/components/ui/tooltip';
import { ApexChart } from '@/features/dashboard/ApexChart';
import { DrilldownDialog } from '@/features/dashboard/DrilldownDialog';
import { FiltersBar } from '@/features/dashboard/FiltersBar';
import { MetricCard } from '@/features/dashboard/MetricCard';
import { generateHourlySeries, resources, sections, type Environment, type Metric, type Period, type SectionData } from '@/features/dashboard/mock-data';

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
    (service === 'All services' || resource.service === service) &&
    (!term || `${resource.name} ${resource.service} ${resource.region} ${resource.type}`.toLowerCase().includes(term))
  ));
}

function getScopedSection(section: SectionData, service: string, scoped: typeof resources[number][]) {
  if (service !== 'All services' && serviceSection[service] !== section.id) return null;
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
        return computed.toLocaleString('en-US', { minimumFractionDigits: decimals, maximumFractionDigits: decimals });
      })
      : item.value;
    return { ...item, value: dynamicValue, resources: relevant };
  });
  return { ...section, metrics };
}

function Dashboard() {
  const [period, setPeriod] = useState<Period>('24h');
  const [environment, setEnvironment] = useState<Environment>('Production');
  const [service, setService] = useState('All services');
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
      const envScale = environment === 'Production' ? 1 : environment === 'Staging' ? 0.58 : 0.31;
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
  const systemStatus = hasCriticalSignals ? 'Attention required' : alertCount > 0 ? 'Warnings active' : 'Systems nominal';

  return (
    <TooltipProvider delayDuration={250}>
      <main className="min-h-[100dvh] bg-[#f6f9f7] text-[#203329]">
        <header className="border-b border-[#dfe8e2] bg-white">
          <div className="mx-auto flex max-w-[1480px] items-center justify-between gap-4 px-4 py-3.5 md:px-8">
            <div className="flex min-w-0 items-center gap-3">
              <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-[#1f684a] text-white shadow-[inset_0_1px_0_rgba(255,255,255,.18)]">
                <Activity className="h-[18px] w-[18px]" strokeWidth={2.1} />
              </div>
              <div className="min-w-0">
                <div className="flex items-center gap-2">
                  <span className="font-display text-[15px] font-extrabold tracking-[-.045em] text-[#203329]">Fieldnote</span>
                  <span className="hidden h-4 w-px bg-[#dfe7e1] sm:block" />
                  <span className="hidden truncate text-[12px] font-medium text-[#69776f] sm:block">Infrastructure observability</span>
                </div>
                <div className="mt-0.5 flex items-center gap-1.5 text-[10px] text-[#9aa69f] sm:hidden">GCP / Platform health</div>
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
                <span className="sr-only">Open alerts</span>
              </Button>
              <div className="hidden h-7 w-px bg-[#e6ece8] sm:block" />
              <div className="flex h-8 w-8 items-center justify-center rounded-full border border-[#d7e5dc] bg-[#eff6f1] text-[10px] font-bold tracking-wide text-[#326b4d]" data-testid="text-team-avatar">PL</div>
            </div>
          </div>
        </header>

        <div className="mx-auto max-w-[1480px] px-4 pb-10 md:px-8">
          <section className="flex flex-col gap-5 pb-5 pt-7 md:flex-row md:items-end md:justify-between md:pt-8">
            <div>
              <div className="mb-2 flex items-center gap-2">
                <span className="font-mono text-[10px] font-medium uppercase tracking-[.15em] text-[#829188]" data-testid="text-overview-breadcrumb">GCP / PLATFORM HEALTH</span>
                <ChevronRight className="h-3 w-3 text-[#b3beb7]" />
                <span className="font-mono text-[10px] uppercase tracking-[.1em] text-[#428160]">{environment}</span>
              </div>
              <h1 className="font-display text-[27px] font-extrabold leading-tight tracking-[-.055em] text-[#1d3027] md:text-[32px]">Infrastructure overview</h1>
              <p className="mt-1.5 max-w-[520px] text-[13px] leading-relaxed text-[#75827a]">A seeded sample of platform health, resource pressure and cloud spend.</p>
            </div>
            <div className="flex items-center justify-between gap-4 md:justify-end">
              <div className="text-left md:text-right">
                <div className="font-mono text-[10px] uppercase tracking-[.11em] text-[#99a49d]">Data source</div>
                <div className="mt-1 flex items-center gap-1.5 text-[11px] font-medium text-[#596a60] md:justify-end"><span className="h-1.5 w-1.5 rounded-full bg-[#4a9867]" />Seeded mock data</div>
              </div>
            </div>
          </section>

          <section className="mb-5 grid grid-cols-1 gap-3 sm:grid-cols-3">
            <Card className="rounded-lg border-[#dce8df] bg-[#f0f7f2] shadow-none">
              <CardContent className="flex items-center justify-between gap-3 p-4">
                <div className="flex items-center gap-3">
                  <span className="flex h-9 w-9 items-center justify-center rounded-md bg-white text-[#347953]"><CheckCircle2 className="h-[17px] w-[17px]" /></span>
                  <div><div className="text-[10px] font-bold uppercase tracking-[.11em] text-[#658071]">Fleet availability</div><div className="mt-1 font-mono text-[20px] font-medium tracking-[-.04em] text-[#244b37]" data-testid="value-fleet-availability">99.96%</div></div>
                </div><span className="font-mono text-[10px] text-[#4b8a66]">+0.03%</span>
              </CardContent>
            </Card>
            <Card className="rounded-lg border-[#e4e9e5] bg-white shadow-none">
              <CardContent className="flex items-center justify-between gap-3 p-4">
                <div className="flex items-center gap-3">
                  <span className="flex h-9 w-9 items-center justify-center rounded-md bg-[#f5f7f5] text-[#62736a]"><Cpu className="h-[17px] w-[17px]" /></span>
                  <div><div className="text-[10px] font-bold uppercase tracking-[.11em] text-[#7e8a82]">Resources in scope</div><div className="mt-1 font-mono text-[20px] font-medium tracking-[-.04em] text-[#26382e]" data-testid="value-resource-count">{selectedResources.length}<span className="ml-1.5 text-[11px] text-[#86938b]">of 8</span></div></div>
                </div><span className="text-[10px] text-[#96a19a]">{environment}</span>
              </CardContent>
            </Card>
            <Card className="rounded-lg border-[#e4e9e5] bg-white shadow-none">
              <CardContent className="flex items-center justify-between gap-3 p-4">
                <div className="flex items-center gap-3">
                  <span className="flex h-9 w-9 items-center justify-center rounded-md bg-[#fff7e8] text-[#ad7921]"><Activity className="h-[17px] w-[17px]" /></span>
                  <div><div className="text-[10px] font-bold uppercase tracking-[.11em] text-[#7e8a82]">Active signals</div><div className="mt-1 font-mono text-[20px] font-medium tracking-[-.04em] text-[#26382e]" data-testid="value-active-signals">{alertCount}<span className="ml-1.5 text-[11px] text-[#86938b]">to review</span></div></div>
                </div><Badge className="rounded-sm border border-[#f0dfbd] bg-[#fff8e9] px-1.5 text-[9px] font-bold uppercase tracking-wide text-[#966c24] hover:bg-[#fff8e9]">Attention</Badge>
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
                      <div className="flex items-center gap-1.5 text-[10px] text-[#86938b]"><span className="h-1.5 w-1.5 rounded-full bg-[#4b9467]" />Reporting window: <span className="font-mono font-medium text-[#52665a]">{period}</span></div>
                    </div>

                    {section.metrics.length > 0 ? (
                      <div className="grid grid-cols-1 gap-3 pb-5 sm:grid-cols-2 xl:grid-cols-3">
                        {section.metrics.map((item) => (
                          <MetricCard key={item.id} metric={item} period={period} multiplier={environment === 'Production' ? 1 : environment === 'Staging' ? 0.64 : 0.37} onSelect={setSelectedMetric} />
                        ))}
                      </div>
                    ) : (
                      <div className="mb-5 rounded-lg border border-dashed border-[#dce6df] bg-[#f9fbf9] px-6 py-12 text-center">
                        <Search className="mx-auto h-5 w-5 text-[#91a097]" />
                        <p className="mt-3 text-sm font-semibold text-[#43564a]">No resources match this search</p>
                        <p className="mt-1 text-xs text-[#87938c]">Try another resource name, region or service.</p>
                      </div>
                    )}

                    <div className="mb-6 grid grid-cols-1 gap-3 lg:grid-cols-[minmax(0,1.7fr)_minmax(260px,.82fr)]">
                      <Card className="rounded-lg border-[#e2e9e4] shadow-none">
                        <CardContent className="p-4 md:p-5">
                          <div className="mb-2 flex items-start justify-between gap-3">
                            <div><h3 className="text-[12px] font-bold text-[#33473b]">Resource activity</h3><p className="mt-1 text-[10px] text-[#8a968f]">Hourly signal · {period} window</p></div>
                            <div className="flex flex-wrap justify-end gap-x-3 gap-y-1">
                              {currentSeries.map((line) => <span key={line.name} className="inline-flex items-center gap-1.5 text-[9px] text-[#75827a]"><i className="h-1.5 w-1.5 rounded-full" style={{ backgroundColor: line.color ?? '#216b4e' }} />{line.name}</span>)}
                            </div>
                          </div>
                          <ApexChart
                            labels={chartLabels}
                            series={currentSeries}
                            type={active?.id === 'storage' ? 'bar' : active?.id === 'processing' || active?.id === 'sla' ? 'line' : 'area'}
                            stacked={active?.id === 'storage'}
                          />
                        </CardContent>
                      </Card>
                      <Card className="rounded-lg border-[#e2e9e4] shadow-none">
                        <CardContent className="p-4 md:p-5">
                          <div className="flex items-center justify-between">
                            <div><h3 className="text-[12px] font-bold text-[#33473b]">Needs attention</h3><p className="mt-1 text-[10px] text-[#8a968f]">Highest priority signals</p></div>
                            <Badge className="rounded-sm border border-[#efd8a8] bg-[#fff8e8] px-1.5 text-[9px] font-bold text-[#916315] hover:bg-[#fff8e8]">{highPriority.length} critical</Badge>
                          </div>
                          <div className="mt-4 space-y-2">
                            {highPriority.length ? highPriority.map((item) => (
                              <button key={item.id} onClick={() => setSelectedMetric(item)} data-testid={`button-alert-${item.id}`} className="flex w-full items-center gap-3 rounded-md border border-[#f0e9dc] bg-[#fffdf9] p-3 text-left transition-colors hover:bg-[#fff9ee]">
                                <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded bg-[#fff2e5] text-[#a96d21]"><ArrowUpRight className="h-3.5 w-3.5" /></span>
                                <span className="min-w-0 flex-1"><span className="block truncate text-[11px] font-semibold text-[#46574b]">{item.label}</span><span className="mt-0.5 block truncate text-[9px] text-[#8e988f]">{item.section} · {item.action}</span></span>
                                <ArrowRight className="h-3.5 w-3.5 shrink-0 text-[#b4b8ac]" />
                              </button>
                            )) : <div className="flex min-h-[114px] flex-col items-center justify-center text-center"><CheckCircle2 className="h-5 w-5 text-[#63a17a]" /><span className="mt-2 text-xs font-semibold text-[#52675a]">No critical signals in scope</span><span className="mt-1 text-[10px] text-[#8b978f]">The selected resources are within limits.</span></div>}
                          </div>
                          <button onClick={() => { setService('All services'); setSearch(''); }} data-testid="button-reset-scope" className="mt-3 flex w-full items-center justify-between border-t border-[#edf1ee] pt-3 text-[10px] font-semibold text-[#438060] hover:text-[#285d42]">
                            <span>Inspect full environment</span><ArrowRight className="h-3 w-3" />
                          </button>
                        </CardContent>
                      </Card>
                    </div>
                  </TabsContent>
                ))}
                {visibleSections.length === 0 && (
                  <div className="flex min-h-[320px] flex-col items-center justify-center text-center">
                    <Sparkles className="h-6 w-6 text-[#8da397]" />
                    <h2 className="mt-4 text-sm font-semibold text-[#41564a]">Nothing in this scope</h2>
                    <p className="mt-1 max-w-xs text-xs leading-relaxed text-[#8a968f]">No resources match your current environment, service and search filters.</p>
                    <Button onClick={() => { setSearch(''); setService('All services'); setEnvironment('Production'); }} data-testid="button-clear-filters" variant="outline" className="mt-4 h-8 border-[#dce5df] text-xs">Clear filters</Button>
                  </div>
                )}
              </Tabs>
            </div>
            <div className="flex flex-col gap-2 border-t border-[#edf1ee] bg-[#fbfcfb] px-4 py-3 text-[9px] text-[#89958d] sm:flex-row sm:items-center sm:justify-between md:px-7">
              <div className="flex items-center gap-2"><span className="font-mono font-medium tracking-wide text-[#718077]">FIELDNOTE / GCP</span><span className="h-3 w-px bg-[#dce5df]" /><span>Metrics are seeded operational samples</span></div>
              <div className="flex items-center gap-2"><span>{selectedResources.length} resources in scope</span><span className="h-1 w-1 rounded-full bg-[#b8c2bb]" /><span className="font-mono">24-hour sample</span></div>
            </div>
          </div>
        </div>
        <DrilldownDialog metric={selectedMetric} onClose={() => setSelectedMetric(null)} />
      </main>
    </TooltipProvider>
  );
}

export default Dashboard;
