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
  conversation_id?: string;
  context?: ConversationContext;
}

/** What a follow-up used: parts the new question named plus parts kept from the conversation. */
export interface ConversationContext {
  variable?: string | null;
  variable_id?: string | null;
  region?: string | null;
  period?: { start: string | null; end?: string | null } | null;
  inherited?: string[];
  explicit?: string[];
  summary?: string;
  message?: string | null;
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
  message?: string;
  data_note?: string;
  test_note?: string;
  conversation_id?: string;
  context?: ConversationContext;
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
export function apiBase(): string {
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

const withConversation = (question: string, conversationId?: string | null) =>
  conversationId ? { ...questionBody(question), conversation_id: conversationId } : questionBody(question);
export const planQuestion = (question: string, signal?: AbortSignal, conversationId?: string | null) =>
  request<PlanResponse>("/ai/plan", withConversation(question, conversationId), signal);
export const askQuestion = (question: string, signal?: AbortSignal, conversationId?: string | null) =>
  request<AIAnswer>("/ai/ask", withConversation(question, conversationId), signal);
/** A client-side conversation id (letters, digits, _) for follow-up memory on /report. */
export function newConversationId(): string {
  const raw = typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID()
    : `${Date.now().toString(36)}${Math.random().toString(36).slice(2)}`;
  return `c_${raw.replace(/[^A-Za-z0-9]/g, "").slice(0, 24)}`;
}
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

// ===================================================================== report story
export interface ReportRequest {
  question: string;
  start?: string;
  end?: string;
  variable_id?: string;
  geometry?: Geometry;
  /** Follow-up memory: the backend fills a missing variable / place / years from this conversation. */
  conversation_id?: string;
}
/** POST /api/report → 202 {job_id} → poll /api/jobs/{id}?wait=10. The raw result is normalised by report.ts. */
export interface ReportPartial {
  status: string;
  progress: number;
  message: string;
  ready: boolean;
  report: unknown;
}
/** With `onPartial`, GET /api/report/{id}/partial is polled alongside the job: the deterministic report arrives
 * within seconds, then AI-written sections replace the template text one by one. */
export async function runReport(
  input: ReportRequest,
  options: {
    signal?: AbortSignal;
    onProgress?: (job: Job<unknown>) => void;
    onPartial?: (report: unknown, partial: ReportPartial) => void;
    partialEveryMs?: number;
  } = {},
): Promise<unknown> {
  const body = { ...input, ...questionBody(input.question) };
  const started = await request<{ job_id?: string } & Record<string, unknown>>("/report", body, options.signal);
  if (typeof started.job_id !== "string") return started;
  const id = started.job_id;
  if (!options.onPartial) return pollJob<unknown>(id, options);
  let finished = false;
  const every = options.partialEveryMs ?? 1200;
  const partials = (async () => {
    let last = "";
    while (!finished && !options.signal?.aborted) {
      try {
        const p = await request<ReportPartial>(`/report/${idPath(id)}/partial`, undefined, options.signal);
        if (p.ready && p.report && !finished) {
          const key = JSON.stringify([p.status, (p.report as { ai?: unknown } | null)?.ai]);
          if (key !== last) { last = key; options.onPartial?.(p.report, p); }
        }
        if (p.status === "done" || p.status === "error") return;
      } catch {
        // partial results are a convenience; the job poll below reports real errors
      }
      await new Promise((r) => setTimeout(r, every));
    }
  })();
  try {
    return await pollJob<unknown>(id, options);
  } finally {
    finished = true;
    void partials;
  }
}

// ===================================================================== active trends (live, verified)
export interface ActiveEvent {
  seq: number;
  type: string;
  t?: number;
  variable_id?: string;
  [key: string]: any;
}
export interface ActiveTrendsRequest {
  geometry?: Geometry;
  start?: string;
  end?: string;
  criteria?: string[];
  variable_ids?: string[];
  series_ids?: string[];
  region_name?: string;
}
export interface WhereToLook {
  name: string;
  url: string;
}
export interface Skipped {
  criterion?: string;
  variable_id?: string;
  reason?: string;
  where_to_look?: WhereToLook[];
}
export interface ActiveTrendsStart {
  job_id: string;
  reused: boolean;
  variables?: string[];
  skipped?: Skipped[];
}
export interface Criterion {
  id: string;
  n: number;
  name: string;
  status: "live" | "proxy" | "short_record" | "not_trendable";
  definition?: string;
  note?: string;
  variables: { id: string; name: string; short_definition?: string }[];
  where_to_look?: WhereToLook[];
}
export type ViewMarkerKind = "beast_confirmed" | "beast_possible" | "beast_weak" | "pelt_break";
export interface SeriesView {
  series_id: string;
  label?: string | null;
  units?: string | null;
  chart: {
    time: string[];
    observed?: (number | null)[];
    deseasonalized?: (number | null)[];
    sen_line?: (number | null)[];
    ols_line?: (number | null)[];
    beast_trend?: (number | null)[];
    change_probability?: (number | null)[];
  };
  markers: { date: string; kind: ViewMarkerKind | string; interval?: string[] | null; probability?: number | null }[];
  recent_window?: { start: string; end: string } | null;
  caption?: string | null;
  limits?: string[];
  explanation?: { text: string; source: string; label: string };
}
export interface Paper {
  title: string;
  year?: number;
  venue?: string;
  authors?: string[];
  doi?: string | null;
  url?: string | null;
  trust?: string;
}
export interface ResearchBlock {
  status?: string;
  reason?: string;
  papers?: Paper[];
  agreement?: { label: string };
  plain_language?: string;
  limits?: string[];
}
export interface ActiveTrend {
  variable_id: string | null;
  name: string;
  series_id: string;
  detect: { state: string; plain_language?: string; rate_per_decade?: number; units?: string; recent_window?: { start: string; end: string } };
  checks: { check: string; status: string; plain_language?: string }[];
  beast?: { status: string; plain_language?: string; active_since?: { date?: string; interval90?: string[] } | null };
  verdict: { label: "VERIFIED" | "PROBABLE" | "NOT VERIFIED"; why?: string; plain_language?: string; limit?: string };
  ai_review?: { status: string; plain_language?: string };
  research?: ResearchBlock;
  view?: SeriesView;
}
export interface ActiveTrendsResult {
  trends: ActiveTrend[];
  not_active?: { variable_id?: string; name?: string; plain_language?: string; state?: string }[];
  failed?: Record<string, string>;
  skipped?: Skipped[];
  summary?: Record<string, number>;
  plain_language?: string;
  limits?: string[];
  best_trend?: { best?: { variable_id?: string; name?: string; label?: string } | null; plain_language?: string; explanation?: string };
}
export interface MethodsLiterature {
  since_year?: number;
  papers: Paper[];
  plain_language?: string;
}

/** Splits an SSE text buffer into complete `data:` JSON events and the unfinished remainder. */
export function parseSSE(buffer: string): { events: ActiveEvent[]; rest: string } {
  const blocks = buffer.replace(/\r\n/g, "\n").split("\n\n");
  const rest = blocks.pop() ?? "";
  const events: ActiveEvent[] = [];
  for (const block of blocks) {
    const data = block.split("\n").filter((l) => l.startsWith("data:")).map((l) => l.slice(5).trimStart()).join("\n");
    if (!data) continue; // keep-alive comment
    try {
      events.push(JSON.parse(data));
    } catch {
      /* malformed block skipped; the long-poll fallback replays by seq */
    }
  }
  return { events, rest };
}

const isEnd = (ev: ActiveEvent) => ev.type === "done" || ev.type === "error";

/** Live events: SSE first, long-poll `/events` from the last seen seq if the stream is unavailable or breaks. */
export async function followActiveTrends(
  jobId: string,
  onEvent: (ev: ActiveEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  let after = 0;
  const emit = (ev: ActiveEvent) => {
    if (typeof ev.seq === "number") {
      if (ev.seq < after) return false;
      after = ev.seq + 1;
    }
    onEvent(ev);
    return isEnd(ev);
  };
  try {
    const res = await fetch(`${apiBase()}/active-trends/${idPath(jobId)}/stream?after=0`, {
      signal, credentials: "same-origin", redirect: "error", headers: { Accept: "text/event-stream" },
    });
    if (res.ok && res.body) {
      const reader = res.body.pipeThrough(new TextDecoderStream()).getReader();
      let buffer = "";
      for (;;) {
        const { value, done } = await reader.read();
        if (done) break;
        const parsed = parseSSE(buffer + value);
        buffer = parsed.rest;
        for (const ev of parsed.events) if (emit(ev)) { void reader.cancel(); return; }
      }
    }
  } catch {
    if (signal?.aborted) throw new DOMException("Request cancelled", "AbortError");
  }
  for (;;) {
    let page: { events: ActiveEvent[]; next: number; done: boolean };
    try {
      page = await request(`/active-trends/${idPath(jobId)}/events?after=${after}&wait=25`, undefined, signal);
    } catch (error) {
      if (error instanceof ApiError && error.status === 404) return; // log gone: the final result is at /jobs/{id}
      throw error;
    }
    for (const ev of page.events) if (emit(ev)) return;
    after = Math.max(after, page.next);
    if (page.done) return;
  }
}

export const startActiveTrends = (body: ActiveTrendsRequest, signal?: AbortSignal) =>
  request<ActiveTrendsStart>("/active-trends", body, signal);

/** Start → live events → final job result. */
export async function runActiveTrends(
  body: ActiveTrendsRequest,
  options: { signal?: AbortSignal; onStart?: (s: ActiveTrendsStart) => void; onEvent: (ev: ActiveEvent) => void },
): Promise<ActiveTrendsResult> {
  const started = await startActiveTrends(body, options.signal);
  options.onStart?.(started);
  await followActiveTrends(started.job_id, options.onEvent, options.signal);
  return pollJob<ActiveTrendsResult>(started.job_id, { signal: options.signal });
}

export const getCriteria = (signal?: AbortSignal) =>
  request<{ criteria: Criterion[] }>("/criteria", undefined, signal);
export const getView = (seriesId: string, signal?: AbortSignal) =>
  request<SeriesView>(`/view/${idPath(seriesId)}`, undefined, signal);
export const cardURL = (seriesId: string) => `${apiBase()}/view/${idPath(seriesId)}/card.svg`;
export const getResearchMethods = (signal?: AbortSignal) =>
  request<MethodsLiterature>("/research/methods", undefined, signal);

/** Local model + harness (GET /ai/hardware, /sources/status, /harness; POST /harness/probe). */
export interface LLMTierStatus {
  provider: string;
  available: boolean;
  model?: string | null;
  reason?: string;
  hint?: string;
  installed_models?: string[];
  note?: string;
  last_error?: string | null;
}
export interface ModelPick { provider?: string; model: string; weights_gb?: number; why?: string; [key: string]: unknown }
export interface HardwareInfo {
  profile: {
    os?: string;
    gpu_name?: string | null;
    gpu_note?: string | null;
    vram_total_gb?: number;
    vram_free_gb?: number;
    ram_total_gb?: number;
    ram_available_gb?: number;
    disk_free_gb?: number;
    packages?: Record<string, boolean>;
  };
  recommendation: { live: ModelPick; deep: ModelPick | null; notes: string[] };
  live: LLMTierStatus;
  deep: LLMTierStatus;
}
export interface SourcesStatus {
  credentials: Record<string, boolean>;
  llm: LLMTierStatus;
}
export interface HarnessStage { id: string; name: string; component: string; model: string }
export interface HarnessInfo {
  config: {
    model: { provider: string; base_url: string; name: string; timeout_s: number; max_tokens: number; temperature: number };
    deep: { provider: string; model: string; max_new_tokens: number };
    pipeline: { alpha: number; min_years: number; verify: string; rewrite: boolean; rewrite_sections: string[] };
    data: { credentials: Record<string, { env: string; set: boolean }> };
  };
  source: string;
  model_status: { live: LLMTierStatus; deep: LLMTierStatus };
  stages: HarnessStage[];
  prompts: string[];
  rewrite_sections_active: string[];
  limit: string;
}
export interface ProbeResult {
  tier: string;
  provider: string;
  model?: string | null;
  available?: boolean;
  verdict: "pass" | "fail" | "unavailable";
  reason?: string;
  latency_s?: number;
  approx_tokens_per_s?: number | null;
  answer?: string;
  verify?: { passed: boolean; badge: string; unsupported_numbers: unknown[] };
}
export const getHardware = (signal?: AbortSignal) =>
  request<HardwareInfo>("/ai/hardware", undefined, signal);
export const getSourcesStatus = (signal?: AbortSignal) =>
  request<SourcesStatus>("/sources/status", undefined, signal);
export const getHarness = (signal?: AbortSignal) =>
  request<HarnessInfo>("/harness", undefined, signal);
export const probeModel = (signal?: AbortSignal) =>
  request<ProbeResult>("/harness/probe", { tier: "live", timeout_s: 90 }, signal);

export const api = {
  report: runReport,
  activeTrends: runActiveTrends,
  criteria: getCriteria,
  view: getView,
  researchMethods: getResearchMethods,
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
