import { useEffect, useRef, useState } from "react";
import { ArrowLeft, ArrowUp, ArrowUpRight, Check, Copy, RotateCcw, Square, Plus } from "lucide-react";
import { api } from "./api";
import Narrative from "./Narrative";
import { conversationQuestion } from "./chatContext";
import "./chat.css";

export type ChatLaunch = { id: number; question: string };
type Props = {
  active: boolean;
  launch: ChatLaunch | null;
  onExit: () => void;
  onInvestigate?: (question: string) => void;
};
type Message = {
  id: number;
  role: "user" | "assistant";
  text: string;
  source?: string;
  note?: string;
  state?: "waiting" | "done" | "error" | "stopped";
  question?: string;
  requestText?: string;
};

function sourceLabel(source?: string) {
  if (source === "local_llm") return "Local AI · number-checked";
  if (source === "guardrail") return "Earth-topic guidance";
  if (source === "deterministic") return "Science engine · deterministic";
  return "Earth assistant";
}

export default function ChatPage({ active, launch, onExit, onInvestigate }: Props) {
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
  const submitRef = useRef<(question: string, retry?: Message) => void>(() => {});

  function update(next: Message[]) {
    messagesRef.current = next;
    setMessages(next);
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
  async function submit(question: string, retry?: Message) {
    const q = question.trim();
    if (!q || q.length > 2000 || controller.current) return;
    const previous = messagesRef.current
      .filter(message => message.role === "user" || message.state === "done")
      .map(message => `${message.role === "user" ? "User" : "Assistant"}: ${message.text.slice(0, 450)}`);
    const requestText = retry?.requestText || conversationQuestion(q, previous);
    const replyId = retry?.id ?? ++sequence.current;
    const userMessage: Message = { id: ++sequence.current, role: "user", text: q };
    const pending: Message = { id: replyId, role: "assistant", text: "", state: "waiting", question: q, requestText };
    update(retry
      ? messagesRef.current.map(message => message.id === retry.id ? pending : message)
      : [...messagesRef.current, userMessage, pending]);
    setDraft("");
    setBusy(true);
    setCopyError("");
    const request = new AbortController();
    controller.current = request;
    activeId.current = replyId;
    try {
      const response = await api.ask(requestText, request.signal);
      if (request.signal.aborted || activeId.current !== replyId) return;
      const text = response.answer || response.explanation;
      if (!text) throw new Error("The assistant returned an empty answer. Try again.");
      update(messagesRef.current.map(message => message.id === replyId
        ? { ...message, text, source: response.source, note: response.note, state: "done" }
        : message));
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
  submitRef.current = (question, retry) => { void submit(question, retry); };

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
    end.current?.scrollIntoView({ block: "end", behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "instant" : "smooth" });
  }, [active, messages, busy]);

  async function copy(message: Message) {
    try {
      await navigator.clipboard.writeText(message.text);
      setCopied(message.id);
      setCopyError("");
    } catch { setCopyError("Copy is unavailable here. Select the answer text to copy it."); }
  }

  return <section className="chat-page" hidden={!active} aria-label="Earth science conversation" data-active={active}>
    <header className="chat-header">
      <button className="chat-exit" type="button" onClick={onExit}><ArrowLeft size={17} strokeWidth={1.6} /> Back to Earth</button>
      <a className="chat-brand" href="/" onClick={event => { event.preventDefault(); onExit(); }} aria-label="Living Atlas home"><img src="/nasa-logo.svg" alt="NASA" width="30" height="27" /><span>Earth conversations</span></a>
      <button className="chat-new" type="button" aria-label="Start a new conversation" disabled={busy || !messages.length} onClick={() => { update([]); setDraft(""); setCopied(null); composer.current?.focus(); }}><Plus size={17} strokeWidth={1.6} /><span>New chat</span></button>
    </header>
    <div className="chat-scroll">
      <div className="chat-transcript" role="log" aria-label="Conversation" aria-live="polite" aria-relevant="additions text" aria-busy={busy}>
        {!messages.length && <div className="chat-empty"><h1>Stay curious<br /><em>about Earth.</em></h1><p>Ask about a place, a changing climate variable, or the methods behind the evidence.</p></div>}
        {messages.map(message => <article className={`chat-turn chat-turn-${message.role}`} key={message.id} aria-label={message.role === "user" ? "Your question" : "Assistant answer"}>
          {message.role === "user" ? <div className="chat-user-message"><span className="sr-only">You</span><p>{message.text}</p></div> : <>
            <div className="chat-answer-byline"><span className="chat-answer-mark" aria-hidden="true" /><span>{message.state === "waiting" ? "Reading your question" : sourceLabel(message.source)}</span></div>
            {message.state === "waiting" ? <div className="chat-waiting" role="status"><span className="chat-think-line" aria-hidden="true" /><p>Working with the science engine…</p></div> : <div className="chat-answer-text"><Narrative value={message.text} />{message.note && <p className="chat-answer-note">{message.note}</p>}</div>}
            {(message.state === "error" || message.state === "stopped") && <button type="button" className="chat-text-action" disabled={busy} onClick={() => submitRef.current(message.question || "", message)}><RotateCcw size={14} /> Try again</button>}
            {message.state === "done" && <div className="chat-answer-actions"><button type="button" className="chat-copy" onClick={() => void copy(message)} aria-label={copied === message.id ? "Answer copied" : "Copy answer"}>{copied === message.id ? <Check size={15} /> : <Copy size={15} />}</button>{onInvestigate && <button className="chat-text-action" type="button" onClick={() => onInvestigate(message.question || "")}>Investigate this question <ArrowUpRight size={14} /></button>}</div>}
          </>}
        </article>)}
        <div ref={end} className="chat-end" />
      </div>
    </div>
    <div className="chat-compose-area">
      {copyError && <p className="chat-copy-error" role="status">{copyError}</p>}
      <form className="chat-composer" style={{ viewTransitionName: active ? "earth-composer" : undefined }} onSubmit={event => { event.preventDefault(); submitRef.current(draft); }}>
        <label className="sr-only" htmlFor="chat-question">Continue your Earth science conversation</label>
        <textarea ref={composer} id="chat-question" rows={1} value={draft} maxLength={2000} placeholder="Ask a follow-up…" onChange={event => setDraft(event.target.value)} onKeyDown={event => { if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); submitRef.current(draft); } }} />
        {busy ? <button type="button" className="chat-send" aria-label="Stop answer" onClick={stop}><Square size={15} fill="currentColor" /></button> : <button type="submit" className="chat-send" aria-label="Send question" disabled={!draft.trim()}><ArrowUp size={21} strokeWidth={1.7} /></button>}
      </form>
      <p className="chat-compose-note">Recent turns provide context. Answers use the connected model or a labeled science-engine fallback.</p>
    </div>
  </section>;
}
