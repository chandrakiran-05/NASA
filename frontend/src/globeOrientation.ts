import { Euler, MathUtils, Quaternion } from "three";

/** Center a longitude and latitude while keeping geographic north above it. */
export function northUpPose(latitude: number, longitude: number): Quaternion {
  return new Quaternion().setFromEuler(new Euler(
    MathUtils.degToRad(MathUtils.clamp(latitude, -90, 90)),
    -MathUtils.degToRad(longitude) - Math.PI / 2,
    0,
    "XYZ",
  ));
}
