import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import ts from 'typescript';

async function load(file) {
  const source = await readFile(new URL(file, import.meta.url), 'utf8');
  const js = ts.transpileModule(source, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext } }).outputText;
  return import(`data:text/javascript;base64,${Buffer.from(js).toString('base64')}`);
}
const R = await load('./report.ts');
const api = await load('./api.ts');
const fixture = JSON.parse(await readFile(new URL('./fixtures/report.india.json', import.meta.url), 'utf8'));

test('fixture sections are reordered into the story order and numbered', () => {
  const report = R.normalizeReport(fixture);
  assert.deepEqual(report.sections.map(s => s.id), R.SECTION_ORDER);
  const story = R.buildStory(report.sections);
  assert.deepEqual(story.map(s => s.number), [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]);
  assert.equal(story[0].anchor, 'report-answer');
  assert.match(story[0].bridge, /^Why this matters next: /);
  assert.equal(story.at(-1).bridge, null);
  assert.ok(report.fixture, 'fixture flag is carried so the UI can label it');
});

test('orderSections keeps unknown ids after known ones, in order, and drops duplicates', () => {
  const out = R.orderSections([{ id: 'extra_b' }, { id: 'map' }, { id: 'extra_a' }, { id: 'answer' }, { id: 'map' }]);
  assert.deepEqual(out.map(s => s.id), ['answer', 'map', 'extra_b', 'extra_a']);
});

test('normalizeReport tolerates missing and malformed fields', () => {
  const r = R.normalizeReport({ sections: [{ id: 'answer', text: 'Yes.' }, null, { title: 'no id' }], limits: 'x', ai: null });
  assert.equal(r.sections.length, 1);
  assert.equal(r.sections[0].kind, 'text');
  assert.equal(r.sections[0].title, 'answer');
  assert.deepEqual(r.limits, []);
  assert.deepEqual(r.glossary, []);
  assert.deepEqual(R.aiLabel(r.ai), { kind: 'template', text: 'Template text' });
  assert.deepEqual(R.normalizeReport(undefined).sections, []);
});

test('ai label, key number, tables, checks and provenance helpers', () => {
  const report = R.normalizeReport(fixture);
  assert.deepEqual(R.aiLabel(report.ai), { kind: 'ai', text: 'AI-written, number-checked' });
  assert.deepEqual(R.keyNumber(report.sections), { label: "Trend rate (Sen's slope)", value: '+0.15 °C/decade' });
  assert.equal(R.seriesIdOf(report), 's_a29efec836c2211a');
  assert.deepEqual(R.tableData({ rows: [['a', 1], { label: 'b', value: null }, 'junk'] }), { columns: null, rows: [['a', 1], ['b', null]] });
  // 3-column rows with headers; an all-empty column is dropped
  assert.deepEqual(R.tableData({ columns: ['M', 'V', 'Note', 'X'], rows: [['Sen', '+0.15', 'CI', ''], ['Total', '+0.3', '', null]] }),
    { columns: ['M', 'V', 'Note'], rows: [['Sen', '+0.15', 'CI'], ['Total', '+0.3', '']] });
  assert.equal(R.formatCell(null), '—');
  assert.equal(R.formatCell(0.0041234), '0.004123');
  assert.deepEqual(R.checkStatus('warn'), { status: 'warn', word: 'Warning' });
  assert.deepEqual(R.checkStatus('fail'), { status: 'fail', word: 'Fail' });
  assert.equal(R.checkName('ai_review'), 'AI reviewer (advisory)');
  const prov = R.provenanceEntries(report.provenance);
  assert.deepEqual(prov.slice(0, 3).map(([k]) => k), ['dataset short name', 'source api', 'version']);
  assert.ok(prov.some(([k, v]) => k === 'doi' && v === '10.1175/1520-0477(1996)077<0437:TNYRP>2.0.CO;2'));
  assert.deepEqual(R.provenanceEntries('Uploaded'), [['source', 'Uploaded']]);
});

test('series figure keeps nulls as gaps and draws markers by kind', () => {
  const data = { chart: { time: ['2001-01', '2001-02', '2001-03'], observed: [1, null, 3], sen_line: [1, 2, 3], change_probability: [0.1, null, 0.8] },
    markers: [{ date: '2001-03', kind: 'beast_possible' }, { date: '2001-02', kind: 'beast_confirmed' }, { date: '2001-02', kind: 'beast_weak' }],
    recent_window: { start: '2001-02', end: '2001-03' }, units: '°C' };
  const fig = R.seriesFigure(data);
  const observed = fig.traces.find(t => t.name.startsWith('Observed monthly values'));
  assert.equal(observed.yaxis, undefined); // no deseasonalized series → single main panel
  const split = R.seriesFigure({ chart: { time: ['a', 'b'], observed: [1, 2], deseasonalized: [1, 2] } });
  assert.ok(split.split);
  assert.equal(split.traces.find(t => t.name.startsWith('Observed')).yaxis, 'y3');
  assert.deepEqual(observed.y, [1, null, 3]);
  assert.equal(observed.connectgaps, false);
  assert.ok(fig.hasProbability);
  assert.equal(fig.traces.find(t => t.yaxis === 'y2').fill, 'tozeroy');
  const lines = fig.shapes.filter(s => s.type === 'line');
  assert.deepEqual(lines.map(s => s.line.dash), ['solid', 'dash']); // weak dropped, sorted by date
  assert.equal(fig.shapes.filter(s => s.type === 'rect').length, 1);
  assert.equal(fig.units, '°C');
  assert.ok(R.seriesFigure({}).empty);
});

test('heat-map transform: 14x15 fixture grid becomes cells, nulls skipped, colours centred on 0', () => {
  const data = R.normalizeReport(fixture).sections.find(s => s.id === 'map').data;
  const map = R.heatmapCells(data);
  const nulls = data.slope_per_decade.flat().filter(v => v === null).length;
  assert.equal(map.rows, 14);
  assert.equal(map.cols, 15);
  assert.equal(map.cells.length + map.missing, 210);
  assert.equal(map.missing, nulls);
  assert.equal(map.units, '°C per decade');
  assert.deepEqual(map.lonRange, [68.4375, 96.5625]);
  assert.ok(Math.abs(map.latRange[0] - 7.618945) < 1e-6 && Math.abs(map.latRange[1] - 34.28515) < 1e-6);
  const sigCount = data.significant.flat().filter(Boolean).length;
  assert.equal(map.cells.filter(c => c.significant).length, sigCount);
  const c0 = map.cells[0];
  assert.equal(c0.x1 - c0.x0, 1.875);
  assert.equal(R.divergingColor(0, 1), 'rgb(244,241,234)');
  assert.equal(R.divergingColor(1, 1), 'rgb(168,50,31)');
  assert.equal(R.divergingColor(-5, 1), 'rgb(44,95,158)'); // clamped
  assert.equal(R.percent(0.6625), '66.3 %');
});

test('heat-map transform transposes a [lon][lat] grid and rejects bad input', () => {
  const map = R.heatmapCells({ lat: [0, 1], lon: [10, 11, 12], slope_per_decade: [[1, 2], [3, null], [5, 6]], significant: [[true, false], [false, false], [false, true]] });
  assert.equal(map.cells.length, 5);
  const cell = map.cells.find(c => c.lat === 1 && c.lon === 12);
  assert.equal(cell.value, 6);
  assert.equal(cell.significant, true);
  assert.equal(R.heatmapCells({ lat: [], lon: [1], slope_per_decade: [] }), null);
  assert.equal(R.heatmapCells({ lat: [0], lon: [0], slope_per_decade: [[null]] }), null);
  assert.deepEqual(R.cellEdges([30, 20, 10]), [[25, 35], [15, 25], [5, 15]]);
});

test('bars and CSV-upload adapter only reshape backend values', () => {
  const b = R.barsData({ months: ['Jan', 'Feb'], slope_per_decade: [0.2, -0.1], units: '°C per decade' });
  assert.deepEqual(b.y, [0.2, -0.1]);
  assert.notEqual(b.colors[0], b.colors[1]);
  const r = R.reportFromAnalysis({ series_id: 'u_1', label: 'My CSV', units: 'mm', verdict: { plain_language: 'Rising.', rate_per_decade: 1.5, rate_units: 'mm per decade', caveats: ['Short record.'] }, chart: { time: ['2000-01'], raw: [null], sen_line: [1] }, period: { start: '2000-01', end: '2010-12', n_valid: 100 } }, 'my.csv');
  assert.deepEqual(r.sections.map(s => s.id), ['answer', 'data', 'series', 'how_much', 'limits']);
  assert.equal(R.keyNumber(r.sections).value, '1.5 mm per decade');
  assert.deepEqual(r.sections.find(s => s.id === 'series').data.chart.observed, [null]);
  assert.equal(R.aiLabel(r.ai).kind, 'template');
});

test('runReport posts the question then polls the job', async t => {
  const original = globalThis.fetch, calls = [];
  globalThis.fetch = async (url, options) => {
    calls.push({ url, method: options?.method ?? 'GET', body: options?.body });
    const json = (b, status = 200) => new Response(JSON.stringify(b), { status, headers: { 'content-type': 'application/json' } });
    if (url === '/api/report') return json({ job_id: 'r 1', status_url: '/api/jobs/r 1' }, 202);
    if (url === '/api/jobs/r%201?wait=10') return json({ status: 'done', progress: 1, message: 'ok', result: fixture });
    throw new Error(url);
  };
  t.after(() => { globalThis.fetch = original; });
  const progress = [];
  const result = await api.runReport({ question: '  India temperature 2002-2022 ' }, { onProgress: j => progress.push(j.message) });
  assert.equal(result.headline, fixture.headline);
  assert.deepEqual(JSON.parse(calls[0].body), { question: 'India temperature 2002-2022' });
  assert.equal(calls[0].method, 'POST');
  assert.deepEqual(progress, ['ok']);
});

test('tolerates the live backend shapes (string verdict, check text, labels/values bars, base units)', () => {
  const v = R.checksVerdict({ verdict: 'NOT VERIFIED', why: null, detect_plain_language: 'No detectable trend.', court: { plain_language: 'NOT PROVEN.' }, limit: 'Not a cause.' });
  assert.deepEqual(v, { label: 'NOT VERIFIED', lines: ['No detectable trend.', 'NOT PROVEN.'], limit: 'Not a cause.' });
  assert.equal(R.checkText({ check: 'court', status: 'fail', text: 'NOT PROVEN (0 of 8).' }), 'NOT PROVEN (0 of 8).');
  assert.equal(R.checksVerdict({ checks: [] }), null);
  const b = R.barsData({ labels: ['Jan', 'Feb'], values: [0.1, -0.2], ci_low: [-0.1, -0.5], ci_high: [0.3, 0.1], units: '°C' });
  assert.deepEqual(b.y, [0.1, -0.2]);
  assert.deepEqual(b.low, [-0.1, -0.5]);
  assert.equal(b.units, '°C per decade');
  assert.equal(R.heatmapCells({ lat: [0], lon: [0], slope_per_decade: [[0.2]], units: '°C' }).units, '°C per decade');
  const how = [{ id: 'how_much', title: '', kind: 'table', text: '', data: { rows: [['Regression', '+0.13 °C/decade'], ["Trend rate (Sen's slope)", '+0.15 °C/decade']] } }];
  assert.deepEqual(R.keyNumber(how), { label: "Trend rate (Sen's slope)", value: '+0.15 °C/decade' });
});

test('fixture is a real backend run and its wording follows the reviewers', () => {
  const report = R.normalizeReport(fixture);
  const all = report.headline + ' ' + report.sections.map(s => s.text).join(' ');
  assert.doesNotMatch(all, /cannot say the change is real|No detectable trend over|mk_ess_ar1|see why below|Unknown et al/);
  assert.match(report.headline, /cannot yet rule out/);
  assert.equal(report.ai.status, 'done');
  assert.ok(report.sections.every(s => typeof s.aiStatus === 'string' && typeof s.textSource === 'string'));
});

test('section wording notes: pending while writing, AI tag once checked, nothing for template', () => {
  const writing = { used: false, status: 'writing' };
  assert.equal(R.sectionWording({ id: 'answer', aiStatus: 'pending' }, writing).kind, 'pending');
  assert.equal(R.sectionWording({ id: 'answer', aiStatus: 'pending' }, { ...writing, status: 'done' }).kind, '');
  assert.equal(R.sectionWording({ id: 'map', aiStatus: 'rewritten', textSource: 'local_llm' }, writing).kind, 'ai');
  assert.equal(R.sectionWording({ id: 'context', data: { research_status: 'pending' } }, writing).kind, 'pending');
  assert.equal(R.sectionWording({ id: 'data', aiStatus: 'not_rewritten', textSource: 'template' }, writing).kind, '');
  assert.ok(R.isImproving(R.normalizeReport({ sections: [{ id: 'answer' }], ai: { status: 'writing' } })));
  assert.ok(!R.isImproving(R.normalizeReport(fixture)));
});

test('runReport hands the deterministic partial to onPartial before the job is done', async t => {
  const original = globalThis.fetch;
  let polls = 0;
  const partial = { ...fixture, ai: { ...fixture.ai, status: 'writing' } };
  globalThis.fetch = async (url) => {
    const json = (b, status = 200) => new Response(JSON.stringify(b), { status, headers: { 'content-type': 'application/json' } });
    if (url === '/api/report') return json({ job_id: 'r2', status_url: '/api/jobs/r2', partial_url: '/api/report/r2/partial' }, 202);
    if (url === '/api/report/r2/partial') return json({ status: 'processing', progress: 0.6, message: 'AI wording', ready: true, report: partial });
    if (url === '/api/jobs/r2?wait=10') { polls += 1; await new Promise(r => setTimeout(r, 60)); return json(polls < 2 ? { status: 'processing', progress: 0.6, message: 'x' } : { status: 'done', progress: 1, message: 'ok', result: fixture }); }
    throw new Error(url);
  };
  t.after(() => { globalThis.fetch = original; });
  const seen = [];
  const result = await api.runReport({ question: 'India temperature 2002-2022' }, { onPartial: r => seen.push(r.ai.status), partialEveryMs: 10 });
  assert.equal(seen[0], 'writing');
  assert.equal(result.ai.status, 'done');
});
