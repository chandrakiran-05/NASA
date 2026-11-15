import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import ts from 'typescript';

// Load the actual TypeScript adapter without a browser or a bundler.
const moduleURL = source => `data:text/javascript;base64,${Buffer.from(source).toString('base64')}`;
const compile = source => ts.transpileModule(source, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext } }).outputText;
const shared = moduleURL(compile(await readFile(new URL('./api.ts', import.meta.url), 'utf8')));
const adapter = compile(await readFile(new URL('./twinApi.ts', import.meta.url), 'utf8')).replace(/from ['"]\.\/api['"]/, `from '${shared}'`);
const { twinApi } = await import(moduleURL(adapter));

test('digital twin adapter uses the branch contract and preserves simulation inputs', async t => {
  const originalFetch = globalThis.fetch;
  const calls = [];
  let responses = [];
  globalThis.fetch = async (url, options) => {
    calls.push({ url, options });
    const response = responses.shift();
    assert.ok(response, `Unexpected request ${url}`);
    return new Response(JSON.stringify(response.body), { status: response.status ?? 200, headers: { 'content-type': 'application/json' } });
  };
  t.after(() => { globalThis.fetch = originalFetch; });
  const id = 't_123456789abc';
  const twin = { id, name: 'Coastal city', variables: [] };

  responses = [{ body: { twins: [twin] } }];
  assert.deepEqual(await twinApi.list(), { twins: [twin] });
  assert.equal(calls.at(-1).url, '/api/twin');

  responses = [{ body: twin }];
  await twinApi.create('  Coastal city  ');
  assert.deepEqual(JSON.parse(calls.at(-1).options.body), { name: 'Coastal city' });

  responses = [{ body: twin }];
  await twinApi.importSeries(id, 's_real');
  assert.equal(calls.at(-1).url, `/api/twin/${id}/import`);
  assert.deepEqual(JSON.parse(calls.at(-1).options.body), { series_id: 's_real' });

  responses = [{ body: twin }];
  const file = new File(['date,temperature\n2001-01,22'], 'research.csv', { type: 'text/csv' });
  await twinApi.uploadCSV(id, file);
  assert.equal(calls.at(-1).url, `/api/twin/${id}/data-csv`);
  assert.equal(calls.at(-1).options.body.get('file').name, 'research.csv');
  assert.equal(calls.at(-1).options.headers['Content-Type'], undefined, 'browser must supply the multipart boundary');

  const scenario = { horizon_years: 30, n_runs: 500, seed: 2026, compare_to_baseline: true, scenario: { temperature: { trend_multiplier: 2, trend_add_per_decade: .2, threshold: { value: 35, direction: 'above' } } } };
  const simulation = { twin_id: id, variables: {}, disclaimer: 'Simulation, not observations' };
  responses = [{ body: simulation }];
  assert.deepEqual(await twinApi.simulate(id, scenario), simulation);
  assert.equal(calls.at(-1).url, `/api/twin/${id}/simulate`);
  assert.deepEqual(JSON.parse(calls.at(-1).options.body), scenario);
  assert.ok(!calls.some(call => call.url.includes('/insights')), 'never substitute historical forecast for DigiTwin');

  const before = calls.length;
  assert.throws(() => twinApi.get('../etc'), /valid digital twin/);
  assert.throws(() => twinApi.simulate(id, { ...scenario, horizon_years: 101 }), /1 to 100/);
  assert.throws(() => twinApi.simulate(id, { ...scenario, scenario: { temperature: { trend_multiplier: Infinity } } }), /finite numbers/);
  assert.equal(calls.length, before, 'invalid inputs must not issue requests');

  responses = [{ status: 404, body: { detail: 'Not Found' } }];
  await assert.rejects(twinApi.list(), error => error.status === 404);

  const controller = new AbortController();
  globalThis.fetch = async (_url, options) => {
    assert.equal(options.signal.aborted, true);
    throw new DOMException('Aborted', 'AbortError');
  };
  controller.abort();
  await assert.rejects(twinApi.list(controller.signal), error => error.name === 'AbortError');
});

test('digital twin engineer tools send the backend shapes and validate before requesting', async t => {
  const originalFetch = globalThis.fetch;
  const calls = [];
  globalThis.fetch = async (url, options) => {
    calls.push({ url, options });
    return new Response(JSON.stringify({ ok: true }), { status: 200, headers: { 'content-type': 'application/json' } });
  };
  t.after(() => { globalThis.fetch = originalFetch; });
  const id = 't_123456789abc';
  const last = () => ({ url: calls.at(-1).url, method: calls.at(-1).options.method, body: calls.at(-1).options.body && JSON.parse(calls.at(-1).options.body) });
  const scenario = { temp: { trend_multiplier: 2, fit_since_year: 'auto', threshold: { value: 30, direction: 'above' } } };

  await twinApi.backtest(id, { holdout_years: 10, n_runs: 300, seed: 2026 });
  assert.deepEqual(last(), { url: `/api/twin/${id}/backtest`, method: 'POST', body: { holdout_years: 10, n_runs: 300, seed: 2026 } });

  const conditions = [{ variable: 'temp', value: 30, direction: 'above' }, { variable: 'rain', value: 1, direction: 'below' }];
  await twinApi.compound(id, { conditions, scenario, horizon_years: 30, n_runs: 500, seed: 2026 });
  assert.deepEqual(last(), { url: `/api/twin/${id}/compound`, method: 'POST', body: { conditions, scenario, horizon_years: 30, n_runs: 500, seed: 2026 } });

  const scenarios = { low: { temp: { trend_multiplier: .5 } }, mid: { temp: {} }, high: { temp: { trend_multiplier: 2 } } };
  await twinApi.scenarios(id, { scenarios, horizon_years: 20 });
  assert.deepEqual(last(), { url: `/api/twin/${id}/scenarios`, method: 'POST', body: { scenarios, horizon_years: 20 } });

  await twinApi.sensitivity(id, { target: 'temp', scenario, n_runs: 300 });
  assert.deepEqual(last(), { url: `/api/twin/${id}/sensitivity`, method: 'POST', body: { target: 'temp', scenario, n_runs: 300 } });

  const data = { source: 'chatbot team', variables: [{ name: 'temp', units: 'degC', time: ['2001-01', '2001-02'], value: [1, null] }] };
  await twinApi.uploadData(id, data);
  assert.deepEqual(last(), { url: `/api/twin/${id}/data`, method: 'POST', body: data });

  await twinApi.importSeries(id, ' s_real ', undefined, ' My copy ');
  assert.deepEqual(last().body, { series_id: 's_real', name: 'My copy' });

  await twinApi.remove(id);
  assert.deepEqual(last(), { url: `/api/twin/${id}`, method: 'DELETE', body: undefined });
  await twinApi.removeVariable(id, 'sea level/m');
  assert.deepEqual(last(), { url: `/api/twin/${id}/variables/sea%20level%2Fm`, method: 'DELETE', body: undefined });

  const before = calls.length;
  assert.throws(() => twinApi.backtest(id, { holdout_years: 1 }), /2 to 40/);
  assert.throws(() => twinApi.compound(id, { conditions: [] }), /1 to 5/);
  assert.throws(() => twinApi.compound(id, { conditions: [{ variable: 'temp', value: NaN, direction: 'above' }] }), /finite level/);
  assert.throws(() => twinApi.scenarios(id, { scenarios: {} }), /1 to 6/);
  assert.throws(() => twinApi.scenarios(id, { scenarios: Object.fromEntries('abcdefg'.split('').map(k => [k, {}])) }), /1 to 6/);
  assert.throws(() => twinApi.sensitivity(id, { target: 'temp', scenario: { temp: { trend_multiplier: 2 } } }), /threshold/);
  assert.throws(() => twinApi.simulate(id, { horizon_years: 30, scenario: { temp: { fit_since_year: 1999.5 } } }), /whole year/);
  assert.throws(() => twinApi.simulate(id, { horizon_years: 30, n_runs: 10, scenario: {} }), /50 to 2,000/);
  assert.throws(() => twinApi.uploadData(id, { variables: [] }), /1 to 50/);
  assert.throws(() => twinApi.uploadData(id, { variables: [{ name: 'x', time: ['2001-01'], value: [] }] }), /same length/);
  assert.throws(() => twinApi.uploadData(id, { variables: [{ name: 'x', time: ['2001-01'], value: ['1'] }] }), /numbers or null/);
  assert.throws(() => twinApi.importSeries(id, '  '), /series id/);
  assert.throws(() => twinApi.removeVariable(id, ''), /1 to 80/);
  assert.throws(() => twinApi.remove('t_bad'), /valid digital twin/);
  assert.equal(calls.length, before, 'invalid inputs must not issue requests');
});
