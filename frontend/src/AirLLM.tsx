import { useState } from "react";

type AirLLMProps = { onBack: () => void };

const modelCommand = "ollama pull qwen3.5:4b";
const settingsCommand = "LLM_PROVIDER=ollama\nLLM_BASE_URL=http://127.0.0.1:11434\nLLM_MODEL=qwen3.5:4b";
const startCommand = "uvicorn backend.main:app --reload --port 8000";
const deepCommand = "pip install -r requirements-airllm.txt\npython scripts/airllm_setup.py";

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

export default function AirLLM({ onBack }: AirLLMProps) {
  return <main className="local-guide" id="local-guide">
    <a className="guide-skip" href="#guide-title">Skip to local AI guide</a>
    <header className="guide-masthead">
      <button type="button" className="guide-home" onClick={onBack}><img src="/nasa-logo.svg" width="43" height="37" alt="NASA" /><span>EARTH SYSTEM<br /><strong>TREND DETECTIVE</strong></span><span className="guide-home-return"><Arrow back /> Back to Earth</span></button>
      <a className="guide-download" href="https://github.com/lyogavin/airllm" target="_blank" rel="noopener noreferrer">Download AirLLM <Arrow /></a>
    </header>

    <section className="guide-opening" aria-labelledby="guide-title">
      <div className="guide-opening-copy"><h1 id="guide-title">Earth questions.<br /><em>Closer to home.</em></h1><p className="guide-lead">A local assistant for reading the evidence. Your computer runs the model; the science engine checks the numbers.</p><a className="guide-action" href="#guide-setup">Set up local AI <Arrow /></a><p className="guide-runtime-note">Ollama for live answers.<br />Optional AirLLM for deeper review.</p></div>
      <div className="guide-mechanism" aria-label="Question goes to the backend science engine, then a local model helps explain the results. Numeric checks validate its explanation, with a deterministic fallback if needed.">
        <div className="guide-diagram-title"><span>THE EXPLANATION PATH</span><span>LOCAL INFERENCE</span></div>
        <div className="guide-map">
          <svg viewBox="0 0 480 360" aria-hidden="true" preserveAspectRatio="none"><path d="M164 68V292M164 180H355V292H164" fill="none" stroke="currentColor" strokeWidth="1" /><circle cx="164" cy="180" r="4" fill="currentColor" /></svg>
          <div className="guide-node guide-question"><span>YOUR QUESTION</span><strong>A place. A changing variable.</strong></div>
          <div className="guide-node guide-science"><span>BACKEND</span><strong>Records &amp; trend tests</strong></div>
          <div className="guide-node guide-model"><span>ON YOUR MACHINE</span><strong>Local model</strong><small>Helps explain the results</small></div>
          <div className="guide-node guide-checked"><span>BEFORE THE ANSWER</span><strong>Check every number</strong></div>
        </div>
        <p className="guide-fallback"><span aria-hidden="true" /> No model connected? The deterministic explanation still works.</p>
      </div>
    </section>

    <section className="guide-technology" aria-labelledby="guide-technology-title"><div><h2 id="guide-technology-title">The model explains.<br /><em>The evidence decides.</em></h2></div><div className="guide-technology-copy"><p>AirLLM is an open-source library that loads model layers as they are needed. It reduces GPU memory use, with more disk activity and slower inference.</p><p>The live assistant uses Ollama or an OpenAI-compatible local server. The newer backend also supports AirLLM for optional background reviews. Those reviews are advisory; they never decide a statistical verdict.</p><a className="guide-inline-link" href="https://github.com/lyogavin/airllm" target="_blank" rel="noopener noreferrer">Read how AirLLM works <Arrow /></a></div></section>

    <section className="guide-setup" id="guide-setup" aria-labelledby="guide-setup-title"><div className="guide-setup-heading"><h2 id="guide-setup-title">From download<br /><em>to first question.</em></h2><a className="guide-outline-action" href="https://ollama.com/download" target="_blank" rel="noopener noreferrer">Get Ollama <Arrow /></a></div>
      <ol className="guide-steps">
        <li><span className="guide-step-index" aria-hidden="true">01</span><div className="guide-step-copy"><h3>Install the local runtime</h3><p>Download Ollama for your operating system and open it. Then download the project’s model in a terminal.</p><small>The first download needs internet access. Speed and memory use depend on your hardware.</small></div><Command text={modelCommand} label="Download model" /></li>
        <li><span className="guide-step-index" aria-hidden="true">02</span><div className="guide-step-copy"><h3>Connect the backend</h3><p>Add these settings to the project root’s <code>.env</code> file. Keep Earthdata and NOAA credentials on the server.</p><small>Using the CLI without the desktop app? Start the local server with <code>ollama serve</code>.</small></div><Command text={settingsCommand} label="Project .env" /></li>
        <li><span className="guide-step-index" aria-hidden="true">03</span><div className="guide-step-copy"><h3>Ask about your part of Earth</h3><p>With the Python dependencies installed, start the backend from the repository root. Return to Earth and submit a question.</p><button type="button" className="guide-inline-link" onClick={onBack}>Return to Earth <Arrow /></button></div><Command text={startCommand} label="Start backend" /></li>
      </ol>
      <details className="guide-deep-review"><summary><span>Set up optional AirLLM deep review</span><svg aria-hidden="true" width="16" height="16" viewBox="0 0 20 20"><path d="M4 7l6 6 6-6" fill="none" stroke="currentColor" strokeWidth="1.3" /></svg></summary><div><p>The <code>backend-active-trends</code> branch includes this optional tier. On that backend, install its extra requirements and run the hardware-aware setup helper.</p><Command text={deepCommand} label="AirLLM setup on the newer backend" /><p>Follow the helper’s model recommendation and set <code>DEEP_LLM_PROVIDER=airllm</code> in <code>.env</code> to enable it. Reviews run in background jobs and may take minutes. The model’s output remains advisory.</p></div></details>
      <aside className="guide-boundary"><strong>Local model. Connected observations.</strong><p>Model inference can run on your machine after download. New NASA and NOAA records still need internet access and may need server-side credentials. Uploaded monthly records can be analyzed without those data-service credentials.</p></aside>
    </section>
    <footer className="guide-footer"><span>EARTH SYSTEM TREND DETECTIVE</span><div><a href="https://github.com/lyogavin/airllm" target="_blank" rel="noopener noreferrer">AirLLM documentation <Arrow /></a><a href="https://docs.ollama.com/quickstart" target="_blank" rel="noopener noreferrer">Ollama quickstart <Arrow /></a></div></footer>
  </main>;
}
