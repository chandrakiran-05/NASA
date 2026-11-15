import { ArrowRight, BookOpenCheck, FileText, Flag, ScanSearch, ShieldCheck, Sparkles } from "lucide-react";
import "./discovery.css";

const STEPS = [
  { icon: ScanSearch, title: "Scan", text: "Sweeps the globe or your region, grid cell by grid cell, for rain, heat, soil moisture and sea temperature." },
  { icon: ShieldCheck, title: "Keep what's real", text: "Each strong cell gets a proper monthly record. Only trends that pass every check and BEAST stay." },
  { icon: BookOpenCheck, title: "Check what's known", text: "Searches published studies for that variable and place, and lists preprints and recent news." },
  { icon: Flag, title: "Flag the gaps", text: "Verified by data, but no matching study found? Marked as a potential new finding, not yet checked by scientists." },
  { icon: FileText, title: "Write it up", text: "A short brief: what changed, where, since when, the rate, associated drivers, a chart, DOIs and a notebook." },
];

const SOURCES: { name: string; role: string; unreviewed?: boolean }[] = [
  { name: "NOAA ERDDAP grids", role: "scan" },
  { name: "NASA Giovanni", role: "checks, with token" },
  { name: "arXiv · OpenAlex · Crossref · NASA NTRS", role: "studies" },
  { name: "OpenAlex preprints · arXiv", role: "preprints", unreviewed: true },
  { name: "GDELT news", role: "news", unreviewed: true },
];

export const DISCOVERY_EXAMPLE = "Find unreported changes in the South Asia monsoon";

/** DigiTwin explainer for Discovery mode: the pipeline, an example brief layout (no real data) and the sources. */
export default function DiscoveryHow({ onTry }: { onTry: (example: string) => void }) {
  return <section className="twin-discovery" id="twin-discovery" aria-labelledby="twin-discovery-title">
    <div className="dh-head">
      <h3 id="twin-discovery-title">How Discovery works. <span>An AI scientist that checks itself.</span></h3>
      <p>Ask a question in the box above. Discovery runs five steps you can watch live, then adds one simulated outlook.
        A run takes up to about 5 minutes; findings appear one by one.</p>
    </div>

    <ol className="dh-pipeline" aria-label="Discovery steps">
      {STEPS.map(({ icon: Icon, title, text }, i) => <li key={title} className="dh-step">
        <span className="dh-node" aria-hidden="true"><Icon size={18} strokeWidth={1.6} /></span>
        <span className="dh-num">Step {i + 1}</span>
        <b>{title}</b>
        <p>{text}</p>
      </li>)}
      <li className="dh-step dh-branch">
        <span className="dh-node" aria-hidden="true"><Sparkles size={18} strokeWidth={1.6} /></span>
        <span className="dh-num">Extra · simulated</span>
        <b>Hypothetical outlook</b>
        <p>The DigiTwin engine simulates a range a few decades ahead from the data till today. A statistical extrapolation, not a prediction.</p>
      </li>
    </ol>

    <div className="dh-lower">
      <figure className="dh-example" aria-label="Example layout of a finding brief, not real data">
        <figcaption>Example layout, not real data</figcaption>
        <div className="dh-badges">
          <span className="dh-badge dh-badge-ok"><span aria-hidden="true">✓</span> VERIFIED</span>
          <span className="dh-badge dh-badge-gap"><span aria-hidden="true">✦</span> Potential new finding</span>
        </div>
        <p className="dh-title">Variable rising in a named region, start–end</p>
        <svg className="dh-chart" viewBox="0 0 240 60" preserveAspectRatio="none" role="img" aria-label="Placeholder chart shape">
          <rect x="150" y="2" width="88" height="56" className="dh-window" />
          <polyline points="0,44 20,40 40,46 60,38 80,42 100,35 120,39 140,30 160,33 180,24 200,27 220,18 240,20" className="dh-line" />
          <line x1="150" y1="0" x2="150" y2="60" className="dh-change" />
        </svg>
        <ul>
          <li><b>Drivers</b> associated with other variables (PCMCI+)</li>
          <li><b>Studies</b> closest related work with DOIs</li>
          <li><b>Notebook</b> a reproducible .ipynb</li>
        </ul>
      </figure>

      <div className="dh-side">
        <h4>Data sources</h4>
        <ul className="dh-chips">
          {SOURCES.map(s => <li key={s.name} className={s.unreviewed ? "dh-chip dh-chip-unreviewed" : "dh-chip"}>
            <b>{s.name}</b><span>{s.role}{s.unreviewed ? " · not peer reviewed" : ""}</span>
          </li>)}
        </ul>
        <button type="button" className="dh-try" onClick={() => onTry(DISCOVERY_EXAMPLE)}>
          Try a discovery <ArrowRight size={15} />
        </button>
        <details className="dh-dev">
          <summary>For developers: the data behind a finding</summary>
          <pre>{`type Finding = {
  title: string;
  verdict: { label: "VERIFIED" | "PROBABLE"; limit: string };
  potential_discovery: boolean | null; // null = literature not checked
  since: { date: string } | null;      // BEAST change date
  figure: { time: string[]; observed: (number | null)[] };
  outlook: { p05: number[]; p50: number[]; p95: number[]; disclaimer: string };
}`}</pre>
          <p>Places that were tested but not kept come back as <code>tested[]</code> cards with their series, rate and reason.</p>
        </details>
      </div>
    </div>
  </section>;
}
