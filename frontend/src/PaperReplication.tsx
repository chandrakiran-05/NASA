import { useEffect, useRef, useState } from "react";
import { ApiError } from "./api";
import {
  badgeClass, fmtP, fmtSlope, getReplication, outlinePath, runReplication,
  type Replication, type River, type RunResult,
} from "./replicationApi";
import "./replication.css";

type Fig = { data: Record<string, unknown>[]; layout: Record<string, unknown> };
type PlotlyLib = typeof import("plotly.js-basic-dist-min").default;
const FONT = { family: "DM Sans, Arial, sans-serif", color: "#4d564f", size: 11 };
const GRID = "#dcdbd0";
const COLORS = { Consistent: "#2f6b45", Differs: "#a63029", "Not enough data": "#8b9188" } as const;
let plotly: Promise<PlotlyLib> | null = null;
const loadPlotly = () => (plotly ??= import("plotly.js-basic-dist-min").then((m) => m.default));

/** Plotly is loaded on first use, so the page does not pay for it until a chart is on screen. */
function Plot({ fig, label, onClick }: { fig: Fig | null; label: string; onClick?: (index: number) => void }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const el = ref.current;
    if (!el || !fig) return;
    let gone = false;
    let observer: ResizeObserver | null = null;
    void loadPlotly().then((P) => {
      if (gone) return;
      void P.newPlot(el, fig.data as Plotly.Data[], {
        autosize: true, paper_bgcolor: "transparent", plot_bgcolor: "transparent", font: FONT,
        hoverlabel: { bgcolor: "#fbf9f3", bordercolor: "#b9bcb1", font: { ...FONT, color: "#1f2723", size: 12 } },
        ...fig.layout,
      } as Partial<Plotly.Layout>, { responsive: true, displayModeBar: false }).then(() => {
        if (onClick) (el as unknown as Plotly.PlotlyHTMLElement).on("plotly_click", (e) => {
          const pt = e.points[0];
          if (pt && pt.customdata != null) onClick(Number(pt.customdata));
        });
      });
      observer = new ResizeObserver(() => { if (el.clientWidth > 0) void P.Plots.resize(el); });
      observer.observe(el);
    });
    return () => {
      gone = true;
      observer?.disconnect();
      void loadPlotly().then((P) => P.purge(el));
    };
  }, [fig]);
  return <div ref={ref} className="rep-plot" role="img" aria-label={label} />;
}

function useOutlines() {
  const [path, setPath] = useState<ReturnType<typeof outlinePath> | null>(null);
  useEffect(() => {
    fetch("/geography/countries.json").then((r) => (r.ok ? r.json() : [])).then((f) => setPath(outlinePath(f))).catch(() => setPath({ x: [], y: [] }));
  }, []);
  return path;
}

function mapFig(rivers: River[], outline: ReturnType<typeof outlinePath>, selected: string | null): Fig {
  return {
    data: [
      { x: outline.x, y: outline.y, type: "scatter", mode: "lines", line: { color: "#b9bcb1", width: 0.7 }, hoverinfo: "skip", showlegend: false },
      ...(["Consistent", "Differs", "Not enough data"] as const).map((label) => {
        const idx = rivers.map((r, i) => [r, i] as const).filter(([r]) => r.agreement.label === label);
        return {
          x: idx.map(([r]) => r.centre[0]), y: idx.map(([r]) => r.centre[1]), customdata: idx.map(([, i]) => i),
          text: idx.map(([r]) => r.name), type: "scatter", mode: "markers+text", textposition: idx.map(([r]) => (r.id === "mississippi_east" ? "bottom right" : r.id === "mississippi_west" ? "top left" : "top center")),
          name: label === "Not enough data" ? "Not run / not enough data" : `${label} with the paper`,
          textfont: { size: 10.5, color: "#1f2723" },
          marker: {
            size: idx.map(([r]) => (r.id === selected ? 15 : 11)), color: COLORS[label],
            symbol: label === "Consistent" ? "circle" : label === "Differs" ? "diamond" : "circle-open",
            line: { width: 1.5, color: label === "Not enough data" ? COLORS[label] : "#fbf9f3" },
          },
          hovertemplate: "%{text}<br>%{y:.2f}°N, %{x:.2f}°E<extra>0.5° box</extra>",
        };
      }),
    ],
    layout: {
      height: 380, margin: { l: 8, r: 8, t: 8, b: 8 }, dragmode: false,
      xaxis: { range: [-140, 140], visible: false, fixedrange: true },
      yaxis: { range: [-35, 60], visible: false, scaleanchor: "x", fixedrange: true },
      legend: { orientation: "h", y: 0.02, x: 0.01, bgcolor: "rgba(246,243,235,0.85)", font: { size: 10.5 } },
    },
  };
}

function seriesFig(run: RunResult): Fig | null {
  if (!run.series || !run.monthly) return null;
  return {
    data: [
      { x: run.series.time, y: run.series.value, type: "scatter", mode: "lines+markers", name: "Monthly area mean",
        line: { color: "#5a635c", width: 1 }, marker: { size: 3 }, connectgaps: false },
      { x: run.series.time, y: run.series.fit, type: "scatter", mode: "lines", name: "Least-squares line",
        line: { color: "#b5452f", width: 2.4 } },
    ],
    layout: {
      height: 300, margin: { l: 56, r: 10, t: 10, b: 40 },
      xaxis: { type: "date", gridcolor: GRID, zeroline: false },
      yaxis: { title: { text: `Chlorophyll a (${run.monthly.units})` }, gridcolor: GRID, zeroline: false },
      legend: { orientation: "h", y: 1.1 },
    },
  };
}

function yearlyFig(run: RunResult): Fig | null {
  const ys = run.yearly_series;
  if (!ys || !ys.year.length) return null;
  return {
    data: [
      { x: ys.year, y: ys.anomaly, type: "bar", name: "Yearly anomaly", customdata: ys.n_months,
        marker: { color: ys.anomaly.map((v) => (v >= 0 ? "#086bdc" : "#b5452f")) },
        hovertemplate: "%{x}: %{y:+.4f} mg m-3<br>from %{customdata} valid months<extra></extra>" },
      ...(ys.fit ? [{ x: ys.year, y: ys.fit, type: "scatter", mode: "lines", name: "Regression line", line: { color: "#1f2723", width: 2 } }] : []),
    ],
    layout: {
      height: 260, margin: { l: 56, r: 10, t: 10, b: 36 },
      xaxis: { gridcolor: GRID, dtick: 2 }, yaxis: { title: { text: "Anomaly (mg m-3)" }, gridcolor: GRID, zeroline: true, zerolinecolor: "#9a9d93" },
      legend: { orientation: "h", y: 1.12 }, bargap: 0.25,
    },
  };
}

const Sig = ({ yes }: { yes: boolean }) => <span className={yes ? "rep-sig is-yes" : "rep-sig"}>{yes ? "significant" : "not significant"}</span>;

function RunCell({ run }: { run: RunResult | null }) {
  if (!run) return <td className="rep-muted">not run yet</td>;
  if (run.status !== "ok" || !run.monthly) return <td className="rep-muted">{run.message ?? "not enough data"}</td>;
  const m = run.monthly;
  return (
    <td>
      <strong>{fmtSlope(m.slope_per_month)}</strong> <span className="rep-muted">mg m-3 / month</span>
      <div>{fmtP(m.p)} · <Sig yes={m.significant} /></div>
      <div className="rep-muted">{run.period?.start}–{run.period?.end} · {run.n_valid} valid months{run.substitute ? " · substitute sensor" : ""}</div>
    </td>
  );
}

function Stat({ k, v }: { k: string; v: string }) {
  return <div><dt>{k}</dt><dd>{v}</dd></div>;
}

function RunDetail({ run, title }: { run: RunResult | null; title: string }) {
  if (!run) return <p className="rep-muted">{title}: not run yet.</p>;
  if (run.status !== "ok" || !run.monthly) return <p className="rep-muted">{title}: {run.message ?? "not enough data"}.</p>;
  const m = run.monthly, y = run.yearly;
  return (
    <div className="rep-run">
      <h4>{title}</h4>
      <p className="rep-muted">{run.dataset}</p>
      <dl className="rep-stats">
        <Stat k="Slope" v={`${fmtSlope(m.slope_per_month)} mg m-3/month (${fmtSlope(m.slope_per_decade, 3)} per decade)`} />
        <Stat k="ANOVA F-test" v={`F = ${m.F.toFixed(2)}, ${fmtP(m.p)}`} />
        <Stat k="R²" v={m.r2.toFixed(4)} />
        <Stat k="Mean" v={`${m.mean.toFixed(3)} mg m-3`} />
        <Stat k="Valid months" v={`${run.n_valid} of ${run.n_months}`} />
        <Stat k="Persistence-corrected" v={`${fmtP(m.p_persistence_corrected)} (${m.significant_persistence_corrected ? "significant" : "not significant"})`} />
      </dl>
      <Plot fig={seriesFig(run)} label={`Monthly chlorophyll a with least-squares line, slope ${fmtSlope(m.slope_per_month)} mg m-3 per month, ${fmtP(m.p)}`} />
      {y && (
        <>
          <p className="rep-muted">Yearly anomalies: slope {fmtSlope(y.slope_per_year)} mg m-3/year, F = {y.F.toFixed(2)}, {fmtP(y.p)}, R² = {y.r2.toFixed(3)}, {y.n_years} years.</p>
          <Plot fig={yearlyFig(run)} label={`Yearly chlorophyll a anomalies, regression ${fmtP(y.p)}`} />
        </>
      )}
      {run.variant?.monthly && (
        <p className="rep-note">{run.variant.label}: slope {fmtSlope(run.variant.monthly.slope_per_month)} mg m-3/month, F = {run.variant.monthly.F.toFixed(2)}, {fmtP(run.variant.monthly.p)} ({run.variant.monthly.significant ? "significant" : "not significant"}).</p>
      )}
      {run.provenance && (
        <p className="rep-prov">
          Source: {run.provenance.dataset_short_name} {run.provenance.version} via {run.provenance.source_api}
          {run.provenance.doi ? <> · DOI <a href={`https://doi.org/${run.provenance.doi}`} target="_blank" rel="noreferrer">{run.provenance.doi}</a></> : null}
          {run.provenance.retrieved_at ? ` · retrieved ${run.provenance.retrieved_at.slice(0, 10)}` : ""}
          {run.area_mean_note ? ` · ${run.area_mean_note}` : ""}
        </p>
      )}
    </div>
  );
}

export default function PaperReplication() {
  const [data, setData] = useState<Replication | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [job, setJob] = useState<{ progress: number; message: string } | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const outline = useOutlines();

  useEffect(() => {
    const ac = new AbortController();
    getReplication(ac.signal).then(setData).catch((e) => { if (!ac.signal.aborted) setError(e instanceof ApiError ? e.message : String(e)); });
    return () => ac.abort();
  }, []);

  const run = async () => {
    setError(null);
    setJob({ progress: 0, message: "Starting" });
    try {
      setData(await runReplication({ onProgress: (j) => setJob({ progress: j.progress, message: j.message }) }));
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    } finally {
      setJob(null);
    }
  };

  const river = data?.rivers.find((r) => r.id === selected) ?? null;
  const [fig, setFig] = useState<Fig | null>(null);
  useEffect(() => { if (data && outline) setFig(mapFig(data.rivers, outline, selected)); }, [data, outline, selected]);

  return (
    <section className="rep" aria-labelledby="rep-title">
      <p className="rep-eyebrow">Replication · NASA technical report</p>
      <h2 id="rep-title">Replicating a NASA study, live.</h2>
      <p className="rep-lede">
        In a NASA study, Acker and colleagues measured how green the sea is (chlorophyll a, from the SeaWiFS satellite)
        in small 0.5° boxes off ten river mouths, month by month from 1998 to 2007. They fitted a straight line to
        each series and tested it with an F-test. They found no significant trend off the least-disturbed rivers,
        significant falls off most rivers that people have changed most, and a rise off the Pearl River.
        Here we run the same method again on NASA satellite data, then extend it to today.{" "}
        {data && <a href={data.paper.url} target="_blank" rel="noreferrer">Read the paper on NASA NTRS</a>}
      </p>

      {error && <div className="rep-error" role="alert"><strong>Could not load the replication.</strong> <span>{error}</span></div>}
      {!data && !error && <p className="rep-muted">Loading the published table…</p>}

      {data && (
        <>
          <div className="rep-run-bar">
            <button type="button" className="rep-button" onClick={run} disabled={!!job}>
              {data.cached ? "Run the replication again" : "Run the replication"}
            </button>
            {job ? (
              <div className="rep-progress" aria-live="polite">
                <progress value={job.progress} max={1} />
                <span>{job.message}</span>
              </div>
            ) : (
              <span className="rep-muted">{data.updated_at ? `Results from ${data.updated_at.slice(0, 16).replace("T", " ")} UTC (cached).` : "Takes a few minutes the first time; later runs come from the cache."}</span>
            )}
          </div>
          <p className="rep-summary">{data.summary}</p>

          <div className="rep-grid">
            <div>
              {fig ? <Plot fig={fig} label="World map of the ten river outflow boxes, coloured by agreement with the paper" onClick={(i) => setSelected(data.rivers[i]?.id ?? null)} /> : <div className="rep-plot rep-muted">Loading map…</div>}
              <p className="rep-muted">Click a river on the map or in the table to see its series.</p>
            </div>
            <div className="rep-table-wrap">
              <table className="rep-table">
                <thead>
                  <tr><th>River</th><th>Published (SeaWiFS 1998–2007)</th><th>Our replication</th><th>Our extension to today</th><th>Agreement</th></tr>
                </thead>
                <tbody>
                  {data.rivers.map((r) => (
                    <tr key={r.id} className={r.id === selected ? "is-selected" : ""} onClick={() => setSelected(r.id)}>
                      <th scope="row">
                        <button type="button" className="rep-link" onClick={() => setSelected(r.id)}>{r.name}</button>
                        <div className="rep-muted">{r.published.distance_km} km of river influence</div>
                      </th>
                      <td>
                        <strong>{fmtSlope(r.published.slope_per_month)}</strong> <span className="rep-muted">mg m-3 / month</span>
                        <div>{fmtP(r.published.p)} · <Sig yes={r.published.significant} /></div>
                        {r.published.footnote_text && <div className="rep-muted">{r.published.footnote} {r.published.footnote_text}</div>}
                      </td>
                      <RunCell run={r.replication} />
                      <RunCell run={r.extension} />
                      <td>
                        <span className={`rep-badge ${badgeClass(r.agreement.label)}`} title={r.agreement.plain_language}>{r.agreement.label}</span>
                        {r.extension?.status === "ok" && <div className="rep-muted">extension: {r.extension_agreement.label.toLowerCase()}</div>}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          {river && (
            <div className="rep-detail" aria-live="polite">
              <h3>{river.name} outflow box <span className="rep-muted">{river.box.south}–{river.box.north}°N, {river.box.west}–{river.box.east}°E</span></h3>
              <p>{river.agreement.plain_language}</p>
              <div className="rep-detail-grid">
                <RunDetail run={river.replication} title="Replication" />
                <RunDetail run={river.extension} title="Extension to the latest full year" />
              </div>
            </div>
          )}

          <div className="rep-method">
            <h3>Method, step by step</h3>
            <ol>
              <li><strong>Area mean.</strong> For each month, average the chlorophyll a of every valid satellite cell in the 0.5° box. Cloudy months stay missing; nothing is filled in.</li>
              <li><strong>Straight line + F-test.</strong> Fit a least-squares line through all monthly values. An ANOVA F-test asks whether the line explains more than chance would; p &lt; 0.05 counts as significant. R² is the share of month-to-month variation the line explains.</li>
              <li><strong>Yearly anomalies.</strong> Subtract each calendar month's average (all Januaries, all Februaries…) to remove the seasons, then average those anomalies within each year.</li>
              <li><strong>Regression on years.</strong> Fit a line through the yearly anomalies and test it the same way.</li>
            </ol>
            <ul className="rep-notes">
              {data.notes.map((n) => <li key={n}>{n}</li>)}
            </ul>
            <p className="rep-muted">Agreement means the same significance call (p &lt; 0.05) as the paper and, where the paper found a significant trend, the same direction; it is "consistent with the published result", not proof that either is right.</p>
            <p className="rep-cite">{data.paper.citation}</p>
          </div>
        </>
      )}
    </section>
  );
}
