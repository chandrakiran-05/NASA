import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import ts from 'typescript';

const source = await readFile(new URL('./api.ts', import.meta.url), 'utf8');
const js = ts.transpileModule(source, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext } }).outputText;
const api = await import(`data:text/javascript;base64,${Buffer.from(js).toString('base64')}`);

const json = (body, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } });
const sse = chunks => new Response(new ReadableStream({ start(c) { for (const x of chunks) c.enqueue(new TextEncoder().encode(x)); c.close(); } }), { headers: { 'content-type': 'text/event-stream' } });
function mockFetch(t, handler) {
  const original = globalThis.fetch, calls = [];
  globalThis.fetch = async (url, options) => { calls.push({ url, method: options?.method ?? 'GET', body: options?.body }); return handler(url, options); };
  t.after(() => { globalThis.fetch = original; });
  return calls;
}

test('parseSSE keeps partial blocks and skips keep-alives', () => {
  const { events, rest } = api.parseSSE('id: 0\nevent: started\ndata: {"seq":0,"type":"started"}\n\n: keep-alive\n\ndata: {"seq":1');
  assert.deepEqual(events, [{ seq: 0, type: 'started' }]);
  assert.equal(rest, 'data: {"seq":1');
});

test('runActiveTrends: POST, SSE events split across chunks, then the final job result', async t => {
  const calls = mockFetch(t, url => {
    if (url === '/api/active-trends') return json({ job_id: 'j_1', reused: false, variables: ['u_1'], skipped: [] }, 202);
    if (url.startsWith('/api/active-trends/j_1/stream')) return sse(['data: {"seq":0,"type":"started"}\n\ndata: {"seq":1,', '"type":"verdict","variable_id":"u_1","label":"VERIFIED"}\n\ndata: {"seq":2,"type":"done"}\n\n']);
    if (url.startsWith('/api/jobs/j_1')) return json({ status: 'done', progress: 1, message: 'done', result: { trends: [] } });
    throw new Error(url);
  });
  const seen = [];
  const result = await api.runActiveTrends({ series_ids: ['u_1'] }, { onEvent: e => seen.push(e.type) });
  assert.deepEqual(seen, ['started', 'verdict', 'done']);
  assert.deepEqual(result, { trends: [] });
  assert.equal(calls[0].method, 'POST');
  assert.deepEqual(JSON.parse(calls[0].body), { series_ids: ['u_1'] });
});

test('followActiveTrends falls back to long-poll from the last seen seq', async t => {
  const calls = mockFetch(t, url => {
    if (url.includes('/stream')) return sse(['data: {"seq":0,"type":"started"}\n\n']); // stream ends early
    if (url.includes('/events?after=1')) return json({ events: [{ seq: 0, type: 'started' }, { seq: 1, type: 'check' }, { seq: 2, type: 'done' }], next: 3, done: true });
    throw new Error(url);
  });
  const seen = [];
  await api.followActiveTrends('j_2', e => seen.push(e.seq));
  assert.deepEqual(seen, [0, 1, 2]);
  assert.ok(calls.some(c => c.url === '/api/active-trends/j_2/events?after=1&wait=25'));
});

test('errors carry error.message; criteria/view/methods hit their endpoints', async t => {
  const calls = mockFetch(t, url => url === '/api/active-trends'
    ? json({ error: { code: 'invalid_request', message: 'No variable can be trend-tested' } }, 422)
    : json({ criteria: [], papers: [], chart: { time: [] }, markers: [] }));
  await assert.rejects(api.startActiveTrends({}), e => e.message === 'No variable can be trend-tested' && e.status === 422);
  await api.getCriteria(); await api.getView('u 1'); await api.getResearchMethods();
  assert.deepEqual(calls.slice(1).map(c => c.url), ['/api/criteria', '/api/view/u%201', '/api/research/methods']);
  assert.equal(api.cardURL('u_1'), '/api/view/u_1/card.svg');
});
