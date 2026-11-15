/** Typed client for Discovery mode (/api/discovery): start, follow live events, final result, notebook link.
 * Every number shown in the UI comes from these responses; nothing is computed here. */
import { ApiError, apiBase, parseSSE, pollJob, request, type ActiveEvent } from "./api";

export interface DiscoveryRequest {
  prompt?: string;
  geometry?: unknown;
  bbox?: [number, number, number, number];
  region_name?: string;
  criteria?: string[];
  start_year?: number;
  end_year?: number;
  max_findings?: number;
  time_budget_s?: number;
}
export interface DiscoveryPlan {
  prompt?: string | null;
  mode: "region" | "global_sweep";
  region_name?: string | null;
  criteria: string[];
  years: [number, number];
  sweeps: { criterion: string; variable_id: string; box: number[] }[];
  direct: { criterion: string; variable_id: string }[];
  skipped: { criterion: string; reason: string }[];
  asked_years?: [number, number];
  period_notice?: PeriodNotice | null;
}
export interface PeriodNotice { asked: [number, number]; used: [number, number]; plain_language: string }
export interface DiscoveryStart {
  job_id: string;
  reused: boolean;
  plan?: DiscoveryPlan;
  time_budget_s?: number;
}
export interface SourceStatus { source: string; status: string; reason?: string; n?: number }
export interface RelatedWork {
  title: string; year?: number; venue?: string | null; doi?: string | null; doi_url?: string | null; url?: string | null;
  peer_reviewed?: boolean; label?: string; region_match?: boolean;
}
export interface UnreviewedItem {
  title: string; url?: string | null; doi?: string | null; date?: string | null; year?: number | null;
  source?: string | null; domain?: string | null; label: string;
}
export interface DriverLink {
  driver_id: string; driver_name: string; lag_months: number; significant?: boolean; plain_language: string;
}
export interface DiscoveryBrief {
  finding_id: string;
  title: string;
  potential_discovery: boolean | null;
  discovery_label: string | null;
  gap: { plain_language: string; rule: string };
  variable: { id: string; name: string; units?: string | null };
  where: { name: string; approximate: boolean; nominated_by?: string };
  what: string;
  since?: { date: string; interval90?: string[] | null; source: string } | null;
  rate: { plain_language: string };
  verdict: { label: "VERIFIED" | "PROBABLE"; why: string; limit: string; data_note?: string | null };
  checks: { check: string; status: string; plain_language: string }[];
  beast: { status?: string; plain_language?: string };
  drivers: { status?: string; links: DriverLink[]; plain_language?: string; disclaimer?: string; explains?: string };
  literature: { plain_language?: string | null; related_works: RelatedWork[]; sources: SourceStatus[] };
  preprints: { status: string; items: UnreviewedItem[]; label: string; sources?: SourceStatus[] };
  news: { status: string; items: UnreviewedItem[]; label: string; sources?: SourceStatus[] };
  figure: {
    time?: string[]; observed?: (number | null)[]; deseasonalized?: (number | null)[]; sen_line?: (number | null)[];
    beast_trend?: (number | null)[]; units?: string | null; change_date?: string | null;
    recent_window?: { start: string; end: string } | null; markers?: { date: string; kind: string }[];
  };
  outlook: {
    status: string; label: string; disclaimer: string; plain_language?: string; time?: string[];
    p05?: number[]; p50?: number[]; p95?: number[]; units?: string | null;
    unreviewed_context: { label: string; plain_language: string };
  };
  summary: { text: string; source: string; label: string };
  provenance?: { dataset_short_name?: string; version?: string | null; doi?: string | null; retrieved_at?: string; source_api?: string } | null;
  limits: string[];
  notebook_url?: string;
}
/** A place that was tested but did not pass: real series + the engine's numbers + the plain reason. */
export interface TestedCard {
  candidate_id: string;
  place: string;
  variable: { id: string; name: string; units?: string | null };
  label: string;
  state?: string | null;
  reason?: string | null;
  why?: string | null;
  rate?: { per_decade: number; units?: string | null; plain_language: string; significant?: boolean | null } | null;
  full_record?: { per_decade: number; significant?: boolean | null; plain_language: string } | null;
  period?: [string, string] | null;
  figure?: DiscoveryBrief["figure"] | null;
  provenance?: DiscoveryBrief["provenance"];
  checks?: { check: string; status: string; plain_language: string }[];
  limit: string;
  note: string;
}
export interface DiscoveryResult {
  plan: DiscoveryPlan;
  findings: DiscoveryBrief[];
  candidates: { id: string; place: string; variable_id: string; status: string; reason?: string | null; text?: string }[];
  tested?: TestedCard[];
  failed_sources: (SourceStatus & { text?: string })[];
  next_steps?: string | null;
  summary: { candidates: number; findings: number; verified: number; probable: number; potential_new_findings: number };
  timing: { elapsed_s: number; budget_s: number };
  plain_language: string;
  limits: string[];
}

const idPath = (id: string) => encodeURIComponent(id);

export const startDiscovery = (body: DiscoveryRequest, signal?: AbortSignal) =>
  request<DiscoveryStart>("/discovery", body, signal);

export const notebookURL = (jobId: string, findingId: string) =>
  `${apiBase()}/discovery/${idPath(jobId)}/notebook/${idPath(findingId)}`;

/** Live events: SSE first, long-poll `/events` from the last seen seq if the stream is unavailable or breaks. */
export async function followDiscovery(jobId: string, onEvent: (ev: ActiveEvent) => void, signal?: AbortSignal) {
  let after = 0;
  const emit = (ev: ActiveEvent) => {
    if (typeof ev.seq === "number") {
      if (ev.seq < after) return false;
      after = ev.seq + 1;
    }
    onEvent(ev);
    return ev.type === "done" || ev.type === "error";
  };
  try {
    const res = await fetch(`${apiBase()}/discovery/${idPath(jobId)}/stream?after=0`, {
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
      page = await request(`/discovery/${idPath(jobId)}/events?after=${after}&wait=25`, undefined, signal);
    } catch (error) {
      if (error instanceof ApiError && error.status === 404) return;
      throw error;
    }
    for (const ev of page.events) if (emit(ev)) return;
    after = Math.max(after, page.next);
    if (page.done) return;
  }
}

/** Start -> live events -> final result (findings carry `notebook_url`). */
export async function runDiscovery(
  body: DiscoveryRequest,
  options: { signal?: AbortSignal; onStart?: (s: DiscoveryStart) => void; onEvent: (ev: ActiveEvent) => void },
): Promise<{ jobId: string; result: DiscoveryResult }> {
  const started = await startDiscovery(body, options.signal);
  options.onStart?.(started);
  await followDiscovery(started.job_id, options.onEvent, options.signal);
  const result = await pollJob<DiscoveryResult>(started.job_id, { signal: options.signal, timeoutMs: 30 * 60_000 });
  return { jobId: started.job_id, result };
}

// ------------------------------------------------------------------ pure helpers (unit-tested)
/** A DigiTwin prompt with explicit scenario knobs ("doubled", "+0.5", "20%", "threshold") stays in the
 * scenario tools; any other what-if or discovery question opens Discovery mode. */
export function twinPromptRoute(question: string): "scenario" | "discovery" {
  const q = question.toLowerCase();
  const knobs = /\b(doubl\w*|tripl\w*|halv\w*|half as|twice|threshold|shock)\b|(^|\s)[+-]\s?\d|\d\s?(%|x\b|×|times\b)/;
  // "if global temp rises 5 c", "suppose rain falls 10 percent": a hypothetical plus a sized change
  const sized = /\b(if|suppose|imagine|assum\w*)\b/.test(q) &&
    /(^|[^\d])\d{1,3}(\.\d+)?\s*(%|percent|°|º|deg\w*|c\b|f\b|celsius|fahrenheit|k\b|mm)/.test(q);
  return knobs.test(q) || sized ? "scenario" : "discovery";
}

export interface DiscoveryProgress {
  lines: { seq: number; text: string; kind: "info" | "ok" | "skip" | "warn" }[];
  findings: DiscoveryBrief[];
  tested: TestedCard[];
  notice: PeriodNotice | null;
  done: boolean;
  error: string | null;
}
export const emptyProgress = (): DiscoveryProgress => ({ lines: [], findings: [], tested: [], notice: null, done: false, error: null });

/** Readable, non-empty list texts (server `text`, else built from server fields); blank entries are dropped. */
export function listTexts(items: { text?: string | null; source?: string; place?: string; reason?: string | null; status?: string }[] | undefined): string[] {
  return (items ?? [])
    .map(i => (i.text ?? [i.source ?? i.place, i.reason ?? i.status].filter(Boolean).join(": ")).trim())
    .filter(t => t.length > 0);
}

/** Folds one server event into the chat's progress state: readable lines plus finished findings. Texts come
 * from the server (`plain_language`, `reason`); only labels are added here. */
export function applyDiscoveryEvent(state: DiscoveryProgress, ev: ActiveEvent): DiscoveryProgress {
  const line = (text: string, kind: DiscoveryProgress["lines"][number]["kind"] = "info") =>
    ({ ...state, lines: [...state.lines, { seq: ev.seq, text, kind }] });
  switch (ev.type) {
    case "started": {
      const notice = ((ev.plan as DiscoveryPlan | undefined)?.period_notice) ?? null;
      return { ...line(String(ev.plain_language ?? "Discovery started.")), notice };
    }
    case "sweep":
      return line(ev.status === "ok" ? String(ev.plain_language) : `Sweep skipped: ${ev.plain_language ?? ev.reason ?? "grid unavailable"}`,
        ev.status === "ok" ? "info" : "warn");
    case "candidate":
      return line(`Checking ${ev.place ?? "a place"} (${ev.variable_id}).`);
    case "candidate_rejected":
      return line(`Not kept: ${ev.reason ?? "did not pass verification"}`, "skip");
    case "candidate_skipped":
      return line(`Skipped: ${ev.reason ?? ""}`, "skip");
    case "checking_literature":
      return line(`Passed verification. Searching published studies, preprints and news${ev.place ? ` for ${ev.place}` : ""}.`, "ok");
    case "finding":
      return ev.finding ? { ...state, findings: [...state.findings, ev.finding as DiscoveryBrief] } : state;
    case "tested":
      return ev.card ? { ...state, tested: [...state.tested, ev.card as TestedCard] } : state;
    case "done":   // the run summary is shown once, under the results, not repeated in the step log
      return { ...state, done: true };
    case "error":
      return { ...line(String(ev.message ?? "Discovery failed."), "warn"), done: true, error: String(ev.message ?? "Discovery failed.") };
    default:
      return state;
  }
}

export const discoveryApi = { start: startDiscovery, follow: followDiscovery, run: runDiscovery, notebookURL };


// ---------------------------------------------------------------- what-if (POST /api/twin/whatif -> job)
export interface WhatIfBand { p05: number[]; p50: number[]; p95: number[] }
export interface WhatIfPlace {
  place: string;
  variable: string;
  variable_id: string;
  units: string;
  label: "simulated";
  observed: { years: number[]; annual_mean: (number | null)[] };
  simulated: { years: number[]; with_change: WhatIfBand; without_change: WhatIfBand };
  trend_per_decade: { observed: number; observed_ci95: number; with_change: number };
  end: { year: number; with_change: number; without_change: number; difference: number; with_change_range90: [number, number] };
  change_applied: string;
  plain_language: string;
  provenance: { dataset?: string | null; version?: string | null; source_api?: string | null; doi?: string | null; retrieved_at?: string | null };
}
export interface WhatIfResult {
  question: string;
  change: { kind: string; value: number; unit: string | null; target_year: number | null; scope: string; text: string };
  target_year: number;
  places: WhatIfPlace[];
  skipped: { place: string; reason: string }[];
  scope_note: string | null;
  label: "simulated";
  disclaimer: string;
  method: string;
}

/** Runs a what-if for every place in the question; progress comes from the job, every number from the API. */
export async function runWhatIf(question: string, options: { signal?: AbortSignal; onProgress?: (message: string) => void } = {}): Promise<WhatIfResult> {
  const started = await request<{ job_id: string }>("/twin/whatif", { question }, options.signal);
  return pollJob<WhatIfResult>(started.job_id, {
    signal: options.signal,
    onProgress: job => options.onProgress?.(job.message || ""),
  });
}
