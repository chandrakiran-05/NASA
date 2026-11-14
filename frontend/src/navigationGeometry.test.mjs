import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {loadNavigationGeometry, selectNavigationGeometry} from './navigationGeometry.ts';

const countries = JSON.parse(await readFile(new URL('../public/geography/countries.json', import.meta.url), 'utf8'));

test('country boundaries use real aliases and do not partially match state names', () => {
  const india = selectNavigationGeometry(countries, 'India');
  assert.ok(india && ['Polygon','MultiPolygon'].includes(india.type));
  assert.ok(india.coordinates.flat(3).length > 100);
  assert.equal(selectNavigationGeometry(countries, 'Indiana'), null);
  assert.equal(selectNavigationGeometry(countries, 'Tamil Nadu'), null);
  assert.deepEqual(selectNavigationGeometry(countries, 'USA'), selectNavigationGeometry(countries, 'United States'));
  assert.deepEqual(selectNavigationGeometry(countries, 'UK'), selectNavigationGeometry(countries, 'United Kingdom'));
});

test('continent geometry groups actual country polygons without South Africa alias collision', () => {
  const africa = selectNavigationGeometry(countries, 'Africa');
  const southAfrica = selectNavigationGeometry(countries, 'South Africa');
  assert.equal(africa.type, 'MultiPolygon');
  assert.ok(africa.coordinates.length > 40);
  assert.notDeepEqual(africa, southAfrica);
  assert.equal(selectNavigationGeometry(countries, 'unknown location'), null);
});

test('local boundary asset is fetched once and a cancelled consumer does not poison later requests', async () => {
  const original = globalThis.fetch;
  let requests = 0;
  let resolveAsset;
  globalThis.fetch = async () => {
    requests++;
    return await new Promise(resolve => {resolveAsset=resolve;});
  };
  try {
    const controller = new AbortController();
    const cancelled = loadNavigationGeometry('India', controller.signal);
    controller.abort();
    await assert.rejects(cancelled, {name:'AbortError'});
    const second = loadNavigationGeometry('Africa');
    resolveAsset({ok:true,json:async()=>countries});
    assert.equal((await second).type, 'MultiPolygon');
    assert.ok(await loadNavigationGeometry('UK'));
    assert.equal(requests,1);
  } finally {globalThis.fetch=original;}
});
