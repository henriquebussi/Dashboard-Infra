// Source inventory contract; controlled JSX, not a browser or GCP connection.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const ts = require('typescript');
function load(file, dependencies = {}) {
  const exports = {};
  const jsx = (type, props) => ({ type, props });
  const code = ts.transpileModule(fs.readFileSync(file, 'utf8'), {compilerOptions: {
    module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX,
  }}).outputText;
  vm.runInNewContext(code, { exports, require(name) {
    if (name === 'react/jsx-runtime') return { jsx, jsxs: jsx };
    if (name in dependencies) return dependencies[name];
    throw Error('Unexpected external dependency: ' + name);
  }});
  return exports;
}
const overview = load('src/lib/overview.ts');
const sources = load('src/lib/metricSources.ts', { './overview': overview });
const component = load('src/features/dashboard/MetricSourceOverview.tsx', { '@/lib/metricSources': sources });
function text(tree) {
  if (Array.isArray(tree)) return tree.map(text).join(' ');
  if (!tree || typeof tree !== 'object') return tree == null ? '' : String(tree);
  return text(tree.props.children);
}
test('four technical sources preserve existing dashboard IDs without copying GCP tokens to local', () => {
  assert.equal(sources.metricSources.length, 4);
  const gcp = sources.metricSources.find(s => s.id === 'gcp');
  const expected = Object.entries(overview.METRIC_KEYS).flatMap(([section, fields]) => Object.values(fields).map(f => `${section}.${f}`));
  assert.equal(JSON.stringify(gcp.metrics), JSON.stringify(expected));
  assert.equal(new Set(gcp.metrics).size, gcp.metrics.length);
  assert.ok(gcp.metrics.includes('tokens.daily_token_count'));
  for (const source of sources.metricSources.filter(s => s.id !== 'gcp' && s.id !== 'qdrant')) assert.equal(source.metrics.length, 0);
});
test('inventory exposes absent collectors and never claims a real read', () => {
  const result = text(component.MetricSourceOverview());
  for (const name of ['Qdrant', 'Google Cloud Platform (GCP)', 'Servidor Interno', 'Tokens Locais']) assert.ok(result.includes(name));
  assert.match(result, /acesso real não confirmado/);
  assert.match(result, /não implica disponibilidade/);
  assert.match(result, /não medem CPU, RAM ou disco/);
  assert.match(result, /Coletor não implementado/);
});
test('source inventory is additive and limited to Real mode', () => {
  const page = fs.readFileSync('src/pages/dashboard.tsx', 'utf8');
  const diagnostics = page.match(/\{realMode && \(\s*<section aria-labelledby="diagnostics-heading"[\s\S]*?<\/section>/)?.[0] ?? "";
  assert.ok(diagnostics.includes("<MetricSourceOverview />"));
  assert.ok(diagnostics.includes("<MetricExplorer env={backendEnv} period={period} />"));
});
