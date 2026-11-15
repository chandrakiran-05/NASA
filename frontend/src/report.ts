/**
 * Pure helpers for the report story (POST /api/report → job result).
 * No statistics are computed here: every number comes from the backend; these
 * functions only order, label, reshape and colour what the API returned.
 * Kept free of runtime imports so node --test can load it directly.
 */
type Data = Record<string, any>;
export type Cell = string | number | null;

export interface ReportSection {
  id: string;
  title: string;
  kind: string;
  text: string;
  data: Data | null;
  /** "local_llm" once the AI wording passed the number check; "template" otherwise. */
  textSource?: string;
  /** pending | rewritten | kept_template | not_rewritten | unavailable (backend `ai_status`). */
  aiStatus?: string;
}
export interface ReportPlan {
  variable_id?: string;
  variable_name?: string;
  units?: string;
  region_name?: string;
  geometry?: Data | null;
  start?: string;
  end?: string;
  source?: string;
}
export interface Report {
  question: string;
  plan: ReportPlan;
  headline: string;
  sections: ReportSection[];
  glossary: { term: string; meaning: string }[];
  provenance: unknown;
  limits: string[];
  ai: { used: boolean; label?: string; status?: string; pending?: string[]; research?: string };
  /** Set only for the bundled development fixture; never for API results. */
  fixture?: string;
}

export const SECTION_ORDER = [
  "answer", "data", "series", "how_much", "is_it_real", "when", "seasons", "map", "context", "limits",
];

/** One-line "why the next section matters" bridges, keyed by the NEXT section id. Wording only, no numbers. */
export const BRIDGES: Record<string, string> = {
  data: "Before trusting any number, see exactly which record it comes from.",
  series: "Now look at the record itself, every month, gaps included.",
  how_much: "The line shows a direction; next is how big the change is.",
  is_it_real: "A slope can appear by chance or from bad data, so it is tested next.",
  when: "If the trend is real, the next question is when it bent.",
  seasons: "An average can hide which part of the year is changing.",
  map: "A regional average can also hide where the change happens.",
  context: "A single record reads better beside the wider picture.",
  limits: "Finally, what this evidence cannot tell you.",
};

const str = (v: unknown) => (typeof v === "string" ? v : v == null ? "" : String(v));
const arr = <T = unknown>(v: unknown): T[] => (Array.isArray(v) ? (v as T[]) : []);

/** Accepts anything the backend might send and returns a safe, fully-shaped report. */
export function normalizeReport(raw: unknown): Report {
  const r: Data = raw && typeof raw === "object" ? (raw as Data) : {};
  const sections = arr<Data>(r.sections)
    .filter((s) => s && typeof s === "object" && typeof s.id === "string" && s.id)
    .map((s) => ({
      id: s.id,
      title: str(s.title) || s.id.replaceAll("_", " "),
      kind: str(s.kind) || "text",
      text: str(s.text),
      data: s.data && typeof s.data === "object" ? s.data : null,
      ...(typeof s.text_source === "string" ? { textSource: s.text_source } : {}),
      ...(typeof s.ai_status === "string" ? { aiStatus: s.ai_status } : {}),
    }));
  return {
    question: str(r.question),
    plan: r.plan && typeof r.plan === "object" ? r.plan : {},
    headline: str(r.headline),
    sections: orderSections(sections),
    glossary: arr<Data>(r.glossary)
      .filter((g) => g && g.term)
      .map((g) => ({ term: str(g.term), meaning: str(g.meaning) })),
    provenance: r.provenance ?? null,
    limits: arr(r.limits).map(str).filter(Boolean),
    ai: {
      used: r.ai?.used === true,
      label: r.ai?.label ? str(r.ai.label) : undefined,
      ...(typeof r.ai?.status === "string" ? { status: r.ai.status } : {}),
      ...(Array.isArray(r.ai?.pending) ? { pending: r.ai.pending.map(str) } : {}),
      ...(typeof r.ai?.research === "string" ? { research: r.ai.research } : {}),
    },
    ...(r._fixture ? { fixture: str(r._fixture) } : {}),
  };
}

/** Known ids follow the story order; unknown ids keep their relative order after them; duplicates dropped. */
export function orderSections<T extends { id: string }>(sections: T[]): T[] {
  const seen = new Set<string>();
  const unique = sections.filter((s) => (seen.has(s.id) ? false : (seen.add(s.id), true)));
  const rank = (id: string) => {
    const i = SECTION_ORDER.indexOf(id);
    return i === -1 ? SECTION_ORDER.length : i;
  };
  return unique
    .map((s, i) => ({ s, i }))
    .sort((a, b) => rank(a.s.id) - rank(b.s.id) || a.i - b.i)
    .map((x) => x.s);
}

export interface StoryStep {
  section: ReportSection;
  number: number;
  anchor: string;
  bridge: string | null;
}
/** Numbered, anchored steps with a bridge line pointing at the next section. */
export function buildStory(sections: ReportSection[]): StoryStep[] {
  return sections.map((section, i) => {
    const next = sections[i + 1];
    return {
      section,
      number: i + 1,
      anchor: `report-${section.id}`,
      bridge: next ? `Why this matters next: ${BRIDGES[next.id] ?? "it adds the next piece of evidence."}` : null,
    };
  });
}

/** Per-section wording state while the report is still being improved (never blocks showing the numbers). */
export function sectionWording(s: ReportSection, ai?: Report["ai"]): { note: string; kind: "pending" | "ai" | "" } {
  if (s.aiStatus === "pending" && ai?.status !== "done") return { note: "AI wording loading… the numbers below are final.", kind: "pending" };
  if (s.id === "context" && s.data?.research_status === "pending" && ai?.status !== "done")
    return { note: "Looking for published research…", kind: "pending" };
  if (s.textSource === "local_llm") return { note: "AI-written, number-checked", kind: "ai" };
  return { note: "", kind: "" };
}
/** True while the backend is still adding AI wording or research to an already complete report. */
export const isImproving = (r: Report | null) => !!r && r.ai.status === "writing";

export function aiLabel(ai: Report["ai"] | undefined): { kind: "ai" | "template"; text: string } {
  if (ai?.used) return { kind: "ai", text: ai.label || "AI-written, number-checked" };
  return { kind: "template", text: ai?.label || "Template text" };
}

/** Table from `data.rows` ([[label, value, note?]]) or {label, value} objects, with optional `data.columns`. */
export function tableData(data: Data | null | undefined): { columns: string[] | null; rows: Cell[][] } {
  const rows = arr<unknown>(data?.rows)
    .map((row): Cell[] | null => {
      if (Array.isArray(row) && row.length) return row.map((c) => (c == null || typeof c === "object" ? null : (c as Cell)));
      if (row && typeof row === "object") {
        const o = row as Data;
        return [str(o.label ?? o.name ?? o.term), (o.value ?? null) as Cell, ...(o.note != null ? [o.note as Cell] : [])];
      }
      return null;
    })
    .filter((r): r is Cell[] => r !== null && str(r[0]) !== "");
  const width = Math.max(0, ...rows.map((r) => r.length));
  const columns = arr(data?.columns).map(str);
  // Drop a column that is empty in every row (e.g. a Note column with no notes).
  const keep = Array.from({ length: width }, (_, i) => i === 0 || rows.some((r) => r[i] != null && r[i] !== ""));
  return {
    columns: columns.length ? columns.filter((_, i) => keep[i] ?? true) : null,
    rows: rows.map((r) => Array.from({ length: width }, (_, i) => r[i] ?? null).filter((_, i) => keep[i])),
  };
}

/** Display formatting only (no rounding of meaning): long floats get 4 significant digits. */
export function formatCell(v: Cell | undefined): string {
  if (v == null || v === "") return "—";
  if (typeof v === "number") return Number.isFinite(v) ? v.toLocaleString("en-US", { maximumSignificantDigits: 4 }) : "—";
  return v;
}

/** The headline's key number: the how_much row for Sen's slope if present, else its first row, as returned. */
export function keyNumber(sections: ReportSection[]): { label: string; value: string } | null {
  const rows = tableData(sections.find((s) => s.id === "how_much")?.data).rows;
  const row = rows.find((r) => /\bsen/i.test(str(r[0]))) ?? rows[0];
  return row ? { label: str(row[0]), value: formatCell(row[1]) } : null;
}

export function seriesIdOf(report: Report | null): string | undefined {
  const id = report?.sections.find((s) => s.id === "series")?.data?.series_id;
  return typeof id === "string" && id ? id : undefined;
}

// ------------------------------------------------------------------ checks
export type CheckStatus = "pass" | "warn" | "fail" | "info";
export function checkStatus(status: unknown): { status: CheckStatus; word: string } {
  const s = str(status).toLowerCase();
  if (s === "pass" || s === "ok") return { status: "pass", word: "Pass" };
  if (s === "warn" || s === "warning" || s === "caution") return { status: "warn", word: "Warning" };
  if (s === "fail" || s === "failed") return { status: "fail", word: "Fail" };
  return { status: "info", word: s ? s.replaceAll("_", " ") : "Not run" };
}
export function checkName(check: unknown): string {
  const c = str(check);
  if (c === "ai_review") return "AI reviewer (advisory)";
  const words = c.replaceAll("_", " ").trim();
  return words ? words[0].toUpperCase() + words.slice(1) : "Check";
}

/** Verdict of the is_it_real section: `data.verdict` may be an object or just the label string. */
export function checksVerdict(data: Data | null | undefined): { label: string; lines: string[]; limit: string } | null {
  const v = data?.verdict;
  const label = typeof v === "string" ? v : str(v?.label);
  const lines = [
    typeof v === "object" && v ? str(v.plain_language) : "",
    str(data?.why),
    str(data?.detect_plain_language),
    str(data?.court?.plain_language),
    str(data?.beast?.plain_language),
  ].filter(Boolean);
  const limit = str((typeof v === "object" && v?.limit) || data?.limit);
  return label || lines.length || limit ? { label, lines, limit } : null;
}
export const checkText = (c: Data | null | undefined) => str(c?.plain_language ?? c?.text ?? c?.message);

// ------------------------------------------------------------------ markers
export interface MarkerStyle { color: string; dash: "solid" | "dash" | "dot"; label: string; word: string }
export const MARKER_STYLES: Record<string, MarkerStyle> = {
  beast_confirmed: { color: "#b5452f", dash: "solid", label: "BEAST change, confirmed (solid)", word: "Confirmed change (BEAST)" },
  beast_possible: { color: "#b5452f", dash: "dash", label: "BEAST change, possible (dashed)", word: "Possible change (BEAST)" },
  pelt_break: { color: "#2f5b8a", dash: "dot", label: "PELT break (dotted)", word: "Break in level (PELT)" },
};
export interface Marker { date: string; kind: string; interval?: string[] | null; probability?: number | null }

/** Drawable markers (weak BEAST events are left out), sorted by date. */
export function drawableMarkers(markers: unknown): Marker[] {
  return arr<Data>(markers)
    .filter((m) => m && typeof m.date === "string" && MARKER_STYLES[m.kind])
    .map((m) => ({ date: m.date, kind: m.kind, interval: Array.isArray(m.interval) ? m.interval : null, probability: typeof m.probability === "number" ? m.probability : null }))
    .sort((a, b) => a.date.localeCompare(b.date));
}

export function markerSentence(m: Marker): string {
  const st = MARKER_STYLES[m.kind];
  const parts = [`${m.date}: ${st?.word ?? m.kind}`];
  if (m.probability != null) parts.push(`probability ${formatCell(m.probability)}`);
  if (m.interval?.length === 2) parts.push(`likely between ${m.interval[0]} and ${m.interval[1]}`);
  return parts.join(" · ");
}

// ------------------------------------------------------------------ series chart
const finiteOrNull = (v: unknown) => (typeof v === "number" && Number.isFinite(v) ? v : null);
const values = (v: unknown) => arr(v).map(finiteOrNull);
const hasValues = (v: (number | null)[]) => v.some((x) => x !== null);

export const COLORS = {
  observed: "#a3a8a0",
  deseasonalized: "#3f6f55",
  sen: "#b5452f",
  beastTrend: "#7a5c2e",
  probability: "#b08a3e",
  recent: "rgba(8,107,220,0.08)",
};

/** Plotly-ready traces/shapes for a `chart` section. Nulls stay null (drawn as gaps). */
export function seriesFigure(data: Data | null | undefined) {
  const c: Data = data?.chart ?? {};
  const time = arr<string>(c.time).map(str);
  const units = str(data?.units);
  const traces: Data[] = [];
  const line = (key: string, name: string, color: string, width: number, extra: Data = {}) => {
    const y = values(c[key]);
    if (time.length && hasValues(y))
      traces.push({ x: time, y, name, type: "scatter", mode: "lines", connectgaps: false, line: { color, width }, ...extra });
  };
  // With both present, the raw record (big seasonal swing) gets its own top panel (y3) so the
  // deseasonalized values and the Sen line keep a readable scale on the main axis (y).
  const split = hasValues(values(c.observed)) && hasValues(values(c.deseasonalized));
  line("observed", "Observed monthly values (top panel)", COLORS.observed, 0.9, split ? { yaxis: "y3" } : {});
  line("deseasonalized", "Seasonal cycle removed", COLORS.deseasonalized, 1.3);
  line("beast_trend", "BEAST fitted trend", COLORS.beastTrend, 1.2, { line: { color: COLORS.beastTrend, width: 1.2, dash: "dot" } });
  line("sen_line", "Sen trend line", COLORS.sen, 3.2);
  const probability = values(c.change_probability);
  const hasProbability = time.length > 0 && hasValues(probability);
  if (hasProbability)
    traces.push({
      x: time, y: probability, name: "BEAST change probability (lower strip)", yaxis: "y2", type: "scatter", mode: "lines",
      connectgaps: false, fill: "tozeroy", line: { color: COLORS.probability, width: 1 }, fillcolor: "rgba(176,138,62,0.3)",
    });
  const shapes: Data[] = [];
  const recent = data?.recent_window;
  if (recent?.start && recent?.end)
    shapes.push({ type: "rect", xref: "x", yref: "paper", x0: recent.start, x1: recent.end, y0: 0, y1: 1, fillcolor: COLORS.recent, line: { width: 0 }, layer: "below" });
  const markers = drawableMarkers(data?.markers);
  const seen = new Set<string>();
  for (const m of markers) {
    const st = MARKER_STYLES[m.kind];
    shapes.push({ type: "line", xref: "x", yref: "paper", x0: m.date, x1: m.date, y0: 0, y1: 1, line: { color: st.color, width: 1.5, dash: st.dash } });
    if (!seen.has(m.kind)) {
      seen.add(m.kind);
      traces.push({ x: [null], y: [null], name: st.label, type: "scatter", mode: "lines", line: { color: st.color, dash: st.dash, width: 1.5 }, hoverinfo: "skip" });
    }
  }
  if (recent?.start && recent?.end)
    traces.push({ x: [null], y: [null], name: `Recent window ${recent.start} – ${recent.end} (shaded)`, type: "scatter", mode: "lines", line: { color: "rgba(8,107,220,0.35)", width: 8 }, hoverinfo: "skip" });
  return { traces, shapes, units, hasProbability, split, empty: !traces.some((t) => t.x?.length > 1) };
}

// ------------------------------------------------------------------ heat map
/** Diverging scale: blue (falling) → paper (0) → red (rising). Used for cells AND the colour bar. */
export const DIVERGING: [number, string][] = [
  [0, "#2c5f9e"], [0.25, "#8fb3d6"], [0.5, "#f4f1ea"], [0.75, "#e39a7a"], [1, "#a8321f"],
];
const hex = (h: string) => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16));
/** Colour for value v on a scale symmetric around 0 (−maxAbs … +maxAbs). */
export function divergingColor(v: number, maxAbs: number): string {
  const t = Math.min(1, Math.max(0, maxAbs > 0 ? 0.5 + v / (2 * maxAbs) : 0.5));
  let k = 0;
  while (k < DIVERGING.length - 2 && t > DIVERGING[k + 1][0]) k++;
  const [t0, c0] = DIVERGING[k], [t1, c1] = DIVERGING[k + 1];
  const f = (t - t0) / (t1 - t0);
  const [a, b] = [hex(c0), hex(c1)];
  return `rgb(${a.map((x, i) => Math.round(x + (b[i] - x) * f)).join(",")})`;
}

/** Cell edges halfway between centres; outer edges extend by half a step. Works for either sort direction. */
export function cellEdges(centres: number[]): [number, number][] {
  if (centres.length === 1) return [[centres[0] - 0.5, centres[0] + 0.5]];
  return centres.map((c, i) => {
    const prev = i > 0 ? (centres[i - 1] + c) / 2 : c - (centres[1] - c) / 2;
    const next = i < centres.length - 1 ? (c + centres[i + 1]) / 2 : c + (c - centres[i - 1]) / 2;
    return [Math.min(prev, next), Math.max(prev, next)];
  });
}

export interface HeatCell { lat: number; lon: number; x0: number; x1: number; y0: number; y1: number; value: number; significant: boolean; color: string }
export interface Heatmap {
  cells: HeatCell[];
  maxAbs: number;
  units: string;
  rows: number;
  cols: number;
  missing: number;
  lonRange: [number, number];
  latRange: [number, number];
  areaRising: number | null;
  areaFalling: number | null;
}

/**
 * Turns the map section's grid (slope_per_decade[lat][lon]) into coloured cells.
 * A grid sent as [lon][lat] is transposed. Null cells are not drawn (gaps), only counted.
 */
export function heatmapCells(data: Data | null | undefined): Heatmap | null {
  const lat = values(data?.lat), lon = values(data?.lon);
  let grid: unknown[][] = arr<unknown[]>(data?.slope_per_decade).map((r) => arr(r));
  let sig: unknown[][] = arr<unknown[]>(data?.significant).map((r) => arr(r));
  if (!lat.length || !lon.length || lat.some((x) => x === null) || lon.some((x) => x === null) || !grid.length) return null;
  if (grid.length === lon.length && grid[0]?.length === lat.length && lat.length !== lon.length) {
    const t = (g: unknown[][]) => lat.map((_, i) => lon.map((__, j) => g[j]?.[i]));
    grid = t(grid);
    sig = sig.length ? t(sig) : sig;
  }
  if (grid.length !== lat.length) return null;
  const latE = cellEdges(lat as number[]), lonE = cellEdges(lon as number[]);
  let maxAbs = 0, missing = 0;
  const raw: Omit<HeatCell, "color">[] = [];
  lat.forEach((la, i) =>
    lon.forEach((lo, j) => {
      const v = finiteOrNull(grid[i]?.[j]);
      if (v === null) return void missing++;
      maxAbs = Math.max(maxAbs, Math.abs(v));
      raw.push({ lat: la as number, lon: lo as number, x0: lonE[j][0], x1: lonE[j][1], y0: latE[i][0], y1: latE[i][1], value: v, significant: sig[i]?.[j] === true });
    }),
  );
  if (!raw.length) return null;
  maxAbs = maxAbs || 1;
  const fraction = (v: unknown) => (typeof v === "number" && Number.isFinite(v) ? v : null);
  return {
    cells: raw.map((c) => ({ ...c, color: divergingColor(c.value, maxAbs) })),
    maxAbs,
    units: perDecade(str(data?.units)),
    rows: lat.length,
    cols: lon.length,
    missing,
    lonRange: [Math.min(...lonE.flat()), Math.max(...lonE.flat())],
    latRange: [Math.min(...latE.flat()), Math.max(...latE.flat())],
    areaRising: fraction(data?.area_fraction_rising),
    areaFalling: fraction(data?.area_fraction_falling),
  };
}

/** Fraction → "37.5 %" (display only). */
export const percent = (f: number | null) => (f == null ? "—" : `${(Math.round(f * 1000) / 10).toLocaleString("en-US")} %`);

// ------------------------------------------------------------------ monthly bars
export function barsData(data: Data | null | undefined) {
  const months = arr(data?.months ?? data?.labels).map(str);
  const slopes = values(data?.slope_per_decade ?? data?.values);
  const n = Math.min(months.length || 12, slopes.length);
  const labels = months.length ? months.slice(0, n) : ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"].slice(0, n);
  const y = slopes.slice(0, n);
  const low = values(data?.ci_low).slice(0, n), high = values(data?.ci_high).slice(0, n);
  const hasRange = low.length === n && high.length === n && hasValues(low);
  return {
    labels,
    y,
    low: hasRange ? low : null,
    high: hasRange ? high : null,
    colors: y.map((v) => (v == null ? "transparent" : v >= 0 ? DIVERGING[4][1] : DIVERGING[0][1])),
    units: perDecade(str(data?.units)),
    empty: !y.some((v) => v !== null),
  };
}

/** Slope fields are per decade; make the unit say so when the backend sent only the base unit. */
export function perDecade(units: string): string {
  if (!units) return "per decade";
  return /decade/i.test(units) ? units : `${units} per decade`;
}

// ------------------------------------------------------------------ provenance
const PROVENANCE_KEYS = ["dataset_short_name", "dataset", "source_api", "version", "doi", "retrieved_at", "citation"];
/** Main provenance fields (dataset, version, DOI, retrieved…) or, with `extras`, every other scalar/list field. */
export function provenanceEntries(p: unknown, extras = false): [string, string][] {
  if (p == null || p === "") return [];
  if (typeof p !== "object") return extras ? [] : [["source", str(p)]];
  if (Array.isArray(p)) return p.flatMap((x) => provenanceEntries(x, extras));
  const o = p as Data;
  const keys = extras ? Object.keys(o).filter((k) => !PROVENANCE_KEYS.includes(k)) : PROVENANCE_KEYS.filter((k) => k in o);
  return keys
    .filter((k) => o[k] != null && o[k] !== "" && (typeof o[k] !== "object" || Array.isArray(o[k])))
    .map((k) => [k.replaceAll("_", " "), Array.isArray(o[k]) ? o[k].map(str).join("; ") : str(o[k])]);
}

// ------------------------------------------------------------------ CSV upload adapter
/**
 * An uploaded CSV is analysed with POST /api/analyze (no report job exists for it).
 * This only re-shapes that response into the report layout; it computes nothing.
 */
export function reportFromAnalysis(analysis: Data, fileName = "Uploaded monthly series"): Report {
  const v: Data = analysis?.verdict ?? {};
  const p: Data = analysis?.period ?? {};
  const c: Data = analysis?.chart ?? {};
  const units = str(analysis?.units);
  const rows: Cell[][] = [["Series", str(analysis?.label) || fileName]];
  if (p.start) rows.push(["Period", `${p.start} – ${p.end ?? ""}`]);
  if (p.n_months != null) rows.push(["Months", p.n_months]);
  if (p.n_valid != null) rows.push(["Valid months", p.n_valid]);
  if (p.missing_pct != null) rows.push(["Missing (%)", p.missing_pct]);
  if (units) rows.push(["Units", units]);
  const how: Cell[][] = [];
  if (v.rate_per_decade != null) how.push(["Sen trend", `${formatCell(v.rate_per_decade)} ${str(v.rate_units)}`.trim()]);
  if (v.headline_p != null) how.push(["Headline p-value", v.headline_p]);
  if (analysis?.court?.stamp) how.push(["Trend court stamp", analysis.court.stamp]);
  const sections: ReportSection[] = [
    { id: "answer", title: "The short answer", kind: "text", text: str(v.plain_language), data: null },
    { id: "data", title: "The record we tested", kind: "table", text: "This is the monthly CSV you uploaded. Missing months stay as gaps.", data: { rows } },
    {
      id: "series", title: "The record, month by month", kind: "chart",
      text: "Grey is each monthly value, green has the seasonal cycle removed, and the bold line is the Sen trend line.",
      data: { series_id: analysis?.series_id, units, chart: { time: c.time, observed: c.raw, deseasonalized: c.deseasonalized, sen_line: c.sen_line }, markers: [] },
    },
  ];
  if (how.length) sections.push({ id: "how_much", title: "How much it changed", kind: "table", text: "", data: { rows: how } });
  const caveats = [...arr(v.caveats), ...arr(v.notes)].map(str).filter(Boolean);
  if (caveats.length) sections.push({ id: "limits", title: "What this cannot tell you", kind: "text", text: caveats.join(" "), data: null });
  return {
    question: fileName,
    plan: { variable_name: str(analysis?.label) || fileName, units, start: p.start, end: p.end, region_name: fileName },
    headline: str(v.plain_language),
    sections: orderSections(sections),
    glossary: [],
    provenance: analysis?.provenance ?? { source: "Uploaded monthly CSV" },
    limits: ["Statistics describe the uploaded record and period only."],
    ai: { used: false, label: "Template text" },
  };
}
