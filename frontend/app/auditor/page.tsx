"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { AnimatePresence, motion } from "motion/react";
import { api, ChatCitation, ChatSessionInfo } from "@/lib/api";
import { EASE, DUR } from "@/lib/motion";
import SplitText from "@/components/SplitText";

interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  citations: ChatCitation[];
  blocked?: boolean;
  reason?: string | null;
}

const SUGGESTIONS = [
  "Summarize this policy",
  "What does this document say about transparency?",
  "How does the EU AI Act classify high-risk AI?",
  "What does NIST AI RMF say about accountability?",
];

/** A PDF attached for document chat (ingested chat-only, never analysed). */
interface AuditorDoc {
  workspace_id: string;
  file_name: string;
}

function ArrowUpIcon({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" className={className}>
      <path d="M12 19V5" />
      <path d="m5 12 7-7 7 7" />
    </svg>
  );
}

function PaperclipIcon({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className={className}>
      <path d="m21.44 11.05-9.19 9.19a6 6 0 0 1-8.49-8.49l8.57-8.57A4 4 0 1 1 18 8.84l-8.59 8.57a2 2 0 0 1-2.83-2.83l8.49-8.48" />
    </svg>
  );
}

function DocIcon({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className={className}>
      <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
      <path d="M14 2v6h6" />
    </svg>
  );
}

function CitationChips({ citations }: { citations: ChatCitation[] }) {
  const [open, setOpen] = useState(false);
  const verified = (citations || []).filter((c) => c.verified);
  if (verified.length === 0) return null;
  return (
    <div className="mt-2">
      <button
        onClick={() => setOpen(!open)}
        className="inline-flex items-center gap-1.5 rounded-full border border-navy-950/15 bg-white px-2.5 py-1 text-[11px] font-medium text-navy-800 hover:border-navy-950/30 transition-colors"
      >
        <span className="h-1.5 w-1.5 rounded-full bg-[#3F7A52]" />
        {open ? "Hide" : "Show"} {verified.length} verified source
        {verified.length > 1 ? "s" : ""}
      </button>
      <AnimatePresence initial={false}>
        {open && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ height: { duration: DUR.fast, ease: EASE.outSoft }, opacity: { duration: DUR.instant, ease: "easeOut" } }}
            className="overflow-hidden"
          >
            <div className="mt-2 space-y-1.5">
              {verified.map((c, i) => (
                <div key={i} className="rounded-lg border border-navy-950/10 bg-[var(--surface)] px-3 py-2">
                  <p className="text-[11px] font-semibold text-navy-800">{c.source}</p>
                  <p className="mt-0.5 text-[11px] leading-relaxed text-gray-600">
                    &ldquo;{c.quote}&rdquo;
                  </p>
                </div>
              ))}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

function MessageBubble({ msg }: { msg: ChatMessage }) {
  const isUser = msg.role === "user";
  const isBlocked = msg.blocked;
  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: DUR.base, ease: EASE.out }}
      className={`flex ${isUser ? "justify-end" : "justify-start"}`}
    >
      <div
        className={`max-w-[82%] rounded-2xl px-4 py-3 text-sm leading-relaxed whitespace-pre-wrap ${
          isUser
            ? "bg-navy-950 text-white rounded-br-md shadow-md shadow-navy-950/15"
            :          isBlocked
            ? "bg-[#F7F0E2] text-[#7A5B1E] border border-[#E4D5B5] rounded-bl-md"
            : "bg-white border border-navy-950/10 text-gray-800 rounded-bl-md shadow-sm"
        }`}
      >
        {msg.content}
        {isBlocked && msg.reason && (
          <p className="mt-1.5 text-xs text-[#8A6420] italic">Reason: {msg.reason}</p>
        )}
        {!isUser && <CitationChips citations={msg.citations} />}
      </div>
    </motion.div>
  );
}

export default function AuditorPage() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [sessions, setSessions] = useState<ChatSessionInfo[]>([]);
  const [showHistory, setShowHistory] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // ── Attached document (chat-only ingestion, never analysed) ──
  const [doc, setDoc] = useState<AuditorDoc | null>(null);
  const [uploading, setUploading] = useState(false);

  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  async function handleFile(file: File) {
    if (!file) return;
    setUploading(true);
    setError(null);
    try {
      const res = await api.auditorUpload(file);
      setDoc({ workspace_id: res.workspace_id, file_name: res.file_name });
      // New document → fresh conversation about it.
      setSessionId(null);
      setMessages([]);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Upload failed");
    } finally {
      setUploading(false);
    }
  }

  function removeDoc() {
    setDoc(null);
  }

  // ── Session history (framework / general scope) ──
  const loadSessions = useCallback(async () => {
    try {
      const data = await api.chat.listSessions("", "auditor");
      setSessions(data);
    } catch {
      // ignore
    }
  }, []);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, loading]);

  // ── Send ──────────────────────────────────────────────────────────────
  async function send(text: string) {
    const trimmed = text.trim();
    if (!trimmed || loading) return;
    setInput("");
    if (textareaRef.current) textareaRef.current.style.height = "auto";
    setMessages((prev) => [
      ...prev,
      { id: `user-${Date.now()}`, role: "user", content: trimmed, citations: [] },
    ]);
    setLoading(true);
    try {
      // With a document attached, questions are routed to that document
      // (Mode B); without one, they draw on the framework knowledge base.
      const wsId = doc ? doc.workspace_id : null;
      const res = await api.chat.sendMessage(
        wsId,
        trimmed,
        sessionId,
        null,
        "auditor"
      );
      if (!sessionId) {
        setSessionId(res.session_id);
        loadSessions();
      }
      setMessages((prev) => [
        ...prev,
        {
          id: `assistant-${Date.now()}`,
          role: "assistant",
          content: res.reply,
          citations: res.citations || [],
          blocked: res.blocked,
          reason: res.reason,
        },
      ]);
    } catch {
      setMessages((prev) => [
        ...prev,
        {
          id: `error-${Date.now()}`,
          role: "assistant",
          content: "Sorry — I hit an error answering that. Please try again.",
          citations: [],
        },
      ]);
    } finally {
      setLoading(false);
    }
  }

  async function switchSession(sid: string) {
    setShowHistory(false);
    setSessionId(sid);
    setMessages([]);
    try {
      const data = await api.chat.getSession(sid);
      setMessages(
        data.messages.map((m) => ({
          id: m.id,
          role: m.role,
          content: m.content,
          citations: m.citations || [],
        }))
      );
    } catch {
      // ignore
    }
  }

  function autoResize() {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 200)}px`;
  }

  const canSend = input.trim().length > 0 && !loading;

  return (
    <div className="flex flex-col h-[calc(100vh-140px)] min-h-[560px]">
      {/* ── Header ─────────────────────────────────────────────────────── */}
      <div className="flex items-center justify-between gap-4">
        <div>
          <SplitText
            tag="h1"
            text="AI Auditor"
            className="text-3xl font-bold text-navy-950 tracking-tight"
            splitType="chars"
            delay={45}
            duration={0.6}
            ease="power3.out"
            from={{ opacity: 0, y: 40 }}
            to={{ opacity: 1, y: 0 }}
            textAlign="left"
            playOnMount
          />
          <p className="mt-1 text-sm text-gray-600">
            One assistant for AI policy assessment — ask about governance
            dimensions and the international frameworks.
          </p>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <button
            onClick={() => {
              setSessionId(null);
              setMessages([]);
            }}
            className="pressable rounded-lg border border-navy-950/15 bg-white px-4 py-2 text-sm font-medium text-navy-800 hover:border-navy-950/30 transition-colors"
          >
            New chat
          </button>
          <div className="relative">
            <button
              onClick={() => {
                setShowHistory(!showHistory);
                if (!showHistory) loadSessions();
              }}
              className="pressable rounded-lg border border-navy-950/15 bg-white px-4 py-2 text-sm font-medium text-navy-800 hover:border-navy-950/30 transition-colors"
            >
              History ({sessions.length})
            </button>
            <AnimatePresence>
              {showHistory && (
                <motion.div
                  initial={{ opacity: 0, y: -6, scale: 0.98 }}
                  animate={{ opacity: 1, y: 0, scale: 1 }}
                  exit={{ opacity: 0, y: -6, scale: 0.98 }}
                  transition={{ duration: DUR.fast, ease: EASE.out }}
                  className="absolute right-0 top-full z-30 mt-2 w-72 overflow-hidden rounded-xl border border-navy-950/10 bg-white shadow-xl shadow-navy-950/10"
                >
                  <div className="max-h-72 overflow-y-auto py-1">
                    {sessions.length === 0 && (
                      <p className="px-4 py-3 text-xs text-gray-400 italic">
                        No previous auditor conversations.
                      </p>
                    )}
                    {sessions.map((s) => (
                      <button
                        key={s.session_id}
                        onClick={() => switchSession(s.session_id)}
                        className="block w-full px-4 py-2 text-left text-xs text-gray-700 hover:bg-[var(--surface)] truncate"
                      >
                        {s.title || "(untitled)"}
                      </button>
                    ))}
                  </div>
                </motion.div>
              )}
            </AnimatePresence>
          </div>
        </div>
      </div>

      {error && (
        <div className="mt-4 rounded-lg border border-[#E4C9C6] bg-[#F6ECEB] px-4 py-2.5 text-sm text-[#A8483F]">
          {error}
        </div>
      )}

      {/* ── Messages ───────────────────────────────────────────────────── */}
      <div className="mt-4 flex-1 overflow-y-auto rounded-2xl">
        {messages.length === 0 ? (
          <div className="flex h-full flex-col items-center justify-center px-6 text-center">
            <div className="grid h-16 w-16 place-items-center rounded-2xl bg-navy-950 shadow-lg shadow-navy-950/25">
              <svg viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" className="h-8 w-8">
                <circle cx="12" cy="12" r="10" />
                <path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3" />
                <path d="M12 17h.01" />
              </svg>
            </div>
            <h2 className="mt-5 text-xl font-bold text-navy-950 tracking-tight">
              Ask the AI Auditor anything
            </h2>
            <p className="mt-2 max-w-md text-sm leading-relaxed text-gray-600">
              Attach a policy PDF to ask questions grounded in its text, or
              ask about governance dimensions and the international
              frameworks — answers come with citations you can verify.
            </p>
            <div className="mt-6 grid w-full max-w-lg grid-cols-1 gap-2 sm:grid-cols-2">
              {SUGGESTIONS.map((label) => (
                <button
                  key={label}
                  onClick={() => send(label)}
                  disabled={loading}
                  className="pressable rounded-xl border border-navy-950/10 bg-white px-4 py-3 text-left text-[13px] font-medium text-navy-900 shadow-sm hover:border-navy-950/30 hover:shadow-md disabled:opacity-50 transition-all"
                >
                  {label}
                </button>
              ))}
            </div>
          </div>
        ) : (
          <div className="mx-auto max-w-3xl space-y-4 py-2">
            {messages.map((m) => (
              <MessageBubble key={m.id} msg={m} />
            ))}
            {loading && (
              <motion.div
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                className="flex justify-start"
              >
                <div className="flex items-center gap-2 rounded-2xl rounded-bl-md border border-navy-950/10 bg-white px-4 py-3 shadow-sm">
                  <span className="flex gap-1">
                    <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-navy-800 [animation-delay:0ms]" />
                    <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-navy-800 [animation-delay:150ms]" />
                    <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-navy-800 [animation-delay:300ms]" />
                  </span>
                  <span className="text-xs text-gray-500">Auditing…</span>
                </div>
              </motion.div>
            )}
            <div ref={bottomRef} />
          </div>
        )}
      </div>

      {/* ── Chatbar (OpenAI-style) ─────────────────────────────────────── */}
      <div className="mt-4 shrink-0">
        <div className="mx-auto max-w-3xl">
          {/* Attached document chip (chat-only ingestion) */}
          {doc && (
            <div className="mb-2 flex items-center gap-2">
              <div className="flex items-center gap-2 rounded-full border border-navy-950/15 bg-white py-1.5 pl-3 pr-1.5 shadow-sm">
                <DocIcon className="h-4 w-4 text-navy-600" />
                <span className="max-w-[220px] truncate text-xs font-medium text-navy-900">
                  {doc.file_name}
                </span>
                <button
                  onClick={removeDoc}
                  title="Remove document"
                  className="pressable grid h-5 w-5 place-items-center rounded-full text-gray-400 hover:bg-gray-100 hover:text-gray-600 transition-colors"
                >
                  &times;
                </button>
              </div>
              <span className="text-[11px] text-gray-400">
                Questions about this document are answered from its text.
              </span>
            </div>
          )}

          <div className="flex items-end gap-1.5 rounded-[28px] border border-navy-950/15 bg-white p-2 pl-1.5 shadow-[0_10px_40px_rgba(10,10,10,0.12)] transition-all focus-within:border-navy-800/40 focus-within:shadow-[0_12px_48px_rgba(10,10,10,0.18)]">
            {/* Attach a policy PDF for document-grounded chat — always
                at the start of the bar, before the text. */}
            <button
              onClick={() => fileInputRef.current?.click()}
              disabled={uploading}
              title={doc ? "Replace document" : "Attach an AI policy PDF"}
              className={`pressable mb-0.5 grid h-10 w-10 shrink-0 place-items-center rounded-full transition-all ${
                uploading
                  ? "bg-gray-200 text-gray-400"
                  : doc
                  ? "bg-navy-950 text-white shadow-lg shadow-navy-950/30 hover:bg-navy-800"
                  : "text-navy-500 hover:bg-navy-950/5 hover:text-navy-800"
              }`}
            >
              {uploading ? (
                <span className="h-4 w-4 animate-spin rounded-full border-2 border-gray-400 border-t-transparent" />
              ) : (
                <PaperclipIcon className="h-5 w-5" />
              )}
            </button>
            <textarea
              ref={textareaRef}
              value={input}
              onChange={(e) => {
                setInput(e.target.value);
                autoResize();
              }}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  send(input);
                }
              }}
              rows={1}
              placeholder={
                doc
                  ? "Ask about this document…"
                  : "Ask about governance dimensions or frameworks…"
              }
              className="max-h-[200px] flex-1 resize-none bg-transparent py-2.5 text-[15px] leading-relaxed text-navy-950 outline-none placeholder:text-gray-400"
            />
            <button
              onClick={() => send(input)}
              disabled={!canSend}
              title="Send"
              className={`pressable mb-0.5 grid h-10 w-10 shrink-0 place-items-center rounded-full transition-all ${
                canSend
                  ? "bg-navy-950 text-white shadow-lg shadow-navy-950/30 hover:bg-navy-800"
                  : "bg-gray-200 text-gray-400"
              }`}
            >
              <ArrowUpIcon className="h-5 w-5" />
            </button>
          </div>

          {/* Hidden file input — opened by the paperclip button */}
          <input
            ref={fileInputRef}
            type="file"
            accept=".pdf,application/pdf"
            className="hidden"
            onChange={(e) => {
              const file = e.target.files?.[0];
              e.target.value = "";
              if (file) handleFile(file);
            }}
          />

          <p className="mt-2 text-center text-[11px] text-gray-400">
            AI Auditor can make mistakes. Verify important claims against the
            source document.
          </p>
        </div>
      </div>
    </div>
  );
}
