import test from 'node:test';
import assert from 'node:assert/strict';
import { conversationQuestion } from './chatContext.ts';

test('first chat turn preserves the actual question', () => {
  assert.equal(conversationQuestion('  What is BEAST?  ', []), 'What is BEAST?');
});
test('follow-up retains recent user context without inventing a history API', () => {
  const result=conversationQuestion('What about rainfall?', ['Temperature in Chennai', 'Explain the seasonal cycle']);
  assert.ok(result.includes('Temperature in Chennai'));
  assert.ok(result.endsWith('Answer this latest question: What about rainfall?'));
});
test('the latest question is never truncated to fit prior context', () => {
  const question='x'.repeat(1980);
  assert.equal(conversationQuestion(question,['y'.repeat(2000)]),question);
  const bounded=conversationQuestion('z'.repeat(1500),['y'.repeat(2000)]);
  assert.ok(bounded.length<=2000);
  assert.ok(bounded.endsWith('z'.repeat(1500)));
  assert.throws(()=>conversationQuestion('x'.repeat(2001),[]));
});
