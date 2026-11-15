import test from 'node:test';
import assert from 'node:assert/strict';
import { initialLive, reduceEvent } from './activeEvents.ts';

const run = (events, vars = []) => events.reduce(reduceEvent, initialLive(vars));
const v = 'merra2_t2m';

test('a candidate walks through checks, BEAST and a verdict with its limit', () => {
  const s = run([
    { seq: 0, type: 'started', variables: [v] },
    { seq: 1, type: 'candidate', variable_id: v, series_id: 's1', state: 'active', plain_language: 'Rising now', rate_per_decade: 0.3, units: 'K' },
    { seq: 2, type: 'check', variable_id: v, check: 'integrity', status: 'pass', plain_language: 'ok' },
    { seq: 3, type: 'check', variable_id: v, check: 'court', status: 'warn' },
    { seq: 4, type: 'beast_started', variable_id: v },
    { seq: 5, type: 'beast', variable_id: v, status: 'agrees', active_since: { date: '2014-02' } },
    { seq: 6, type: 'verdict', variable_id: v, provisional: true, label: 'PROBABLE', limit: 'Not a cause.' },
    { seq: 7, type: 'check', variable_id: v, check: 'court', status: 'fail' },
    { seq: 8, type: 'verdict', variable_id: v, provisional: false, label: 'NOT VERIFIED', limit: 'Not a cause.' },
    { seq: 9, type: 'best_trend', best: null, plain_language: 'None verified.' },
    { seq: 10, type: 'done', plain_language: '0 of 1 verified.' },
  ]);
  const c = s.cards[v];
  assert.deepEqual(s.order, [v]);
  assert.equal(c.series_id, 's1');
  assert.equal(c.stage, 'verdict');
  assert.deepEqual(c.checks.map(x => [x.check, x.status]), [['integrity', 'pass'], ['court', 'fail']]);
  assert.equal(c.beast.active_since.date, '2014-02');
  assert.deepEqual(c.verdict, { label: 'NOT VERIFIED', why: undefined, plain_language: undefined, limit: 'Not a cause.', provisional: false });
  assert.equal(s.best.plain_language, 'None verified.');
  assert.equal(s.done, true);
  assert.equal(s.summary, '0 of 1 verified.');
});

test('replayed events (SSE then long-poll overlap) are ignored by seq', () => {
  const ev = { seq: 0, type: 'check', variable_id: v, check: 'chance', status: 'pass' };
  const once = run([ev]);
  assert.equal(reduceEvent(once, ev), once);
  assert.equal(once.next, 1);
});

test('failed variables and job errors are surfaced, unknown events are harmless', () => {
  const s = run([
    { seq: 0, type: 'failed', variable_id: 'x', message: 'Upstream down' },
    { seq: 1, type: 'deep_review', variable_id: 'x' },
    { seq: 2, type: 'error', message: 'Boom' },
  ]);
  assert.equal(s.cards.x.stage, 'failed');
  assert.equal(s.cards.x.message, 'Upstream down');
  assert.equal(s.error, 'Boom');
  assert.equal(s.done, true);
});
