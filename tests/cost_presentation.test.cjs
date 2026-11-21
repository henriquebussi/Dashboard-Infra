// Billing provenance/rendering regression checks using actual mapping + virtual JSX.
// No browser or real billing connection is claimed.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const ts = require('typescript');

function load(file, dependencies = {}) {
  const exports = {};
  const jsx = (type, props, key) => ({ type, props: props || {}, key });
  const source = fs.readFileSync(file, 'utf8');
  const code = ts.transpileModule(source, { compilerOptions: {
    jsx: ts.JsxEmit.ReactJSX, module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022,
  }}).outputText;
  vm.runInNewContext(code, { exports, require(name) {
    if (name === 'react/jsx-runtime') return { jsx, jsxs: jsx };
    if (name in dependencies) return dependencies[name];
    throw Error('Unexpected dependency: ' + name);
  }});
  return exports;
}
const overview = load('src/lib/overview.ts');
const mock = load('src/features/dashboard/mock-data.ts');
const names = ['ArrowDownRight', 'ArrowRight', 'ArrowUpRight', 'HelpCircle', 'Minus'];
const icons = Object.fromEntries(names.map(name => [name, name]));
const source = load('src/features/dashboard/SourceDot.tsx', {
  '@/components/ui/tooltip': { Tooltip: 'Tooltip', TooltipContent: 'TooltipContent', TooltipTrigger: 'TooltipTrigger' },
});
const chartCalls = [];
const ui = load('src/features/dashboard/MetricCard.tsx', {
  'lucide-react': icons,
  '@/components/ui/card': { Card: 'Card', CardContent: 'CardContent' },
  '@/components/ui/badge': { Badge: 'Badge' },
  '@/components/ui/tooltip': { Tooltip: 'Tooltip', TooltipContent: 'TooltipContent', TooltipTrigger: 'TooltipTrigger' },
  './ApexChart': { ApexChart: function ApexChart(props) { chartCalls.push(props); return { type: 'Chart', props }; } },
  './mock-data': mock,
  './SourceDot': source,
});
function expand(tree) {
  if (Array.isArray(tree)) return tree.map(expand);
  if (!tree || typeof tree !== 'object') return tree;
  if (typeof tree.type === 'function') return expand(tree.type(tree.props));
  return { ...tree, props: { ...tree.props, children: expand(tree.props.children) } };
}
function text(tree) {
  if (Array.isArray(tree)) return tree.map(text).join(' ');
  if (!tree || typeof tree !== 'object') return tree == null || typeof tree === 'boolean' ? '' : String(tree);
  return text(tree.props.children);
}
function inputReading(patch = {}) {
  return { current_value: 0, unit: 'USD', status: 'HEALTHY', available: false, source: 'unavailable',
    reason: 'Billing source is not configured', resources: [], time_series: [], metadata: {}, ...patch };
}
function mapped(reading, sectionId = 'cloud', metricId = 'cost') {
  const payload = { active_alerts: [], [sectionId]: {
    [sectionId === 'cloud' ? 'estimated_cost_usd' : 'cost_per_model']: reading,
  }};
  return overview.applyOverviewToSections(mock.sections, payload)
    .find(section => section.id === sectionId).metrics.find(metric => metric.id === metricId);
}
function render(metric) {
  chartCalls.length = 0;
  return expand(ui.MetricCard({ metric, period: '24h', multiplier: 1, onSelect() {} }));
}

for (const [section, metricId] of [['cloud', 'cost'], ['tokens', 'model-cost']]) {
  test(`${section} unavailable billing never becomes a zero cost/history`, () => {
    const metric = mapped(inputReading(), section, metricId);
    assert.equal(metric.value, 'Indisponível');
    assert.equal(metric.change, '—');
    assert.equal(metric.available, false);
    assert.doesNotMatch(metric.label, /estimado/);
    assert.equal(metric.series.length, 0);
    const rendered = text(render(metric));
    assert.match(rendered, /Indisponível/);
    assert.match(rendered, /Billing source is not configured/);
    assert.doesNotMatch(rendered, /\$0|GCP Live|Estimated/);
    assert.equal(chartCalls.length, 0);
  });
}

test('available estimated scalar keeps provenance and rule without synthetic history', () => {
  const metric = mapped(inputReading({ current_value: 12, available: true, source: 'estimated',
    reason: 'Explicit estimate rule: 10 units × USD 1.20' }));
  assert.equal(metric.value, '$12');
  assert.equal(metric.series.length, 0);
  const rendered = text(render(metric));
  assert.match(rendered, /Estimated/);
  assert.match(rendered, /Explicit estimate rule/);
  assert.match(rendered, /Sem histórico disponível/);
  assert.doesNotMatch(rendered, /GCP Live/);
  assert.equal(chartCalls.length, 0);
});

test('explicitly available zero remains a zero and retains supplied real history', () => {
  const metric = mapped(inputReading({ available: true, source: 'gcp', reason: null,
    time_series: [{ timestamp: '2026-11-18T12:00:00Z', value: 0 }] }));
  assert.equal(metric.value, '$0');
  render(metric);
  assert.equal(chartCalls.length, 1);
  assert.equal(chartCalls[0].series[0].values[0], 0);
});

test('demonstration costs retain their dataset and explicit Demo badge', () => {
  const metric = mock.sections.find(s => s.id === 'cloud').metrics.find(m => m.id === 'cost');
  const copy = JSON.stringify(metric);
  const rendered = text(render(metric));
  assert.match(rendered, /Demo/);
  assert.match(rendered, /\$18,426/);
  assert.equal(chartCalls.length, 1);
  assert.equal(JSON.stringify(metric), copy);
});


test('unavailable provenance overrides an omitted availability flag', () => {
  const reading = inputReading();
  delete reading.available;
  const metric = mapped(reading);
  assert.equal(metric.available, false);
  assert.equal(metric.value, 'Indisponível');
  assert.equal(metric.series.length, 0);
});

test('source supplied reading uses neutral cost label, not estimate claim', () => {
  const metric = mapped(inputReading({ available: true, source: 'gcp', current_value: 12 }));
  assert.equal(metric.label, 'Custo de infraestrutura');
  assert.equal(metric.value, '$12');
});


test('root demo provenance overrides default gcp readings and never enters Real costs', () => {
  const payload = { data_source: 'demo', active_alerts: [], cloud: {
    estimated_cost_usd: inputReading({ available: true, source: 'gcp', current_value: 18426 }),
  }};
  const section = mock.sections.find(s => s.id === 'cloud');
  const mappedSections = overview.applyOverviewToSections([section], payload);
  const metric = mappedSections[0].metrics.find(m => m.id === 'cost');
  assert.equal(metric.source, 'demo');
  assert.equal(metric.label, 'Custo estimado');
  const rendered = text(render(metric));
  assert.match(rendered, /Demo/);
  assert.doesNotMatch(rendered, /GCP Live/);

  // Compile the actual pure sanitiser from the page; avoid importing browser hooks.
  const pageSource = fs.readFileSync('src/pages/dashboard.tsx', 'utf8');
  const snippet = pageSource.slice(pageSource.indexOf("const UNAVAILABLE ="),
    pageSource.indexOf('function getRealScopedSection')) + '\nexport { sanitizeRealSections };';
  const code = ts.transpileModule(snippet, { compilerOptions: {
    module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022,
  }}).outputText;
  const exports = {};
  vm.runInNewContext(code, { exports });
  const real = exports.sanitizeRealSections(mappedSections)[0].metrics.find(m => m.id === 'cost');
  assert.equal(real.available, false);
  assert.equal(real.source, 'unavailable');
  assert.equal(real.value, 'Indisponível');
  assert.equal(real.resources.length, 0);
  const realRendered = text(render(real));
  assert.doesNotMatch(realRendered, /\$18|GCP Live|Demo/);
  assert.equal(chartCalls.length, 0);
});
