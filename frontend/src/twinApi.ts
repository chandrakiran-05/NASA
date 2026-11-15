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
  /** Fit the trend only from this year; "auto" = after the last detected break. */
  fit_since_year?: number | "auto";
}
export type TwinScenario = Record<string, TwinKnobs>;
export interface TwinRunOptions {
  horizon_years?: number;
  n_runs?: number;
  seed?: number;
}
export interface TwinSimulationRequest {
  horizon_years: number;
  n_runs?: number;
  seed?: number;
  compare_to_baseline?: boolean;
  scenario: TwinScenario;
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
export interface TwinBacktestVariable {
  status?: "no_overlap";
  months_scored?: number;
  band_coverage?: number;
  target_coverage?: number;
  median_abs_error?: number;
  units?: string | null;
  held_out?: [string, string];
  plain_language?: string;
}
export interface TwinBacktest {
  twin_id: string;
  holdout_years: number;
  n_runs: number;
  seed: number;
  variables: Record<string, TwinBacktestVariable>;
  limit: string;
}
export interface TwinCondition {
  variable: string;
  value: number;
  direction: "above" | "below";
}
export interface TwinCompound {
  twin_id: string;
  horizon_years: number;
  n_runs: number;
  seed: number;
  conditions: (TwinCondition & { probability_by_end: number })[];
  probability_same_year: { year: number; p: number }[];
  probability_by_end: number;
  plain_language: string;
  label: "simulated";
  disclaimer: string;
}
export interface TwinScenarioCurve {
  time: string[];
  p50: number[];
  threshold?: TwinThreshold | null;
  label: string;
}
export interface TwinScenarioSet {
  twin_id: string;
  horizon_years: number;
  n_runs: number;
  seed: number;
  scenarios: Record<string, Record<string, TwinScenarioCurve>>;
  label: "simulated";
  disclaimer: string;
}
export interface TwinSensitivity {
  twin_id: string;
  horizon_years: number;
  n_runs: number;
  seed: number;
  target: string;
  probability_with_all_knobs: number;
  ranking: {
    variable: string;
    knob: string;
    item: number | null;
    setting: unknown;
    probability_without: number;
    change: number;
  }[];
  note: string;
  label: "simulated";
  disclaimer: string;
}
export interface TwinDataUpload {
  source?: string;
  variables: {
    name: string;
    units?: string | null;
    time: string[];
    value: (number | null)[];
  }[];
}

function invalid(code: string, message: string): never {
  throw new ApiError({ code, message });
}
function checkRun(o: TwinRunOptions) {
  const h = o.horizon_years;
  if (h !== undefined && (!Number.isInteger(h) || h < 1 || h > 100))
    invalid("invalid_horizon", "Choose a whole number of years from 1 to 100.");
  const n = o.n_runs;
  if (n !== undefined && (!Number.isInteger(n) || n < 50 || n > 2000))
    invalid("invalid_runs", "Choose 50 to 2,000 simulated runs.");
}
function checkScenario(scenario: TwinScenario) {
  for (const knobs of Object.values(scenario)) {
    const numbers = [
      knobs.trend_multiplier,
      knobs.trend_add_per_decade,
      knobs.threshold?.value,
      ...(knobs.shocks ?? []).flatMap((shock) => [shock.year, shock.size]),
      ...(knobs.drivers ?? []).map((driver) => driver.coefficient),
    ].filter((value) => value !== undefined);
    if (numbers.some((value) => !Number.isFinite(value)))
      invalid("invalid_scenario", "Scenario settings must be finite numbers.");
    const fit = knobs.fit_since_year;
    if (fit !== undefined && fit !== "auto" && !Number.isInteger(fit))
      invalid("invalid_fit_since", 'Fit-since must be a whole year or "auto".');
  }
}
const variableName = (name: string) => {
  if (!name || name.length > 80)
    invalid("invalid_variable", "Use a variable name of 1 to 80 characters.");
  return encodeURIComponent(name);
};

const path = (id: string) => {
  if (!/^t_[0-9a-f]{12}$/.test(id))
    invalid("invalid_twin", "Choose a valid digital twin.");
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
      invalid("invalid_name", "Use a twin name of 1 to 120 characters.");
    return request<Twin>(
      "/twin",
      { name: clean, ...(description ? { description } : {}) },
      signal,
    );
  },
  importSeries: (
    id: string,
    seriesId: string,
    signal?: AbortSignal,
    name?: string,
  ) => {
    const clean = seriesId.trim();
    if (!clean) invalid("invalid_series", "Enter a series id to copy.");
    const label = name?.trim();
    if (label) variableName(label);
    return request<Twin>(
      `${path(id)}/import`,
      { series_id: clean, ...(label ? { name: label } : {}) },
      signal,
    );
  },
  uploadCSV: (id: string, file: File, signal?: AbortSignal) => {
    if (file.size > 20 * 1024 * 1024)
      invalid("file_too_large", "Choose a CSV smaller than 20 MB.");
    const body = new FormData();
    body.append("file", file);
    return request<Twin>(`${path(id)}/data-csv`, body, signal);
  },
  uploadData: (id: string, body: TwinDataUpload, signal?: AbortSignal) => {
    const vars = body?.variables;
    if (!Array.isArray(vars) || !vars.length || vars.length > 50)
      invalid("invalid_data", "Send 1 to 50 variables.");
    for (const v of vars) {
      variableName(v?.name);
      if (
        !Array.isArray(v.time) ||
        !Array.isArray(v.value) ||
        v.time.length !== v.value.length
      )
        invalid("invalid_data", `${v.name}: time and value need the same length.`);
      if (v.value.some((x) => x !== null && !Number.isFinite(x)))
        invalid("invalid_data", `${v.name}: values must be numbers or null.`);
    }
    return request<Twin>(`${path(id)}/data`, body, signal);
  },
  simulate: (id: string, body: TwinSimulationRequest, signal?: AbortSignal) => {
    checkRun({ ...body, horizon_years: body.horizon_years ?? NaN });
    checkScenario(body.scenario);
    return request<TwinSimulation>(`${path(id)}/simulate`, body, signal);
  },
  backtest: (
    id: string,
    body: { holdout_years?: number; n_runs?: number; seed?: number } = {},
    signal?: AbortSignal,
  ) => {
    const h = body.holdout_years;
    if (h !== undefined && (!Number.isInteger(h) || h < 2 || h > 40))
      invalid("invalid_holdout", "Hold out a whole number of years from 2 to 40.");
    checkRun({ n_runs: body.n_runs });
    return request<TwinBacktest>(`${path(id)}/backtest`, body, signal);
  },
  compound: (
    id: string,
    body: TwinRunOptions & {
      conditions: TwinCondition[];
      scenario?: TwinScenario;
    },
    signal?: AbortSignal,
  ) => {
    if (!body.conditions.length || body.conditions.length > 5)
      invalid("invalid_conditions", "Use 1 to 5 conditions.");
    if (body.conditions.some((c) => !c.variable || !Number.isFinite(c.value)))
      invalid(
        "invalid_conditions",
        "Each condition needs a variable and a finite level.",
      );
    checkRun(body);
    checkScenario(body.scenario ?? {});
    return request<TwinCompound>(`${path(id)}/compound`, body, signal);
  },
  scenarios: (
    id: string,
    body: TwinRunOptions & { scenarios: Record<string, TwinScenario> },
    signal?: AbortSignal,
  ) => {
    const count = Object.keys(body.scenarios).length;
    if (!count || count > 6)
      invalid("invalid_scenarios", "Compare 1 to 6 named scenarios.");
    checkRun(body);
    Object.values(body.scenarios).forEach(checkScenario);
    return request<TwinScenarioSet>(`${path(id)}/scenarios`, body, signal);
  },
  sensitivity: (
    id: string,
    body: TwinRunOptions & { target: string; scenario: TwinScenario },
    signal?: AbortSignal,
  ) => {
    if (!body.scenario[body.target]?.threshold)
      invalid("invalid_target", "Give the target variable a threshold first.");
    checkRun(body);
    checkScenario(body.scenario);
    return request<TwinSensitivity>(`${path(id)}/sensitivity`, body, signal);
  },
  remove: (id: string, signal?: AbortSignal) =>
    request<{ deleted: string }>(path(id), undefined, signal, "DELETE"),
  removeVariable: (id: string, name: string, signal?: AbortSignal) =>
    request<{ deleted: string; twin_id: string; variables: string[] }>(
      `${path(id)}/variables/${variableName(name)}`,
      undefined,
      signal,
      "DELETE",
    ),
};
