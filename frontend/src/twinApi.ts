import { request, ApiError } from "./api";

export interface TwinBaseline {
  n_valid: number;
  start: string;
  last_observed: string;
  units: string | null;
  slope_per_decade: number;
  slope_se_per_decade: number;
  noise_sd: number;
  lag1_autocorr: number;
  frequency: "annual" | "monthly";
}
export interface TwinVariable {
  name: string;
  units?: string | null;
  source?: string | null;
  uploaded_at?: string;
  time?: string[];
  value?: (number | null)[];
  baseline?: TwinBaseline | { error: string };
}
export interface Twin {
  id: string;
  name: string;
  description?: string | null;
  created_at?: string;
  variables: TwinVariable[];
}
export interface TwinKnobs {
  trend_multiplier?: number;
  trend_add_per_decade?: number;
  shocks?: { year: number; size: number }[];
  drivers?: { from: string; coefficient: number }[];
  threshold?: { value: number; direction: "above" | "below" };
}
export interface TwinSimulationRequest {
  horizon_years: number;
  n_runs?: number;
  seed?: number;
  compare_to_baseline?: boolean;
  scenario: Record<string, TwinKnobs>;
}
export interface TwinThreshold {
  value: number;
  direction: "above" | "below";
  probability_by_end: number;
  probability_by_year: { year: number; p: number }[];
  median_first_crossing: string | null;
  earliest_10pct: string | null;
  plain_language: string;
}
export interface TwinCurve {
  label: string;
  p05: number[];
  p50: number[];
  p95: number[];
  threshold?: TwinThreshold | null;
}
export interface TwinSimulationVariable extends TwinCurve {
  baseline: TwinBaseline;
  scenario: TwinKnobs;
  time: string[];
  reference?: TwinCurve;
  delta_p50?: number[];
}
export interface TwinSimulation {
  twin_id: string;
  horizon_years: number;
  n_runs: number;
  seed: number;
  disclaimer: string;
  variables: Record<string, TwinSimulationVariable>;
}

const path = (id: string) => {
  if (!/^t_[0-9a-f]{12}$/.test(id))
    throw new ApiError({
      code: "invalid_twin",
      message: "Choose a valid digital twin.",
    });
  return `/twin/${encodeURIComponent(id)}`;
};

export const twinApi = {
  list: (signal?: AbortSignal) =>
    request<{ twins: Twin[] }>("/twin", undefined, signal),
  get: (id: string, signal?: AbortSignal) =>
    request<Twin>(path(id), undefined, signal),
  create: (name: string, description?: string, signal?: AbortSignal) => {
    const clean = name.trim();
    if (!clean || clean.length > 120)
      throw new ApiError({
        code: "invalid_name",
        message: "Use a twin name of 1 to 120 characters.",
      });
    return request<Twin>(
      "/twin",
      { name: clean, ...(description ? { description } : {}) },
      signal,
    );
  },
  importSeries: (id: string, seriesId: string, signal?: AbortSignal) =>
    request<Twin>(`${path(id)}/import`, { series_id: seriesId }, signal),
  uploadCSV: (id: string, file: File, signal?: AbortSignal) => {
    if (file.size > 20 * 1024 * 1024)
      throw new ApiError({
        code: "file_too_large",
        message: "Choose a CSV smaller than 20 MB.",
      });
    const body = new FormData();
    body.append("file", file);
    return request<Twin>(`${path(id)}/data-csv`, body, signal);
  },
  simulate: (id: string, body: TwinSimulationRequest, signal?: AbortSignal) => {
    if (
      !Number.isInteger(body.horizon_years) ||
      body.horizon_years < 1 ||
      body.horizon_years > 100
    ) {
      throw new ApiError({
        code: "invalid_horizon",
        message: "Choose a whole number of years from 1 to 100.",
      });
    }
    for (const knobs of Object.values(body.scenario)) {
      const numbers = [
        knobs.trend_multiplier,
        knobs.trend_add_per_decade,
        knobs.threshold?.value,
        ...(knobs.shocks ?? []).flatMap((shock) => [shock.year, shock.size]),
        ...(knobs.drivers ?? []).map((driver) => driver.coefficient),
      ].filter((value) => value !== undefined);
      if (numbers.some((value) => !Number.isFinite(value)))
        throw new ApiError({
          code: "invalid_scenario",
          message: "Scenario settings must be finite numbers.",
        });
    }
    return request<TwinSimulation>(`${path(id)}/simulate`, body, signal);
  },
};
