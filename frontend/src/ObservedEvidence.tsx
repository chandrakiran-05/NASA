import { lazy, Suspense, useEffect, useRef, useState } from "react";
import {
  ArrowDownToLine,
  ArrowUpRight,
  Check,
  FileText,
  Upload,
  X,
} from "lucide-react";
import { api, exportURL } from "./api";
import Narrative from "./Narrative";
import "./evidence.css";
const EvidenceChart = lazy(() => import("./EvidenceChart"));
type Data = Record<string, any>;
type Props = {
  report: Data | null;
  plan: Data | null;
  busy: boolean;
  progress: { progress: number; message: string };
  error: string;
  onUpload: (file: File) => void;
  onCancel: () => void;
  onRegion: (geometry: Data) => void;
  onSelectSeries: (id: string) => void;
};
const views = [
  ["overview", "The record"],
  ["integrity", "Data integrity"],
  ["court", "Trend court"],
  ["clock", "Evidence clock"],
];
function number(value: unknown) {
  return typeof value === "number" && Number.isFinite(value)
    ? value.toLocaleString(undefined, { maximumSignificantDigits: 4 })
    : "Not returned";
}
export default function ObservedEvidence({
  report,
  plan,
  busy,
  progress,
  error,
  onUpload,
  onCancel,
  onRegion,
  onSelectSeries,
}: Props) {
  const [index, setIndex] = useState(0),
    [tab, setTab] = useState("overview"),
    [evidence, setEvidence] = useState<Data | null>(null),
    [tabError, setTabError] = useState("");
  const serial = useRef(0),
    request = useRef<AbortController | null>(null);
  const analysis = report?.results?.[index]?.analysis;
  const region = plan?.regions?.[index];
  const period = analysis?.period || plan?.period;
  const verdict = analysis?.verdict;
  const stamp =
    analysis?.court?.stamp ||
    (verdict?.significant === true
      ? "SIGNIFICANT"
      : verdict?.significant === false
        ? "NOT PROVEN"
        : null);
  useEffect(() => {
    setIndex(0);
    setTab("overview");
    setEvidence(null);
    setTabError("");
    serial.current++;
    request.current?.abort();
    return () => {
      request.current?.abort();
      serial.current++;
    };
  }, [report]);
  async function selectTab(next: string) {
    const token = ++serial.current;
    request.current?.abort();
    setTab(next);
    setEvidence(null);
    setTabError("");
    if (next === "overview" || !analysis) return;
    const controller = new AbortController();
    request.current = controller;
    try {
      const result = await (next === "integrity"
        ? api.integrity(analysis.series_id, controller.signal)
        : next === "court"
          ? api.court(analysis.series_id, controller.signal)
          : api.clock(analysis.series_id, controller.signal));
      if (token === serial.current && !controller.signal.aborted)
        setEvidence(result);
    } catch (e) {
      if (token === serial.current && !controller.signal.aborted)
        setTabError(
          e instanceof Error ? e.message : "Evidence could not be loaded.",
        );
    }
  }
  function selectRegion(i: number) {
    const next = report?.results?.[i];
    if (!next) return;
    request.current?.abort();
    serial.current++;
    setIndex(i);
    onSelectSeries(next.analysis.series_id);
    setTab("overview");
    setEvidence(null);
    setTabError("");
    const geometry = plan?.regions?.[i]?.geometry;
    if (geometry) onRegion(geometry);
  }
  return (
    <section
      className="workspace evidence-sheet"
      id="workspace"
      aria-labelledby="evidence-title"
    >
      <header className="evidence-sheet-head">
        <div>
          <h2 id="evidence-title">
            {region?.name || analysis?.label || "Your investigation"}
          </h2>
          <p className="evidence-file-meta">
            <FileText size={13} />
            <span>Evidence file</span>
            {period?.start && (
              <span>
                {period.start} — {period.end}
              </span>
            )}
          </p>
          <Narrative value={plan?.period?.note} />
        </div>
        <label className="evidence-upload">
          <Upload size={15} />
          <span>Use a monthly CSV</span>
          <input
            aria-label="Upload monthly CSV for analysis"
            type="file"
            accept=".csv,text/csv"
            disabled={busy}
            onChange={(e) => {
              if (e.target.files?.[0]) onUpload(e.target.files[0]);
              e.target.value = "";
            }}
          />
        </label>
      </header>
      {busy && (
        <div className="evidence-progress" role="status">
          <div>
            <span>{progress.message || "Preparing the regional record…"}</span>
            <button type="button" onClick={onCancel}>
              Stop waiting
              <X size={14} />
            </button>
          </div>
          <progress max={1} value={progress.progress} />
        </div>
      )}
      {error && (
        <div className="evidence-error" role="alert">
          <strong>The record could not be completed.</strong>
          <p>{error}</p>
        </div>
      )}
      {analysis && (
        <div className="evidence-sheet-body">
          <aside className="record-index" aria-label="Investigation index">
            <h3>Records</h3>
            <div className="record-index-items">
              {report?.results?.map((record: Data, i: number) => (
                <button
                  key={record.analysis.series_id || i}
                  aria-pressed={i === index}
                  onClick={() => selectRegion(i)}
                >
                  <span>
                    {plan?.regions?.[i]?.name ||
                      record.analysis.label ||
                      "Uploaded series"}
                  </span>
                  {i === index ? (
                    <Check size={13} />
                  ) : (
                    <ArrowUpRight size={13} />
                  )}
                </button>
              ))}
            </div>
            <p>Each record keeps its own test result and source.</p>
            {report?.comparison && (
              <details className="comparison-note">
                <summary>Regional comparison</summary>
                <Narrative value={report.comparison} />
                <pre>{JSON.stringify(report.comparison, null, 2)}</pre>
              </details>
            )}
          </aside>
          <div className="evidence-document">
            <nav className="evidence-contents" aria-label="Evidence views">
              {views.map(([id, label]) => (
                <button
                  key={id}
                  aria-pressed={tab === id}
                  onClick={() => void selectTab(id)}
                >
                  {label}
                </button>
              ))}
            </nav>
            <div className="evidence-reading-layout">
              <div className="evidence-reading-main">
                {tab === "overview" ? (
                  <>
                    <div className="record-heading">
                      <div>
                        <h3>{analysis.label || "Monthly observations"}</h3>
                        <p>
                          {analysis.deseasonalized === false
                            ? "Monthly record"
                            : "Seasonal cycle removed for trend testing"}
                        </p>
                      </div>
                      {analysis.units && <span>{analysis.units}</span>}
                    </div>
                    <Suspense
                      fallback={
                        <p className="evidence-loading" role="status">
                          Preparing the chart…
                        </p>
                      }
                    >
                      <EvidenceChart analysis={analysis} />
                    </Suspense>
                    <div className="record-summary">
                      <Narrative value={verdict?.plain_language} />
                    </div>
                    <dl className="record-facts">
                      {verdict?.rate_per_decade != null && (
                        <div>
                          <dt>Rate of change</dt>
                          <dd>
                            {number(verdict.rate_per_decade)}
                            <span>{verdict.rate_units}</span>
                          </dd>
                        </div>
                      )}
                      {verdict?.headline_p != null && (
                        <div>
                          <dt>Headline p-value</dt>
                          <dd>{number(verdict.headline_p)}</dd>
                        </div>
                      )}
                      {analysis.period?.n_valid != null && (
                        <div>
                          <dt>Valid observations</dt>
                          <dd>
                            {analysis.period.n_valid}
                            <span>monthly values</span>
                          </dd>
                        </div>
                      )}
                    </dl>
                  </>
                ) : evidence ? (
                  <div className="evidence-detail">
                    <h3>
                      {evidence.badge || evidence.stamp || "Evidence over time"}
                    </h3>
                    {tab === "clock" && (
                      <p className="evidence-exploratory">
                        Exploratory analysis — time windows are not independent
                        tests.
                      </p>
                    )}
                    <Narrative value={evidence} />
                    {tab === "court" && evidence.jurors?.length > 0 && (
                      <div className="court-table-wrap">
                        <table className="court-table">
                          <thead>
                            <tr>
                              <th scope="col">Method</th>
                              <th scope="col">Finding</th>
                            </tr>
                          </thead>
                          <tbody>
                            {evidence.jurors.map((juror: Data, i: number) => (
                              <tr key={i}>
                                <th scope="row">
                                  {juror.name || juror.test || juror.method}
                                </th>
                                <td>
                                  {juror.significant === true
                                    ? "SIGNIFICANT"
                                    : juror.significant === false
                                      ? "NOT PROVEN"
                                      : juror.verdict}
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    )}
                    <details>
                      <summary>Inspect the evidence response</summary>
                      <pre>{JSON.stringify(evidence, null, 2)}</pre>
                    </details>
                  </div>
                ) : tabError ? (
                  <div className="evidence-error" role="alert">
                    <p>{tabError}</p>
                  </div>
                ) : (
                  <p className="evidence-loading" role="status">
                    Reading{" "}
                    {views.find(([id]) => id === tab)?.[1].toLowerCase()}…
                  </p>
                )}
              </div>
              <aside className="verdict-margin" aria-label="Verdict and limits">
                <h3>The finding</h3>
                {stamp && (
                  <p
                    className={`finding-stamp ${stamp === "SIGNIFICANT" ? "is-significant" : ""}`}
                  >
                    {stamp}
                  </p>
                )}
                <Narrative value={verdict?.caveats} />
                <Narrative value={verdict?.notes} />
                {index === 0 && (
                  <Narrative value={report?.explanation?.explanation} />
                )}
                <p className="finding-note">
                  A statistical finding describes this record and period. Its
                  limits remain part of the answer.
                </p>
              </aside>
            </div>
            <footer className="record-provenance">
              <div>
                <h3>Follow the source</h3>
                <p>
                  {analysis.provenance?.dataset_short_name ||
                    analysis.provenance?.source_api ||
                    "Uploaded monthly series"}
                </p>
              </div>
              <a
                className="record-download"
                href={exportURL(analysis.series_id)}
              >
                <ArrowDownToLine size={15} />
                Download observations
              </a>
              <details>
                <summary>Provenance and retrieval details</summary>
                <dl>
                  {Object.entries(analysis.provenance || {})
                    .filter(([key]) =>
                      [
                        "dataset_short_name",
                        "source_api",
                        "version",
                        "doi",
                        "retrieved_at",
                        "citation",
                      ].includes(key),
                    )
                    .map(([key, value]) => (
                      <div key={key}>
                        <dt>{key.replaceAll("_", " ")}</dt>
                        <dd>{String(value)}</dd>
                      </div>
                    ))}
                </dl>
                <Narrative value={analysis.provenance?.notes} />
              </details>
            </footer>
          </div>
        </div>
      )}
    </section>
  );
}
