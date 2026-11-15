import { useEffect, useRef } from "react";
import Plotly from "plotly.js-basic-dist-min";
import { barsData, DIVERGING, heatmapCells, seriesFigure } from "./report";

type Data = Record<string, any>;
const FONT = { family: "DM Sans, Arial, sans-serif", color: "#4d564f", size: 11 };
const GRID = "#dcdbd0";
const narrow = () => window.matchMedia("(max-width:700px)").matches;

function usePlot(build: () => { data: Data[]; layout: Data } | null, deps: unknown[]) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const el = ref.current;
    const fig = build();
    if (!el || !fig) return;
    void Plotly.newPlot(
      el,
      fig.data as Plotly.Data[],
      {
        autosize: true,
        paper_bgcolor: "transparent",
        plot_bgcolor: "transparent",
        font: FONT,
        hoverlabel: { bgcolor: "#fbf9f3", bordercolor: "#b9bcb1", font: { ...FONT, color: "#1f2723", size: 12 } },
        ...fig.layout,
      } as Partial<Plotly.Layout>,
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
  }, deps);
  return ref;
}

/** Monthly record: observed (thin grey), seasonal cycle removed, Sen line (bold), BEAST probability strip, markers, recent window. */
export function SeriesPlot({ data, label }: { data: Data; label: string }) {
  const ref = usePlot(() => {
    const fig = seriesFigure(data);
    if (fig.empty) return null;
    const small = narrow();
    const unitTitle = (t: string) => ({ text: fig.units ? `${t} (${fig.units})` : t, font: { size: 10.5 } });
    const bottom = fig.hasProbability ? 0.22 : 0;
    const mainTop = fig.split ? 0.6 : 1;
    return {
      data: fig.traces,
      layout: {
        height: small ? 560 : 620,
        margin: { l: 62, r: 14, t: small ? 150 : 96, b: 46 },
        xaxis: { gridcolor: GRID, zeroline: false, title: { text: "Month" }, type: "date", anchor: fig.hasProbability ? "y2" : "y" },
        yaxis: { gridcolor: GRID, zeroline: false, domain: [bottom, mainTop], title: unitTitle(fig.split ? (small ? "No seasons" : "Seasonal cycle removed") : "Value") },
        ...(fig.split ? { yaxis3: { gridcolor: GRID, zeroline: false, domain: [0.66, 1], title: unitTitle("Observed") } } : {}),
        ...(fig.hasProbability
          ? { yaxis2: { domain: [0, 0.15], range: [0, 1], title: { text: "P(change)", font: { size: 10 } }, tickvals: [0, 0.5, 1], gridcolor: GRID, zeroline: false } }
          : {}),
        shapes: fig.shapes,
        legend: { orientation: "h", x: 0, y: 1.02, yanchor: "bottom", font: { size: 10.5 } },
        showlegend: true,
      },
    };
  }, [data]);
  return <div ref={ref} className="report-plot" role="img" aria-label={label} />;
}

/** Grid of per-cell trends drawn as coloured rectangles (basic Plotly has no heatmap trace). */
export function MapPlot({ data, label }: { data: Data; label: string }) {
  const ref = usePlot(() => {
    const map = heatmapCells(data);
    if (!map) return null;
    const small = narrow();
    const sig = map.cells.filter((c) => c.significant);
    const colorscale = DIVERGING.map(([t, c]) => [t, c]);
    return {
      data: [
        {
          x: map.cells.map((c) => c.lon), y: map.cells.map((c) => c.lat), type: "scatter", mode: "markers", name: "Grid cell",
          showlegend: false,
          marker: {
            size: 14, opacity: 0, color: map.cells.map((c) => c.value), colorscale, cmin: -map.maxAbs, cmax: map.maxAbs, cmid: 0,
            showscale: true,
            colorbar: { title: { text: map.units, side: "right" }, thickness: 12, len: 0.9, outlinewidth: 0, ticks: "outside" },
          },
          customdata: map.cells.map((c) => (c.significant ? "significant" : "not significant")),
          hovertemplate: `%{y}°N, %{x}°E<br>%{marker.color:+.3f} ${map.units}<br>%{customdata}<extra></extra>`,
        },
        {
          x: sig.map((c) => c.lon), y: sig.map((c) => c.lat), type: "scatter", mode: "markers", name: "Significant cell (dot)",
          marker: { size: small ? 4 : 5, color: "#1f2723", line: { width: 1, color: "#fbf9f3" } }, hoverinfo: "skip",
        },
      ],
      layout: {
        height: small ? 420 : 560,
        margin: { l: 52, r: 10, t: 10, b: 70 },
        xaxis: { title: { text: "Longitude (°E)" }, range: map.lonRange, gridcolor: GRID, zeroline: false, showgrid: false, constrain: "domain" },
        yaxis: { title: { text: "Latitude (°N)" }, range: map.latRange, gridcolor: GRID, zeroline: false, showgrid: false, scaleanchor: "x", scaleratio: 1, constrain: "domain" },
        shapes: map.cells.map((c) => ({
          type: "rect", xref: "x", yref: "y", x0: c.x0, x1: c.x1, y0: c.y0, y1: c.y1, fillcolor: c.color, line: { width: 0.5, color: "rgba(39,52,46,0.12)" }, layer: "below",
        })),
        legend: { orientation: "h", y: -0.14, font: { size: 10.5 } },
        showlegend: true,
      },
    };
  }, [data]);
  return <div ref={ref} className="report-plot report-map-plot" role="img" aria-label={label} />;
}

export function BarsPlot({ data, label }: { data: Data; label: string }) {
  const ref = usePlot(() => {
    const b = barsData(data);
    if (b.empty) return null;
    return {
      data: [{
        x: b.labels, y: b.y, type: "bar", marker: { color: b.colors, line: { width: 0 } }, name: "Trend per calendar month",
        ...(b.low && b.high
          ? { error_y: { type: "data", symmetric: false, color: "#5b645d", thickness: 1, width: 3,
              array: b.y.map((v, i) => (v == null || b.high![i] == null ? null : b.high![i]! - v)),
              arrayminus: b.y.map((v, i) => (v == null || b.low![i] == null ? null : v - b.low![i]!)) } }
          : {}),
        hovertemplate: `%{x}: %{y:+.3f} ${b.units}<extra></extra>`,
      }],
      layout: {
        height: narrow() ? 280 : 320,
        margin: { l: 58, r: 10, t: 10, b: 40 },
        xaxis: { gridcolor: GRID, title: { text: "Calendar month" } },
        yaxis: { gridcolor: GRID, zeroline: true, zerolinecolor: "#5b645d", zerolinewidth: 1, title: { text: b.units ? `Trend (${b.units})` : "Trend" } },
        bargap: 0.25,
        showlegend: false,
      },
    };
  }, [data]);
  return <div ref={ref} className="report-plot" role="img" aria-label={label} />;
}

