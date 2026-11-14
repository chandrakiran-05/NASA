import { test } from 'node:test';
import assert from 'node:assert/strict';
import { Vector3 } from 'three';
import { northUpPose } from './globeOrientation.ts';

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
