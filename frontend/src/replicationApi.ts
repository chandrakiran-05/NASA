/** Typed client for the SeaWiFS paper replication (/api/replication/seawifs).
 * Every number shown comes from these responses; the helpers below only format text and map outlines. */
import { pollJob, request, type Job } from "./api";

export interface Fit {
  slope: number; F: number; p: number; r2: number; n: number; significant: boolean;
  p_persistence_corrected: number; significant_persistence_corrected: boolean;
}
export interface MonthlyFit extends Fit { slope_per_month: number; slope_per_decade: number; mean: number; units: string }
export interface YearlyFit extends Fit { slope_per_year: number; slope_per_decade: number; n_years: number }
export interface RunResult {
  status: "ok" | "insufficient" | "error";
  message?: string;
  n_months?: number;
  n_valid?: number;
  period?: { start: string; end: string } | null;
  dataset?: string;
  variable?: string;
  substitute?: boolean;
  monthly?: MonthlyFit;
  yearly?: YearlyFit | null;
  series?: { time: string[]; value: (number | null)[]; fit: number[] };
  yearly_series?: { year: number[]; anomaly: number[]; n_months: number[]; fit: number[] | null };
  variant?: RunResult & { label: string };
  provenance?: { source_api: string; dataset_short_name?: string | null; version?: string | null; doi?: string | null; retrieved_at?: string; citation?: string | null };
  area_mean_note?: string;
}
export interface Agreement {
  label: "Consistent" | "Differs" | "Not enough data";
  same_sign: boolean | null;
  same_significance: boolean | null;
  within_factor_2: boolean | null;
  slope_ratio?: number | null;
  plain_language: string;
}
export interface Published {
  distance_km: number; p: number; F: number; slope_per_month: number; slope_per_decade: number;
  r2: number; mean: number; units: string; significant: boolean; footnote: string | null; footnote_text: string | null;
}
export interface River {
  id: string; name: string; bbox: [number, number, number, number]; centre: [number, number];
  box: { north: number; south: number; west: number; east: number };
  published: Published;
  replication: RunResult | null;
  extension: RunResult | null;
  agreement: Agreement;
  extension_agreement: Agreement;
}
export interface Replication {
  paper: { title: string; authors: string; url: string; citation: string; data: string; period: { start: string; end: string };
    boxes: string; method: string[]; conclusion: string; caveat: string };
  rivers: River[];
  summary: string;
  updated_at: string | null;
  cached: boolean;
  notes: string[];
}

export const getReplication = (signal?: AbortSignal) => request<Replication>("/replication/seawifs", undefined, signal);

export async function runReplication(
  options: { rivers?: string[]; refresh?: boolean; signal?: AbortSignal; onProgress?: (job: Job<Replication>) => void } = {},
): Promise<Replication> {
  const { job_id } = await request<{ job_id: string }>(
    "/replication/seawifs", { rivers: options.rivers, refresh: options.refresh ?? false }, options.signal);
  return pollJob<Replication>(job_id, { signal: options.signal, onProgress: options.onProgress, timeoutMs: 30 * 60_000 });
}

/** Text only: "p = 0.018" / "p < 0.001". */
export function fmtP(p: number | null | undefined): string {
  if (p == null || !Number.isFinite(p)) return "p = n/a";
  return p < 0.001 ? "p < 0.001" : `p = ${p < 0.01 ? p.toFixed(4) : p.toFixed(3)}`;
}

/** Text only: signed slope with fixed decimals, e.g. "-0.0043". */
export function fmtSlope(x: number | null | undefined, digits = 4): string {
  if (x == null || !Number.isFinite(x)) return "n/a";
  return `${x > 0 ? "+" : x < 0 ? "−" : ""}${Math.abs(x).toFixed(digits)}`;
}

export const badgeClass = (label: Agreement["label"]) =>
  label === "Consistent" ? "is-consistent" : label === "Differs" ? "is-differs" : "is-nodata";

type Ring = [number, number][];
/** Country outlines (GeoJSON Polygon/MultiPolygon) -> one x/y path with null breaks, for a plain lon/lat plot. */
export function outlinePath(features: { geometry: { type: string; coordinates: unknown } }[]): { x: (number | null)[]; y: (number | null)[] } {
  const x: (number | null)[] = [], y: (number | null)[] = [];
  for (const f of features) {
    const polys = (f.geometry.type === "Polygon" ? [f.geometry.coordinates] : f.geometry.coordinates) as Ring[][];
    for (const poly of polys) for (const ring of poly) {
      for (const [lon, lat] of ring) { x.push(lon); y.push(lat); }
      x.push(null); y.push(null);
    }
  }
  return { x, y };
}
