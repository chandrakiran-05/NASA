import { lazy, Suspense, useEffect, useMemo, useRef, useState } from "react";
import { flushSync } from "react-dom";
import {
  ArrowUp,
  ArrowUpRight,
  ArrowDown,
  ArrowLeftRight,
  FlaskConical,
  Globe2,
  Menu,
  MapPin,
  Waves,
  X,
  Upload,
  ChevronDown,
} from "lucide-react";
import { api } from "./api";
import AirLLM from "./AirLLM";
import ChatPage from "./ChatPage";
import DiscoveryChat from "./DiscoveryChat";
import DiscoveryHow from "./DiscoveryHow";
import { seriesIdOf, type Report } from "./report";
import { loadNavigationGeometry, navigationStateFocus } from "./navigationGeometry";
import type { GlobeGeometry } from "./Globe";
import AtlasStory from "./AtlasStory";
import PaperReplication from "./PaperReplication";
import CursorFollower from "./CursorFollower";
import TwinLab from "./TwinLab";
import type { TwinLabHandle } from "./TwinLab";
import { inferPromptContext } from "./promptContext";
const Globe = lazy(() => import("./Globe"));
type Data = Record<string, any>;
type Focus = { lat: number; lon: number };
function pageFromPath(path: string) {
  if (path.startsWith("/airllm")) return "airllm";
  if (path.startsWith("/chat")) return "chat";
  if (path.startsWith("/digitwin/discover")) return "discover";
  return "earth";
}
function geometryCenter(g: Data): Focus | null {
  if (g.type === "Point")
    return { lon: g.coordinates[0], lat: g.coordinates[1] };
  if (g.bbox)
    return {
      lon: (g.bbox[0] + g.bbox[2]) / 2,
      lat: (g.bbox[1] + g.bbox[3]) / 2,
    };
  return null;
}
export default function App() {
  const [page, setPage] = useState(pageFromPath(location.pathname));
  const [twin, setTwin] = useState(location.pathname.startsWith("/digitwin"));
  const [observedQuestion, setObservedQuestion] = useState(""),
    [twinQuestion, setTwinQuestion] = useState("");
  const question = twin ? twinQuestion : observedQuestion;
  const setQuestion = twin ? setTwinQuestion : setObservedQuestion;
  const [chatLaunch, setChatLaunch] = useState<{id:number; question:string}|null>(null);
  const [discoveryLaunch, setDiscoveryLaunch] = useState<{id:number; question:string}|null>(null);
  const [motionPaused, setMotionPaused] = useState(false);
  const [menu, setMenu] = useState(false),
    [changing, setChanging] = useState(false);
  const [observedFocus, setObservedFocus] = useState<Focus | null>(null),
    [scenarioFocus, setScenarioFocus] = useState<Focus | null>(null);
  const [observedPlace, setObservedPlace] = useState(""),
    [scenarioPlace, setScenarioPlace] = useState("");
  const [observedNote, setObservedNote] = useState(""),
    [scenarioNote, setScenarioNote] = useState("");
  const locationNote = twin ? scenarioNote : observedNote,
    setLocationNote = twin ? setScenarioNote : setObservedNote;
  const focus = twin ? scenarioFocus : observedFocus,
    setFocus = twin ? setScenarioFocus : setObservedFocus;
  const place = twin ? scenarioPlace : observedPlace,
    setPlace = twin ? setScenarioPlace : setObservedPlace;
  const [observedGeometry, setObservedGeometry] = useState<GlobeGeometry|null>(null);
  const [scenarioGeometry, setScenarioGeometry] = useState<GlobeGeometry|null>(null);
  const geometry = twin ? scenarioGeometry : observedGeometry;
  const setGeometry = twin ? setScenarioGeometry : setObservedGeometry;
  const currentWorld = useRef({ twin, page });
  currentWorld.current = { twin, page };
  const [report, setReport] = useState<Report | null>(null);
  const [twinBusy, setTwinBusy] = useState(false);
  const [connection, setConnection] = useState("Checking connection");
  const twinLab = useRef<TwinLabHandle>(null),
    transitionTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const cursor = useRef<HTMLDivElement>(null),
    pointerFrame = useRef(0);
  const context = useMemo(() => inferPromptContext(question), [question]);
  useEffect(() => {
    let frame = 0;
    const surface = document.querySelector<HTMLElement>(".experience");
    const motion = matchMedia("(prefers-reduced-motion: reduce)");
    function syncScroll() {
      if (frame) return;
      frame = requestAnimationFrame(() => {
        surface?.style.setProperty("--earth-scroll", `${page === "earth" && !motion.matches && !motionPaused ? -Math.min(scrollY, 1200) * .055 : 0}px`);
        frame = 0;
      });
    }
    syncScroll();
    window.addEventListener("scroll", syncScroll, {passive:true});
    motion.addEventListener("change", syncScroll);
    return () => {window.removeEventListener("scroll", syncScroll);motion.removeEventListener("change", syncScroll);cancelAnimationFrame(frame);};
  }, [page, motionPaused]);
  const selectedSeriesId = seriesIdOf(report);
  useEffect(() => {
    document.title =
      page === "chat" ? "Earth conversations - Living Atlas" : page === "discover" ? "Discovery mode — DigiTwin" : page === "airllm"
        ? "Local AI — Earth System Trend Detective"
        : twin
          ? "DigiTwin — A possible Earth"
          : "Earth System Trend Detective";
  }, [page, twin]);
  useEffect(() => {
    const pop = () => {
      setPage(pageFromPath(location.pathname));
      setTwin(location.pathname.startsWith("/digitwin"));
      setMenu(false);
    };
    window.addEventListener("popstate", pop);
    return () => window.removeEventListener("popstate", pop);
  }, []);
  useEffect(() => {
    const controller = new AbortController();
    api
      .status(controller.signal)
      .then((s) =>
        setConnection(
          s.available ? "Local AI connected" : "Local reasoning ready",
        ),
      )
      .catch(() => {
        if (!controller.signal.aborted) setConnection("Backend offline");
      });
    return () => {
      controller.abort();
      if (transitionTimer.current) clearTimeout(transitionTimer.current);
      cancelAnimationFrame(pointerFrame.current);
    };
  }, []);
  useEffect(() => {
    if (!question.trim()) {
      setLocationNote("");
      setFocus(null); setPlace(""); setGeometry(null);
      return;
    }
    const controller = new AbortController();
    let stale = false;
    const timer = setTimeout(async () => {
      const navigationFocus = context.navigationFocus || navigationStateFocus(context.placeQuery || "");
      if (navigationFocus) {
        setFocus(navigationFocus);
        setPlace(navigationFocus.name);
        setLocationNote("Navigation view · not a data boundary");
        try {
          const outline = await loadNavigationGeometry(navigationFocus.name, controller.signal);
          if (!stale) setGeometry(outline);
        } catch { if (!stale) setGeometry(null); }
        return;
      }
      if (!context.placeQuery) return;
      try {
        const regions = await api.regions(
          context.placeQuery,
          controller.signal,
        );
        if (stale) return;
        const region = regions.results?.[0];
        if (region) {
          const target = geometryCenter(region.geometry);
          if (target) {
            setFocus(target);
            setPlace(region.name);
            setGeometry(region.geometry);
            setLocationNote(
              region.approximate
                ? "Approximate region · confirm in your investigation"
                : "Location resolved by the backend",
            );
            try {
              const outline = await loadNavigationGeometry(region.name, controller.signal);
              if (!stale && outline) setGeometry(outline);
            } catch { /* The resolved marker remains usable without boundary assets. */ }
          }
        }
      } catch {
        /* Typing remains responsive when the backend is unavailable. */
      }
    }, 450);
    return () => {
      stale = true;
      controller.abort();
      clearTimeout(timer);
    };
  }, [question, context, twin]);
  function changeWorld(next: boolean) {
    if (next === twin) return;
    if (next && !scenarioFocus) {
      setScenarioFocus(observedFocus);
      setScenarioPlace(observedPlace);
      setScenarioGeometry(observedGeometry);
      if (!twinQuestion) setTwinQuestion(observedQuestion);
    }
    setTwin(next);
    setMenu(false);
    setChanging(true);
    history.pushState({}, "", next ? "/digitwin" : "/");
    if (transitionTimer.current) clearTimeout(transitionTimer.current);
    transitionTimer.current = setTimeout(() => setChanging(false), 2900);
    window.scrollTo({ top: 0, behavior: "auto" });
  }
  function openAir() {
    history.pushState({}, "", "/airllm");
    setPage("airllm");
    setMenu(false);
    window.scrollTo(0, 0);
  }
  function returnEarth() {
    history.pushState({}, "", twin ? "/digitwin" : "/");
    setPage("earth");
    window.scrollTo(0, 0);
  }
  function openChat() {
    history.pushState({}, "", "/chat");
    setChatLaunch(null);
    setPage("chat");
    window.scrollTo({ top: 0, behavior: "instant" });
  }
  /** The hero question opens the chat page; each answer there is the full evidence report. */
  function submit(value = question) {
    const q = value.trim();
    if (!q || (twin && twinBusy)) return;
    if (!twin) setObservedQuestion(q);
    // Observed world: the evidence chat. DigiTwin: what-if / discovery questions open Discovery mode.
    const enter = twin ? () => {
      history.pushState({}, "", "/digitwin/discover");
      setDiscoveryLaunch({ id: Date.now(), question: q });
      setPage("discover");
      window.scrollTo({ top: 0, behavior: "instant" });
    } : () => {
      history.pushState({}, "", "/chat");
      setChatLaunch({ id: Date.now(), question: q });
      setPage("chat");
      window.scrollTo({ top: 0, behavior: "instant" });
    };
    if (document.startViewTransition && !matchMedia("(prefers-reduced-motion: reduce)").matches)
      void document.startViewTransition(() => flushSync(enter)).finished.catch(() => {});
    else enter();
  }
  function showReport(next: Report) {
    setReport(next);
    const target = next.plan.geometry ? geometryCenter(next.plan.geometry) : null;
    if (target) setObservedFocus(target);
    if (next.plan.region_name) setObservedPlace(next.plan.region_name);
  }
  function pointerMove(e: React.PointerEvent<HTMLDivElement>) {
    if (
      e.pointerType === "touch" ||
      matchMedia("(prefers-reduced-motion: reduce)").matches ||
      pointerFrame.current
    )
      return;
    const x = e.clientX,
      y = e.clientY;
    pointerFrame.current = requestAnimationFrame(() => {
      if (cursor.current)
        cursor.current.style.transform = `translate3d(${x - 180}px,${y - 180}px,0)`;
      pointerFrame.current = 0;
    });
  }
  const topicLabel = {
    earth: "Earth systems",
    temperature: "Temperature",
    rainfall: "Rainfall",
    vegetation: "Vegetation",
    weather: "Weather patterns",
  }[context.topic];
  return (
    <div
      className={`experience ${changing ? "is-changing" : ""}`}
      data-motion-paused={motionPaused}
      data-world={twin ? "twin" : "observed"}
      data-topic={context.topic}
      onPointerMove={pointerMove}
    >
      <div ref={cursor} className="cursor-light" aria-hidden="true" />
      <CursorFollower />
      <div className="ambient-field" aria-hidden="true"><i/><i/></div>
      <ChatPage active={page === "chat"} launch={chatLaunch} onExit={returnEarth} onReport={showReport}/>
      {(page === "discover" || discoveryLaunch) && <DiscoveryChat active={page === "discover"} launch={discoveryLaunch} onExit={returnEarth}/>}
      {page === "airllm" ? (
        <AirLLM onBack={returnEarth} />
      ) : page !== "chat" && page !== "discover" ? (
        <>
          <a className="skip-link" href="#main">
            Skip to content
          </a>
          <header className="site-header">
            <a
              className="identity"
              href="/"
              onClick={(e) => {
                e.preventDefault();
                changeWorld(false);
              }}
              aria-label="Earth System Trend Detective home"
            >
              <img src="/nasa-logo.svg" width={45} height={39} alt="NASA" />
              <span className="brand-divider" />
              <span>
                EARTH SYSTEM
                <br />
                <b>TREND DETECTIVE</b>
              </span>
            </a>
            <nav
              className={menu ? "main-nav is-open" : "main-nav"}
              aria-label="Main navigation"
            >
              <a
                href={twin ? "#twin-how" : "#features"}
                onClick={() => setMenu(false)}
              >
                Features
              </a>
              <button className="nav-air" onClick={openAir}>
                Try AirLLM <ArrowUpRight size={14} />
              </button>
            </nav>
            <button
              className="menu-toggle"
              aria-label="Toggle navigation"
              aria-expanded={menu}
              onClick={() => setMenu(!menu)}
            >
              {menu ? <X /> : <Menu />}
            </button>
          </header>
        </>
      ) : null}
      <main
        id="main"
        className={page !== "earth" ? "earth-hidden" : ""}
        aria-hidden={page !== "earth"}
        inert={page !== "earth"}
      >
        <section className="hero" aria-labelledby="hero-title">
          <div className="world-light" aria-hidden="true" />
          <div className="hero-intro">
            <span className="world-state">
              <i />
              {twin ? "SIMULATED WORLD" : "THE OBSERVED WORLD"}
            </span>
            <p>
              {twin
                ? "A scenario is a question. Make the assumptions visible."
                : "Investigate regional trends in NASA data. See what changes, and whether the evidence holds."}
            </p>
          </div>
          <div className="hero-title-layer">
            <h1 id="hero-title"><span>{twin ? "Another Earth" : "Earth"}</span><span className="hero-subtitle">{twin ? "a future to explore." : "in perspective."}</span></h1>
          </div>
          <svg className="atlas-orbit" viewBox="0 0 1000 500" aria-hidden="true"><ellipse cx="500" cy="250" rx="475" ry="180" transform="rotate(-12 500 250)"/></svg>
          <div className="hero-globe">
            <Suspense
              fallback={<div className="globe-loading">Preparing Earth…</div>}
            >
              <Globe
                focus={focus}
                geometry={geometry}
                paused={motionPaused}
                twin={twin}
                topic={context.topic}
              />
            </Suspense>
          </div>
          <div className="globe-side left">
            <span className="detail-rule" />
            <span>{place || "A PLACE TO BEGIN"}</span>
            <small>
              {place
                ? locationNote || "Selected location"
                : "Drag Earth to change your view"}
            </small>
          </div>
          <div className="globe-side right">
            <span>{topicLabel}</span>
            <small>
              {twin
                ? "Scenario view · simulated"
                : "Visible imagery · topic cue"}
            </small>
            <span className="detail-rule" />
          </div>
          <div className="command-dock">
            {place && <div className="prompt-location" role="status"><MapPin size={14}/><strong>{place}</strong><span>{geometry?.type === "BBox" ? "Approximate area" : geometry?.type === "Point" ? "Selected point" : "In view"}</span></div>}
            <label className={place ? "sr-only" : "command-label"} htmlFor="earth-question">
              {twin
                ? "Your what-if question"
                : "What is changing in your part of Earth?"}
            </label>
            <form
              className="command-glass"
              style={{viewTransitionName:page === "earth" ? "earth-composer" : undefined}}
              onSubmit={(e) => {
                e.preventDefault();
                void submit();
              }}
            >
              <span className="command-mode" aria-label={twin ? "DigiTwin scenario" : "Earth conversation"}>
                {twin ? <FlaskConical size={18} strokeWidth={1.5}/> : <Globe2 size={18} strokeWidth={1.5}/>}
              </span>
              <input
                id="earth-question"
                className="command-input"
                value={question}
                onChange={(e) => setQuestion(e.target.value)}
                maxLength={2000}
                autoComplete="off"
                placeholder={
                  twin
                    ? "Find unreported changes in the South Asia monsoon"
                    : "Ask about temperature in India…"
                }
              />
              <button
                className="command-send"
                type="submit"
                disabled={!question.trim() || (twin && twinBusy)}
                aria-label={twin ? "Start a Discovery run or a DigiTwin scenario" : "Build the evidence report"}
              >
                <ArrowUp size={21} />
              </button>
            </form>
            <div className="dock-under">
              <span className="connection">
                <i />
                {twin
                  ? <>Discovery mode · <a href="#twin-discovery">how it works</a></>
                  : connection}
              </span>
              <button
                className="world-switch"
                onClick={() => changeWorld(!twin)}
              >
                {twin ? <Globe2 size={13} /> : <FlaskConical size={13} />}{" "}
                {twin ? "Return to observed Earth" : "Enter DigiTwin"}
                <ArrowLeftRight size={12} />
              </button>
            </div>
          </div>
          <div className="hero-bottom">
            <span>NASA SPACE APPS 2026</span>
            <a href={twin ? "#twin-how" : "#features"}>
              {twin ? "HOW THIS WORLD WORKS" : "FOLLOW THE EVIDENCE"}
              <ArrowDown size={12} />
            </a>
            <span>{twin ? "SIMULATED, NOT OBSERVED" : "NASA + NOAA DATA"}</span>
          </div>
        </section>
        <div className="earth-continuation" aria-hidden="true" />
        <div className="earth-content" hidden={twin}>
          <AtlasStory onAir={openAir} onQuestion={(value)=>{setObservedQuestion(value);window.scrollTo({top:0,behavior:'smooth'});document.getElementById('earth-question')?.focus();}}/>
          <PaperReplication />

        </div>
        <div className="earth-content" hidden={!twin}>
          <TwinLab
            ref={twinLab}
            active={twin && page !== "airllm"}
            place={place}
            importSeriesId={selectedSeriesId}
            onBusyChange={setTwinBusy}
          />
          <section className="twin-how" id="twin-how">
            <div>
              <h2>
                Your assumptions.
                <br />
                <span>A different trajectory.</span>
              </h2>
              <p>
                DigiTwin fits a baseline to your research data, then simulates
                how explicit changes could alter it. Each result stays separate
                from observed evidence.
              </p>
            </div>
            <div className="twin-pipeline">
              <div>
                <b>Research data</b>
                <p>Upload time series or copy an observed record.</p>
              </div>
              <div>
                <b>A fitted baseline</b>
                <p>Seasonal cycle, linear trend and AR(1) noise.</p>
              </div>
              <div>
                <b>Your scenario</b>
                <p>Adjust trends, add shocks or test a threshold.</p>
              </div>
              <div>
                <b>Simulated ranges</b>
                <p>Compare the scenario with a simulated reference.</p>
              </div>
            </div>
            <DiscoveryHow onTry={(example) => {
              setQuestion(example);
              window.scrollTo({ top: 0, behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "instant" : "smooth" });
              document.getElementById("earth-question")?.focus({ preventScroll: true });
            }} />
            <details className="data-structure">
              <summary>
                The data behind this world <ChevronDown size={14} />
              </summary>
              <pre>
                {
                  'type TwinVariable = {\n  name: string;\n  units?: string;\n  time: string[]; // dates, e.g. YYYY-MM\n  value: (number | null)[];\n}'
                }
              </pre>
              <p>
                One variable, its units, dates and values. At least 24 valid
                observations are needed. Null represents a gap. Simulation dates
                begin after the record’s last observation.
              </p>
            </details>
          </section>
        </div>
        <footer className="site-footer">
          <span>EARTH SYSTEM TREND DETECTIVE</span>
          <button className="motion-control" aria-pressed={motionPaused} onClick={()=>setMotionPaused(!motionPaused)}><Waves size={14}/>{motionPaused ? "Resume ambient motion" : "Pause ambient motion"}</button>
          <a
            href="https://github.com/chandrakiran-05/NASA"
            target="_blank"
            rel="noopener noreferrer"
          >
            Open project <ArrowUpRight size={12} />
          </a>
          <p>
            Independent NASA Space Apps project. Earth textures: Three.js
            examples. NASA insignia does not imply endorsement.
          </p>
        </footer>
      </main>
    </div>
  );
}
