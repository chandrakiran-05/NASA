import { useEffect, useRef } from "react";
import Plotly from "plotly.js-basic-dist-min";
export default function EvidenceChart({
  analysis,
}: {
  analysis: Record<string, any>;
}) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const c = analysis.chart;
    if (!c) return;
    const traces: Plotly.Data[] = [
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
          title: { text: analysis.units },
        },
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
  }, [analysis]);
  return (
    <div
      ref={ref}
      className="evidence-chart"
      role="img"
      aria-label={
        analysis.verdict?.plain_language ||
        `Monthly ${analysis.label} in ${analysis.units}. Missing observations appear as gaps.`
      }
    />
  );
}
