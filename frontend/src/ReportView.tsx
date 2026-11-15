import { lazy, Suspense, useEffect, useMemo, useState } from "react";
import { AlertTriangle, ArrowDownToLine, ArrowUp, Check, Info, MessageCircle, Printer, X } from "lucide-react";
import { cardURL, exportURL } from "./api";
import {
  aiLabel, buildStory, checkName, checkStatus, drawableMarkers, formatCell, heatmapCells, keyNumber,
  markerSentence, percent, perDecade, provenanceEntries, tableData, checksVerdict, checkText, type Report, type ReportSection,
  isImproving, sectionWording,
} from "./report";
import "./report.css";

const SeriesPlot = lazy(() => import("./ReportPlots").then((m) => ({ default: m.SeriesPlot })));
const MapPlot = lazy(() => import("./ReportPlots").then((m) => ({ default: m.MapPlot })));
const BarsPlot = lazy(() => import("./ReportPlots").then((m) => ({ default: m.BarsPlot })));

type Data = Record<string, any>;
type Props = {
  report: Report | null;
  busy: boolean;
  progress: { progress: number; message: string };
  error: string;
  onCancel: () => void;
  onConversation?: () => void;
};

const Paragraphs = ({ text }: { text: string }) =>
  text ? <div className="report-text">{text.split(/\n\s*\n/).map((p, i) => <p key={i}>{p}</p>)}</div> : null;

const PlotFallback = () => <p className="report-muted" role="status">Drawing the chart…</p>;

function Table({ data, caption }: { data: Data | null; caption: string }) {
  const { columns, rows } = tableData(data);
  if (!rows.length) return null;
  return (
    <div className="report-table-wrap">
      <table className="report-table">
        <caption className="sr-only">{caption}</caption>
        {columns && <thead><tr>{columns.map((c, i) => <th key={i} scope="col">{c}</th>)}</tr></thead>}
        <tbody>
          {rows.map((row, i) => (
            <tr key={i}>{row.map((cell, j) => (j === 0 ? <th key={j} scope="row">{formatCell(cell)}</th> : <td key={j} className={j > 1 ? "is-note" : undefined}>{formatCell(cell)}</td>))}</tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function StatusIcon({ status }: { status: string }) {
  const Icon = status === "pass" ? Check : status === "fail" ? X : status === "warn" ? AlertTriangle : Info;
  return <Icon size={14} aria-hidden="true" />;
}

function Checks({ data }: { data: Data | null }) {
  const checks: Data[] = Array.isArray(data?.checks) ? data!.checks : [];
  const verdict = checksVerdict(data);
  return (
    <div className="report-checks">
      {verdict && (
        <div className="report-verdict">
          {verdict.label && <p className={`report-stamp is-${verdict.label.toLowerCase().replaceAll(" ", "-")}`}>{verdict.label}</p>}
          {verdict.lines.map((l, i) => <p key={i}>{l}</p>)}
          {verdict.limit && <p className="report-limit"><b>Limit:</b> {verdict.limit}</p>}
        </div>
      )}
      {checks.length > 0 && (
        <ul>
          {checks.map((c, i) => {
            const s = checkStatus(c.status);
            const text = checkText(c);
            return (
              <li key={i} className={`is-${s.status}`}>
                <span className="report-check-status"><StatusIcon status={s.status} />{s.word}</span>
                <div>
                  <b>{checkName(c.check)}</b>
                  {text && <p>{text}</p>}
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}

/** Backend-written notes attached to a chart (caption, onset, limits). */
function ChartNotes({ data }: { data: Data }) {
  const lines = [data.caption, data.onset_plain_language].filter((x) => typeof x === "string" && x);
  const limits: string[] = Array.isArray(data.limits) ? data.limits.filter((x: unknown) => typeof x === "string") : [];
  if (!lines.length && !limits.length) return null;
  return (
    <div className="report-notes">
      {lines.map((l, i) => <p key={i}>{l}</p>)}
      {limits.length > 0 && <ul>{limits.map((l, i) => <li key={i}>{l}</li>)}</ul>}
    </div>
  );
}

function Segments({ data }: { data: Data }) {
  const segs: Data[] = Array.isArray(data.segments) ? data.segments.filter((x: unknown) => x && typeof x === "object") : [];
  if (!segs.length) return null;
  const unit = perDecade(String(data.units ?? ""));
  return (
    <div className="report-table-wrap">
      <table className="report-table">
        <caption className="sr-only">Trend before and after each detected change</caption>
        <thead><tr><th scope="col">Period</th><th scope="col">Trend ({unit})</th><th scope="col">95 % range</th><th scope="col">Significant</th></tr></thead>
        <tbody>
          {segs.map((g, i) => (
            <tr key={i}>
              <th scope="row">{g.start} – {g.end}</th>
              <td>{formatCell(g.slope_per_decade)}</td>
              <td>{Array.isArray(g.ci95_adj_per_decade) ? `${formatCell(g.ci95_adj_per_decade[0])} to ${formatCell(g.ci95_adj_per_decade[1])}` : "—"}</td>
              <td>{g.significant === true ? "Yes" : g.significant === false ? "No" : "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Papers({ research }: { research: Data | null | undefined }) {
  const papers: Data[] = Array.isArray(research?.papers) ? research!.papers.filter((p: Data) => p?.title) : [];
  if (!papers.length) return null;
  return (
    <div className="report-papers">
      <p className="report-eyebrow">Published research found{research?.since_year ? ` since ${research.since_year}` : ""}</p>
      <ol>
        {papers.slice(0, 6).map((p, i) => (
          <li key={i}>
            {p.url ? <a href={p.url} target="_blank" rel="noreferrer">{p.title}</a> : p.title}
            <span>{[p.year, p.venue, p.trust, p.stance && `reports: ${p.stance}`].filter(Boolean).join(" · ")}</span>
          </li>
        ))}
      </ol>
      {papers.length > 6 && <p className="report-muted">{papers.length - 6} more papers were found.</p>}
    </div>
  );
}

function MarkerList({ markers }: { markers: unknown }) {
  const list = drawableMarkers(markers);
  if (!list.length) return null;
  return (
    <ol className="report-markers" aria-label="Detected change dates">
      {list.map((m, i) => (
        <li key={i} className={`is-${m.kind}`}><span aria-hidden="true" className="report-marker-line" />{markerSentence(m)}</li>
      ))}
    </ol>
  );
}

function SeriesLinks({ id, hidden }: { id?: string; hidden: boolean }) {
  if (!id || hidden) return null;
  return (
    <p className="report-links">
      <a href={cardURL(id)} target="_blank" rel="noreferrer"><Printer size={14} /> Printable card</a>
      <a href={exportURL(id)}><ArrowDownToLine size={14} /> Download observations (CSV)</a>
    </p>
  );
}

function Visual({ section, fixture, drawnSeries }: { section: ReportSection; fixture: boolean; drawnSeries?: string }) {
  const { kind, data } = section;
  const label = section.text.split(/(?<=\.)\s/)[0] || section.title;
  if (kind === "table") return <Table data={data} caption={section.title} />;
  if (kind === "checks") return <Checks data={data} />;
  if (kind === "chart" && data?.chart && section.id !== "series" && drawnSeries && data.series_id === drawnSeries)
    // Same series as the main chart: show the change dates and the rates around them instead of a duplicate chart.
    return (
      <>
        <MarkerList markers={data.markers} />
        <Segments data={data} />
        {typeof data.onset_plain_language === "string" && <p className="report-legend-note">{data.onset_plain_language}</p>}
      </>
    );
  if (kind === "chart" && data?.chart)
    return (
      <>
        {data.label && <p className="report-figure-title">{data.label}{data.units ? ` · ${data.units}` : ""}</p>}
        <Suspense fallback={<PlotFallback />}><SeriesPlot data={data} label={label} /></Suspense>
        <p className="report-legend-note">
          Gaps are missing months; nothing is filled in. Vertical lines: solid = confirmed change, dashed = possible change, dotted = PELT break.
          {data.recent_window?.start ? ` Shaded band: recent window ${data.recent_window.start} – ${data.recent_window.end}.` : ""}
        </p>
        <MarkerList markers={data.markers} />
        <ChartNotes data={data} />
        <SeriesLinks id={data.series_id} hidden={fixture} />
      </>
    );
  if (kind === "map") {
    const map = heatmapCells(data);
    if (!map) return <p className="report-muted">The map grid was not returned for this question.</p>;
    return (
      <>
        <p className="report-figure-title"><span className="report-tag">Exploratory</span> Trend per grid cell, {map.units}</p>
        <Suspense fallback={<PlotFallback />}><MapPlot data={data!} label={label} /></Suspense>
        <dl className="report-figures">
          <div><dt>Area with a significant rise</dt><dd>{percent(map.areaRising)}</dd></div>
          <div><dt>Area with a significant fall</dt><dd>{percent(map.areaFalling)}</dd></div>
          <div><dt>Grid</dt><dd>{map.rows} × {map.cols} cells{map.missing ? `, ${map.missing} without data` : ""}</dd></div>
        </dl>
        <p className="report-legend-note">
          Colour: trend in {map.units}; red is rising, blue is falling, pale is near zero. A dot marks a cell the backend flagged as significant.
          Each cell is tested on its own, so read the map as a pattern, not as many separate proofs.
        </p>
        {typeof data?.field_significance?.plain_language === "string" && <p className="report-legend-note">{data.field_significance.plain_language}</p>}
      </>
    );
  }
  if (kind === "bars")
    return (
      <>
        <Suspense fallback={<PlotFallback />}><BarsPlot data={data!} label={label} /></Suspense>
        <p className="report-legend-note">Bars above the line are rising months; below the line, falling. Thin whiskers, when shown, are the 95 % range returned for each month.</p>
      </>
    );
  // text sections (and `when` without chart data) may still carry markers or research
  return (
    <>
      <MarkerList markers={data?.markers} />
      <Papers research={data?.research} />
    </>
  );
}

function Provenance({ report }: { report: Report }) {
  const entries = provenanceEntries(report.provenance);
  const extras = provenanceEntries(report.provenance, true);
  return (
    <div className="report-trust" aria-label="Source and limits">
      <div>
        <h3>Source</h3>
        {entries.length ? (
          <dl>{entries.map(([k, v]) => <div key={k}><dt>{k}</dt><dd>{v}</dd></div>)}</dl>
        ) : (
          <p className="report-muted">{report.plan.source || "The source was not returned."}</p>
        )}
        {extras.length > 0 && (
          <details className="report-more">
            <summary>Retrieval details</summary>
            <dl>{extras.map(([k, v]) => <div key={k}><dt>{k}</dt><dd>{v}</dd></div>)}</dl>
          </details>
        )}
      </div>
      <div>
        <h3>Limits</h3>
        {report.limits.length ? <ul>{report.limits.map((l, i) => <li key={i}>{l}</li>)}</ul> : <p className="report-muted">No limits were returned.</p>}
      </div>
    </div>
  );
}

export default function ReportView({ report, busy, progress, error, onCancel, onConversation }: Props) {
  const steps = useMemo(() => (report ? buildStory(report.sections) : []), [report]);
  const [current, setCurrent] = useState("");
  useEffect(() => {
    if (!steps.length) return;
    // The current section is the last one whose top has passed 30 % of the viewport.
    let frame = 0;
    const update = () => {
      frame = 0;
      let id = "";
      for (const s of steps) {
        const el = document.getElementById(s.anchor);
        if (el && el.getBoundingClientRect().top <= window.innerHeight * 0.3) id = s.anchor;
      }
      setCurrent(id);
    };
    const onScroll = () => { if (!frame) frame = requestAnimationFrame(update); };
    update();
    document.addEventListener("scroll", onScroll, { passive: true, capture: true });
    return () => { document.removeEventListener("scroll", onScroll, { capture: true }); cancelAnimationFrame(frame); };
  }, [steps]);

  useEffect(() => {
    // Keep the active entry visible in the horizontally scrolling mobile contents strip.
    const link = current ? document.querySelector<HTMLElement>(`.report-toc a[href="#${current}"]`) : null;
    const strip = link?.closest<HTMLElement>(".report-toc");
    if (link && strip && strip.scrollWidth > strip.clientWidth) strip.scrollTo({ left: link.offsetLeft - 16 });
  }, [current]);

  const label = aiLabel(report?.ai);
  const seriesData = report?.sections.find((x) => x.id === "series")?.data;
  const drawnSeries = seriesData?.chart && typeof seriesData.series_id === "string" ? seriesData.series_id : undefined;
  const key = report ? keyNumber(report.sections) : null;
  const plan = report?.plan ?? {};
  const meta = [plan.region_name, plan.variable_name, plan.start && `${plan.start} – ${plan.end ?? ""}`, plan.units && `units: ${plan.units}`].filter(Boolean);

  return (
    <section className="report" id="workspace" aria-labelledby="report-title" aria-busy={busy}>
      {busy && report && (
        <div className="report-improving" role="status">
          <span className="report-spinner" aria-hidden="true" />
          <p>
            <b>Report ready.</b> {isImproving(report) ? "Improving the wording section by section" : "Finishing"}
            {progress.message ? `: ${progress.message}` : ""}. Every number shown is already final.
          </p>
          <button type="button" className="report-button" onClick={onCancel}>Stop <X size={14} /></button>
        </div>
      )}
      {busy && !report && (
        <div className="report-loading" role="status">
          <p className="report-eyebrow">Building your report</p>
          <p className="report-loading-message">{progress.message || "Starting…"}</p>
          <progress max={1} value={progress.progress || 0} aria-label="Report progress" />
          <p className="report-muted">{Math.round((progress.progress || 0) * 100)} % · Live data can take several minutes. Stopping only stops waiting; the backend job may continue.</p>
          <button type="button" className="report-button" onClick={onCancel}>Stop waiting <X size={14} /></button>
        </div>
      )}
      {error && !busy && (
        <div className="report-error" role="alert"><strong>The report could not be completed.</strong><p>{error}</p></div>
      )}
      {report && (
        <>
          {report.fixture && <p className="report-fixture" role="note">Sample fixture for development: {report.fixture}</p>}
          <header className="report-head">
            <p className="report-eyebrow">{report.question || "Your question"}</p>
            {meta.length > 0 && <p className="report-meta">{meta.map((m, i) => <span key={i}>{m}</span>)}</p>}
            <h2 id="report-title">{report.headline || "Your report"}</h2>
            <div className="report-key-row">
              {key && (
                <p className="report-key"><span className="report-key-value">{key.value}</span><span className="report-key-label">{key.label}</span></p>
              )}
              <p className={`report-ai is-${label.kind}`}>{label.text}{isImproving(report) ? " · AI wording on the way" : ""}</p>
            </div>
            <Provenance report={report} />
          </header>
          <div className="report-body">
            <nav className="report-toc" aria-label="Report sections">
              <p>In this report</p>
              <ol>
                {steps.map((s) => (
                  <li key={s.anchor}>
                    <a href={`#${s.anchor}`} aria-current={current === s.anchor ? "true" : undefined}>
                      <span>{String(s.number).padStart(2, "0")}</span>{s.section.title}
                    </a>
                  </li>
                ))}
                {report.glossary.length > 0 && <li><a href="#report-glossary"><span>—</span>Glossary</a></li>}
              </ol>
            </nav>
            <div className="report-story">
              {steps.map((s) => (
                <section key={s.anchor} id={s.anchor} className={`report-step kind-${s.section.kind}`} aria-labelledby={`${s.anchor}-title`}>
                  <header>
                    <span className="report-number" aria-hidden="true">{String(s.number).padStart(2, "0")}</span>
                    <h3 id={`${s.anchor}-title`}><span className="sr-only">Section {s.number}: </span>{s.section.title}</h3>
                  </header>
                  {(() => {
                    const w = sectionWording(s.section, report.ai);
                    return w.kind ? <p className={`report-wording is-${w.kind}`} aria-live="polite">{w.note}</p> : null;
                  })()}
                  <Paragraphs text={s.section.text} />
                  <Visual section={s.section} fixture={!!report.fixture} drawnSeries={drawnSeries} />
                  {s.bridge && <p className="report-bridge">{s.bridge}</p>}
                </section>
              ))}
              {report.glossary.length > 0 && (
                <section id="report-glossary" className="report-step report-glossary" aria-labelledby="report-glossary-title">
                  <header><span className="report-number" aria-hidden="true">—</span><h3 id="report-glossary-title">Glossary</h3></header>
                  <dl>{report.glossary.map((g) => <div key={g.term}><dt>{g.term}</dt><dd>{g.meaning}</dd></div>)}</dl>
                </section>
              )}
              <footer className="report-end">
                <a href="#workspace"><ArrowUp size={14} /> Back to the answer</a>
                {onConversation && <button type="button" className="report-button" onClick={onConversation}><MessageCircle size={14} /> Ask a follow-up question</button>}
              </footer>
            </div>
          </div>
        </>
      )}
    </section>
  );
}
