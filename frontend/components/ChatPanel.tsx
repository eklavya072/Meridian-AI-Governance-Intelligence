"use client";

import { useState, useRef, useEffect } from "react";
import { AnimatePresence, motion } from "motion/react";
import { useChat, ChatMessage } from "./ChatProvider";
import { EASE, DUR } from "@/lib/motion";
import MarkdownLite from "@/components/MarkdownLite";

const INTENT_BADGES: Record<string, { label: string; color: string }> = {
  concept_explanation: {
    label: "Concept Explanation",
    color: "bg-grey-100 text-grey-700",
  },
  analysis_explanation: {
    label: "Analysis Explanation",
    color: "bg-grey-100 text-grey-700",
  },
  recommendation_explanation: {
    label: "Recommendation",
    color: "bg-status-green-tint text-status-green-ink",
  },
  educational: {
    label: "Educational",
    color: "bg-status-amber-tint text-status-amber-ink",
  },
  greeting: {
    label: "Greeting",
    color: "bg-grey-50 text-grey-700",
  },
  general: {
    label: "General",
    color: "bg-grey-100 text-grey-700",
  },
};

function IntentBadge({ intent }: { intent?: string }) {
  if (!intent) return null;
  const badge = INTENT_BADGES[intent];
  if (!badge) return null;
  return (
    <span
      className={`inline-flex items-center gap-1 text-[10px] font-medium px-1.5 py-0.5 rounded-full ${badge.color}`}
    >
      {badge.label}
    </span>
  );
}

function ProviderLabel({ provider }: { provider?: string }) {
  if (!provider || provider === "template") return null;
  return (
    <span className="text-[10px] text-grey-600 italic">
      Enriched by {provider}
    </span>
  );
}

function CitationBadge({ citations }: { citations: ChatMessage["citations"] }) {
  if (!citations || citations.length === 0) return null;
  const passed = citations.filter((c) => c.verified).length;
  // Only show verified count — unverified citations are hidden entirely
  if (passed === 0) return null;
  return (
    <div className="flex gap-2 mt-2 text-[10px]">
      <span className="text-status-green-ink bg-status-green-tint px-1.5 py-0.5 rounded">
        {passed} verified
      </span>
    </div>
  );
}

function MessageBubble({ msg }: { msg: ChatMessage }) {
  const [showCitations, setShowCitations] = useState(false);
  const isUser = msg.role === "user";
  const isBlocked = msg.blocked;
  const isFailed = msg.failed;
  const intent = msg.intent;

  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: DUR.base, ease: EASE.out }}
      className={`flex ${isUser ? "justify-end" : "justify-start"}`}
    >
      <div
        className={`max-w-[85%] rounded-xl px-4 py-2.5 text-sm ${
          isUser
            ? "bg-grey-950 text-white rounded-br-md"
            : isFailed
            ? "bg-status-red-tint text-grey-900 border border-status-red-line rounded-bl-md"
            : isBlocked
            ? "bg-status-amber-tint text-status-amber-ink border border-status-amber-line rounded-bl-md"
            : "bg-grey-50 text-grey-900 rounded-bl-md"
        }`}
        role={isFailed ? "alert" : undefined}
      >
        {/* Intent badge + provider label */}
        {!isUser && !isBlocked && !isFailed && (
          <div className="flex items-center gap-2 mb-1.5 flex-wrap">
            {intent && <IntentBadge intent={intent} />}
            {msg.provider && msg.provider !== "template" && (
              <ProviderLabel provider={msg.provider} />
            )}
          </div>
        )}

        {/* Message content. Assistant replies arrive as light Markdown (the
            model emits **bold** and lists whether asked to or not), so they
            are rendered rather than shown as literal asterisks. User messages
            are their own typing and stay verbatim. */}
        {isUser ? (
          <p className="whitespace-pre-wrap">{msg.content}</p>
        ) : (
          <MarkdownLite text={msg.content} />
        )}

        {/* Blocked reason */}
        {isBlocked && msg.reason && (
          <p className="text-xs mt-1 text-status-amber-ink italic">
            Reason: {msg.reason}
          </p>
        )}

        {/* Citations — only show verified ones, hide unverified entirely */}
        {!isUser && msg.citations && msg.citations.some((c) => c.verified) && (
          <div className="mt-1">
            <button
              onClick={() => setShowCitations(!showCitations)}
              className="text-[10px] text-grey-600 underline hover:text-grey-800"
            >
              {showCitations ? "Hide" : "Show"} citations
              ({msg.citations.filter((c) => c.verified).length})
            </button>
            <AnimatePresence initial={false}>
              {showCitations && (
                <motion.div
                  initial={{ height: 0, opacity: 0 }}
                  animate={{ height: "auto", opacity: 1 }}
                  exit={{ height: 0, opacity: 0 }}
                  transition={{
                    height: { duration: DUR.fast, ease: EASE.outSoft },
                    opacity: { duration: DUR.instant, ease: "easeOut" },
                  }}
                  className="overflow-hidden"
                >
                  <div className="mt-1 space-y-1">
                    {msg.citations
                      .filter((cit) => cit.verified)
                      .map((cit, i) => (
                        <div
                          key={i}
                          className="text-[10px] bg-white rounded p-1.5 border border-grey-100"
                        >
                          <span className="font-medium text-grey-800">{cit.source}:</span>{" "}
                          <span className="text-grey-600">&ldquo;{cit.quote}&rdquo;</span>
                          <span className="ml-1 text-status-green">✓</span>
                        </div>
                      ))}
                  </div>
                </motion.div>
              )}
            </AnimatePresence>
          </div>
        )}
        <CitationBadge citations={msg.citations} />
      </div>
    </motion.div>
  );
}

// Suggested prompts — each maps to a real question a user would ask about a
// completed analysis: how a dimension was scored, the evidence, the
// recommendations, the roadmap, and the case intelligence.
const SUGGESTIONS = [
  "Which dimension came out strongest, and why?",
  "What are the main gaps in this analysis?",
  "Why did Transparency receive its coverage level?",
  "What evidence supports the Safety verdict?",
  "Which mechanisms are missing, and which are binding?",
  "What are the implementation roadmap phases?",
];

export default function ChatPanel() {
  const {
    isOpen,
    closePanel,
    workspaceId,
    messages,
    loading,
    sendMessage,
    findingLabel,
    sessions,
    loadSessions,
    switchSession,
    newSession,
  } = useChat();

  const [input, setInput] = useState("");
  const [showSessions, setShowSessions] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);
  /* React 18 does not forward `inert` as a prop — it is not in its known
     attribute list, so it is silently dropped, and passing it through
     framer-motion drops it again. Measured after trying the prop: the
     drawer still exposed 11 focusable controls. Set on the element. */
  const drawerRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  // Whatever had focus when the drawer opened (usually the Ask button), so
  // closing it puts the keyboard user back where they were.
  const returnFocusRef = useRef<HTMLElement | null>(null);

  useEffect(() => {
    const el = drawerRef.current;
    if (!el) return;
    if (isOpen) {
      el.removeAttribute("inert");
      returnFocusRef.current = document.activeElement as HTMLElement | null;
      inputRef.current?.focus();
    } else {
      el.setAttribute("inert", "");
      returnFocusRef.current?.focus?.();
      returnFocusRef.current = null;
    }
  }, [isOpen]);

  useEffect(() => {
    if (!isOpen) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") closePanel();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [isOpen, closePanel]);

  useEffect(() => {
    if (isOpen && workspaceId) {
      loadSessions();
    }
  }, [isOpen, workspaceId, loadSessions]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  async function handleSend(e: React.FormEvent) {
    e.preventDefault();
    if (!input.trim() || loading) return;
    const text = input;
    setInput("");
    await sendMessage(text);
  }

  return (
    <>
      {/* Backdrop: fades in/out with the panel — a state change (the drawer
          is open) communicated by dimming the context behind it. */}
      <AnimatePresence>
        {isOpen && (
          <motion.div
            className="fixed inset-0 bg-black/30 z-40"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: DUR.fast, ease: "easeOut" }}
            onClick={closePanel}
          />
        )}
      </AnimatePresence>

      {/* Drawer: slide-in on a transform, not layout — the panel never
          reflows the page, it glides over it. Stays mounted so the input
          and scroll state survive closing.

          Staying mounted is the right call for state and the wrong one for
          everything else unless it is also inert. Translated off-screen it
          kept `visibility: visible`, so it contributed eleven focusable
          controls and an `<h2>` to every route that renders it — including
          the landing page, where tabbing off the hero dropped a keyboard
          user into a chat about an analysis that does not exist, and where
          its heading sat in the document outline. `inert` removes it from
          the tab order, the accessibility tree and find-in-page in one
          attribute; `aria-hidden` is belt and braces for older engines. */}
      <motion.div
        initial={false}
        animate={{ x: isOpen ? "0%" : "100%" }}
        transition={{ duration: DUR.slow, ease: EASE.outSoft }}
        ref={drawerRef}
        role="dialog"
        data-lenis-prevent
        aria-modal="true"
        aria-labelledby="chat-panel-title"
        aria-hidden={!isOpen || undefined}
        className="fixed top-0 right-0 h-full w-full max-w-md bg-white shadow-2xl z-50 flex flex-col"
      >
        {/* Header */}
        <div className="shrink-0 border-b border-grey-100 px-4 py-3">
          <div className="flex items-center justify-between mb-2">
            <h2 id="chat-panel-title" className="text-base font-semibold text-grey-950">
              {findingLabel ? `Ask about: ${findingLabel}` : "AI Rapporteur"}
            </h2>
<button
              type="button"
              onClick={closePanel}
              aria-label="Close chat"
              className="text-grey-600 hover:text-grey-700 text-xl leading-none"
            >
              <span aria-hidden>&times;</span>
            </button>
          </div>

          <div className="flex items-center gap-2 flex-wrap">
            <button
              onClick={() => {
                newSession();
                setShowSessions(false);
              }}
              className="text-xs text-grey-600 hover:text-grey-950"
            >
              New chat
            </button>
            <span aria-hidden className="text-grey-300">|</span>
            <button
              onClick={() => setShowSessions(!showSessions)}
              className="text-xs text-grey-600 hover:text-grey-950"
            >
              {showSessions ? "Hide history" : `History (${sessions.length})`}
            </button>
            {findingLabel && (
              <>
                <span aria-hidden className="text-grey-300">|</span>
                <span className="text-xs text-grey-950 font-medium">
                  {findingLabel}
                </span>
              </>
            )}
          </div>
          {showSessions && (
            <div className="mt-2 max-h-32 overflow-y-auto space-y-1">
              {sessions.length === 0 && (
                <p className="text-[11px] text-grey-600 italic">
                  No previous sessions
                </p>
              )}
              {sessions.map((s) => (
                <button
                  key={s.session_id}
                  onClick={() => {
                    switchSession(s.session_id);
                    setShowSessions(false);
                  }}
                  className="block w-full text-left text-[11px] text-grey-700 hover:bg-grey-50 rounded px-2 py-1 truncate"
                >
                  {s.title || "(untitled)"}
                </button>
              ))}
            </div>
          )}
        </div>

        {/* Messages */}
        <div className="flex-1 overflow-y-auto px-4 py-4 space-y-3">
          {messages.length === 0 && (
            <div className="text-center text-grey-600 text-sm mt-8 space-y-4">
              <p className="font-medium text-grey-600">AI Rapporteur</p>
              <p>
                Ask about this analysis: how each dimension was scored, the
                evidence, recommendations, roadmap, and case intelligence.
              </p>
              <div className="text-xs space-y-1 text-left max-w-xs mx-auto">
                <p className="font-medium text-grey-600 mt-4">
                  Try asking:
                </p>
                {SUGGESTIONS.map((s) => (
                  <button
                    key={s}
                    onClick={() => sendMessage(s)}
                    className="block w-full text-left text-grey-950 hover:bg-grey-50 rounded px-2 py-1"
                  >
                    {s}
                  </button>
                ))}
              </div>
            </div>
          )}
          {messages.map((msg) => (
            <MessageBubble key={msg.id} msg={msg} />
          ))}
          {loading && (
            <div className="flex justify-start">
              <div className="bg-grey-50 rounded-xl rounded-bl-md px-4 py-2.5 text-sm text-grey-600">
                <span className="animate-pulse">Thinking...</span>
              </div>
            </div>
          )}
          <div ref={bottomRef} />
        </div>

        {/* Input */}
        <div className="shrink-0 border-t border-grey-100 px-4 py-3">
          <form onSubmit={handleSend} className="flex gap-2">
            <input
              ref={inputRef}
              type="text"
              aria-label="Your question"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="Ask about this analysis..."
              disabled={loading}
              className="flex-1 border border-grey-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-grey-950 disabled:opacity-50"
            />
            <button
              type="submit"
              disabled={!input.trim() || loading}
              className="pressable bg-grey-950 text-white px-4 py-2 rounded-lg text-sm font-medium hover:bg-grey-800 disabled:opacity-50 transition-colors"
            >
              Send
            </button>
          </form>
        </div>
      </motion.div>
    </>
  );
}
