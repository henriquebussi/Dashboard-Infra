// Component-level tests using virtual JSX and hook scheduling; no browser/DOM claims.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const ts = require('typescript');

function harness(component, api, initialProps = { env: 'DEV', period: '7d', type: 'custom.googleapis.com/test', unit: '1' }) {
  let index = 0, dirty = false, tree, props = initialProps;
  const state = [], effects = [], pending = [];
  const react = {
    useState(initial) {
      const slot = index++;
      if (!(slot in state)) state[slot] = typeof initial === 'function' ? initial() : initial;
      return [state[slot], value => {
        const next = typeof value === 'function' ? value(state[slot]) : value;
        if (!Object.is(next, state[slot])) { state[slot] = next; dirty = true; }
      }];
    },
    useEffect(callback, deps) {
      const slot = index++;
      const prior = effects[slot];
      if (!prior || deps.some((v, i) => !Object.is(v, prior.deps[i]))) {
        pending.push(() => { prior?.cleanup?.(); effects[slot] = { deps, cleanup: callback() }; });
      }
    },
  };
  class ApiError extends Error { constructor(status, detail) { super(detail); this.status = status; this.detail = detail; } }
  const jsx = (type, props, key) => ({ type, props: props || {}, key });
  const source = fs.readFileSync('src/features/dashboard/MetricExplorer.tsx', 'utf8');
  const code = ts.transpileModule(source, { compilerOptions: {
    jsx: ts.JsxEmit.ReactJSX, module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022,
  }}).outputText;
  const module = { exports: {} };
  vm.runInNewContext(code, { module, exports: module.exports, AbortController,
    require(name) {
      if (name === 'react') return react;
      if (name === 'react/jsx-runtime') return { jsx, jsxs: jsx };
      if (name === '@/lib/api') return { ApiError, ...api };
      throw Error('Unexpected module ' + name);
    },
  });
  function render() { index = 0; dirty = false; tree = module.exports[component](props); while (pending.length) pending.shift()(); return tree; }
  async function flush() {
    for (let i = 0; i < 10; i++) {
      await new Promise(resolve => setImmediate(resolve));
      if (!dirty) break;
      render();
    }
    return tree;
  }
  render();
  return { flush, get tree() { return tree; }, render, ApiError,
    update(next) { props = { ...props, ...next }; return render(); },
    unmount() { effects.forEach(e => e?.cleanup?.()); },
  };
}
function nodes(tree) {
  if (Array.isArray(tree)) return tree.flatMap(nodes);
  if (!tree || typeof tree !== 'object') return [];
  return [tree, ...nodes(tree.props?.children)];
}
function text(tree) {
  if (Array.isArray(tree)) return tree.map(text).join(' ');
  if (tree == null || tree === false) return '';
  return typeof tree === 'object' ? text(tree.props?.children) : String(tree);
}
function button(h, match) { return nodes(h.tree).find(n => n.type === 'button' && match.test(text(n))); }
function page(series = [], extra = {}) {
  return { series, warnings: [], project: 'dev-project', scope: 'project-mapped', warning: null,
    start: '2026-11-11T00:00:00Z', end: '2026-11-18T00:00:00Z', next_page_token: '', ...extra };
}
function series(values) {
  return [{ resource: { type: 'test', labels: {} }, metric: { labels: {} }, unit: 'ms',
    points: values.map(value => ({ interval: { end_time: '2026-11-18T00:00:00Z' }, value })) }];
}

test('rendered samples preserve false, zero, int64 text and distributions', async () => {
  const distribution = { count: '2', mean: 1.5, bucket_counts: ['1', '1'] };
  const h = harness('Series', { getCatalogSeries: async () => page(series([
    { bool_value: false }, { double_value: 0 }, { int64_value: '9007199254740993' },
    { string_value: 'healthy' }, { distribution_value: distribution },
  ])) });
  await h.flush();
  const output = text(h.tree);
  for (const value of ['false', '0', '9007199254740993', 'healthy', JSON.stringify(distribution)]) assert.ok(output.includes(value), value);
  assert.ok(!output.includes('Sem amostras'));
});

test('empty response displays no-data and partial warnings remain visible', async () => {
  const h = harness('Series', { getCatalogSeries: async () => page([], { warnings: ['Leitura parcial'] }) });
  await h.flush();
  assert.match(text(h.tree), /Leitura parcial/);
  assert.doesNotMatch(text(h.tree), /Sem amostras nesta janela e ambiente/);
});

test('clean empty response displays no-data state', async () => {
  const h = harness('Series', { getCatalogSeries: async () => page() });
  await h.flush();
  assert.match(text(h.tree), /Sem amostras/);
});

test('next sample page retains original end and forwards server token', async () => {
  const calls = [];
  const h = harness('Series', { getCatalogSeries: async (...args) => {
    calls.push(args);
    return page([], { next_page_token: calls.length === 1 ? 'continuation' : '' });
  }});
  await h.flush();
  const next = button(h, /Próxima página.*amostras/);
  assert.ok(next);
  next.props.onClick(); h.render(); await h.flush();
  assert.equal(calls.length, 2);
  assert.equal(calls[1][0], 'DEV'); assert.equal(calls[1][1], '7d');
  assert.equal(calls[1][3].end, '2026-11-18T00:00:00Z');
  assert.equal(calls[1][3].token, 'continuation');
});

test('closing explorer aborts in-flight sample and ignores late response', async () => {
  let resolve, signal;
  const h = harness('Series', { getCatalogSeries: (...args) => {
    signal = args.at(-1); return new Promise(r => { resolve = r; });
  }});
  h.unmount(); assert.equal(signal.aborted, true);
  resolve(page(series([{ bool_value: false }]))); await h.flush();
  assert.doesNotMatch(text(h.tree), /false/);
});

test('catalog next page is requested explicitly and selection is passed to Series', async () => {
  const calls = [];
  const h = harness('Catalog', { getMetricCatalog: async (...args) => {
    calls.push(args);
    return { metrics: [{ type: calls.length === 1 ? 'custom.googleapis.com/first' : 'custom.googleapis.com/second', name: 'Metric', unit: 'ms' }],
      project: 'dev-project', scope: 'project-mapped', warning: null,
      next_page_token: calls.length === 1 ? 'catalog-next' : '' };
  }});
  await h.flush();
  const next = button(h, /Próxima página.*(tipos|catálogo|métricas)/);
  assert.ok(next, 'catalog must offer explicit pagination');
  next.props.onClick(); h.render(); await h.flush();
  assert.equal(calls[1][3], 'catalog-next');
  const input = nodes(h.tree).find(n => n.type === 'input' && n.props['aria-label'] === 'Tipo de métrica GCP');
  input.props.onChange({ target: { value: 'custom.googleapis.com/second' } }); h.render();
  nodes(h.tree).find(n => n.type === 'form').props.onSubmit({ preventDefault() {} }); h.render();
  const child = nodes(h.tree).find(n => typeof n.type === 'function' && n.type.name === 'Series');
  assert.ok(child); assert.equal(child.props.env, 'DEV'); assert.equal(child.props.period, '7d');
  assert.equal(child.props.type, 'custom.googleapis.com/second');
});

test('explorer environment key remounts catalog, isolating selections and cursors', () => {
  const h = harness('MetricExplorer', {}, { env: 'PROD', period: '1h' });
  nodes(h.tree).find(n => n.type === 'details').props.onToggle({ currentTarget: { open: true } }); h.render();
  const child = () => nodes(h.tree).find(n => typeof n.type === 'function' && n.type.name === 'Catalog');
  assert.equal(child().key, 'PROD');
  h.update({ env: 'DEV' });
  assert.equal(child().key, 'DEV');
  assert.equal(child().props.env, 'DEV');
});

for (const [status, message] of [[403, /Acesso negado/], [503, /Falha de conexão/]]) {
  test(`HTTP ${status} has distinct error state and retry clears stale errors`, async () => {
    let calls = 0;
    const h = harness('Series', { getCatalogSeries: () => Promise.resolve().then(() => {
      if (++calls === 1) throw new h.ApiError(status, 'sensitive upstream details');
      return page(series([{ bool_value: false }]));
    }) });
    await h.flush();
    assert.match(text(h.tree), message);
    assert.doesNotMatch(text(h.tree), /sensitive upstream details/);
    button(h, /Tentar novamente/).props.onClick(); h.render(); await h.flush();
    assert.equal(calls, 2);
    assert.doesNotMatch(text(h.tree), message);
    assert.match(text(h.tree), /false/);
  });
}

test('fetch rejection is a connection failure rather than no-data', async () => {
  const h = harness('Series', { getCatalogSeries: async () => { throw new TypeError('fetch failed'); } });
  await h.flush();
  assert.match(text(h.tree), /Falha de conexão/);
  assert.doesNotMatch(text(h.tree), /Sem amostras/);
});

test('series unit and UTC bounds are visible with samples', async () => {
  const h = harness('Series', { getCatalogSeries: async () => page(series([{ double_value: 0 }])) });
  await h.flush();
  assert.match(text(h.tree), /Unidade:\s+ms/);
  assert.match(text(h.tree), /dev-project/);
  assert.match(text(h.tree), /2026-11-11T00:00:00Z/);
  assert.match(text(h.tree), /2026-11-18T00:00:00Z/);
});

test('nonempty series without points still reports no samples', async () => {
  const h = harness('Series', { getCatalogSeries: async () => page(series([])) });
  await h.flush();
  assert.match(text(h.tree), /Sem amostras nesta janela e ambiente/);
});

test('changing active filter discards prior catalog page cursor', async () => {
  const calls = [];
  const h = harness('Catalog', { getMetricCatalog: async (...args) => {
    calls.push(args);
    return { metrics: [], project: 'dev-project', next_page_token: calls.length === 1 ? 'catalog-next' : '' };
  }});
  await h.flush();
  button(h, /Próxima página/).props.onClick(); h.render(); await h.flush();
  assert.equal(calls[1][3], 'catalog-next');
  nodes(h.tree).find(n => n.type === 'input' && n.props.type === 'checkbox').props.onChange({ target: { checked: false } });
  h.render(); await h.flush();
  assert.equal(calls[2][1], false);
  assert.equal(calls[2][3], '');
});
