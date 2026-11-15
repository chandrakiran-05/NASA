import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import ts from 'typescript';

const moduleURL = source => `data:text/javascript;base64,${Buffer.from(source).toString('base64')}`;
const compile = source => ts.transpileModule(source, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext } }).outputText;
const shared = moduleURL(compile(await readFile(new URL('./api.ts', import.meta.url), 'utf8')));
const adapter = compile(await readFile(new URL('./discoveryApi.ts', import.meta.url), 'utf8')).replace(/from ['"]\.\/api['"]/, `from '${shared}'`);
const d = await import(moduleURL(adapter));

const json = (body, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } });
const sse = chunks => new Response(new ReadableStream({ start(c) { for (const x of chunks) c.enqueue(new TextEncoder().encode(x)); c.close(); } }), { headers: { 'content-type': 'text/event-stream' } });
function mockFetch(t, handler) {
  const original = globalThis.fetch, calls = [];
  globalThis.fetch = async (url, options) => { calls.push({ url, method: options?.method ?? 'GET', body: options?.body }); return handler(url, options); };
  t.after(() => { globalThis.fetch = original; });
  return calls;
}

test('DigiTwin prompts: explicit scenario knobs stay in the scenario tools, everything else opens Discovery', () => {
  for (const q of ['What if warming in Chennai doubled?', 'rainfall +20% in Kerala', 'add a shock in 2030', 'warming 2x faster',
    'if global temp rises 5 c overall what would be the change in trend for chennai and california',
    'suppose rainfall drops 20 percent in Kerala by 2050'])
    assert.equal(d.twinPromptRoute(q), 'scenario', q);
  for (const q of ['find unreported changes in South Asia monsoon', 'what if the Amazon keeps drying',
    'vegetation in the Sahel 2001-2024', 'is snow changing in the Alps?'])
    assert.equal(d.twinPromptRoute(q), 'discovery', q);
});

test('applyDiscoveryEvent turns server events into progress lines and findings without computing numbers', () => {
  let s = d.emptyProgress();
  const events = [
    { seq: 0, type: 'started', plain_language: 'Scanning the Sahel.' },
    { seq: 1, type: 'sweep', status: 'failed', plain_language: 'The grid could not be read.' },
    { seq: 2, type: 'candidate', place: 'Sahel', variable_id: 'merra2_t2m' },
    { seq: 3, type: 'step', step: 'check' },
    { seq: 4, type: 'candidate_rejected', reason: 'No detectable trend.' },
    { seq: 5, type: 'checking_literature', place: 'Sahel' },
    { seq: 6, type: 'finding', finding: { finding_id: 'f1', title: 'T' } },
    { seq: 7, type: 'done', plain_language: 'Tested 2 places.' },
  ];
  for (const ev of events) s = d.applyDiscoveryEvent(s, ev);
  assert.equal(s.done, true);
  assert.equal(s.error, null);
  assert.deepEqual(s.findings.map(f => f.finding_id), ['f1']);
  assert.deepEqual(s.lines.map(l => l.kind), ['info', 'warn', 'info', 'skip', 'ok']);   // 'done' adds no duplicate summary line
  assert.ok(!s.lines.some(l => l.text === 'Tested 2 places.'));
  assert.equal(s.lines[0].text, 'Scanning the Sahel.');
  assert.match(s.lines[3].text, /No detectable trend/);
  const err = d.applyDiscoveryEvent(d.emptyProgress(), { seq: 0, type: 'error', message: 'boom' });
  assert.equal(err.error, 'boom');
  assert.equal(err.done, true);
});

test('runDiscovery: POST /api/discovery, live SSE events, then the job result; notebook URL is encoded', async t => {
  const calls = mockFetch(t, url => {
    if (url === '/api/discovery') return json({ job_id: 'j_1', reused: false }, 202);
    if (url.startsWith('/api/discovery/j_1/stream')) return sse(['data: {"seq":0,"type":"started"}\n\n', 'data: {"seq":1,"type":"done"}\n\n']);
    if (url.startsWith('/api/jobs/j_1')) return json({ status: 'done', progress: 1, message: 'done', result: { findings: [] } });
    throw new Error(url);
  });
  const seen = [];
  const out = await d.runDiscovery({ prompt: 'heat in the Sahel' }, { onEvent: e => seen.push(e.type) });
  assert.deepEqual(seen, ['started', 'done']);
  assert.equal(out.jobId, 'j_1');
  assert.deepEqual(out.result, { findings: [] });
  assert.equal(calls[0].method, 'POST');
  assert.deepEqual(JSON.parse(calls[0].body), { prompt: 'heat in the Sahel' });
  assert.equal(d.notebookURL('j_1', 'f 1'), '/api/discovery/j_1/notebook/f%201');
});

test('startDiscovery surfaces error.message', async t => {
  mockFetch(t, () => json({ error: { code: 'invalid_request', message: 'Nothing to scan for this request' } }, 422));
  await assert.rejects(d.startDiscovery({}), e => e.message === 'Nothing to scan for this request' && e.status === 422);
});

test('period shift notice and not-kept cards reach the progress state; list texts are never empty', () => {
  const notice = { asked: [1700, 2025], used: [1979, 2025], plain_language: 'You asked for 1700-2025, but no instrument or satellite record ...' };
  let s = d.applyDiscoveryEvent(d.emptyProgress(), { seq: 0, type: 'started', plain_language: 'Scanning Africa.', plan: { period_notice: notice } });
  assert.deepEqual(s.notice, notice);
  const card = { candidate_id: 'c1', label: 'NOT VERIFIED', rate: { per_decade: -1.2, units: 'mm/month', plain_language: '-1.2 mm/month per decade' },
    figure: { time: ['1981-01', '1981-02'], observed: [1, 2] }, reason: 'No detectable trend.' };
  s = d.applyDiscoveryEvent(s, { seq: 1, type: 'tested', card });
  assert.equal(s.tested[0].rate.per_decade, -1.2);
  assert.equal(s.tested[0].figure.time.length, 2);
  assert.deepEqual(d.listTexts([{ text: 'NOAA ERDDAP grid: 404' }, { text: '  ' }, { source: 'GDELT', reason: 'TimeoutError' }, {}, { place: 'Africa', status: 'not kept' }]),
    ['NOAA ERDDAP grid: 404', 'GDELT: TimeoutError', 'Africa: not kept']);
  assert.deepEqual(d.listTexts(undefined), []);
});
