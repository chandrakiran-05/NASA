import { useEffect, useRef, useState } from "react";
import { ArrowLeft, ArrowUp, Check, Copy, FileText, MessageSquare, RotateCcw, Square, Plus } from "lucide-react";
import { api, newConversationId, type ConversationContext } from "./api";
import ReportView from "./ReportView";
import { keyNumber, normalizeReport, type Report } from "./report";
import Narrative from "./Narrative";
import "./chat.css";

export type ChatLaunch = { id: number; question: string };
type Props = {
  active: boolean;
  launch: ChatLaunch | null;
  onExit: () => void;
  onReport?: (report: Report) => void;
};
type Message = {
  id: number;
  role: "user" | "assistant";
  text: string;
  source?: string;
  note?: string;
  state?: "choose" | "waiting" | "done" | "error" | "stopped";
  /** short = a chat-sized answer from the same computed report; report = the full evidence report */
  mode?: "short" | "report";
  question?: string;
  requestText?: string;
  context?: ConversationContext;
  report?: Report;
  progress?: { progress: number; message: string };
};

const KEPT: Record<string, string> = { variable: "variable", region: "place", period: "years" };
function contextLine(context?: ConversationContext) {
  if (!context?.summary) return "";
  const kept = (context.inherited || []).map(key => KEPT[key] || key);
  return `Using: ${context.summary}` + (kept.length ? ` (kept from earlier: ${kept.join(", ")})` : "");
}

function sourceLabel(source?: string) {
  if (source === "local_llm") return "Local AI · number-checked";
  if (source === "guardrail") return "Earth-topic guidance";
  if (source === "deterministic") return "Science engine · deterministic";
  return "Earth assistant";
}

export default function ChatPage({ active, launch, onExit, onReport }: Props) {
  const [messages, setMessages] = useState<Message[]>([]);
  const messagesRef = useRef<Message[]>([]);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [copied, setCopied] = useState<number | null>(null);
  const [copyError, setCopyError] = useState("");
  const controller = useRef<AbortController | null>(null);
  const sequence = useRef(0);
  const activeId = useRef<number | null>(null);
  const launched = useRef<number | null>(null);
  const composer = useRef<HTMLTextAreaElement>(null);
  const end = useRef<HTMLDivElement>(null);
  const submitRef = useRef<(question: string, retry?: Message, chosen?: "short" | "report") => void>(() => {});
  /** Server-side follow-up memory: the backend remembers variable, place and years per conversation. */
  const conversationId = useRef<string>(newConversationId());
  /** Only one report is expanded at a time (section anchors are page-wide ids); null = the newest. */
  const [openId, setOpenId] = useState<number | null>(null);

  function update(next: Message[]) {
    messagesRef.current = next;
    setMessages(next);
  }
  function patch(id: number, fields: Partial<Message>) {
    update(messagesRef.current.map(message => message.id === id ? { ...message, ...fields } : message));
  }
  function stop() {
    controller.current?.abort();
    controller.current = null;
    const id = activeId.current;
    activeId.current = null;
    setBusy(false);
    if (id !== null) update(messagesRef.current.map(message => message.id === id
      ? { ...message, state: "stopped", text: "Answer stopped. You can try this question again." }
      : message));
  }
  async function submit(question: string, retry?: Message, chosen?: "short" | "report") {
    const q = question.trim();
    if (!q || q.length > 2000 || controller.current) return;
    const mode = chosen ?? retry?.mode;
    if (!mode) {
      // Ask first: a quick chat answer or the full evidence report (both come from the same computed numbers).
      update([...messagesRef.current, { id: ++sequence.current, role: "user", text: q },
        { id: ++sequence.current, role: "assistant", text: "", state: "choose", question: q, requestText: q }]);
      setDraft("");
      return;
    }
    const requestText = retry?.requestText || q;
    const replyId = retry?.id ?? ++sequence.current;
    const userMessage: Message = { id: ++sequence.current, role: "user", text: q };
    const pending: Message = { id: replyId, role: "assistant", text: "", state: "waiting", question: q, requestText, mode };
    update(retry
      ? messagesRef.current.map(message => message.id === retry.id ? pending : message)
      : [...messagesRef.current, userMessage, pending]);
    setDraft("");
    setOpenId(null);
    setBusy(true);
    setCopyError("");
    const request = new AbortController();
    controller.current = request;
    activeId.current = replyId;
    try {
      const live = () => !request.signal.aborted && activeId.current === replyId;
      // Data questions get the full evidence report: numbers first, AI wording replaces sections as it arrives.
      const raw = await api.report({ question: requestText, conversation_id: conversationId.current }, {
        signal: request.signal,
        onProgress: job => { if (live()) patch(replyId, { progress: { progress: job.progress || 0, message: job.message || "" } }); },
        onPartial: partial => {
          if (!live()) return;
          const shown = normalizeReport(partial);
          if (!shown.sections.length) return;
          if (mode !== "short") { patch(replyId, { report: shown }); return; }
          // A short answer needs only the computed numbers: free the chat instead of waiting for AI wording.
          patch(replyId, { report: shown, text: shown.headline || "", state: "done" });
          onReport?.(shown);
          controller.current = null;
          activeId.current = null;
          setBusy(false);
          request.abort();
        },
      });
      if (!live()) return;
      const report = normalizeReport(raw);
      if (report.sections.length || report.headline) {
        const context = (raw as { conversation?: ConversationContext } | null)?.conversation;
        patch(replyId, { report, text: report.headline || "", context, state: "done" });
        onReport?.(report);
        return;
      }
      // Method or general questions ("what is BEAST?") have no data to report: answer in words.
      const response = await api.ask(requestText, request.signal, conversationId.current);
      if (!live()) return;
      const text = response.answer || response.explanation;
      if (!text) throw new Error("The assistant returned an empty answer. Try again.");
      patch(replyId, { report: undefined, text, source: response.source, note: response.note, context: response.context, state: "done" });
    } catch (error) {
      if (request.signal.aborted || activeId.current !== replyId) return;
      update(messagesRef.current.map(message => message.id === replyId
        ? { ...message, state: "error", text: error instanceof Error ? error.message : "The answer could not finish. Try again." }
        : message));
    } finally {
      if (controller.current === request) {
        controller.current = null;
        activeId.current = null;
        setBusy(false);
      }
    }
  }
  submitRef.current = (question, retry, chosen) => { void submit(question, retry, chosen); };

  useEffect(() => {
    if (!active) return;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const timer = setTimeout(() => composer.current?.focus({ preventScroll: true }), 620);
    return () => {
      clearTimeout(timer);
      document.body.style.overflow = previousOverflow;
      stop();
    };
  }, [active]);

  useEffect(() => {
    if (!active || !launch || launch.id === launched.current) return;
    // Deferring one task lets StrictMode undo its trial setup before any request starts.
    const timer = setTimeout(() => {
      if (launch.id === launched.current) return;
      launched.current = launch.id;
      submitRef.current(launch.question);
    }, 0);
    return () => clearTimeout(timer);
  }, [active, launch?.id]);

  useEffect(() => {
    if (!active) return;
    // Scroll once per new turn (not on every partial update), so a report is read from its top.
    end.current?.scrollIntoView({ block: "end", behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "instant" : "smooth" });
  }, [active, messages.length]);

  async function copy(message: Message) {
    try {
      await navigator.clipboard.writeText(message.text);
      setCopied(message.id);
      setCopyError("");
    } catch { setCopyError("Copy is unavailable here. Select the answer text to copy it."); }
  }

  const isReport = (m: Message) => m.role === "assistant" && m.mode === "report" && (!!m.report || m.state === "waiting");
  const latestReport = [...messages].reverse().find(isReport);
  const shownId = openId ?? latestReport?.id;

  return <section className="chat-page" hidden={!active} aria-label="Earth science conversation" data-active={active}>
    <header className="chat-header">
      <button className="chat-exit" type="button" onClick={onExit}><ArrowLeft size={17} strokeWidth={1.6} /> Back to Earth</button>
      <a className="chat-brand" href="/" onClick={event => { event.preventDefault(); onExit(); }} aria-label="Living Atlas home"><img src="/nasa-logo.svg" alt="NASA" width="30" height="27" /><span>Earth conversations</span></a>
      <button className="chat-new" type="button" aria-label="Start a new conversation" disabled={busy || !messages.length} onClick={() => { update([]); conversationId.current = newConversationId(); setOpenId(null); setDraft(""); setCopied(null); composer.current?.focus(); }}><Plus size={17} strokeWidth={1.6} /><span>New conversation</span></button>
    </header>
    <div className="chat-scroll">
      <div className="chat-transcript" role="log" aria-label="Conversation" aria-live="polite" aria-relevant="additions text" aria-busy={busy}>
        {!messages.length && <div className="chat-empty"><h1>Stay curious<br /><em>about Earth.</em></h1><p>Ask about a place, a changing climate variable, or the methods behind the evidence.</p></div>}
        {messages.map(message => message.state === "choose" ? <article className="chat-turn chat-turn-assistant" key={message.id} aria-label="Choose the answer type">
          <div className="chat-answer-byline"><span className="chat-answer-mark" aria-hidden="true" /><span>How would you like the answer?</span></div>
          <div className="chat-choice">
            <button type="button" disabled={busy} onClick={() => submitRef.current(message.question || "", message, "short")}><MessageSquare size={16} /><b>Short answer</b><span>A few sentences with the main number</span></button>
            <button type="button" disabled={busy} onClick={() => submitRef.current(message.question || "", message, "report")}><FileText size={16} /><b>Full report</b><span>Charts, map, checks, research and limits</span></button>
          </div>
        </article> : message.role === "assistant" && message.mode === "short" && (message.report || message.state === "waiting") ? <article className="chat-turn chat-turn-assistant" key={message.id} aria-label="Short answer">
          <div className="chat-answer-byline"><span className="chat-answer-mark" aria-hidden="true" /><span>{message.report ? "Short answer · numbers from the science engine" : "Checking the data"}</span></div>
          {!message.report ? <div className="chat-waiting" role="status"><span className="chat-think-line" aria-hidden="true" /><p>{message.progress?.message || "Working with the science engine…"}</p></div> : <div className="chat-answer-text">
            {contextLine(message.context) && <p className="chat-context" role="note">{contextLine(message.context)}</p>}
            {(() => { const k = keyNumber(message.report.sections); return k ? <p className="chat-key"><b>{k.value}</b> {k.label}</p> : null; })()}
            <Narrative value={message.report.headline || message.report.sections.find(x => x.id === "answer")?.text || ""} />
            <button type="button" className="chat-text-action" disabled={busy} onClick={() => submitRef.current(message.question || "", message, "report")}><FileText size={14} /> Show the full report</button>
          </div>}
        </article> : isReport(message) ? <article className="chat-turn chat-turn-report" key={message.id} aria-label="Evidence report">
          <div className="chat-answer-byline"><span className="chat-answer-mark" aria-hidden="true" /><span>{message.state === "waiting" ? "Building the evidence report" : "Evidence report · numbers from the science engine"}</span></div>
          {contextLine(message.context) && <p className="chat-context" role="note">{contextLine(message.context)}</p>}
          {message.id === shownId
            ? <ReportView report={message.report ?? null} busy={message.state === "waiting"} progress={message.progress ?? { progress: 0, message: "" }} error="" onCancel={stop} />
            : <div className="chat-report-folded"><p>{message.report?.headline || "Earlier report"}</p><button type="button" className="chat-text-action" onClick={() => setOpenId(message.id)}>Open this report</button></div>}
        </article> : <article className={`chat-turn chat-turn-${message.role}`} key={message.id} aria-label={message.role === "user" ? "Your question" : "Assistant answer"}>
          {message.role === "user" ? <div className="chat-user-message"><span className="sr-only">You</span><p>{message.text}</p></div> : <>
            <div className="chat-answer-byline"><span className="chat-answer-mark" aria-hidden="true" /><span>{message.state === "waiting" ? "Reading your question" : sourceLabel(message.source)}</span></div>
            {message.state === "waiting" ? <div className="chat-waiting" role="status"><span className="chat-think-line" aria-hidden="true" /><p>Working with the science engine…</p></div> : <div className="chat-answer-text">{contextLine(message.context) && <p className="chat-context" role="note">{contextLine(message.context)}</p>}<Narrative value={message.text} />{message.note && <p className="chat-answer-note">{message.note}</p>}</div>}
            {(message.state === "error" || message.state === "stopped") && <button type="button" className="chat-text-action" disabled={busy} onClick={() => submitRef.current(message.question || "", message)}><RotateCcw size={14} /> Try again</button>}
            {message.state === "done" && <div className="chat-answer-actions"><button type="button" className="chat-copy" onClick={() => void copy(message)} aria-label={copied === message.id ? "Answer copied" : "Copy answer"}>{copied === message.id ? <Check size={15} /> : <Copy size={15} />}</button></div>}
          </>}
        </article>)}
        <div ref={end} className="chat-end" />
      </div>
    </div>
    <div className="chat-compose-area">
      {copyError && <p className="chat-copy-error" role="status">{copyError}</p>}
      <form className="chat-composer" style={{ viewTransitionName: active ? "earth-composer" : undefined }} onSubmit={event => { event.preventDefault(); submitRef.current(draft); }}>
        <label className="sr-only" htmlFor="chat-question">Continue your Earth science conversation</label>
        <textarea ref={composer} id="chat-question" rows={1} value={draft} maxLength={2000} placeholder={messages.length ? "Ask a follow-up…" : "Ask about temperature in India since 2002…"} onChange={event => setDraft(event.target.value)} onKeyDown={event => { if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); submitRef.current(draft); } }} />
        {busy ? <button type="button" className="chat-send" aria-label="Stop answer" onClick={stop}><Square size={15} fill="currentColor" /></button> : <button type="submit" className="chat-send" aria-label="Send question" disabled={!draft.trim()}><ArrowUp size={21} strokeWidth={1.7} /></button>}
      </form>
      <p className="chat-compose-note">Follow-ups remember the variable, place and years until you start a new conversation. Answers use the connected model or a labeled science-engine fallback.</p>
    </div>
  </section>;
}
