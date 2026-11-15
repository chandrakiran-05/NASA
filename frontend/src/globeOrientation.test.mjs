import { test } from 'node:test';
import assert from 'node:assert/strict';
import { Quaternion, Vector3 } from 'three';
import { boundaryRibbon, focusedPose, northUpPose } from './globeOrientation.ts';

for (const [name, lat, lon] of [['equator',0,0],['India',20.6,78.9],['Chennai',13.08,80.27],['Africa',2,21],['Sydney',-33.87,151.2],['date line',45,180]]) {
  test(`${name}: location faces the camera and north stays above it`, () => {
    const phi=lat*Math.PI/180, theta=lon*Math.PI/180;
    const pose=northUpPose(lat,lon);
    const point=new Vector3(Math.cos(phi)*Math.cos(theta),Math.sin(phi),-Math.cos(phi)*Math.sin(theta)).applyQuaternion(pose);
    assert.ok(point.distanceTo(new Vector3(0,0,1))<1e-10);
    const north=new Vector3(-Math.sin(phi)*Math.cos(theta),Math.cos(phi),Math.sin(phi)*Math.sin(theta)).applyQuaternion(pose);
    assert.ok(north.distanceTo(new Vector3(0,1,0))<1e-10);
  });
}

for (const roll of [0, Math.PI / 2, Math.PI]) {
  test(`focused India remains front and north-up with a parent roll of ${roll}`, () => {
    const latitude = 20.6 * Math.PI / 180, longitude = 78.9 * Math.PI / 180;
    const presentation = new Quaternion().setFromAxisAngle(new Vector3(0, 0, 1), roll);
    const pose = focusedPose(20.6, 78.9, roll);
    const point = new Vector3(Math.cos(latitude)*Math.cos(longitude), Math.sin(latitude), -Math.cos(latitude)*Math.sin(longitude));
    point.applyQuaternion(pose).applyQuaternion(presentation);
    assert.ok(point.distanceTo(new Vector3(0, 0, 1)) < 1e-10);
    const north = new Vector3(-Math.sin(latitude)*Math.cos(longitude), Math.cos(latitude), Math.sin(latitude)*Math.sin(longitude));
    north.applyQuaternion(pose).applyQuaternion(presentation);
    assert.ok(north.distanceTo(new Vector3(0, 1, 0)) < 1e-10);
  });
}

test('a supplied polygon boundary is tessellated on the Earth surface and a point invents no border', () => {
  const vertices = boundaryRibbon({type:'Polygon', coordinates:[[[179,10],[-179,10],[-179,12],[179,10]]]}, .0014);
  assert.ok(vertices.length > 0);
  assert.equal(vertices.length % 18, 0);
  for (let i=0; i<vertices.length; i+=3) {
    const point = new Vector3(...vertices.slice(i,i+3));
    assert.ok(point.length()>1.013 && point.length()<1.015);
    assert.ok(point.x < -.9, 'date-line boundary stays at the date line');
  }
  assert.deepEqual(boundaryRibbon({type:'Point',coordinates:[78,20]}, .0014), []);
  assert.deepEqual(boundaryRibbon({type:'Polygon',coordinates:null}, .0014), []);
  assert.ok(boundaryRibbon({type:'BBox',bbox:[80,12.8,80.5,13.4]},.0014).length>0,'backend city search extent is outlined as its labeled approximate area');
});
