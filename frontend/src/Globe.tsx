import { useEffect, useRef, useState } from "react";
import * as THREE from "three";
import { boundaryRibbon, focusedPose, northUpPose } from "./globeOrientation";
import type { GlobeGeometry } from "./globeOrientation";
export type { GlobeGeometry } from "./globeOrientation";

export type GlobeFocus = { lat: number; lon: number };
export type GlobeTopic =
  "earth" | "temperature" | "rainfall" | "vegetation" | "weather";
type GlobeProps = {
  focus?: GlobeFocus | null;
  paused?: boolean;
  className?: string;
  twin?: boolean;
  topic?: GlobeTopic;
  geometry?: GlobeGeometry | null;
};
const accents: Record<GlobeTopic, string> = {
  earth: "#4c9dff",
  temperature: "#d98d66",
  rainfall: "#7aacc2",
  vegetation: "#a4bd86",
  weather: "#a0b8bd",
};

/** Illustrative satellite imagery. The grid and topic colours are navigation cues, not measured data. */
export default function Globe({
  focus = null,
  paused = false,
  className = "",
  twin = false,
  topic = "earth",
  geometry = null,
}: GlobeProps) {
  const container = useRef<HTMLDivElement>(null);
  const props = useRef({ focus, paused, twin, topic, geometry });
  const update = useRef<(() => void) | null>(null);
  const [unavailable, setUnavailable] = useState(false);
  props.current = { focus, paused, twin, topic, geometry };

  useEffect(() => {
    const host = container.current;
    if (!host) return;
    let renderer: THREE.WebGLRenderer;
    try {
      renderer = new THREE.WebGLRenderer({
        antialias: true,
        alpha: true,
        powerPreference: "low-power",
      });
    } catch {
      setUnavailable(true);
      return;
    }
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    renderer.setClearColor(0, 0);
    const canvas = renderer.domElement;
    canvas.setAttribute("aria-hidden", "true");
    canvas.style.cssText =
      "display:block;width:100%;height:100%;pointer-events:none;";
    host.appendChild(canvas);
    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(36, 1, 0.1, 40);
    const presentation = new THREE.Group();
    presentation.position.y = 0.16;
    const earth = new THREE.Group();
    // A real geographic camera target: Africa, Europe and the Indian Ocean
    // share the opening view instead of starting on an anonymous ocean face.
    const initialPose = northUpPose(20, 25);
    earth.quaternion.copy(initialPose);
    presentation.add(earth);
    scene.add(presentation);
    const sphere = new THREE.SphereGeometry(1, 64, 32);
    const textures: THREE.Texture[] = [];
    let disposed = false;
    let frame = 0;
    let timer: ReturnType<typeof setTimeout> | null = null;
    let visible = false;
    let width = 1;
    let height = 1;
    let dpr = 1;
    let qualityCap = 1.25;
    let dirty = true;
    let rendering = false;
    let lastRender = 0;
    let renderCount = 0;
    let totalDrawCalls = 0;
    let slowFrames = 0;
    let dragging = false;
    let rotationPaused = false;
    let activePointer: number | null = null;
    let startX = 0;
    let startY = 0;
    let pointerX = 0;
    let pointerY = 0;
    let gesture: "pending" | "rotate" | "scroll" = "pending";
    let focused = false;
    let aimPending = false;
    let previousFocus = "";
    let previousTopic = "";
    let previousTwin: boolean | undefined;
    let targetRoll = 0;
    let modeTransition: { elapsed: number; fromRoll: number; fromDistance: number; tint: THREE.Color } | null = null;
    let previousGeometry: GlobeGeometry | null | undefined;
    let targetDistance = 4.05;
    camera.position.z = targetDistance;
    const targetPose = initialPose.clone();
    const targetTint = new THREE.Color(accents.earth);
    const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
    const targetLight = new THREE.Vector3(-3.6, 2.8, 5);
    const forward = new THREE.Vector3(0, 0, 1);
    const turn = new THREE.Quaternion();
    const axis = new THREE.Vector3();
    const point = new THREE.Vector3();

    function cancelScheduled() {
      if (frame) cancelAnimationFrame(frame);
      if (timer !== null) clearTimeout(timer);
      frame = 0;
      timer = null;
    }
    function canRender() {
      return !disposed && visible && !document.hidden;
    }
    function invalidate() {
      dirty = true;
      if (!canRender() || rendering || frame || timer !== null) return;
      frame = requestAnimationFrame(render);
    }
    function load(name: string, color = false) {
      const texture = new THREE.TextureLoader().load(
        `/textures/${name}`,
        () => {
          if (disposed) texture.dispose();
          else invalidate();
        },
        undefined,
        () => {
          if (!disposed && name === "earth-day.jpg") setUnavailable(true);
        },
      );
      if (color) texture.colorSpace = THREE.SRGBColorSpace;
      texture.anisotropy = Math.min(
        2,
        renderer.capabilities.getMaxAnisotropy(),
      );
      textures.push(texture);
      return texture;
    }
    const surface = new THREE.MeshPhongMaterial({
      map: load("earth-day.jpg", true),
      specularMap: load("earth-specular.jpg"),
      specular: new THREE.Color("#547981"),
      shininess: 8,
      color: new THREE.Color("#fffdf2"),
    });
    earth.add(new THREE.Mesh(sphere, surface));
    const cloudMaterial = new THREE.MeshPhongMaterial({
      map: load("earth-clouds.png", true),
      transparent: true,
      opacity: 0.65,
      depthWrite: false,
      shininess: 0,
    });
    const clouds = new THREE.Mesh(sphere, cloudMaterial);
    clouds.scale.setScalar(1.005);
    earth.add(clouds);
    scene.add(new THREE.AmbientLight("#d7e3d7", 0.86));
    const sunlight = new THREE.DirectionalLight("#fff4df", 2.35);
    sunlight.position.copy(targetLight);
    scene.add(sunlight);
    const rimLight = new THREE.DirectionalLight("#bad7cd", 0.48);
    rimLight.position.set(3, 1, -3);
    scene.add(rimLight);
    const atmosphereMaterial = new THREE.ShaderMaterial({
      transparent: true,
      depthWrite: false,
      side: THREE.BackSide,
      blending: THREE.AdditiveBlending,
      uniforms: { tint: { value: targetTint.clone() } },
      vertexShader: `varying vec3 vNormal; varying vec3 vPosition;
        void main(){vec4 p=modelViewMatrix*vec4(position,1.0);vPosition=p.xyz;
        vNormal=normalize(normalMatrix*normal);gl_Position=projectionMatrix*p;}`,
      fragmentShader: `uniform vec3 tint; varying vec3 vNormal; varying vec3 vPosition;
        void main(){float rim=pow(1.0-abs(dot(normalize(vNormal),normalize(-vPosition))),3.7);
        gl_FragColor=vec4(tint,rim*0.48);}`,
    });
    const atmosphere = new THREE.Mesh(
      new THREE.SphereGeometry(1.025, 48, 24),
      atmosphereMaterial,
    );
    presentation.add(atmosphere);

    // One geographic grid draw call. Surface depth hides the far-side lines.
    const gridVertices: number[] = [];
    function geographic(lat: number, lon: number) {
      const phi = THREE.MathUtils.degToRad(lat);
      const theta = THREE.MathUtils.degToRad(lon);
      return [
        Math.cos(phi) * Math.cos(theta) * 1.009,
        Math.sin(phi) * 1.009,
        -Math.cos(phi) * Math.sin(theta) * 1.009,
      ];
    }
    for (let lon = -180; lon < 180; lon += 30) {
      for (let i = 0; i < 48; i++)
        gridVertices.push(
          ...geographic(-90 + (i * 180) / 48, lon),
          ...geographic(-90 + ((i + 1) * 180) / 48, lon),
        );
    }
    for (let lat = -60; lat <= 60; lat += 30) {
      for (let i = 0; i < 96; i++)
        gridVertices.push(
          ...geographic(lat, -180 + (i * 360) / 96),
          ...geographic(lat, -180 + ((i + 1) * 360) / 96),
        );
    }
    const gridGeometry = new THREE.BufferGeometry();
    gridGeometry.setAttribute(
      "position",
      new THREE.Float32BufferAttribute(gridVertices, 3),
    );
    const gridMaterial = new THREE.LineBasicMaterial({
      color: "#d3ddd0",
      transparent: true,
      opacity: 0.14,
      depthWrite: false,
    });
    earth.add(new THREE.LineSegments(gridGeometry, gridMaterial));
    const pinGeometry = new THREE.SphereGeometry(0.009, 10, 8);
    const pinMaterial = new THREE.MeshBasicMaterial({ color: "#f3e8ba" });
    const pin = new THREE.Mesh(pinGeometry, pinMaterial);
    pin.visible = false;
    earth.add(pin);
    const haloGeometry = new THREE.RingGeometry(0.019, 0.022, 32);
    const haloMaterial = new THREE.MeshBasicMaterial({
      color: "#d3e9b3",
      transparent: true,
      opacity: 0.85,
      side: THREE.DoubleSide,
      depthWrite: false,
    });
    const halo = new THREE.Mesh(haloGeometry, haloMaterial);
    halo.visible = false;
    earth.add(halo);
    const outlineGeometry = new THREE.BufferGeometry();
    const glowGeometry = new THREE.BufferGeometry();
    const outlineMaterial = new THREE.MeshBasicMaterial({ color: "#8bc9ff", transparent: true, opacity: 0.98, depthWrite: false, side: THREE.DoubleSide });
    const glowMaterial = new THREE.MeshBasicMaterial({ color: "#398bff", transparent: true, opacity: 0.28, depthWrite: false, blending: THREE.AdditiveBlending, side: THREE.DoubleSide });
    const outline = new THREE.Mesh(outlineGeometry, outlineMaterial);
    const outlineGlow = new THREE.Mesh(glowGeometry, glowMaterial);
    outline.visible = outlineGlow.visible = false;
    earth.add(outlineGlow, outline);

    function resize() {
      const rect = host!.getBoundingClientRect();
      width = Math.max(1, rect.width);
      height = Math.max(1, rect.height);
      // Physical pixel ceiling matters more than CSS dimensions on a large retina display.
      dpr = Math.min(
        window.devicePixelRatio || 1,
        qualityCap,
        Math.sqrt(1_600_000 / (width * height)),
      );
      renderer.setPixelRatio(dpr);
      renderer.setSize(width, height, false);
      camera.aspect = width / height;
      camera.zoom = Math.min(1, camera.aspect);
      camera.updateProjectionMatrix();
      host!.dataset.dpr = dpr.toFixed(2);
      invalidate();
    }
    function syncProps() {
      const current = props.current;
      if (current.twin !== previousTwin) {
        const firstView = previousTwin === undefined;
        previousTwin = current.twin;
        targetRoll = current.twin ? Math.PI : 0;
        if (firstView || reducedMotion.matches) presentation.rotation.z = targetRoll;
        else modeTransition = {
          elapsed: 0,
          fromRoll: presentation.rotation.z,
          fromDistance: camera.position.z,
          tint: (atmosphereMaterial.uniforms.tint.value as THREE.Color).clone(),
        };
      }
      const validFocus =
        current.focus &&
        Number.isFinite(current.focus.lat) &&
        Number.isFinite(current.focus.lon);
      const key = validFocus
        ? `${current.focus!.lat},${current.focus!.lon}`
        : "";
      if (key !== previousFocus) {
        previousFocus = key;
        focused = Boolean(validFocus);
        pin.visible = halo.visible = focused;
        if (focused) {
          const coords = geographic(
            THREE.MathUtils.clamp(current.focus!.lat, -90, 90),
            current.focus!.lon,
          );
          point.set(...(coords as [number, number, number])).normalize();
          targetPose.copy(focusedPose(current.focus!.lat, current.focus!.lon, targetRoll));
          pin.position.copy(point).multiplyScalar(1.016);
          halo.position.copy(point).multiplyScalar(1.017);
          halo.quaternion.setFromUnitVectors(forward, point);
          aimPending = true;
        }
        targetDistance = focused ? 3.85 : 4.05;
      }
      if (current.geometry !== previousGeometry) {
        previousGeometry = current.geometry;
        const core = boundaryRibbon(current.geometry, 0.0014);
        const glow = boundaryRibbon(current.geometry, 0.006);
        outlineGeometry.dispose();
        glowGeometry.dispose();
        outlineGeometry.setAttribute("position", new THREE.Float32BufferAttribute(core, 3));
        glowGeometry.setAttribute("position", new THREE.Float32BufferAttribute(glow, 3));
        outlineGeometry.computeBoundingSphere();
        glowGeometry.computeBoundingSphere();
        outline.visible = outlineGlow.visible = focused && core.length > 0;
        host!.dataset.boundaryVertices = String(core.length / 3);
      }
      outline.visible = outlineGlow.visible = focused && Boolean(outlineGeometry.getAttribute("position")?.count);
      outlineMaterial.color.set(current.twin ? "#ffe1cc" : "#8bc9ff");
      glowMaterial.color.set(current.twin ? "#ffb697" : "#398bff");
      pinMaterial.color.set(current.twin ? "#ffe1cc" : "#d2ecff");
      haloMaterial.color.set(current.twin ? "#ffb697" : "#6ab6ff");
      if (previousTopic !== `${current.twin}-${current.topic}`) {
        previousTopic = `${current.twin}-${current.topic}`;
        targetTint.set(current.twin ? "#d6a7a4" : accents[current.topic]);
      }
      invalidate();
    }
    update.current = syncProps;

    function transitioning() {
      const tint = atmosphereMaterial.uniforms.tint.value as THREE.Color;
      return (
        modeTransition !== null ||
        (aimPending && earth.quaternion.angleTo(targetPose) > 0.001) ||
        Math.abs(presentation.rotation.z - targetRoll) > 0.0005 ||
        Math.abs(camera.position.z - targetDistance) > 0.0005 ||
        Math.abs(tint.r - targetTint.r) +
          Math.abs(tint.g - targetTint.g) +
          Math.abs(tint.b - targetTint.b) >
          0.002
      );
    }
    function render(now: number) {
      frame = 0;
      if (!canRender()) return;
      rendering = true;
      const dt = Math.min(
        lastRender ? (now - lastRender) / 1000 : 1 / 60,
        0.06,
      );
      const wasTransitioning = transitioning();
      if ((wasTransitioning || dragging) && lastRender && now - lastRender > 38)
        slowFrames++;
      else slowFrames = Math.max(0, slowFrames - 1);
      if (slowFrames > 18 && qualityCap > 1) {
        qualityCap = 1;
        slowFrames = 0;
        resize();
      }
      lastRender = now;
      const ease = reducedMotion.matches ? 1 : 1 - Math.exp(-dt * 8);
      if (aimPending && !modeTransition) {
        earth.quaternion.slerp(targetPose, ease);
        if (earth.quaternion.angleTo(targetPose) < 0.001) {
          earth.quaternion.copy(targetPose);
          aimPending = false;
        }
      }
      if (modeTransition && !reducedMotion.matches) {
        modeTransition.elapsed += dt;
        const progress = Math.min(1, modeTransition.elapsed / 2.8);
        const rollProgress = THREE.MathUtils.smootherstep(progress, 0.12, 1);
        presentation.rotation.z = THREE.MathUtils.lerp(modeTransition.fromRoll, targetRoll, rollProgress);
        const distance = THREE.MathUtils.lerp(modeTransition.fromDistance, targetDistance, progress);
        camera.position.z = distance - Math.sin(Math.PI * progress) * 0.62;
        (atmosphereMaterial.uniforms.tint.value as THREE.Color).copy(modeTransition.tint).lerp(targetTint, THREE.MathUtils.smoothstep(progress, 0, 1));
        host!.dataset.worldTransition = progress.toFixed(3);
        if (progress === 1) modeTransition = null;
      } else {
        modeTransition = null;
        presentation.rotation.z = THREE.MathUtils.lerp(presentation.rotation.z, targetRoll, ease);
        camera.position.z = THREE.MathUtils.lerp(camera.position.z, targetDistance, ease);
        (atmosphereMaterial.uniforms.tint.value as THREE.Color).lerp(targetTint, ease);
      }
      host!.dataset.worldTurn = presentation.rotation.y.toFixed(3);
      host!.dataset.worldRoll = presentation.rotation.z.toFixed(3);
      host!.dataset.cameraDistance = camera.position.z.toFixed(3);
      const markerPosition = pin.position.clone().applyQuaternion(earth.quaternion).applyQuaternion(presentation.quaternion).add(presentation.position).project(camera);
      host!.dataset.focusScreen = `${((markerPosition.x + 1) / 2).toFixed(3)},${((1 - markerPosition.y) / 2).toFixed(3)}`;
      const moving = transitioning();
      const idle =
        !props.current.paused &&
        !rotationPaused &&
        !reducedMotion.matches &&
        !focused &&
        !dragging &&
        !moving;
      if (idle) {
        turn.setFromAxisAngle(axis.set(0, 1, 0), dt * 0.043);
        earth.quaternion.multiply(turn);
        clouds.rotation.y += dt * 0.004;
      }
      host!.dataset.renderState = dragging
        ? "dragging"
        : moving
          ? "transition"
          : idle
            ? "idle"
            : props.current.paused || rotationPaused
              ? "paused"
              : "settled";
      if (dirty || moving || wasTransitioning || idle || dragging) {
        renderer.render(scene, camera);
        renderCount++;
        totalDrawCalls += renderer.info.render.calls;
        host!.dataset.renderCount = String(renderCount);
        host!.dataset.drawCalls = String(totalDrawCalls);
        dirty = false;
      }
      rendering = false;
      if (moving) frame = requestAnimationFrame(render);
      else if (idle)
        timer = setTimeout(
          () => {
            timer = null;
            if (canRender()) frame = requestAnimationFrame(render);
          },
          Math.max(0, 1000 / 30 - (performance.now() - now) - 4),
        );
      // Gestures schedule their own frames. Static, paused and focused states stop here.
    }

    function rotate(dx: number, dy: number) {
      aimPending = false;
      const roll = presentation.rotation.z;
      turn.setFromAxisAngle(axis.set(Math.sin(roll), Math.cos(roll), 0), dx);
      earth.quaternion.premultiply(turn);
      turn.setFromAxisAngle(axis.set(Math.cos(roll), -Math.sin(roll), 0), dy);
      earth.quaternion.premultiply(turn);
      invalidate();
    }
    function hitGlobe(event: PointerEvent) {
      const rect = host!.getBoundingClientRect();
      const radius = Math.min(rect.height * 0.43, rect.width * 0.49);
      return (
        Math.hypot(
          event.clientX - rect.left - rect.width / 2,
          event.clientY - rect.top - rect.height / 2,
        ) <= radius
      );
    }
    function pointerDown(event: PointerEvent) {
      if (!event.isPrimary || event.button !== 0 || !hitGlobe(event)) return;
      activePointer = event.pointerId;
      startX = pointerX = event.clientX;
      startY = pointerY = event.clientY;
      gesture = event.pointerType === "touch" ? "pending" : "rotate";
      dragging = gesture === "rotate";
      host!.setPointerCapture(event.pointerId);
      host!.style.cursor = "grabbing";
      host!.focus({ preventScroll: true });
    }
    function pointerMove(event: PointerEvent) {
      if (event.pointerId !== activePointer) return;
      if (gesture === "pending") {
        const dx = event.clientX - startX;
        const dy = event.clientY - startY;
        if (Math.hypot(dx, dy) < 6) return;
        gesture = Math.abs(dx) > Math.abs(dy) ? "rotate" : "scroll";
        dragging = gesture === "rotate";
      }
      if (gesture !== "rotate") return;
      rotate(
        (event.clientX - pointerX) * 0.005,
        (event.clientY - pointerY) * 0.005,
      );
      pointerX = event.clientX;
      pointerY = event.clientY;
    }
    function pointerUp(event: PointerEvent) {
      if (event.pointerId !== activePointer) return;
      if (host!.hasPointerCapture(event.pointerId))
        host!.releasePointerCapture(event.pointerId);
      activePointer = null;
      dragging = false;
      host!.style.cursor = "grab";
      invalidate();
    }
    function keyDown(event: KeyboardEvent) {
      if (event.key === " ") {
        rotationPaused = !rotationPaused;
        invalidate();
        event.preventDefault();
        return;
      }
      const step = event.shiftKey ? 0.25 : 0.1;
      if (event.key === "ArrowLeft") rotate(-step, 0);
      else if (event.key === "ArrowRight") rotate(step, 0);
      else if (event.key === "ArrowUp") rotate(0, -step);
      else if (event.key === "ArrowDown") rotate(0, step);
      else if (event.key === "Home") {
        targetPose.copy(initialPose);
        aimPending = true;
        invalidate();
      } else return;
      event.preventDefault();
    }
    function visibilityChange() {
      cancelScheduled();
      lastRender = 0;
      if (document.hidden) host!.dataset.renderState = "hidden";
      else invalidate();
    }
    function motionChange() {
      invalidate();
    }
    const resizeObserver = new ResizeObserver(resize);
    resizeObserver.observe(host);
    const intersectionObserver = new IntersectionObserver(
      ([entry]) => {
        visible = entry.isIntersecting;
        cancelScheduled();
        lastRender = 0;
        if (visible) invalidate();
        else host.dataset.renderState = "offscreen";
      },
      { threshold: 0 },
    );
    intersectionObserver.observe(host);
    host.addEventListener("pointerdown", pointerDown);
    host.addEventListener("pointermove", pointerMove);
    host.addEventListener("pointerup", pointerUp);
    host.addEventListener("pointercancel", pointerUp);
    host.addEventListener("keydown", keyDown);
    document.addEventListener("visibilitychange", visibilityChange);
    reducedMotion.addEventListener("change", motionChange);
    resize();
    syncProps();
    return () => {
      disposed = true;
      update.current = null;
      cancelScheduled();
      resizeObserver.disconnect();
      intersectionObserver.disconnect();
      host.removeEventListener("pointerdown", pointerDown);
      host.removeEventListener("pointermove", pointerMove);
      host.removeEventListener("pointerup", pointerUp);
      host.removeEventListener("pointercancel", pointerUp);
      host.removeEventListener("keydown", keyDown);
      document.removeEventListener("visibilitychange", visibilityChange);
      reducedMotion.removeEventListener("change", motionChange);
      textures.forEach((texture) => texture.dispose());
      [
        sphere,
        atmosphere.geometry,
        gridGeometry,
        outlineGeometry,
        glowGeometry,
        pinGeometry,
        haloGeometry,
      ].forEach((geometry) => geometry.dispose());
      [
        surface,
        cloudMaterial,
        atmosphereMaterial,
        gridMaterial,
        outlineMaterial,
        glowMaterial,
        pinMaterial,
        haloMaterial,
      ].forEach((material) => material.dispose());
      renderer.dispose();
      renderer.forceContextLoss();
      canvas.remove();
    };
  }, []);

  useEffect(() => {
    update.current?.();
  }, [focus?.lat, focus?.lon, paused, twin, topic, geometry]);

  return (
    <div
      className={`globe-scene ${className}`}
      ref={container}
      role="group"
      tabIndex={0}
      aria-roledescription="interactive globe"
      aria-label={`${twin ? "Scenario" : "Observed"} Earth. Drag to rotate, or use arrow keys. Space pauses automatic rotation. Home resets the view. ${topic} colour is an illustrative topic accent, not measured data.`}
      style={{
        position: "relative",
        width: "100%",
        height: "100%",
        minHeight: 240,
        touchAction: "pan-y",
        cursor: "grab",
      }}
    >
      {unavailable && (
        <div
          aria-hidden="true"
          style={{
            position: "absolute",
            width: "min(72%, 65vh)",
            aspectRatio: "1",
            left: "50%",
            top: "50%",
            transform: `translate(-50%,-50%) rotate(${twin ? 180 : 0}deg)`,
            borderRadius: "50%",
            background: "url(/textures/earth-day.jpg) center / cover",
            boxShadow: `inset -50px -20px 70px #02070fe0, 0 0 28px ${twin ? "#d8a0af44" : "#227caf40"}`,
            pointerEvents: "none",
          }}
        />
      )}
    </div>
  );
}
