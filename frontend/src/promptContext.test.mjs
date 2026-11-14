import test from 'node:test';
import assert from 'node:assert/strict';
import { inferPromptContext } from './promptContext.ts';

test('empty and unrelated prompts do not invent a topic or geography', () => {
  assert.deepEqual(inferPromptContext(''), { topic: 'earth', placeQuery: null });
  assert.deepEqual(inferPromptContext('Explain my research'), { topic: 'earth', placeQuery: null });
});

test('topic keywords respect word boundaries and case', () => {
  assert.equal(inferPromptContext('HEAT in India').topic, 'temperature');
  assert.equal(inferPromptContext('Is Chennai getting hotter?').topic, 'temperature');
  assert.equal(inferPromptContext('Rainfall in Chennai').topic, 'rainfall');
  assert.equal(inferPromptContext('Vegetation in Brazil').topic, 'vegetation');
  assert.equal(inferPromptContext('Weather in Tokyo').topic, 'weather');
  assert.equal(inferPromptContext('theatre and terrain').topic, 'earth');
});

test('recognized places react without a preposition or submission', () => {
  assert.equal(inferPromptContext('India').placeQuery, 'India');
  assert.equal(inferPromptContext('TAMIL NADU temperature').placeQuery, 'Tamil Nadu');
  assert.equal(inferPromptContext('Chennai’s warming').placeQuery, 'Chennai');
});

test('continents supply navigation centers without scientific region queries', () => {
  const africa = inferPromptContext('rain in Africa');
  assert.equal(africa.placeQuery, null);
  assert.deepEqual(africa.navigationFocus, { name: 'Africa', lat: 2, lon: 20 });
  assert.equal(inferPromptContext('South America').navigationFocus?.name, 'South America');
  assert.equal(inferPromptContext('Antarctica').navigationFocus?.name, 'Antarctica');
});

test('longer names do not become a contained continent or city', () => {
  assert.equal(inferPromptContext('temperature in South Africa').placeQuery, 'South Africa');
  assert.equal(inferPromptContext('weather in New Delhi').placeQuery, 'New Delhi');
  const ocean = inferPromptContext('rainfall in Indian Ocean since 2001');
  assert.equal(ocean.placeQuery, 'Indian Ocean');
  assert.equal(ocean.navigationFocus, undefined);
});

test('generic place queries exclude dates and trailing weather language', () => {
  assert.equal(inferPromptContext('Rainfall in Coimbatore since 2001').placeQuery, 'Coimbatore');
  assert.equal(inferPromptContext('temperature near São Paulo from 1981 to 2024').placeQuery, 'São Paulo');
  assert.equal(inferPromptContext('Heat at Jaipur today').placeQuery, 'Jaipur');
  assert.equal(inferPromptContext('Show me in Kochi rainfall trends').placeQuery, 'Kochi');
  assert.equal(inferPromptContext('weather from San José over the last 20 years').placeQuery, 'San José');
});

test('topic and date fragments are never sent as place names', () => {
  for (const question of ['changes in rainfall', 'heat in 2001', 'rain in the last decade', 'weather near me', 'data from 1980 to 2024']) {
    assert.equal(inferPromptContext(question).placeQuery, null, question);
  }
});

test('place aliases retain a canonical query and word boundaries', () => {
  assert.equal(inferPromptContext('Rain in Bengaluru').placeQuery, 'Bengaluru');
  assert.equal(inferPromptContext('temperature in USA').placeQuery, 'United States');
  assert.equal(inferPromptContext('Indiana heat').placeQuery, 'Indiana');
  assert.equal(inferPromptContext('Indianapolis heat').placeQuery, null);
});
