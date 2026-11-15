import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import ts from 'typescript';

const moduleURL = source => `data:text/javascript;base64,${Buffer.from(source).toString('base64')}`;
const compile = source => ts.transpileModule(source, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext } }).outputText;
const shared = moduleURL(compile(await readFile(new URL('./api.ts', import.meta.url), 'utf8')));
const adapter = compile(await readFile(new URL('./replicationApi.ts', import.meta.url), 'utf8')).replace(/from ['"]\.\/api['"]/, `from '${shared}'`);
const r = await import(moduleURL(adapter));

test('formatting helpers only format API numbers', () => {
  assert.equal(r.fmtP(0.0018), 'p = 0.0018');
  assert.equal(r.fmtP(0.78), 'p = 0.780');
  assert.equal(r.fmtP(0.00001), 'p < 0.001');
  assert.equal(r.fmtP(null), 'p = n/a');
  assert.equal(r.fmtSlope(-0.0043), '−0.0043');
  assert.equal(r.fmtSlope(0.0006), '+0.0006');
  assert.equal(r.badgeClass('Consistent'), 'is-consistent');
  assert.equal(r.badgeClass('Not enough data'), 'is-nodata');
});

test('outlinePath breaks rings with nulls', () => {
  const sq = [[0, 0], [1, 0], [1, 1], [0, 0]];
  const p = r.outlinePath([{ geometry: { type: 'Polygon', coordinates: [sq] } }, { geometry: { type: 'MultiPolygon', coordinates: [[sq], [sq]] } }]);
  assert.equal(p.x.length, 15);
  assert.equal(p.x.filter(v => v === null).length, 3);
});

test('runReplication starts the job and polls the shared jobs endpoint', async t => {
  const original = globalThis.fetch, calls = [];
  globalThis.fetch = async (url, options) => {
    calls.push({ url, method: options?.method ?? 'GET', body: options?.body });
    const body = calls.length === 1 ? { job_id: 'j_0123456789abcdef' } : { status: 'done', progress: 1, message: 'done', result: { rivers: [], summary: 's' } };
    return new Response(JSON.stringify(body), { status: calls.length === 1 ? 202 : 200, headers: { 'content-type': 'application/json' } });
  };
  t.after(() => { globalThis.fetch = original; });
  const out = await r.runReplication({ rivers: ['po'] });
  assert.equal(out.summary, 's');
  assert.equal(calls[0].url, '/api/replication/seawifs');
  assert.equal(calls[0].method, 'POST');
  assert.deepEqual(JSON.parse(calls[0].body), { rivers: ['po'], refresh: false });
  assert.match(calls[1].url, /^\/api\/jobs\/j_0123456789abcdef\?wait=10$/);
});
