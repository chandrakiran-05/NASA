import { lazy, Suspense, useEffect, useReducer, useState } from "react";
import { AlertTriangle, ArrowUpRight, Check, Minus, Printer, X } from "lucide-react";
import {
  api, cardURL,
  type ActiveTrend, type ActiveTrendsRequest, type ActiveTrendsResult, type Criterion,
  type MethodsLiterature, type SeriesView, type Skipped,
} from "./api";
import { initialLive, reduceEvent, type ActiveEvent, type LiveCard, type LiveState } from "./activeEvents";
import Narrative from "./Narrative";
import "./evidence.css";
import "./active.css";
const EvidenceChart = lazy(() => import("./EvidenceChart"));

export type ActiveRun = { id: number; body: ActiveTrendsRequest; title?: string };

type Action = { reset: string[] } | { event: ActiveEvent };
const reducer = (s: LiveState, a: Action) => ("reset" in a ? initialLive(a.reset) : reduceEvent(s, a.event));

const stageText: Record<LiveCard["stage"], string> = {
  waiting: "Waiting", fetching: "Fetching the record", candidate: "Candidate: running checks",
  not_active: "Not changing in the recent window", beast: "BEAST dating the change", verdict: "Verdict", failed: "Could not be tested",
};
const errorText = (e: unknown, fallback: string) => (e instanceof Error ? e.message : fallback);

function StatusMark({ status }: { status: string }) {
  const Icon = status === "pass" ? Check : status === "fail" ? X : status === "warn" ? AlertTriangle : Minus;
  return <span className={`check-mark is-${status}`}><Icon size={12} aria-hidden="true" />{status}</span>;
}
function LabelStamp({ label }: { label: string }) {
  return <p className={`active-label is-${label.replace(" ", "-").toLowerCase()}`}>{label}</p>;
}

function LiveCardView({ card, name }: { card: LiveCard; name: string }) {
  return (
    <article className="active-card" aria-label={name}>
      <header><h4>{name}</h4><span className="active-stage">{stageText[card.stage]}</span></header>
      {card.state && <p className="active-state">State: {card.state}</p>}
      <Narrative value={card.plain_language} />
      {card.message && <p className="evidence-error">{card.message}</p>}
      {card.checks.length > 0 && (
        <ul className="active-checks">
          {card.checks.map((c) => (
            <li key={c.check}>
              <StatusMark status={c.status} />
              <b>{c.check === "ai_review" ? "AI reviewer (advisory)" : c.check.replaceAll("_", " ")}</b>
              <span>{c.plain_language}</span>
            </li>
          ))}
        </ul>
      )}
      {card.beast && <p className="active-beast"><b>BEAST:</b> {card.beast.status}{card.beast.active_since?.date ? ` · active since about ${card.beast.active_since.date}` : ""}{card.beast.plain_language ? ` — ${card.beast.plain_language}` : ""}</p>}
      {card.verdict && (
        <div className="active-verdict">
          <LabelStamp label={card.verdict.label} />
          {card.verdict.provisional && <span className="active-provisional">provisional, cross-variable checks pending</span>}
          <Narrative value={card.verdict.why} />
          {card.verdict.limit && <p className="active-limit">{card.verdict.limit}</p>}
        </div>
      )}
      {card.research?.plain_language && <p className="active-research-line">Research: {card.research.plain_language}</p>}
    </article>
  );
}

function TrendDetail({ trend }: { trend: ActiveTrend }) {
  const [view, setView] = useState<SeriesView | null>(trend.view ?? null);
  const [error, setError] = useState("");
  useEffect(() => {
    if (trend.view) return setView(trend.view);
    const c = new AbortController();
    api.view(trend.series_id, c.signal).then(setView, (e) => !c.signal.aborted && setError(errorText(e, "The chart view could not be loaded.")));
    return () => c.abort();
  }, [trend]);
  return (
    <section className="trend-detail" aria-label={`Evidence for ${trend.name}`}>
      <div className="record-heading">
        <div><h3>{view?.label || trend.name}</h3><p>{trend.detect.plain_language}</p></div>
        <LabelStamp label={trend.verdict.label} />
      </div>
      {error && <p className="evidence-error" role="alert">{error}</p>}
      {view && (
        <>
          <Suspense fallback={<p className="evidence-loading" role="status">Preparing the chart…</p>}>
            <EvidenceChart view={view} />
          </Suspense>
          <p className="trend-legend-note">Shaded: recent window tested. Solid line: confirmed BEAST change; dashed: possible; dotted: PELT break. Gaps are missing months.</p>
          <Narrative value={view.caption} />
          {view.explanation && (
            <div className="trend-explanation">
              <span className="trend-source">{view.explanation.label}</span>
              <Narrative value={view.explanation.text} />
            </div>
          )}
          <Narrative value={view.limits} />
        </>
      )}
      {trend.verdict.limit && <p className="active-limit">{trend.verdict.limit}</p>}
      {trend.ai_review?.plain_language && <p className="active-research-line">AI reviewer (advisory): {trend.ai_review.plain_language}</p>}
      {trend.research && (
        <details className="trend-research">
          <summary>Recent research{trend.research.agreement ? `: ${trend.research.agreement.label.replaceAll("_", " ")}` : ""}</summary>
          <Narrative value={trend.research.plain_language ?? trend.research.reason} />
          {!!trend.research.papers?.length && (
            <ul>{trend.research.papers.map((p, i) => <li key={i}>{p.url ? <a href={p.url} target="_blank" rel="noreferrer">{p.title}</a> : p.title}{p.year ? ` (${p.year})` : ""}{p.trust ? ` · ${p.trust}` : ""}</li>)}</ul>
          )}
          <Narrative value={trend.research.limits} />
        </details>
      )}
      <a className="record-download" href={cardURL(trend.series_id)} target="_blank" rel="noreferrer"><Printer size={15} /> Printable card</a>
    </section>
  );
}

function SkippedList({ items }: { items: Skipped[] }) {
  if (!items.length) return null;
  return (
    <details className="active-skipped">
      <summary>Not tested here ({items.length})</summary>
      <ul>
        {items.map((s, i) => (
          <li key={i}>
            <b>{s.criterion || s.variable_id}</b> — {s.reason}
            {!!s.where_to_look?.length && <> Where to look: {s.where_to_look.map((w, j) => <a key={j} href={w.url} target="_blank" rel="noreferrer">{w.name}</a>)}</>}
          </li>
        ))}
      </ul>
    </details>
  );
}

function CriteriaPicker({ onRun, disabled }: { onRun: (ids: string[]) => void; disabled: boolean }) {
  const [list, setList] = useState<Criterion[] | null>(null);
  const [picked, setPicked] = useState<string[]>([]);
  const [error, setError] = useState("");
  const load = () => { if (!list) api.criteria().then((r) => setList(r.criteria), (e) => setError(errorText(e, "Criteria could not be loaded."))); };
  return (
    <details className="criteria-picker" onToggle={(e) => (e.currentTarget.open ? load() : undefined)}>
      <summary>What can I investigate here?</summary>
      {error && <p className="evidence-error" role="alert">{error}</p>}
      {!list && !error && <p className="evidence-loading" role="status">Loading criteria…</p>}
      {list && (
        <>
          <ul>
            {list.map((c) => (
              <li key={c.id} className={c.status === "not_trendable" ? "is-off" : ""}>
                <label>
                  <input type="checkbox" disabled={c.status === "not_trendable"} checked={picked.includes(c.id)}
                    onChange={(e) => setPicked(e.target.checked ? [...picked, c.id] : picked.filter((x) => x !== c.id))} />
                  <b>{c.name}</b> <span className="criteria-status">{c.status === "not_trendable" ? "cannot be trend-tested" : c.status.replace("_", " ")}</span>
                </label>
                <p>{c.definition}</p>
                {c.note && <p>{c.note}</p>}
                {c.status === "not_trendable" && !!c.where_to_look?.length && (
                  <p>Where to look: {c.where_to_look.map((w, j) => <a key={j} href={w.url} target="_blank" rel="noreferrer">{w.name}</a>)}</p>
                )}
              </li>
            ))}
          </ul>
          <button type="button" className="record-download" disabled={disabled || !picked.length} onClick={() => onRun(picked)}>
            Check these now <ArrowUpRight size={14} />
          </button>
        </>
      )}
    </details>
  );
}

function MethodsBehind() {
  const [data, setData] = useState<MethodsLiterature | null>(null);
  const [error, setError] = useState("");
  return (
    <details className="trend-research" onToggle={(e) => { if (e.currentTarget.open && !data) api.researchMethods().then(setData, (x) => setError(errorText(x, "Method papers could not be loaded."))); }}>
      <summary>Methods behind this</summary>
      {error && <p className="evidence-error" role="alert">{error}</p>}
      {!data && !error && <p className="evidence-loading" role="status">Searching method papers…</p>}
      {data && (
        <>
          <Narrative value={data.plain_language} />
          <ul>{data.papers.map((p, i) => <li key={i}>{p.url ? <a href={p.url} target="_blank" rel="noreferrer">{p.title}</a> : p.title}{p.year ? ` (${p.year})` : ""}{p.trust ? ` · ${p.trust}` : ""}</li>)}</ul>
        </>
      )}
    </details>
  );
}

export default function ActiveTrends({ run }: { run: ActiveRun }) {
  // Parent remounts with key={run.id}; the criteria picker starts further runs from here.
  const [body, setBody] = useState({ key: 0, body: run.body });
  const [live, dispatch] = useReducer(reducer, undefined, () => initialLive());
  const [result, setResult] = useState<ActiveTrendsResult | null>(null);
  const [skipped, setSkipped] = useState<Skipped[]>([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    const controller = new AbortController();
    dispatch({ reset: [] });
    setResult(null); setSkipped([]); setError(""); setBusy(true);
    api.activeTrends(body.body, {
      signal: controller.signal,
      onStart: (s) => { dispatch({ reset: s.variables ?? [] }); setSkipped(s.skipped ?? []); },
      onEvent: (event) => dispatch({ event }),
    }).then(
      (r) => { setResult(r); if (r.skipped) setSkipped(r.skipped); },
      (e) => { if (!controller.signal.aborted) setError(errorText(e, "The active-trend scan could not finish.")); },
    ).finally(() => { if (!controller.signal.aborted) setBusy(false); });
    return () => controller.abort();
  }, [body.key]);

  const nameOf = (vid: string) => result?.trends.find((t) => t.variable_id === vid || t.series_id === vid)?.name || vid;
  return (
    <section className="workspace evidence-sheet active-trends" aria-labelledby="active-title">
      <header className="evidence-sheet-head">
        <div>
          <h2 id="active-title">What is changing now?</h2>
          <p className="evidence-file-meta"><span>{run.title || "Active trends"}</span>{busy && <span role="status">Live checks running…</span>}</p>
          <p>Recent years are tested against the years before, then checked independently. Labels: VERIFIED, PROBABLE, NOT VERIFIED.</p>
        </div>
      </header>
      {(error || live.error) && <div className="evidence-error" role="alert"><strong>The scan stopped.</strong><p>{error || live.error}</p></div>}
      {live.summary && <p className="active-summary">{live.summary}</p>}
      {live.best?.plain_language && <p className="active-best"><b>Best-supported trend.</b> {live.best.plain_language}</p>}
      <div className="active-grid" aria-live="polite">
        {live.order.map((vid) => live.cards[vid] && <LiveCardView key={vid} card={live.cards[vid]} name={nameOf(vid)} />)}
      </div>
      {result?.trends.map((t) => <TrendDetail key={t.series_id} trend={t} />)}
      {!!result?.failed && Object.keys(result.failed).length > 0 && (
        <ul className="active-failed">{Object.entries(result.failed).map(([k, v]) => <li key={k}><b>{k}</b>: {v}</li>)}</ul>
      )}
      <SkippedList items={skipped} />
      {result?.limits && <div className="active-limits"><Narrative value={result.limits} /></div>}
      {body.body.geometry && (
        <CriteriaPicker disabled={busy} onRun={(criteria) => {
          const { variable_ids: _ignored, ...rest } = body.body;
          setBody({ key: body.key + 1, body: { ...rest, criteria } });
        }} />
      )}
      <MethodsBehind />
    </section>
  );
}
