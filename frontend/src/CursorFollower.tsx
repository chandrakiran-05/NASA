import { useEffect, useRef } from "react";
import "./cursor.css";

const INTERACTIVE = "a, button, summary, label, select, [role=button], .rep-table tbody tr";
const TEXT = "input, textarea, [contenteditable=true]";

/** A soft ring that trails the pointer and grows over things you can press. The native cursor stays
 * visible (accessibility); the ring is decoration only, and is off for touch and reduced motion. */
export default function CursorFollower() {
  const ring = useRef<HTMLDivElement>(null);
  const dot = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const fine = matchMedia("(pointer: fine)").matches;
    const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (!fine || reduce || !ring.current || !dot.current) return;
    const r = ring.current, d = dot.current;
    let x = -100, y = -100, rx = -100, ry = -100, frame = 0;
    const tick = () => {
      rx += (x - rx) * 0.18;              // spring-like trailing; settles in ~10 frames
      ry += (y - ry) * 0.18;
      r.style.transform = `translate3d(${rx}px,${ry}px,0)`;
      frame = Math.abs(x - rx) + Math.abs(y - ry) > 0.2 ? requestAnimationFrame(tick) : 0;
    };
    const move = (e: PointerEvent) => {
      if (e.pointerType !== "mouse") return;
      x = e.clientX; y = e.clientY;
      d.style.transform = `translate3d(${x}px,${y}px,0)`;
      document.documentElement.classList.add("has-cursor");
      const t = e.target as Element | null;
      r.dataset.mode = t?.closest(TEXT) ? "text" : t?.closest(INTERACTIVE) ? "press" : "";
      if (!frame) frame = requestAnimationFrame(tick);
    };
    const down = () => r.classList.add("is-down");
    const up = () => r.classList.remove("is-down");
    const leave = () => document.documentElement.classList.remove("has-cursor");
    window.addEventListener("pointermove", move, { passive: true });
    window.addEventListener("pointerdown", down);
    window.addEventListener("pointerup", up);
    document.addEventListener("pointerleave", leave);
    return () => {
      cancelAnimationFrame(frame);
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerdown", down);
      window.removeEventListener("pointerup", up);
      document.removeEventListener("pointerleave", leave);
      document.documentElement.classList.remove("has-cursor");
    };
  }, []);
  return <>
    <div ref={ring} className="cursor-ring" aria-hidden="true"><i /></div>
    <div ref={dot} className="cursor-dot" aria-hidden="true" />
  </>;
}
