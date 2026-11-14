import { lazy, Suspense, useEffect, useMemo, useRef, useState } from "react";
import {
  ArrowUp,
  ArrowUpRight,
  ArrowDown,
  ArrowLeftRight,
  FlaskConical,
  Globe2,
  Menu,
  X,
  Upload,
  ChevronDown,
} from "lucide-react";
import { api } from "./api";
import AirLLM from "./AirLLM";
import ObservedEvidence from "./ObservedEvidence";
import Narrative from "./Narrative";
import AtlasStory from "./AtlasStory";
import TwinLab from "./TwinLab";
import type { TwinLabHandle } from "./TwinLab";
import { inferPromptContext } from "./promptContext";
const Globe = lazy(() => import("./Globe"));
type Data = Record<string, any>;
type Focus = { lat: number; lon: number };
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
  const [page, setPage] = useState(
    location.pathname.startsWith("/airllm") ? "airllm" : "earth",
  );
  const [twin, setTwin] = useState(location.pathname.startsWith("/digitwin"));
  const [observedQuestion, setObservedQuestion] = useState(""),
    [twinQuestion, setTwinQuestion] = useState("");
  const question = twin ? twinQuestion : observedQuestion;
  const setQuestion = twin ? setTwinQuestion : setObservedQuestion;
  const [inputMode, setInputMode] = useState<"investigate" | "ask">(
    "investigate",
  );
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
  const currentWorld = useRef({ twin, page });
  currentWorld.current = { twin, page };
  const [plan, setPlan] = useState<Data | null>(null),
    [report, setReport] = useState<Data | null>(null),
    [answer, setAnswer] = useState<Data | null>(null);
  const [busy, setBusy] = useState(false),
    [twinBusy, setTwinBusy] = useState(false),
    [error, setError] = useState("");
  const [workspace, setWorkspace] = useState(false),
    [progress, setProgress] = useState({ progress: 0, message: "" });
  const [connection, setConnection] = useState("Checking connection");
  const active = useRef<AbortController | null>(null),
    twinLab = useRef<TwinLabHandle>(null),
    transitionTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const cursor = useRef<HTMLDivElement>(null),
    pointerFrame = useRef(0);
  const context = useMemo(() => inferPromptContext(question), [question]);
  const currentAnalysis = report?.results?.[0]?.analysis;
  const [selectedSeriesId, setSelectedSeriesId] = useState<
    string | undefined
  >();
  useEffect(
    () => setSelectedSeriesId(report?.results?.[0]?.analysis?.series_id),
    [report],
  );
  useEffect(() => {
    document.title =
      page === "airllm"
        ? "Local AI — Earth System Trend Detective"
        : twin
          ? "DigiTwin — A possible Earth"
          : "Earth System Trend Detective";
  }, [page, twin]);
  useEffect(() => {
    const pop = () => {
      setPage(location.pathname.startsWith("/airllm") ? "airllm" : "earth");
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
      active.current?.abort();
      if (transitionTimer.current) clearTimeout(transitionTimer.current);
      cancelAnimationFrame(pointerFrame.current);
    };
  }, []);
  useEffect(() => {
    if (!question.trim()) {
      setLocationNote("");
      return;
    }
    const controller = new AbortController();
    let stale = false;
    const timer = setTimeout(async () => {
      if (context.navigationFocus) {
        setFocus(context.navigationFocus);
        setPlace(context.navigationFocus.name);
        setLocationNote("Navigation view · not a data boundary");
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
            setLocationNote(
              region.approximate
                ? "Approximate region · confirm in your investigation"
                : "Location resolved by the backend",
            );
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
  }, [question, context]);
  function changeWorld(next: boolean) {
    if (next === twin) return;
    if (next && !scenarioFocus) {
      setScenarioFocus(observedFocus);
      setScenarioPlace(observedPlace);
    }
    setTwin(next);
    setAnswer(null);
    setMenu(false);
    setChanging(true);
    history.pushState({}, "", next ? "/digitwin" : "/");
    if (transitionTimer.current) clearTimeout(transitionTimer.current);
    transitionTimer.current = setTimeout(() => setChanging(false), 1100);
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
  async function submit(value = question) {
    const q = value.trim();
    if (!q || (twin ? twinBusy : busy)) return;
    if (twin) {
      twinLab.current?.submitPrompt(q);
      return;
    }
    setObservedQuestion(q);
    setError("");
    setAnswer(null);
    setReport(null);
    setBusy(true);
    setProgress({ progress: 0.02, message: "Reading your question…" });
    active.current?.abort();
    const controller = new AbortController();
    active.current = controller;
    try {
      if (inputMode === "ask") {
        setAnswer(await api.ask(q, controller.signal));
        return;
      }
      const nextPlan = await api.plan(q, controller.signal);
      setPlan(nextPlan);
      if (nextPlan.on_topic === false)
        throw new Error(nextPlan.message || "Ask about Earth-system data.");
      if (nextPlan.needs_user_input?.length)
        throw new Error(
          `Add ${nextPlan.needs_user_input.join(" and ")} to your question.`,
        );
      if (nextPlan.regions?.some((r) => r.needs_confirmation))
        throw new Error(
          "Use a recognized city or country to confirm the estimated location.",
        );
      const region = nextPlan.regions?.[0];
      if (region) {
        const target = geometryCenter(region.geometry);
        if (target) setFocus(target);
        setPlace(region.name);
      }
      setWorkspace(true);
      setProgress({
        progress: 0.05,
        message: "Acquiring the regional record…",
      });
      const nextReport = await api.investigate(
        nextPlan.wishes?.compare
          ? { question: q }
          : {
              question: q,
              variable_id: nextPlan.variables?.[0]?.id,
              geometry: region?.geometry,
              start: nextPlan.period?.start || undefined,
              end: nextPlan.period?.end || undefined,
            },
        {
          signal: controller.signal,
          onProgress: (job) =>
            setProgress({ progress: job.progress || 0, message: job.message }),
        },
      );
      if (nextReport.on_topic === false || nextReport.needs_user_input?.length)
        throw new Error(
          nextReport.message || "Add a place and a variable to continue.",
        );
      setReport(nextReport);
      if (nextReport.plan) setPlan(nextReport.plan);
      setProgress({ progress: 1, message: "Evidence ready" });
      if (!currentWorld.current.twin && currentWorld.current.page === "earth")
        document
          .getElementById("workspace")
          ?.scrollIntoView({
            behavior: matchMedia("(prefers-reduced-motion: reduce)").matches
              ? "auto"
              : "smooth",
          });
    } catch (e) {
      if (!controller.signal.aborted)
        setError(
          e instanceof Error
            ? e.message
            : "The investigation could not finish.",
        );
    } finally {
      if (active.current === controller) setBusy(false);
    }
  }
  function cancel() {
    active.current?.abort();
    setBusy(false);
    setError("Stopped waiting. The backend job may continue.");
  }
  async function upload(file: File) {
    if (busy) return;
    setWorkspace(true);
    setBusy(true);
    setError("");
    setPlan(null);
    setReport(null);
    setProgress({ progress: 0.1, message: "Reading monthly observations…" });
    const controller = new AbortController();
    active.current?.abort();
    active.current = controller;
    try {
      const series = await api.uploadCSV(file, controller.signal);
      const analysis = await api.analyze(series.series_id, controller.signal);
      setReport({ results: [{ series, analysis }] });
      if (!currentWorld.current.twin && currentWorld.current.page === "earth") {
        document
          .getElementById("workspace")
          ?.scrollIntoView({ behavior: "smooth" });
      }
    } catch (e) {
      if (!controller.signal.aborted)
        setError(
          e instanceof Error ? e.message : "The CSV could not be analyzed.",
        );
    } finally {
      if (active.current === controller) setBusy(false);
    }
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
      data-world={twin ? "twin" : "observed"}
      data-topic={context.topic}
      onPointerMove={pointerMove}
    >
      <div ref={cursor} className="cursor-light" aria-hidden="true" />
      {page === "airllm" ? (
        <AirLLM onBack={returnEarth} />
      ) : (
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
      )}
      <main
        id="main"
        className={page === "airllm" ? "earth-hidden" : ""}
        aria-hidden={page === "airllm"}
        inert={page === "airllm"}
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
            <label className="command-label" htmlFor="earth-question">
              {twin
                ? "Your what-if question"
                : "What is changing in your part of Earth?"}
            </label>
            <form
              className="command-glass"
              onSubmit={(e) => {
                e.preventDefault();
                void submit();
              }}
            >
              <button
                className="command-mode"
                type="button"
                aria-label={
                  twin
                    ? "DigiTwin scenario mode"
                    : `Mode: ${inputMode}. Switch question mode`
                }
                onClick={() => {
                  if (!twin)
                    setInputMode(inputMode === "ask" ? "investigate" : "ask");
                }}
              >
                {twin ? <FlaskConical size={17} /> : <Globe2 size={17} />}
                <ChevronDown size={10} />
              </button>
              <input
                id="earth-question"
                className="command-input"
                value={question}
                onChange={(e) => setQuestion(e.target.value)}
                maxLength={2000}
                autoComplete="off"
                placeholder={
                  twin
                    ? "What if warming in Chennai doubled?"
                    : inputMode === "ask"
                      ? "Ask about Earth data or trend tests…"
                      : "Try “temperature trends in India”"
                }
              />
              {!twin && busy ? (
                <button
                  type="button"
                  className="command-send"
                  aria-label="Stop waiting"
                  onClick={cancel}
                >
                  <X size={19} />
                </button>
              ) : (
                <button
                  className="command-send"
                  type="submit"
                  disabled={!question.trim() || (twin ? twinBusy : busy)}
                  aria-label={
                    twin
                      ? "Prepare DigiTwin scenario"
                      : inputMode === "ask"
                        ? "Ask the assistant"
                        : "Investigate Earth"
                  }
                >
                  <ArrowUp size={21} />
                </button>
              )}
            </form>
            <div className="dock-under">
              <span className="connection">
                <i />
                {twin
                  ? "DigiTwin input selected"
                  : `${inputMode === "ask" ? "Ask · " : ""}${connection}`}
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
            {!twin && busy && (
              <p className="dock-feedback" role="status">
                {progress.message}
              </p>
            )}
            {!twin && error && (
              <p className="dock-feedback error" role="alert">
                {error}
              </p>
            )}
              {!twin && answer && (
              <div className="assistant-answer" aria-live="polite">
                <button
                  className="answer-close"
                  aria-label="Close assistant answer"
                  onClick={() => setAnswer(null)}
                >
                  <X size={14} />
                </button>
                <span>
                  {answer.source === "local_llm"
                    ? "AI-written, number-checked"
                    : answer.source === "guardrail"
                      ? "Earth-topic guardrail"
                      : "Local deterministic answer"}
                </span>
                <Narrative value={answer.answer || answer.message} />
              </div>
            )}
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
          {workspace && (
            <ObservedEvidence
              report={report}
              plan={plan}
              busy={busy}
              progress={progress}
              error={error}
              onUpload={(file) => void upload(file)}
              onCancel={cancel}
              onRegion={(g) => setFocus(geometryCenter(g))}
              onSelectSeries={setSelectedSeriesId}
            />
          )}
          <AtlasStory onAir={openAir} onQuestion={(value)=>{setObservedQuestion(value);window.scrollTo({top:0,behavior:'smooth'});document.getElementById('earth-question')?.focus();}} onUpload={(file)=>void upload(file)} busy={busy}/>

        </div>
        <div className="earth-content" hidden={!twin}>
          <TwinLab
            ref={twinLab}
            active={twin && page !== "airllm"}
            place={place}
            importSeriesId={selectedSeriesId || currentAnalysis?.series_id}
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
