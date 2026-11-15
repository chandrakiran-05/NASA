import { useEffect, useRef, useState, type CSSProperties, type ReactNode } from "react";
import {
  ApiError,
  getHardware,
  getHarness,
  getSourcesStatus,
  probeModel,
  type HardwareInfo,
  type HarnessInfo,
  type ProbeResult,
  type SourcesStatus,
} from "./api";

type AirLLMProps = { onBack: () => void };
type Load<T> = { data?: T; error?: string };

const errorText = (e: unknown) => e instanceof ApiError || e instanceof Error ? e.message : "Unexpected error.";

// Static architecture: what each stage is and whether the model may touch it. The live component names
// come from GET /api/harness when the backend is reachable.
const FLOW: { id: string; label: string; what: string; role: "none" | "suggest" | "wording" }[] = [
  { id: "plan", label: "Planner", what: "Question to variable, place and period. The offline planner runs first.", role: "suggest" },
  { id: "data", label: "Data", what: "NASA and NOAA records fetched, quality-checked and cached on the server.", role: "none" },
  { id: "engine", label: "Trend tests", what: "Regression with autocorrelation correction, Mann-Kendall, Sen's slope, Trend Court.", role: "none" },
  { id: "gate", label: "BEAST + PELT", what: "Change points from BEAST, checked by PELT, through a calibrated active-trend gate.", role: "none" },
  { id: "wording", label: "Wording", what: "The model rewrites report text from a FACTS object, for a student reader.", role: "wording" },
  { id: "verify", label: "Number check", what: "Every number, direction and significance claim is traced; causal words and predictions are rejected.", role: "none" },
];
const ROLE_LABEL = { none: "No model", suggest: "Model may suggest", wording: "Model writes words" };

// Weights-only sizes: parameters x bytes per parameter. Layer counts are the published configs of each model.
const MODELS = [
  { id: "7b", label: "7B", name: "Qwen2.5-7B", params: 7.6, layers: 28 },
  { id: "14b", label: "14B", name: "Qwen2.5-14B", params: 14.8, layers: 48 },
  { id: "72b", label: "72B", name: "Qwen2.5-72B", params: 72.7, layers: 80 },
] as const;
const WORDS = "Each new word passes through every layer, loaded from disk one at a time.".split(" ");
const round1 = (x: number) => (x >= 10 ? Math.round(x) : Math.round(x * 10) / 10);

/** Animated AirLLM illustration: layers stream disk -> GPU -> released; each full pass writes one word. */
function LayerStream({ layers, running }: { layers: number; running: boolean }) {
  const [step, setStep] = useState(0);          // layer index within the current word
  const [word, setWord] = useState(0);
  useEffect(() => { setStep(0); setWord(0); }, [layers]);
  useEffect(() => {
    if (!running) return;
    const id = setInterval(() => setStep(k => {
      if (k + 1 < layers) return k + 1;
      setWord(w => (w + 1) % (WORDS.length + 1));
      return 0;
    }), Math.max(28, 2400 / layers));           // about 2.4 s per word, whatever the depth
    return () => clearInterval(id);
  }, [running, layers]);
  return <div className="air-stream" aria-hidden="true">
    <div className="air-stream-disk">
      <span className="air-stream-label">On disk: {layers} layers</span>
      <div className="air-stream-cells" style={{ "--cols": layers > 48 ? 16 : 12 } as CSSProperties}>
        {Array.from({ length: layers }, (_, i) => <i key={i} className={i < step ? "is-done" : i === step ? "is-live" : undefined} />)}
      </div>
    </div>
    <div className="air-stream-gpu">
      <span className="air-stream-label">GPU memory</span>
      <div className="air-stream-slot"><b>Layer {step + 1} <span>of {layers}</span></b><small>load, run, release</small></div>
    </div>
    <p className="air-stream-out"><span className="air-stream-label">Output</span>{WORDS.slice(0, word).join(" ")}<i className="air-stream-caret" /></p>
  </div>;
}

function Arrow({ back = false }: { back?: boolean }) {
  return <svg aria-hidden="true" viewBox="0 0 20 20" width="16" height="16" className={back ? "guide-arrow-back" : undefined}><path d="M4 10h12M11 5l5 5-5 5" fill="none" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round" /></svg>;
}

function Command({ text, label }: { text: string; label: string }) {
  const [status, setStatus] = useState("");
  async function copy() {
    try { await navigator.clipboard.writeText(text); setStatus("Copied"); }
    catch { setStatus("Select the command below to copy it."); }
  }
  return <div className="guide-command"><div className="guide-command-head"><span>{label}</span><button type="button" aria-label={`Copy ${label}`} onClick={copy}>{status === "Copied" ? "Copied" : "Copy"}</button></div><pre><code>{text}</code></pre><span className="guide-copy-status" role="status">{status}</span></div>;
}

function Panel({ title, state, children }: { title: string; state: Load<unknown>; children: () => ReactNode }) {
  return <section className="guide-panel" aria-live="polite"><h3>{title}</h3>
    {state.error ? <p className="guide-panel-error" role="alert">{state.error}</p>
      : state.data === undefined ? <p className="guide-panel-muted">Loading from your backend…</p>
      : children()}
  </section>;
}

const gb = (x?: number | null) => x === undefined || x === null ? "n/a" : `${x} GB`;

export default function AirLLM({ onBack }: AirLLMProps) {
  const guideRef = useRef<HTMLElement>(null);
  const [motionPaused, setMotionPaused] = useState(false);
  const [hw, setHw] = useState<Load<HardwareInfo>>({});
  const [src, setSrc] = useState<Load<SourcesStatus>>({});
  const [harness, setHarness] = useState<Load<HarnessInfo>>({});
  const [probe, setProbe] = useState<Load<ProbeResult> & { running?: boolean }>({});
  const [modelId, setModelId] = useState<string>("14b");
  const [streamOn, setStreamOn] = useState(false);
  const model = MODELS.find(m => m.id === modelId) ?? MODELS[1];
  const vram = hw.data?.profile.vram_total_gb;

  useEffect(() => {
    const ctrl = new AbortController();
    const load = <T,>(p: Promise<T>, set: (v: Load<T>) => void) =>
      p.then(data => set({ data }), e => { if (!ctrl.signal.aborted) set({ error: errorText(e) }); });
    load(getHardware(ctrl.signal), setHw);
    load(getSourcesStatus(ctrl.signal), setSrc);
    load(getHarness(ctrl.signal), setHarness);
    return () => ctrl.abort();
  }, []);

  useEffect(() => {
    const guide = guideRef.current;
    if (!guide) return;
    const surfaces = guide.querySelectorAll<HTMLElement>("[data-flow-surface]");
    const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
    const observer = new IntersectionObserver(entries => {
      entries.forEach(entry => {
        entry.target.classList.toggle("is-flow-visible", entry.isIntersecting);
        if (entry.target.id === "guide-layer-flow") setStreamOn(entry.isIntersecting && !reduce);
      });
    }, { threshold: 0.12 });
    surfaces.forEach(surface => observer.observe(surface));

    function syncVisibility() {
      guide?.classList.toggle("is-document-hidden", document.hidden);
    }
    syncVisibility();
    document.addEventListener("visibilitychange", syncVisibility);
    return () => {
      observer.disconnect();
      document.removeEventListener("visibilitychange", syncVisibility);
    };
  }, []);

  async function runProbe() {
    setProbe({ running: true });
    try { setProbe({ data: await probeModel() }); }
    catch (e) { setProbe({ error: errorText(e) }); }
  }

  const liveModel = hw.data?.recommendation.live.model ?? "qwen3.5:4b";
  const stageComponent = (id: string) => harness.data?.stages.find(s => s.id === id)?.component;
  const cfg = harness.data?.config;

  const runCommands = {
    install: "git clone <this repository> && cd NASA\npip install -e .",
    model: `ollama pull ${liveModel}`,
    init: "trend-harness init      # writes harness.toml, finds Ollama / LM Studio / llama.cpp",
    doctor: "trend-harness doctor    # config, model probe, credentials, BEAST",
    ask: 'trend-harness ask "temperature in India from 2002 to 2022"\ntrend-harness ask "rainfall in Chennai since 2001" --json',
    serve: "trend-harness serve --host 127.0.0.1 --port 8000",
  };

  return <main ref={guideRef} className="local-guide" id="local-guide" data-flow-paused={motionPaused}>
    <a className="guide-skip" href="#guide-title">Skip to local AI guide</a>
    <header className="guide-masthead">
      <button type="button" className="guide-home" onClick={onBack}><img src="/nasa-logo.svg" width="43" height="37" alt="NASA" /><span>EARTH SYSTEM<br /><strong>TREND DETECTIVE</strong></span><span className="guide-home-return"><Arrow back /> Back to Earth</span></button>
      <a className="guide-download" href="#guide-setup">Run it yourself <Arrow /></a>
    </header>

    <section className="guide-opening" aria-labelledby="guide-title">
      <div className="guide-opening-copy"><h1 id="guide-title">Your model.<br /><em>Our evidence engine.</em></h1><p className="guide-lead">The trend harness packs our whole pipeline: planner prompts, NASA and NOAA data, trend tests, the BEAST + PELT gate and the number check. Plug in any local model. The engine computes every number; the model only writes words, and those words are checked.</p><a className="guide-action" href="#guide-live">Test your model <Arrow /></a><p className="guide-runtime-note">Ollama, LM Studio, llama.cpp or vLLM for live answers.<br />AirLLM for big models on small GPUs, layer by layer.</p></div>
      <div className="guide-mechanism" data-flow-surface aria-label="Your question goes to the science engine, which computes every number. The local model rewrites the explanation. A number check accepts or rejects the wording; rejected text falls back to the template.">
        <div className="guide-diagram-title"><span>WHO DECIDES WHAT</span><button className="guide-motion-toggle" type="button" aria-pressed={motionPaused} aria-controls="guide-explanation-flow guide-layer-flow" onClick={() => setMotionPaused(paused => !paused)}>{motionPaused ? "Resume motion" : "Pause motion"}<span aria-hidden="true">{motionPaused ? <svg viewBox="0 0 16 16"><path d="m6 4 6 4-6 4Z" fill="currentColor" /></svg> : <svg viewBox="0 0 16 16"><path d="M6 4v8M10 4v8" stroke="currentColor" strokeWidth="1.5" /></svg>}</span></button></div>
        <div className="guide-map" id="guide-explanation-flow">
          <svg viewBox="0 0 480 360" aria-hidden="true" preserveAspectRatio="none"><path d="M164 68V292M164 180H355V292H164" fill="none" stroke="currentColor" strokeWidth="1" /><path className="guide-flow-line" pathLength="1" d="M164 68V180H355V292H164" fill="none" strokeWidth="2.5" strokeLinecap="round" /><circle cx="164" cy="180" r="4" fill="currentColor" /></svg>
          <div className="guide-node guide-question"><span>YOUR QUESTION</span><strong>A place. A variable. A period.</strong></div>
          <div className="guide-node guide-science"><span>SCIENCE ENGINE · DECIDES</span><strong>Data, trend tests, BEAST + PELT</strong></div>
          <div className="guide-node guide-model"><span>YOUR MODEL · WRITES</span><strong>Wording only</strong><small>From a FACTS object</small></div>
          <div className="guide-node guide-checked"><span>NUMBER CHECK · ACCEPTS OR REJECTS</span><strong>Every number traced to the data</strong></div>
        </div>
        <p className="guide-flow-note">Illustrated processing flow</p>
        <p className="guide-fallback"><span aria-hidden="true" /> No model, or the model's text fails the check? The deterministic template text is shown instead. The verdict is the same either way.</p>
      </div>
    </section>

    <section className="guide-live-section" id="guide-live" aria-labelledby="guide-live-title">
      <div className="guide-setup-heading"><h2 id="guide-live-title">This machine,<br /><em>right now.</em></h2><p className="guide-section-note">Read live from your backend. Speeds are measured on one short answer; hardware advice is an estimate.</p></div>
      <div className="guide-live">
        <Panel title="Your machine" state={hw}>{() => {
          const p = hw.data!.profile, r = hw.data!.recommendation;
          return <>
            <dl className="guide-kv">
              <dt>GPU</dt><dd>{p.gpu_name ?? p.gpu_note ?? "none found"}</dd>
              <dt>VRAM</dt><dd>{gb(p.vram_total_gb)} total · {gb(p.vram_free_gb)} free</dd>
              <dt>RAM</dt><dd>{gb(p.ram_total_gb)} total · {gb(p.ram_available_gb)} available</dd>
              <dt>Disk free</dt><dd>{gb(p.disk_free_gb)}</dd>
            </dl>
            <p className="guide-panel-pick"><span>Live model</span><strong>{r.live.model}</strong>{r.live.why && <small>{r.live.why}</small>}</p>
            <p className="guide-panel-pick"><span>Deep model (AirLLM)</span><strong>{r.deep?.model ?? "off for this machine"}</strong></p>
            {r.notes.length > 0 && <ul className="guide-notes">{r.notes.map(n => <li key={n}>{n}</li>)}</ul>}
          </>;
        }}</Panel>
        <Panel title="Connected model" state={harness.error ? harness : src.error ? src : harness.data && src.data ? { data: 1 } : {}}>{() => {
          const live = src.data!.llm, h = harness.data!;
          return <>
            <p className={`guide-status ${live.available ? "is-ok" : "is-off"}`}><span aria-hidden="true" />{live.available ? "Connected" : "Not connected"}: {live.provider} {live.model ?? ""}</p>
            {!live.available && (live.reason || live.hint) && <p className="guide-panel-muted">{live.reason ?? live.hint}</p>}
            <dl className="guide-kv">
              <dt>Endpoint</dt><dd><code>{cfg?.model.base_url}</code></dd>
              <dt>Deep tier</dt><dd>{h.model_status.deep.available ? `AirLLM ${h.model_status.deep.model ?? ""}` : (h.model_status.deep.reason ?? "off")}</dd>
              <dt>Significance level</dt><dd>{cfg?.pipeline.alpha}</dd>
              <dt>Minimum record</dt><dd>{cfg?.pipeline.min_years} years</dd>
              <dt>Number check</dt><dd>{cfg?.pipeline.verify} (cannot be switched off)</dd>
              <dt>Model rewrites</dt><dd>{h.rewrite_sections_active.length ? h.rewrite_sections_active.join(", ") : "nothing (template text only)"}</dd>
            </dl>
            <p className="guide-panel-muted">Config from: {h.source}</p>
          </>;
        }}</Panel>
        <section className="guide-panel" aria-live="polite"><h3>Test my model</h3>
          <p className="guide-panel-muted">Gives your model a small set of facts, asks for two sentences, then runs the same number check the reports use. A model that invents a number fails.</p>
          <button type="button" className="guide-action guide-probe" onClick={runProbe} disabled={probe.running}>{probe.running ? "Waiting for the model…" : "Run the test"} <Arrow /></button>
          {probe.error && <p className="guide-panel-error" role="alert">{probe.error}</p>}
          {probe.data && <div className="guide-probe-result">
            <p className={`guide-status ${probe.data.verdict === "pass" ? "is-ok" : "is-off"}`}><span aria-hidden="true" />{probe.data.verdict === "pass" ? "PASS: faithful to the facts" : probe.data.verdict === "fail" ? "FAIL" : "Model unavailable"}</p>
            {probe.data.reason && <p className="guide-panel-muted">{probe.data.reason}</p>}
            {probe.data.latency_s !== undefined && <dl className="guide-kv"><dt>Latency</dt><dd>{probe.data.latency_s} s</dd><dt>Speed</dt><dd>about {probe.data.approx_tokens_per_s ?? "n/a"} tokens/s (estimated from length)</dd>{probe.data.verify && <><dt>Number check</dt><dd>{probe.data.verify.badge}</dd></>}</dl>}
            {probe.data.answer && <blockquote>{probe.data.answer}</blockquote>}
          </div>}
        </section>
      </div>
    </section>

    <section className="guide-pipeline-section" aria-labelledby="guide-pipeline-title">
      <div className="guide-setup-heading"><h2 id="guide-pipeline-title">The harness,<br /><em>stage by stage.</em></h2><p className="guide-section-note">Swap the model and only the two marked stages change. Every number, test and verdict stays the same.</p></div>
      {harness.error && <p className="guide-panel-error" role="alert">Live component names unavailable: {harness.error}</p>}
      <ol className="guide-pipeline">
        <li className="guide-stage"><span className="guide-stage-tag is-none">Input</span><h3>Your question</h3><p>Plain words, any Earth place, any period.</p></li>
        {FLOW.map(s => <li key={s.id} className="guide-stage"><span className={`guide-stage-tag is-${s.role}`}>{ROLE_LABEL[s.role]}</span><h3>{s.label}</h3><p>{s.what}</p>{stageComponent(s.id) && <code>{stageComponent(s.id)}</code>}</li>)}
        <li className="guide-stage"><span className="guide-stage-tag is-none">Output</span><h3>Answer</h3><p>Verdict, numbers with units, provenance and limits. Labelled "AI-written, number-checked" only where the model's text passed.</p></li>
      </ol>
      <div className="guide-may">
        <div><h3>The model may</h3><ul><li>Suggest a variable, place and period when the offline planner cannot.</li><li>Rewrite report sections in simpler words.</li><li>Add an advisory deep-review note (AirLLM, a big model on a small GPU).</li></ul></div>
        <div><h3>The model may not</h3><ul><li>Compute or change any number, p-value or date.</li><li>Decide SIGNIFICANT / NOT PROVEN or VERIFIED / PROBABLE / NOT VERIFIED.</li><li>Use causal words or predict the future; such text is rejected.</li></ul></div>
      </div>
    </section>

    <section className="guide-technology air-feature" aria-labelledby="guide-technology-title">
      <div className="air-feature-head">
        <h2 id="guide-technology-title">Big models.<br /><em>Small laptops.</em></h2>
        <p>Most students do not own a 24 GB graphics card. AirLLM, an open-source project, keeps a large model's layers on disk and streams them through the GPU one at a time.</p>
      </div>
      <div className="air-feature-grid">
        <div className="air-demo" id="guide-layer-flow" data-flow-surface role="img" aria-label={`AirLLM illustration: the ${model.name} model's ${model.layers} layers stay on disk; each one is loaded into GPU memory, run and released before the next, and one full pass writes one word.`}>
          <div className="air-demo-top">
            <div className="air-model-pick" role="group" aria-label="Model size">
              {MODELS.map(m => <button key={m.id} type="button" aria-pressed={m.id === model.id} onClick={() => setModelId(m.id)}>{m.label}</button>)}
            </div>
            <span className="air-demo-name">{model.name}</span>
          </div>
          <LayerStream layers={model.layers} running={streamOn && !motionPaused} />
        </div>
        <div className="air-numbers">
          <div><span>Load the whole model</span><strong>{round1(model.params * 2)} GB</strong><small>16-bit weights, all at once</small></div>
          <div className="is-yours"><span>Your GPU</span><strong>{vram === undefined ? "n/a" : `${vram} GB`}</strong><small>{hw.data?.profile.gpu_name ?? "read from your backend"}</small></div>
          <div className="is-air"><span>AirLLM needs at a time</span><strong>{round1((model.params * 2) / model.layers)} GB</strong><small>about one layer, plus working memory</small></div>
          <p className="air-numbers-note">Weights only, rounded. Real use adds working memory for the text being written.</p>
        </div>
      </div>
      <div className="air-facts">
        <div><h3>Full model, not a shrunken copy</h3><p>Every layer and every parameter is still used, so the answer comes from the full model. Optional 4-bit compression is faster with a small quality cost, according to the AirLLM project.</p></div>
        <div><h3>The price is time</h3><p>Every new word re-reads every layer from disk: seconds per word, not words per second. Fast disks (NVMe) help most.</p></div>
        <div><h3>Its job in the harness</h3><p>The deep tier: a background reviewer that reads finished results and writes a note labelled "AI reviewer (advisory)". It never changes a number or a verdict.</p></div>
      </div>
      <p className="air-enable">Turn it on: <code>pip install -r requirements-airllm.txt</code>, then <code>[deep] provider = "airllm"</code> in <code>harness.toml</code>. If your GPU already holds the model, Ollama or vLLM is faster. <a className="guide-inline-link" href="https://github.com/lyogavin/airllm" target="_blank" rel="noopener noreferrer">AirLLM on GitHub <Arrow /></a></p>
    </section>

    <section className="guide-setup" id="guide-setup" aria-labelledby="guide-setup-title"><div className="guide-setup-heading"><h2 id="guide-setup-title">Run it<br /><em>yourself.</em></h2><a className="guide-outline-action" href="https://ollama.com/download" target="_blank" rel="noopener noreferrer">Get Ollama <Arrow /></a></div>
      <ol className="guide-steps">
        <li><span className="guide-step-index" aria-hidden="true">01</span><div className="guide-step-copy"><h3>Install the harness</h3><p>Python 3.11 or newer. This installs the backend and the <code>trend-harness</code> command. Docker works too: the repository's Dockerfile serves the same API.</p></div><Command text={runCommands.install} label="Install" /></li>
        <li><span className="guide-step-index" aria-hidden="true">02</span><div className="guide-step-copy"><h3>Get a local model</h3><p>The recommendation for this machine is <code>{liveModel}</code>. Any model your runtime serves can be tested in step 04.</p><small>The first download needs internet access.</small></div><Command text={runCommands.model} label="Download model" /></li>
        <li><span className="guide-step-index" aria-hidden="true">03</span><div className="guide-step-copy"><h3>Write your config</h3><p>Detects a running runtime and writes a commented <code>harness.toml</code>. Data credentials are named by environment variable; their values never go in the file.</p></div><Command text={runCommands.init} label="Configure" /></li>
        <li><span className="guide-step-index" aria-hidden="true">04</span><div className="guide-step-copy"><h3>Check everything</h3><p>Probes the model with the number-faithfulness test, lists which data credentials are set, and checks that BEAST is installed.</p></div><Command text={runCommands.doctor} label="Doctor" /></li>
        <li><span className="guide-step-index" aria-hidden="true">05</span><div className="guide-step-copy"><h3>Ask, or serve</h3><p><code>ask</code> runs the full report pipeline in your terminal and prints the answer, verdict and where the numbers came from. <code>serve</code> starts the API with your config for this web app.</p></div><Command text={`${runCommands.ask}\n${runCommands.serve}`} label="Ask and serve" /></li>
      </ol>
      <details className="guide-deep-review"><summary><span>Supported runtimes and their settings</span><svg aria-hidden="true" width="16" height="16" viewBox="0 0 20 20"><path d="M4 7l6 6 6-6" fill="none" stroke="currentColor" strokeWidth="1.3" /></svg></summary><div>
        <p><strong>Ollama</strong> (default, port 11434): <code>provider = "ollama"</code>. <strong>LM Studio</strong> (port 1234), <strong>llama.cpp server</strong> (port 8080), <strong>vLLM</strong> (port 8000) and Ollama's <code>/v1</code>: <code>provider = "openai-compatible"</code> with that <code>base_url</code>. <strong>AirLLM</strong>: deep tier only. <code>provider = "none"</code> runs with template text.</p>
        <Command text={'[model]\nprovider = "openai-compatible"\nbase_url = "http://127.0.0.1:1234"\nname = "your-model-name"'} label="harness.toml for LM Studio" />
        <p>Everything stays on your machine except the NASA and NOAA data requests, which the backend makes with your own credentials.</p>
      </div></details>
      <aside className="guide-boundary"><strong>What "higher accuracy" means here.</strong><p>A bigger or better local model gives clearer wording, more of it passing the number check, and better planning of unusual questions. It does not change the statistics: slopes, p-values, change dates and verdicts come from the engine and are identical with any model, or with none. AI review is advisory; the model never decides a verdict.</p></aside>
    </section>
    <footer className="guide-footer"><span>EARTH SYSTEM TREND DETECTIVE · TREND HARNESS</span><div><a href="https://github.com/lyogavin/airllm" target="_blank" rel="noopener noreferrer">AirLLM documentation <Arrow /></a><a href="https://docs.ollama.com/quickstart" target="_blank" rel="noopener noreferrer">Ollama quickstart <Arrow /></a></div></footer>
  </main>;
}
