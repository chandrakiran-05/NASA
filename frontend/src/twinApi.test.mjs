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
