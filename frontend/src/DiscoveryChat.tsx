import { lazy, Suspense, useEffect, useRef, useState, type ReactNode } from "react";
import { ArrowLeft, ArrowUp, CalendarClock, Download, FlaskConical, Plus, RotateCcw, Square } from "lucide-react";
import {
  applyDiscoveryEvent, emptyProgress, listTexts, notebookURL, runDiscovery, runWhatIf, twinPromptRoute,
  type DiscoveryBrief, type DiscoveryProgress, type DiscoveryResult, type TestedCard, type WhatIfPlace, type WhatIfResult,
} from "./discoveryApi";
import "./chat.css";
import "./discovery.css";

const FindingSeries = lazy(() => import("./DiscoveryPlots").then(m => ({ default: m.FindingSeries })));
const TestedSeries = lazy(() => import("./DiscoveryPlots").then(m => ({ default: m.TestedSeries })));
const OutlookPlot = lazy(() => import("./DiscoveryPlots").then(m => ({ default: m.OutlookPlot })));
const WhatIfPlot = lazy(() => import("./DiscoveryPlots").then(m => ({ default: m.WhatIfPlot })));

export type DiscoveryLaunch = { id: number; question: string };
type Props = { active: boolean; launch: DiscoveryLaunch | null; onExit: () => void };
type Turn = {
  id: number;
  role: "user" | "assistant";
  text: string;
  state?: "waiting" | "done" | "error" | "stopped";
  progress?: DiscoveryProgress;
  result?: DiscoveryResult;
  jobId?: string;
  whatif?: WhatIfResult;
  kind?: "discovery" | "whatif";
  status?: string;
};

const fmt = (x: number, d = 2) => `${x > 0 ? "+" : ""}${x.toFixed(d)}`;

/** One place of a what-if: the sentence, three key numbers and its own chart. All values from the API. */
function WhatIfCard({ p }: { p: WhatIfPlace }) {
  const u = p.units;
  return <article className="discovery-card whatif-card" aria-label={`What-if for ${p.place}`}>
    <header>
      <div className="discovery-badges"><span className="discovery-badge discovery-badge-sim">Simulated</span></div>
      <h2>{p.place}</h2>
      <p className="discovery-meta">{p.variable}</p>
    </header>
    <dl className="whatif-numbers">
      <div><dt>Trend observed</dt><dd>{fmt(p.trend_per_decade.observed)} <small>{u}/decade</small></dd><span>±{p.trend_per_decade.observed_ci95.toFixed(2)} (95%)</span></div>
      <div className="is-change"><dt>Trend with the change</dt><dd>{fmt(p.trend_per_decade.with_change)} <small>{u}/decade</small></dd><span>simulated</span></div>
      <div><dt>In {p.end.year}</dt><dd>{p.end.with_change.toFixed(1)} <small>{u}</small></dd><span>vs {p.end.without_change.toFixed(1)} without ({fmt(p.end.difference, 1)})</span></div>
    </dl>
    <Suspense fallback={<p className="discovery-plot-loading">Drawing the chart…</p>}><WhatIfPlot place={p} /></Suspense>
    <p className="discovery-summary">{p.plain_language}</p>
    <p className="discovery-limit">Data: {p.provenance.dataset ?? "n/a"} {p.provenance.version ?? ""} via {p.provenance.source_api ?? "n/a"}{p.provenance.doi ? `, DOI ${p.provenance.doi}` : ""}. Real observations up to {p.observed.years[p.observed.years.length - 1]}; everything after is simulated.</p>
  </article>;
}

function Badge({ label }: { label: string }) {
  const icon = label === "VERIFIED" ? "✓" : label === "PROBABLE" ? "◐" : "○";
  return <span className={`discovery-badge discovery-badge-${label.toLowerCase().replace(/\s+/g, "-")}`}><span aria-hidden="true">{icon}</span> {label}</span>;
}

/** A disclosure whose body is only rendered while open, so collapsed lists never show up as empty bullets
 * (in copied text, screen-reader browse mode or text extraction). */
function Fold({ className, summary, children }: { className: string; summary: ReactNode; children: ReactNode }) {
  const [open, setOpen] = useState(false);
  return <details className={className} open={open} onToggle={e => setOpen(e.currentTarget.open)}>
    <summary>{summary}</summary>{open && children}
  </details>;
}

function linkOf(item: { doi_url?: string | null; url?: string | null; doi?: string | null }) {
  return item.doi_url || (item.doi ? `https://doi.org/${item.doi}` : item.url) || undefined;
}

function FindingCard({ brief, jobId, finished }: { brief: DiscoveryBrief; jobId?: string; finished: boolean }) {
  const prov = brief.provenance;
  return <article className="discovery-card" aria-label={brief.title}>
    <header>
      <div className="discovery-badges">
        <Badge label={brief.verdict.label} />
        {brief.potential_discovery === true && <span className="discovery-badge discovery-badge-gap">
          <span aria-hidden="true">✦</span> Potential new finding — no published study found
        </span>}
      </div>
      <h2>{brief.title}</h2>
      <p className="discovery-summary">{brief.summary.text}</p>
      <p className="discovery-meta">{brief.summary.label}</p>
    </header>

    <dl className="discovery-facts">
      <div><dt>What changed</dt><dd>{brief.what}</dd></div>
      <div><dt>Where</dt><dd>{brief.where.name}{brief.where.approximate && <em> · approximate box</em>}</dd></div>
      <div><dt>Since when</dt><dd>{brief.since
        ? <>Around {brief.since.date}{brief.since.interval90 ? ` (likely between ${brief.since.interval90[0]} and ${brief.since.interval90[1]})` : ""} · {brief.since.source}</>
        : "BEAST did not date a regime change."}</dd></div>
      <div><dt>Rate</dt><dd>{brief.rate.plain_language}</dd></div>
    </dl>

    <section className="discovery-verdict" aria-label="Verdict">
      <p><b>{brief.verdict.label}</b> · {brief.verdict.why}</p>
      <p className="discovery-limit">{brief.verdict.limit}</p>
      <p className="discovery-gap">{brief.gap.plain_language}</p>
      {brief.potential_discovery === true && <p className="discovery-limit">{brief.gap.rule}</p>}
    </section>

    <Suspense fallback={<div className="discovery-plot-loading">Loading chart…</div>}>
      <FindingSeries brief={brief} />
    </Suspense>
    {brief.figure.change_date && <p className="discovery-caption">Dashed line: BEAST change date {brief.figure.change_date}. Shaded: the recent window that was tested.</p>}
    {prov && <Fold className="discovery-details" summary={<>Data source</>}>
      <p>{prov.dataset_short_name}{prov.version ? ` v${prov.version}` : ""}{prov.doi ? <> · DOI <a href={`https://doi.org/${prov.doi}`} target="_blank" rel="noopener noreferrer">{prov.doi}</a></> : null} · via {prov.source_api} · retrieved {prov.retrieved_at}</p>
    </Fold>}

    <section aria-label="Likely drivers">
      <h3>Associated drivers (PCMCI+)</h3>
      <p>{brief.drivers.plain_language}</p>
      {brief.drivers.links.length > 0 && <ul>{brief.drivers.links.map(l => <li key={l.driver_id}>{l.plain_language}</li>)}</ul>}
      {brief.drivers.disclaimer && <p className="discovery-limit">{brief.drivers.disclaimer}</p>}
    </section>

    <section aria-label="Closest published work">
      <h3>Closest related work</h3>
      {brief.literature.plain_language && <p>{brief.literature.plain_language}</p>}
      {brief.literature.related_works.length ? <ul className="discovery-works">{brief.literature.related_works.map((w, i) =>
        <li key={i}><a href={linkOf(w)} target="_blank" rel="noopener noreferrer">{w.title}</a> <span>({w.year}{w.venue ? `, ${w.venue}` : ""}) · {w.peer_reviewed ? "peer reviewed" : "not peer reviewed"}{w.doi ? ` · doi:${w.doi}` : ""}</span></li>)}</ul>
        : <p className="discovery-limit">No related studies were returned by the searched sources.</p>}
    </section>

    <section className="discovery-unreviewed" aria-label="Not peer reviewed">
      <h3>Preprints and news <span className="discovery-tag">not peer reviewed</span></h3>
      {brief.preprints.items.length > 0 && <ul>{brief.preprints.items.map((p, i) =>
        <li key={`p${i}`}><a href={linkOf(p)} target="_blank" rel="noopener noreferrer">{p.title}</a> <span>({p.year ?? ""}) · {p.label}</span></li>)}</ul>}
      {brief.news.items.length > 0 && <ul>{brief.news.items.map((n, i) =>
        <li key={`n${i}`}><a href={n.url ?? undefined} target="_blank" rel="noopener noreferrer">{n.title}</a> <span>{n.domain} · {n.date} · {n.label}</span></li>)}</ul>}
      {!brief.preprints.items.length && !brief.news.items.length && <p className="discovery-limit">No preprints or news reports were found{brief.preprints.status !== "ok" || brief.news.status !== "ok" ? " (a source was unavailable)" : ""}.</p>}
    </section>

    <section className="discovery-outlook" aria-label="Simulated outlook">
      <h3>Hypothetical outlook <span className="discovery-tag">{brief.outlook.label}</span></h3>
      {brief.outlook.plain_language && <p>{brief.outlook.plain_language}</p>}
      <Suspense fallback={<div className="discovery-plot-loading">Loading simulation…</div>}>
        <OutlookPlot brief={brief} />
      </Suspense>
      <p className="discovery-limit">{brief.outlook.disclaimer}</p>
      <p><b>{brief.outlook.unreviewed_context.label}.</b> {brief.outlook.unreviewed_context.plain_language}</p>
    </section>

    <footer className="discovery-card-footer">
      {finished && jobId
        ? <a className="discovery-notebook" href={notebookURL(jobId, brief.finding_id)} download><Download size={15} /> Download reproducible notebook</a>
        : <span className="discovery-limit">The notebook link appears when the run finishes.</span>}
      <Fold className="discovery-details" summary={<>Checks and limits</>}>
        <ul>{brief.checks.map(c => <li key={c.check}><b>{c.check}</b> ({c.status}): {c.plain_language}</li>)}</ul>
        {brief.beast.plain_language && <p>{brief.beast.plain_language}</p>}
        <ul>{brief.limits.map((l, i) => <li key={i}>{l}</li>)}</ul>
      </Fold>
    </footer>
  </article>;
}

/** A place that was tested but not kept: the real record and the engine's numbers, so the student still learns. */
function TestedCardView({ card }: { card: TestedCard }) {
  const prov = card.provenance;
  return <article className="discovery-card discovery-tested" aria-label={`${card.variable.name} in ${card.place}: ${card.label}`}>
    <header>
      <div className="discovery-badges"><Badge label={card.label} />{card.state && <span className="discovery-tag">{card.state.replace(/_/g, " ")}</span>}</div>
      <h2>{card.variable.name} in {card.place.split(" (")[0]}</h2>
      {card.reason && <p className="discovery-summary">{card.reason}</p>}
    </header>
    <dl className="discovery-facts">
      <div><dt>Recent rate</dt><dd>{card.rate?.plain_language ?? "Not enough months to estimate a rate."}</dd></div>
      <div><dt>Whole record</dt><dd>{card.full_record?.plain_language ?? "Not available"}</dd></div>
      <div><dt>Period of data</dt><dd>{card.period ? `${card.period[0]} to ${card.period[1]}` : "Not available"}</dd></div>
      <div><dt>Where</dt><dd>{card.place} <em>· approximate box</em></dd></div>
    </dl>
    {card.figure?.time?.length ? <Suspense fallback={<div className="discovery-plot-loading">Loading chart…</div>}><TestedSeries card={card} /></Suspense> : null}
    <p className="discovery-tested-note">{card.note}</p>
    <Fold className="discovery-details" summary={<>Why it was not kept, and the data source</>}>
      {card.why && <p>{card.why}</p>}
      {card.checks?.length ? <ul>{card.checks.map(c => <li key={c.check}><b>{c.check}</b> ({c.status}): {c.plain_language}</li>)}</ul> : null}
      <p className="discovery-limit">{card.limit}</p>
      {prov && <p className="discovery-limit">{prov.dataset_short_name}{prov.version ? ` v${prov.version}` : ""}{prov.doi ? <> · DOI <a href={`https://doi.org/${prov.doi}`} target="_blank" rel="noopener noreferrer">{prov.doi}</a></> : null} · via {prov.source_api} · retrieved {prov.retrieved_at}</p>}
    </Fold>
  </article>;
}

function StepLog({ progress, running }: { progress: DiscoveryProgress; running: boolean }) {
  const steps = <ol className="discovery-progress" aria-label="Progress">
    {(running ? progress.lines.slice(-6) : progress.lines).map(l => <li key={l.seq} data-kind={l.kind}>{l.text}</li>)}
    {running && <li className="discovery-working" aria-hidden="true"><span className="chat-think-line" /></li>}
  </ol>;
  if (running) return steps;
  return <Fold className="discovery-details discovery-steps" summary={<>How this run went ({progress.lines.length} steps)</>}>{steps}</Fold>;
}

export default function DiscoveryChat({ active, launch, onExit }: Props) {
  const [turns, setTurns] = useState<Turn[]>([]);
  const turnsRef = useRef<Turn[]>([]);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const controller = useRef<AbortController | null>(null);
  const sequence = useRef(0);
  const launched = useRef<number | null>(null);
  const composer = useRef<HTMLTextAreaElement>(null);
  const end = useRef<HTMLDivElement>(null);
  const submitRef = useRef<(q: string) => void>(() => {});

  function update(next: Turn[]) { turnsRef.current = next; setTurns(next); }
  function patch(id: number, fields: Partial<Turn> | ((t: Turn) => Partial<Turn>)) {
    update(turnsRef.current.map(t => t.id === id ? { ...t, ...(typeof fields === "function" ? fields(t) : fields) } : t));
  }
  function stop() {
    controller.current?.abort();
    controller.current = null;
    setBusy(false);
    update(turnsRef.current.map(t => t.state === "waiting"
      ? { ...t, state: "stopped", text: "Stopped watching. The server may still finish this run; ask again to see it." } : t));
  }
  async function submit(question: string) {
    const q = question.trim();
    if (!q || q.length > 500 || controller.current) return;
    const replyId = ++sequence.current + 1;
    sequence.current = replyId;
    update([...turnsRef.current, { id: replyId - 1, role: "user", text: q },
      { id: replyId, role: "assistant", text: "", state: "waiting", progress: emptyProgress() }]);
    setDraft("");
    setBusy(true);
    const request = new AbortController();
    controller.current = request;
    if (twinPromptRoute(q) === "scenario") {
      patch(replyId, { kind: "whatif", status: "Reading the question" });
      try {
        const whatif = await runWhatIf(q, { signal: request.signal, onProgress: m => patch(replyId, { status: m }) });
        if (request.signal.aborted) return;
        patch(replyId, { state: "done", whatif });
      } catch (error) {
        if (request.signal.aborted) return;
        patch(replyId, { state: "error", text: error instanceof Error ? error.message : "The what-if could not finish." });
      } finally {
        if (controller.current === request) { controller.current = null; setBusy(false); }
      }
      return;
    }
    try {
      const { jobId, result } = await runDiscovery({ prompt: q, max_findings: 3 }, {
        signal: request.signal,
        onStart: s => patch(replyId, { jobId: s.job_id }),
        onEvent: ev => patch(replyId, t => ({ progress: applyDiscoveryEvent(t.progress ?? emptyProgress(), ev) })),
      });
      if (request.signal.aborted) return;
      patch(replyId, { state: "done", result, jobId, text: result.plain_language });
    } catch (error) {
      if (request.signal.aborted) return;
      patch(replyId, { state: "error", text: error instanceof Error ? error.message : "The discovery run could not finish." });
    } finally {
      if (controller.current === request) { controller.current = null; setBusy(false); }
    }
  }
  submitRef.current = q => { void submit(q); };

  useEffect(() => {
    if (!active) return;
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const timer = setTimeout(() => composer.current?.focus({ preventScroll: true }), 620);
    return () => { clearTimeout(timer); document.body.style.overflow = previous; stop(); };
  }, [active]);
  useEffect(() => {
    if (!active || !launch || launch.id === launched.current) return;
    const timer = setTimeout(() => {
      if (launch.id === launched.current) return;
      launched.current = launch.id;
      submitRef.current(launch.question);
    }, 0);
    return () => clearTimeout(timer);
  }, [active, launch?.id]);
  useEffect(() => {
    if (!active) return;
    end.current?.scrollIntoView({ block: "end", behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "instant" : "smooth" });
  }, [active, turns.length]);

  return <section className="chat-page discovery-page" hidden={!active} aria-label="Discovery mode" data-active={active}>
    <header className="chat-header">
      <button className="chat-exit" type="button" onClick={onExit}><ArrowLeft size={17} strokeWidth={1.6} /> Back to DigiTwin</button>
      <span className="chat-brand"><FlaskConical size={20} strokeWidth={1.5} /><span>Discovery mode</span></span>
      <button className="chat-new" type="button" aria-label="Start a new discovery conversation" disabled={busy || !turns.length}
        onClick={() => { update([]); setDraft(""); composer.current?.focus(); }}><Plus size={17} strokeWidth={1.6} /><span>New run</span></button>
    </header>
    <div className="chat-scroll">
      <div className="chat-transcript" role="log" aria-label="Discovery conversation" aria-live="polite" aria-busy={busy}>
        {!turns.length && <div className="chat-empty"><h1>Look for what<br /><em>nobody wrote yet.</em></h1>
          <p>Name a place and a variable, or ask a what-if. The tool scans the data, keeps only trends that pass every check, then searches published studies. Anything without a matching study is shown as a potential new finding, not yet checked by scientists.</p></div>}
        {turns.map(t => t.role === "user"
          ? <article className="chat-turn chat-turn-user" key={t.id} aria-label="Your question"><div className="chat-user-message"><span className="sr-only">You</span><p>{t.text}</p></div></article>
          : <article className="chat-turn chat-turn-report discovery-turn" key={t.id} aria-label="Discovery run">
            <div className="chat-answer-byline"><span className="chat-answer-mark" aria-hidden="true" />
              <span>{t.kind === "whatif" ? (t.state === "waiting" ? "Simulating each place" : "What-if · simulated from real records")
                : t.state === "waiting" ? "Scanning, checking, searching" : t.state === "done" ? "Discovery run · numbers from the science engine" : "Discovery run"}</span></div>
            {t.kind === "whatif" && t.state === "waiting" && <div className="chat-waiting" role="status"><span className="chat-think-line" aria-hidden="true" /><p>{t.status || "Working…"} (live NASA data can take a few minutes the first time)</p></div>}
            {t.whatif && <div className="whatif-run">
              <p className="discovery-run-answer">Change applied: <b>{t.whatif.change.text}</b>{t.whatif.change.target_year ? "" : ` by ${t.whatif.target_year}`}, to {t.whatif.places.map(p => p.place).join(" and ")}.</p>
              {t.whatif.scope_note && <p className="discovery-notice" role="note"><CalendarClock size={16} aria-hidden="true" /><span>{t.whatif.scope_note}</span></p>}
              <div className="whatif-grid">{t.whatif.places.map(p => <WhatIfCard key={p.place} p={p} />)}</div>
              {t.whatif.skipped.length > 0 && <ul className="discovery-limit">{t.whatif.skipped.map(s => <li key={s.place}>{s.place}: {s.reason}</li>)}</ul>}
              <p className="discovery-limit">{t.whatif.method} {t.whatif.disclaimer}</p>
            </div>}
            {(() => {
              const notice = t.progress?.notice ?? t.result?.plan.period_notice;
              return notice ? <p className="discovery-notice" role="note"><CalendarClock size={16} aria-hidden="true" /><span>{notice.plain_language}</span></p> : null;
            })()}
            {t.progress && t.progress.lines.length > 0 && <StepLog progress={t.progress} running={t.state === "waiting"} />}
            {t.kind !== "whatif" && t.state === "waiting" && !t.progress?.lines.length && <div className="chat-waiting" role="status"><span className="chat-think-line" aria-hidden="true" /><p>Planning the scan…</p></div>}
            {(t.result?.findings ?? t.progress?.findings ?? []).map(b =>
              <FindingCard key={b.finding_id} brief={b} jobId={t.jobId} finished={t.state === "done"} />)}
            {(t.result?.tested ?? t.progress?.tested ?? []).map(c => <TestedCardView key={c.candidate_id} card={c} />)}
            {t.state === "done" && t.result && (() => {
              const r = t.result;
              const failed = listTexts(r.failed_sources);
              const places = listTexts(r.candidates);
              const skipped = r.plan.skipped.map(s => `${s.criterion}: ${s.reason}`);
              const limits = r.limits.filter(l => l && l.trim());
              return <div className="discovery-run-summary">
                <p className="discovery-run-answer">{r.plain_language}</p>
                {r.next_steps && <p className="discovery-next">{r.next_steps}</p>}
                {skipped.length > 0 && <ul className="discovery-limit">{skipped.map(x => <li key={x}>{x}</li>)}</ul>}
                <div className="discovery-run-more">
                  {places.length > 0 && <Fold className="discovery-details" summary={<>All candidate places ({places.length})</>}>
                    <ul>{places.map((x, i) => <li key={i}>{x}</li>)}</ul></Fold>}
                  {failed.length > 0 && <Fold className="discovery-details" summary={<>Sources that did not answer ({failed.length})</>}>
                    <ul>{failed.map((x, i) => <li key={i}>{x}</li>)}</ul></Fold>}
                  {limits.length > 0 && <Fold className="discovery-details" summary={<>How to read this</>}>
                    <ul>{limits.map((l, i) => <li key={i}>{l}</li>)}</ul></Fold>}
                </div>
                <p className="discovery-limit">Run time {r.timing.elapsed_s} s (budget {r.timing.budget_s} s).</p>
              </div>;
            })()}
            {(t.state === "error" || t.state === "stopped") && <div className="chat-answer-text"><p>{t.text}</p>
              <button type="button" className="chat-text-action" disabled={busy} onClick={() => {
                const i = turnsRef.current.findIndex(x => x.id === t.id);
                const q = turnsRef.current[i - 1]?.text;
                if (q) submitRef.current(q);
              }}><RotateCcw size={14} /> Try again</button></div>}
          </article>)}
        <div ref={end} className="chat-end" />
      </div>
    </div>
    <div className="chat-compose-area">
      <form className="chat-composer" style={{ viewTransitionName: active ? "earth-composer" : undefined }} onSubmit={e => { e.preventDefault(); submitRef.current(draft); }}>
        <label className="sr-only" htmlFor="discovery-question">Ask Discovery mode</label>
        <textarea ref={composer} id="discovery-question" rows={1} value={draft} maxLength={500}
          placeholder={turns.length ? "Start another discovery run…" : "Find unreported changes in the South Asia monsoon…"}
          onChange={e => setDraft(e.target.value)}
          onKeyDown={e => { if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); submitRef.current(draft); } }} />
        {busy ? <button type="button" className="chat-send" aria-label="Stop watching this run" onClick={stop}><Square size={15} fill="currentColor" /></button>
          : <button type="submit" className="chat-send" aria-label="Start discovery run" disabled={!draft.trim()}><ArrowUp size={21} strokeWidth={1.7} /></button>}
      </form>
      <p className="chat-compose-note">Each message starts a new run (a few minutes). Findings are checked by statistics, not by scientists. Outlooks are simulated, not predictions.</p>
    </div>
  </section>;
}
