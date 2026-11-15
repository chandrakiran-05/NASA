import { useEffect, useRef } from "react";
import Plotly from "plotly.js-basic-dist-min";
import type { SeriesView } from "./api";

const markerStyle: Record<string, { color: string; dash: string; label: string }> = {
  beast_confirmed: { color: "#c45036", dash: "solid", label: "BEAST change (confirmed)" },
  beast_possible: { color: "#c45036", dash: "dash", label: "BEAST change (possible)" },
  pelt_break: { color: "#3e5f8a", dash: "dot", label: "PELT break" },
};

/** Draws GET /api/view or trend.view: observed + Sen line, BEAST change probability, markers, recent window. */
function viewFigure(view: SeriesView): { traces: Plotly.Data[]; shapes: Partial<Plotly.Shape>[] } {
  const c = view.chart;
  const traces: Plotly.Data[] = [
    { x: c.time, y: c.observed, name: "Observed (monthly)", type: "scatter", mode: "lines", connectgaps: false, line: { color: "#7a9089", width: 1 } },
    { x: c.time, y: c.sen_line, name: "Sen’s trend", type: "scatter", mode: "lines", connectgaps: false, line: { color: "#c45036", width: 2.2 } },
  ];
  if (c.change_probability?.some((v) => v != null))
    traces.push({
      x: c.time, y: c.change_probability, name: "BEAST change probability", yaxis: "y2", type: "scatter", mode: "lines",
      connectgaps: false, fill: "tozeroy", line: { color: "#b08a3e", width: 1 }, fillcolor: "rgba(176,138,62,0.22)",
    });
  const shapes: Partial<Plotly.Shape>[] = [];
  if (view.recent_window)
    shapes.push({ type: "rect", xref: "x", yref: "paper", x0: view.recent_window.start, x1: view.recent_window.end, y0: 0, y1: 1,
      fillcolor: "rgba(196,80,54,0.07)", line: { width: 0 }, layer: "below" });
  const seen = new Set<string>();
  for (const m of view.markers) {
    const st = markerStyle[m.kind];
    if (!st) continue; // weak BEAST events are not drawn
    shapes.push({ type: "line", xref: "x", yref: "paper", x0: m.date, x1: m.date, y0: 0.18, y1: 1, line: { color: st.color, width: 1.4, dash: st.dash as Plotly.Dash } });
    if (!seen.has(m.kind)) {
      seen.add(m.kind); // legend entry for the shape style
      traces.push({ x: [null], y: [null], name: st.label, type: "scatter", mode: "lines", line: { color: st.color, dash: st.dash as Plotly.Dash } });
    }
  }
  return { traces, shapes };
}

export default function EvidenceChart({
  analysis,
  view,
}: {
  analysis?: Record<string, any>;
  view?: SeriesView;
}) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const c = view ? null : analysis?.chart;
    if (!view && !c) return;
    const fig = view ? viewFigure(view) : null;
    const traces: Plotly.Data[] = fig ? fig.traces : [
      {
        x: c.time,
        y: c.deseasonalized,
        name: "Deseasonalized observations",
        type: "scatter",
        mode: "lines",
        connectgaps: false,
        line: { color: "#7a9089", width: 1.2 },
      },
      {
        x: c.time,
        y: c.sen_line,
        name: "Sen’s trend",
        type: "scatter",
        mode: "lines",
        connectgaps: false,
        line: { color: "#c45036", width: 2.2 },
      },
    ];
    const units = view ? view.units : analysis?.units;
    void Plotly.newPlot(
      el,
      traces,
      {
        autosize: true,
        height: window.matchMedia("(max-width:700px)").matches ? 310 : 345,
        margin: { l: 55, r: 12, t: 22, b: 55 },
        paper_bgcolor: "transparent",
        plot_bgcolor: "transparent",
        font: {
          family: "DM Sans, Arial, sans-serif",
          color: "#5f6862",
          size: 11,
        },
        xaxis: {
          gridcolor: "#dedfd5",
          zeroline: false,
          title: { text: "Year" },
        },
        yaxis: {
          gridcolor: "#dedfd5",
          zeroline: false,
          title: { text: units || "" },
          ...(fig ? { domain: [0.18, 1] } : {}),
        },
        ...(fig
          ? {
              yaxis2: { domain: [0, 0.14], range: [0, 1], title: { text: "P(change)" }, gridcolor: "#dedfd5", zeroline: false },
              shapes: fig.shapes,
            }
          : {}),
        legend: { orientation: "h", y: -0.2, font: { size: 10 } },
        hoverlabel: {
          bgcolor: "#f6f3eb",
          bordercolor: "#bcbfb5",
          font: {
            color: "#242c29",
            family: "DM Sans, Arial, sans-serif",
            size: 12,
          },
        },
        showlegend: true,
      },
      { responsive: true, displayModeBar: false },
    );
    const observer = new ResizeObserver(() => {
      if (el.clientWidth > 0) void Plotly.Plots.resize(el);
    });
    observer.observe(el);
    return () => {
      observer.disconnect();
      Plotly.purge(el);
    };
  }, [analysis, view]);
  return (
    <div
      ref={ref}
      className="evidence-chart"
      role="img"
      aria-label={
        (view
          ? view.caption
          : analysis?.verdict?.plain_language) ||
        `Monthly ${view?.label ?? analysis?.label} in ${view?.units ?? analysis?.units}. Missing observations appear as gaps.`
      }
    />
  );
}
