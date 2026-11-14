/** The browser talks only to our backend. NASA credentials and model keys stay there. */
export type Coordinate = [number, number];
export type Geometry =
  | { type: "Point"; coordinates: Coordinate; name?: string }
  | { type: "BBox"; bbox: [number, number, number, number]; name?: string }
  | { type: "Polygon"; coordinates: Coordinate[][]; name?: string };

export interface Variable {
  id: string;
  name: string;
  definition?: string | null;
  units?: string | null;
  source?: string;
  coverage_start?: string | null;
  coverage_end?: string | null;
  verified?: boolean;
}

export interface Region {
  name: string;
  geometry: Geometry;
  kind?: string;
  source?: string;
  approximate?: boolean;
  needs_confirmation?: boolean;
}

export interface PlanResponse {
  on_topic: boolean;
  message?: string;
  question?: string;
  variables?: Variable[];
  regions?: Region[];
  period?: { start: string | null; end: string | null; note?: string | null };
  wishes?: Record<string, boolean>;
  needs_user_input?: string[];
  planner?: string;
}

export interface AIStatus {
  available: boolean;
  provider: string;
  model?: string;
  reason?: string;
  hint?: string;
}

export interface AIAnswer {
  on_topic?: boolean;
  answer?: string;
  explanation?: string;
  source?: "local_llm" | "deterministic" | "guardrail" | string;
  note?: string;
  fact_check?: { passed?: boolean; [key: string]: unknown };
}

export interface Provenance {
  source_api?: string;
  dataset_short_name?: string;
  version?: string;
  doi?: string | null;
  retrieved_at?: string;
  citation?: string;
  notes?: string[];
}

export interface Verdict {
  direction: string;
  arrow: string;
  significant: boolean;
  rate_per_decade: number | null;
  rate_units: string;
  plain_language: string;
  caveats?: string[];
  notes?: string[];
  headline_p?: number | null;
  strength?: string;
}

export interface Analysis {
  series_id: string;
  label: string;
  variable_id?: string;
  units: string | null;
  verdict: Verdict;
  period?: {
    start: string;
    end: string;
    n_months: number;
    n_valid: number;
    missing_pct: number;
    years: number;
  };
  chart?: {
    time: string[];
    raw: (number | null)[];
    deseasonalized?: (number | null)[];
    seasonal?: (number | null)[];
    stl_trend?: (number | null)[];
    ols_line?: (number | null)[];
    sen_line?: (number | null)[];
  };
  provenance?: Provenance;
  court?: Court;
}

export interface Court {
  stamp: "SIGNIFICANT" | "NOT PROVEN";
  chosen_test: string;
  reason: string;
  plain_language?: string;
  limit?: string;
  flips?: boolean;
  jurors?: {
    id: string;
    name: string;
    significant: boolean;
    p: number | null;
    slope_per_decade?: number | null;
  }[];
  consistency?: string[];
}

export interface Integrity {
  badge: "OK" | "CAUTION" | "NOT_FIT";
  badge_icon: string;
  reasons: string[];
  limits: string[];
  trend_or_jump?: { plain_language?: string; [key: string]: unknown };
  seams?: {
    date: string;
    description?: string;
    citation?: string;
    url?: string;
    significant?: boolean;
  }[];
}

export interface EvidenceClock {
  triangle_label?: string;
  triangle?: {
    start_years?: number[];
    end_years?: number[];
    slope_per_decade?: (number | null)[][];
    p_value?: (number | null)[][];
    [key: string]: unknown;
  };
  years_to_detect: { plain_language?: string; [key: string]: unknown };
  assumptions?: string[];
  window_rank?: { plain_language?: string } | null;
}

export interface InvestigationRequest {
  question?: string;
  variable_id?: string;
  geometry?: Geometry;
  start?: string;
  end?: string;
  insights?: string[];
  explain?: boolean;
  max_regions?: number;
}

export interface InvestigationReport {
  on_topic?: boolean;
  message?: string;
  needs_user_input?: string[];
  plan?: PlanResponse;
  results?: {
    series: {
      series_id: string;
      source_api?: string;
      notes?: string[];
      [key: string]: unknown;
    };
    analysis: Analysis;
    insights?: Record<string, unknown> | null;
  }[];
  explanation?: AIAnswer;
  answer?: {
    headline?: string;
    sections?: {
      intent: string;
      question: string;
      answer: string;
      source: string;
    }[];
  };
}

export interface ApiErrorDetail {
  code: string;
  message: string;
  detail?: unknown;
}
export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly detail: unknown;
  constructor(error: ApiErrorDetail, status = 0) {
    super(error.message);
    this.name = "ApiError";
    this.status = status;
    this.code = error.code;
    this.detail = error.detail;
  }
}

export interface Job<T> {
  job_id?: string;
  id?: string;
  status: "queued" | "fetching" | "processing" | "done" | "error";
  progress: number;
  message: string;
  result?: T | null;
  error?: ApiErrorDetail | null;
}
export interface JobOptions {
  signal?: AbortSignal;
  onProgress?: (job: Job<InvestigationReport>) => void;
  /** Stop browser polling after this interval; does not cancel the backend job. */
  timeoutMs?: number;
}

const configuredBase = (
  import.meta as ImportMeta & { env?: Record<string, string> }
).env?.VITE_API_URL?.trim();
function apiBase(): string {
  if (!configuredBase) return "/api";
  const url = new URL(configuredBase, window.location.origin);
  if (
    !["http:", "https:"].includes(url.protocol) ||
    url.username ||
    url.password ||
    url.search ||
    url.hash
  ) {
    throw new ApiError({
      code: "configuration",
      message:
        "The backend URL must be an HTTP URL without credentials, query or fragment.",
    });
  }
  const base = url.href.replace(/\/+$/, "");
  return base.endsWith("/api") ? base : `${base}/api`;
}

export async function request<T>(
  path: string,
  body?: unknown,
  signal?: AbortSignal,
  method = body === undefined ? "GET" : "POST",
): Promise<T> {
  // Paths are internal constants. Never follow a status_url returned by a server.
  const controller = new AbortController();
  const abort = () => controller.abort(signal?.reason);
  if (signal?.aborted) abort();
  else signal?.addEventListener("abort", abort, { once: true });
  let timedOut = false;
  const timer = setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, 120_000);
  try {
    const response = await fetch(`${apiBase()}${path}`, {
      method,
      signal: controller.signal,
      credentials: "same-origin",
      redirect: "error",
      headers: {
        Accept: "application/json",
        ...(body === undefined || body instanceof FormData
          ? {}
          : { "Content-Type": "application/json" }),
      },
      body:
        body === undefined
          ? undefined
          : body instanceof FormData
            ? body
            : JSON.stringify(body),
    });
    const payload: unknown = await response.json().catch(() => null);
    if (!response.ok) {
      const error =
        payload && typeof payload === "object" && "error" in payload
          ? (payload as { error: ApiErrorDetail }).error
          : null;
      throw new ApiError(
        {
          code: error?.code ?? "http_error",
          message:
            error?.message ?? `The backend returned HTTP ${response.status}.`,
          detail: error?.detail,
        },
        response.status,
      );
    }
    if (payload === null)
      throw new ApiError({
        code: "invalid_response",
        message: "The backend returned an empty or invalid response.",
      });
    return payload as T;
  } catch (error) {
    if (signal?.aborted)
      throw new DOMException("Request cancelled", "AbortError");
    if (timedOut)
      throw new ApiError({
        code: "timeout",
        message: "The backend took too long to respond. Please try again.",
      });
    if (error instanceof ApiError) throw error;
    throw new ApiError({
      code: "network_error",
      message: "Cannot reach the backend. Start the API server and try again.",
    });
  } finally {
    clearTimeout(timer);
    signal?.removeEventListener("abort", abort);
  }
}

function questionBody(question: string): { question: string } {
  const cleaned = question.trim();
  if (!cleaned || cleaned.length > 2000)
    throw new ApiError({
      code: "invalid_question",
      message: "Enter an Earth-system question of 1 to 2,000 characters.",
    });
  return { question: cleaned };
}
const idPath = (id: string) => encodeURIComponent(id);
export const exportURL = (id: string, format: "csv" | "json" = "csv") =>
  `${apiBase()}/export/${idPath(id)}?format=${format}`;

export const planQuestion = (question: string, signal?: AbortSignal) =>
  request<PlanResponse>("/ai/plan", questionBody(question), signal);
export const askQuestion = (question: string, signal?: AbortSignal) =>
  request<AIAnswer>("/ai/ask", questionBody(question), signal);
export const getAIStatus = (signal?: AbortSignal) =>
  request<AIStatus>("/ai/status", undefined, signal);
export const getHealth = (signal?: AbortSignal) =>
  request<{ status: string; version: string; catalog_variables: number }>(
    "/health",
    undefined,
    signal,
  );
export const getIntegrity = (id: string, signal?: AbortSignal) =>
  request<Integrity>(`/timeseries/${idPath(id)}/integrity`, undefined, signal);
export const getCourt = (id: string, signal?: AbortSignal) =>
  request<Court>(`/analyze/${idPath(id)}/court`, undefined, signal);
export const getEvidenceClock = (id: string, signal?: AbortSignal) =>
  request<EvidenceClock>(
    `/analyze/${idPath(id)}/detectability`,
    undefined,
    signal,
  );
export const analyzeSeries = (id: string, signal?: AbortSignal) =>
  request<Analysis>(
    "/analyze",
    { series_id: id, include_series: true, include_court: true },
    signal,
  );
export const explainSeries = (id: string, signal?: AbortSignal) =>
  request<AIAnswer>(
    "/ai/explain",
    { series_id: id, include_insights: true },
    signal,
  );
export const searchRegions = (query: string, signal?: AbortSignal) =>
  request<{ results: Region[] }>(
    `/regions/search?q=${encodeURIComponent(query)}&point=false`,
    undefined,
    signal,
  );
export const getVariables = (query = "", signal?: AbortSignal) =>
  request<{ variables: Variable[] }>(
    `/variables?q=${encodeURIComponent(query)}`,
    undefined,
    signal,
  );

export async function uploadCSV(
  file: File,
  signal?: AbortSignal,
): Promise<{ series_id: string }> {
  const form = new FormData();
  form.append("file", file);
  return request("/timeseries/upload-csv", form, signal);
}

export async function pollJob<T = InvestigationReport>(
  id: string,
  options: {
    signal?: AbortSignal;
    onProgress?: (job: Job<T>) => void;
    timeoutMs?: number;
  } = {},
): Promise<T> {
  const deadline = Date.now() + (options.timeoutMs ?? 20 * 60_000);
  while (Date.now() < deadline) {
    if (options.signal?.aborted)
      throw new DOMException("Request cancelled", "AbortError");
    const job = await request<Job<T>>(
      `/jobs/${idPath(id)}?wait=10`,
      undefined,
      options.signal,
    );
    options.onProgress?.(job);
    if (job.status === "done") {
      if (job.result == null)
        throw new ApiError({
          code: "invalid_response",
          message: "The completed investigation has no result.",
        });
      return job.result;
    }
    if (job.status === "error")
      throw new ApiError(
        job.error ?? {
          code: "job_error",
          message: job.message || "The investigation could not finish.",
        },
      );
    // The backend long-polls active work. Queued jobs can return immediately.
    await new Promise<void>((resolve, reject) => {
      const cancel = () => {
        clearTimeout(timer);
        reject(new DOMException("Request cancelled", "AbortError"));
      };
      const timer = setTimeout(() => {
        options.signal?.removeEventListener("abort", cancel);
        resolve();
      }, 500);
      if (options.signal?.aborted) cancel();
      else options.signal?.addEventListener("abort", cancel, { once: true });
    });
  }
  throw new ApiError({
    code: "poll_timeout",
    message:
      "The investigation is still taking time. Browser polling has stopped; the backend job may continue.",
  });
}

/** Aborting stops the browser request/polling. The API does not expose server-job cancellation. */
export async function investigate(
  input: InvestigationRequest,
  options: JobOptions = {},
): Promise<InvestigationReport> {
  const body =
    input.question === undefined
      ? input
      : { ...input, ...questionBody(input.question) };
  const started = await request<{ job_id: string } | InvestigationReport>(
    "/investigate",
    body,
    options.signal,
  );
  if (!("job_id" in started)) return started;
  return pollJob<InvestigationReport>(started.job_id, options);
}

export const api = {
  plan: planQuestion,
  ask: askQuestion,
  status: getAIStatus,
  health: getHealth,
  investigate,
  pollJob,
  integrity: getIntegrity,
  court: getCourt,
  clock: getEvidenceClock,
  analyze: analyzeSeries,
  explain: explainSeries,
  regions: searchRegions,
  variables: getVariables,
  uploadCSV,
};
