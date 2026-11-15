/** Pure reducer for the active-trends live view. No numbers are computed here. */
export type CheckStatus = "pass" | "warn" | "fail" | "skipped" | string;
export type Label = "VERIFIED" | "PROBABLE" | "NOT VERIFIED";

import type { ActiveEvent } from "./api";
export type { ActiveEvent };

export interface CheckResult {
  check: string;
  status: CheckStatus;
  plain_language?: string;
  detail?: Record<string, unknown>;
}

export interface LiveCard {
  variable_id: string;
  series_id?: string;
  stage: "waiting" | "fetching" | "candidate" | "not_active" | "beast" | "verdict" | "failed";
  state?: string;
  plain_language?: string;
  rate_per_decade?: number | null;
  units?: string | null;
  checks: CheckResult[];
  beast?: { status: string; plain_language?: string; active_since?: { date?: string; interval90?: string[] } | null };
  verdict?: { label: Label; why?: string; plain_language?: string; limit?: string; provisional?: boolean };
  research?: { agreement?: string; plain_language?: string };
  caption?: string;
  message?: string;
}

export interface LiveState {
  next: number;
  order: string[];
  cards: Record<string, LiveCard>;
  best?: { best?: Record<string, unknown> | null; plain_language?: string };
  summary?: string;
  done: boolean;
  error?: string;
}

export const initialLive = (variables: string[] = []): LiveState => ({
  next: 0,
  order: [...variables],
  cards: Object.fromEntries(variables.map((v) => [v, { variable_id: v, stage: "waiting", checks: [] } as LiveCard])),
  done: false,
});

/** Applies one server event. Events with an already-seen `seq` are ignored, so SSE and long-poll can overlap. */
export function reduceEvent(state: LiveState, ev: ActiveEvent): LiveState {
  if (typeof ev.seq === "number" && ev.seq < state.next) return state;
  const s: LiveState = { ...state, next: typeof ev.seq === "number" ? ev.seq + 1 : state.next };
  const vid = ev.variable_id;
  const card = (): LiveCard => {
    const prev = (vid && s.cards[vid]) || { variable_id: vid!, stage: "waiting", checks: [] };
    if (vid && !s.order.includes(vid)) s.order = [...s.order, vid];
    return { ...prev };
  };
  const put = (c: LiveCard) => (s.cards = { ...s.cards, [c.variable_id]: c });
  switch (ev.type) {
    case "started":
      for (const v of (ev.variables as string[]) || []) if (!s.order.includes(v)) {
        s.order = [...s.order, v];
        s.cards = { ...s.cards, [v]: { variable_id: v, stage: "waiting", checks: [] } };
      }
      return s;
    case "fetching":
      if (vid) put({ ...card(), stage: "fetching" });
      return s;
    case "fetched":
      if (vid) put({ ...card(), series_id: ev.series_id });
      return s;
    case "candidate":
    case "not_active":
      if (vid) put({
        ...card(), stage: ev.type, series_id: ev.series_id ?? card().series_id, state: ev.state,
        plain_language: ev.plain_language, rate_per_decade: ev.rate_per_decade, units: ev.units,
      });
      return s;
    case "check": {
      if (!vid) return s;
      const c = card();
      const item: CheckResult = { check: ev.check, status: ev.status, plain_language: ev.plain_language, detail: ev.detail };
      put({ ...c, checks: [...c.checks.filter((x) => x.check !== ev.check), item] });
      return s;
    }
    case "beast_started":
      if (vid) put({ ...card(), stage: "beast" });
      return s;
    case "beast":
      if (vid) put({ ...card(), beast: { status: ev.status, plain_language: ev.plain_language, active_since: ev.active_since } });
      return s;
    case "verdict":
      if (vid) put({
        ...card(), stage: "verdict",
        verdict: { label: ev.label, why: ev.why, plain_language: ev.plain_language, limit: ev.limit, provisional: ev.provisional },
      });
      return s;
    case "research":
      if (vid) put({ ...card(), research: { agreement: ev.agreement, plain_language: ev.plain_language } });
      return s;
    case "view":
      if (vid) put({ ...card(), caption: ev.caption });
      return s;
    case "failed":
      if (vid) put({ ...card(), stage: "failed", message: ev.message });
      return s;
    case "best_trend":
      s.best = { best: ev.best, plain_language: ev.plain_language };
      return s;
    case "done":
      s.done = true;
      s.summary = ev.plain_language;
      return s;
    case "error":
      s.done = true;
      s.error = ev.message || "The active-trend scan stopped.";
      return s;
    default:
      return s;
  }
}
