import { Euler, MathUtils, Quaternion, Vector3 } from "three";

export type GlobeGeometry = {
  type: string;
  coordinates?: unknown;
  bbox?: number[];
};

/** Center a longitude and latitude while keeping geographic north above it. */
export function northUpPose(latitude: number, longitude: number): Quaternion {
  return new Quaternion().setFromEuler(new Euler(
    MathUtils.degToRad(MathUtils.clamp(latitude, -90, 90)),
    -MathUtils.degToRad(longitude) - Math.PI / 2,
    0,
    "XYZ",
  ));
}

/** A new location must face the camera even inside the rolled scenario parent. */
export function focusedPose(latitude: number, longitude: number, parentRoll: number): Quaternion {
  const parent = new Quaternion().setFromAxisAngle(new Vector3(0, 0, 1), parentRoll);
  return northUpPose(latitude, longitude).premultiply(parent.invert());
}

/** Surface ribbons follow supplied geographic boundaries, never estimated shapes. */
export function boundaryRibbon(geometry: GlobeGeometry | null | undefined, halfWidth: number): number[] {
  if (geometry?.type === "BBox" && geometry.bbox?.length === 4 && geometry.bbox.every(Number.isFinite)) {
    const [w,s,e,n] = geometry.bbox;
    return boundaryRibbon({type:"Polygon",coordinates:[[[w,s],[e,s],[e,n],[w,n],[w,s]]]},halfWidth);
  }
  if (!geometry?.coordinates || !Array.isArray(geometry.coordinates)) return [];
  const coordinates = geometry.coordinates as number[][][][];
  const rings: number[][][] = geometry.type === "Polygon"
    ? coordinates as unknown as number[][][]
    : geometry.type === "MultiPolygon" ? coordinates.flat() : [];
  const vertices: number[] = [];
  const geographic = (coordinate: number[]) => {
    const lat = MathUtils.degToRad(coordinate[1]);
    const lon = MathUtils.degToRad(coordinate[0]);
    return new Vector3(Math.cos(lat) * Math.cos(lon), Math.sin(lat), -Math.cos(lat) * Math.sin(lon));
  };
  for (const ring of rings) {
    if (!Array.isArray(ring)) continue;
    for (let index = 1; index < ring.length && vertices.length < 360_000; index++) {
      const start = ring[index - 1], end = ring[index];
      if (!Array.isArray(start) || !Array.isArray(end) || ![start[0], start[1], end[0], end[1]].every(Number.isFinite)) continue;
      const a = geographic(start), b = geographic(end);
      const steps = Math.max(1, Math.ceil(a.angleTo(b) / MathUtils.degToRad(3)));
      for (let step = 0; step < steps; step++) {
        const p = a.clone().lerp(b, step / steps).normalize().multiplyScalar(1.014);
        const q = a.clone().lerp(b, (step + 1) / steps).normalize().multiplyScalar(1.014);
        const side = new Vector3().crossVectors(q.clone().sub(p), p.clone().add(q)).normalize().multiplyScalar(halfWidth);
        const p1 = p.clone().add(side), p2 = p.clone().sub(side);
        const q1 = q.clone().add(side), q2 = q.clone().sub(side);
        for (const vertex of [p1, p2, q1, q1, p2, q2]) vertices.push(vertex.x, vertex.y, vertex.z);
      }
    }
  }
  return vertices;
}
