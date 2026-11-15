import { useEffect, useRef } from "react";
import Plotly from "plotly.js-basic-dist-min";
import { SeriesPlot } from "./ReportPlots";
import type { DiscoveryBrief, TestedCard, WhatIfPlace } from "./discoveryApi";

const FONT = { family: "DM Sans, Arial, sans-serif", color: "#4d564f", size: 11 };
const GRID = "#dcdbd0";

/** The finding's monthly record, drawn by the shared report chart (BEAST change date and recent window marked). */
export function FindingSeries({ brief }: { brief: DiscoveryBrief }) {
  const f = brief.figure;
  const view = {
    units: f.units,
    chart: { time: f.time, observed: f.observed, deseasonalized: f.deseasonalized, sen_line: f.sen_line, beast_trend: f.beast_trend },
    markers: f.markers ?? [],
    recent_window: f.recent_window,
  };
  return <SeriesPlot data={view} label={`${brief.title}. ${brief.what}`} />;
}

/** A tested place that did not pass: its real monthly record (all values from the API), recent window shaded. */
export function TestedSeries({ card }: { card: TestedCard }) {
  const f = card.figure;
  if (!f?.time?.length) return null;
  const view = {
    units: f.units ?? card.variable.units,
    chart: { time: f.time, observed: f.observed, deseasonalized: f.deseasonalized, sen_line: f.sen_line, beast_trend: f.beast_trend },
    markers: f.markers ?? [],
    recent_window: f.recent_window,
  };
  return <SeriesPlot data={view} label={`${card.variable.name} in ${card.place}. ${card.reason ?? ""}`} />;
}

/** Simulated outlook: 5-95% band and median of simulated annual means, all values from the API. */
export function OutlookPlot({ brief }: { brief: DiscoveryBrief }) {
  const ref = useRef<HTMLDivElement>(null);
  const o = brief.outlook;
  useEffect(() => {
    const el = ref.current;
    if (!el || o.status !== "ok" || !o.time?.length) return;
    const units = o.units ? ` (${o.units})` : "";
    void Plotly.newPlot(el, [
      { x: o.time, y: o.p95, type: "scatter", mode: "lines", line: { width: 0 }, hoverinfo: "skip", showlegend: false },
      { x: o.time, y: o.p05, type: "scatter", mode: "lines", line: { width: 0 }, fill: "tonexty",
        fillcolor: "rgba(122,92,180,0.18)", name: "Simulated 5-95% range" },
      { x: o.time, y: o.p50, type: "scatter", mode: "lines", line: { color: "#6a4fb0", width: 2, dash: "dot" },
        name: "Simulated median" },
    ] as Plotly.Data[], {
      autosize: true, height: 300, paper_bgcolor: "transparent", plot_bgcolor: "transparent", font: FONT,
      margin: { l: 62, r: 14, t: 40, b: 40 },
      title: { text: "Simulated, not observed", font: { size: 12 } },
      xaxis: { gridcolor: GRID, zeroline: false, type: "date", title: { text: "Year" } },
      yaxis: { gridcolor: GRID, zeroline: false, title: { text: `Annual mean${units}`, font: { size: 10.5 } } },
      legend: { orientation: "h", x: 0, y: -0.25 },
    } as Partial<Plotly.Layout>, { responsive: true, displayModeBar: false });
    const observer = new ResizeObserver(() => { if (el.clientWidth > 0) void Plotly.Plots.resize(el); });
    observer.observe(el);
    return () => { observer.disconnect(); Plotly.purge(el); };
  }, [o]);
  if (o.status !== "ok") return null;
  return <div ref={ref} className="report-plot discovery-outlook-plot" role="img"
    aria-label={`Simulated outlook band. ${o.plain_language ?? ""} ${o.disclaimer}`} />;
}

/** What-if for one place: observed annual means, then the simulated band with and without the change. */
export function WhatIfPlot({ place }: { place: WhatIfPlace }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const s = place.simulated, x = s.years.map(String), ox = place.observed.years.map(String);
    const band = (b: { p05: number[]; p95: number[] }, fill: string, name: string) => [
      { x, y: b.p95, type: "scatter", mode: "lines", line: { width: 0 }, hoverinfo: "skip", showlegend: false },
      { x, y: b.p05, type: "scatter", mode: "lines", line: { width: 0 }, fill: "tonexty", fillcolor: fill, name },
    ];
    void Plotly.newPlot(el, [
      ...band(s.without_change, "rgba(120,128,122,0.18)", "Without the change (simulated 5-95%)"),
      { x, y: s.without_change.p50, type: "scatter", mode: "lines", line: { color: "#7a827c", width: 1.5, dash: "dot" }, name: "Without the change, median" },
      ...band(s.with_change, "rgba(233,161,127,0.30)", "With the change (simulated 5-95%)"),
      { x, y: s.with_change.p50, type: "scatter", mode: "lines", line: { color: "#d9774a", width: 2.4 }, name: "With the change, median" },
      { x: ox, y: place.observed.annual_mean, type: "scatter", mode: "lines+markers", connectgaps: false,
        line: { color: "#242c29", width: 1.6 }, marker: { size: 3 }, name: "Observed annual mean" },
    ] as Plotly.Data[], {
      autosize: true, height: 340, paper_bgcolor: "transparent", plot_bgcolor: "transparent", font: FONT,
      margin: { l: 58, r: 14, t: 36, b: 44 },
      title: { text: `${place.place}: observed, then simulated (not a prediction)`, font: { size: 12 } },
      xaxis: { gridcolor: GRID, zeroline: false, title: { text: "Year" } },
      yaxis: { gridcolor: GRID, zeroline: false, title: { text: `Annual mean (${place.units})`, font: { size: 10.5 } } },
      legend: { orientation: "h", x: 0, y: -0.22, font: { size: 10 } },
      shapes: [{ type: "line", xref: "x", yref: "paper", x0: x[0], x1: x[0], y0: 0, y1: 1, line: { color: "#b9b6a8", width: 1, dash: "dash" } }],
    } as Partial<Plotly.Layout>, { responsive: true, displayModeBar: false });
    const observer = new ResizeObserver(() => { if (el.clientWidth > 0) void Plotly.Plots.resize(el); });
    observer.observe(el);
    return () => { observer.disconnect(); Plotly.purge(el); };
  }, [place]);
  return <div ref={ref} className="report-plot whatif-plot" role="img" aria-label={place.plain_language} />;
}

export default { FindingSeries, OutlookPlot, TestedSeries, WhatIfPlot };
