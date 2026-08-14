"use client";

import { useState, useRef, useEffect } from "react";
import { AnimatePresence, motion } from "motion/react";
import { useChat, ChatMessage } from "./ChatProvider";
import { EASE, DUR } from "@/lib/motion";

const INTENT_BADGES: Record<string, { label: string; color: string }> = {
  concept_explanation: {
    label: "Concept Explanation",
    color: "bg-navy-100 text-navy-700",
  },
  analysis_explanation: {
    label: "Analysis Explanation",
    color: "bg-navy-100 text-navy-700",
  },
  recommendation_explanation: {
    label: "Recommendation",
    color: "bg-[#EAF1EC] text-[#3F7A52]",
  },
  educational: {
    label: "Educational",
    color: "bg-[#F7F0E2] text-[#7A5B1E]",
  },
  greeting: {
    label: "Greeting",
    color: "bg-gray-100 text-gray-600",
  },
  general: {
    label: "General",
    color: "bg-navy-100 text-navy-700",
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
    <span className="text-[10px] text-gray-400 italic">
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
      <span className="text-[#3F7A52] bg-[#EAF1EC] px-1.5 py-0.5 rounded">
        {passed} verified
      </span>
    </div>
  );
}

function MessageBubble({ msg }: { msg: ChatMessage }) {
  const [showCitations, setShowCitations] = useState(false);
  const isUser = msg.role === "user";
  const isBlocked = msg.blocked;
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
            ? "bg-undp-blue text-white rounded-br-md"
            : isBlocked
            ? "bg-[#F7F0E2] text-[#7A5B1E] border border-[#E4D5B5] rounded-bl-md"
            : "bg-gray-100 text-gray-800 rounded-bl-md"
        }`}
      >
        {/* Intent badge + provider label */}
        {!isUser && !isBlocked && (
          <div className="flex items-center gap-2 mb-1.5 flex-wrap">
            {intent && <IntentBadge intent={intent} />}
            {msg.provider && msg.provider !== "template" && (
              <ProviderLabel provider={msg.provider} />
            )}
          </div>
        )}

        {/* Message content */}
        <p className="whitespace-pre-wrap">{msg.content}</p>

        {/* Blocked reason */}
        {isBlocked && msg.reason && (
          <p className="text-xs mt-1 text-[#8A6420] italic">
            Reason: {msg.reason}
          </p>
        )}

        {/* Citations — only show verified ones, hide unverified entirely */}
        {!isUser && msg.citations && msg.citations.some((c) => c.verified) && (
          <div className="mt-1">
            <button
              onClick={() => setShowCitations(!showCitations)}
              className="text-[10px] text-gray-500 underline hover:text-gray-700"
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
                          className="text-[10px] bg-white rounded p-1.5 border border-gray-200"
                        >
                          <span className="font-medium text-gray-700">{cit.source}:</span>{" "}
                          <span className="text-gray-500">&ldquo;{cit.quote}&rdquo;</span>
                          <span className="ml-1 text-[#3F7A52]">✓</span>
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
  "Why did Transparency receive its coverage level?",
  "What evidence supports the Safety verdict?",
  "Summarize the recommendations for Inclusivity",
  "What are the implementation roadmap phases?",
  "Explain the case intelligence match for Accountability",
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
          and scroll state survive closing. */}
      <motion.div
        initial={false}
        animate={{ x: isOpen ? "0%" : "100%" }}
        transition={{ duration: DUR.slow, ease: EASE.outSoft }}
        className="fixed top-0 right-0 h-full w-full max-w-md bg-white shadow-2xl z-50 flex flex-col"
      >
        {/* Header */}
        <div className="shrink-0 border-b border-gray-200 px-4 py-3">
          <div className="flex items-center justify-between mb-2">
            <h2 className="text-base font-semibold text-undp-blue">
              {findingLabel ? `Ask about: ${findingLabel}` : "AI Rapporteur"}
            </h2>
            <button
              onClick={closePanel}
              className="text-gray-400 hover:text-gray-600 text-xl leading-none"
            >
              &times;
            </button>
          </div>

          <div className="flex items-center gap-2 flex-wrap">
            <button
              onClick={() => {
                newSession();
                setShowSessions(false);
              }}
              className="text-xs text-gray-500 hover:text-undp-blue"
            >
              New chat
            </button>
            <span className="text-gray-300">|</span>
            <button
              onClick={() => setShowSessions(!showSessions)}
              className="text-xs text-gray-500 hover:text-undp-blue"
            >
              {showSessions ? "Hide history" : `History (${sessions.length})`}
            </button>
            {findingLabel && (
              <>
                <span className="text-gray-300">|</span>
                <span className="text-xs text-undp-blue font-medium">
                  {findingLabel}
                </span>
              </>
            )}
          </div>
          {showSessions && (
            <div className="mt-2 max-h-32 overflow-y-auto space-y-1">
              {sessions.length === 0 && (
                <p className="text-[11px] text-gray-400 italic">
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
                  className="block w-full text-left text-[11px] text-gray-600 hover:bg-gray-50 rounded px-2 py-1 truncate"
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
            <div className="text-center text-gray-400 text-sm mt-8 space-y-4">
              <p className="font-medium text-gray-500">AI Rapporteur</p>
              <p>
                Ask about this analysis — how each dimension was scored, the
                evidence, recommendations, roadmap, and case intelligence.
              </p>
              <div className="text-xs space-y-1 text-left max-w-xs mx-auto">
                <p className="font-medium text-gray-500 mt-4">
                  Try asking:
                </p>
                {SUGGESTIONS.map((s) => (
                  <button
                    key={s}
                    onClick={() => sendMessage(s)}
                    className="block w-full text-left text-undp-blue hover:bg-navy-50 rounded px-2 py-1"
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
              <div className="bg-gray-100 rounded-xl rounded-bl-md px-4 py-2.5 text-sm text-gray-500">
                <span className="animate-pulse">Thinking...</span>
              </div>
            </div>
          )}
          <div ref={bottomRef} />
        </div>

        {/* Input */}
        <div className="shrink-0 border-t border-gray-200 px-4 py-3">
          <form onSubmit={handleSend} className="flex gap-2">
            <input
              type="text"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="Ask about this analysis..."
              disabled={loading}
              className="flex-1 border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-undp-blue disabled:opacity-50"
            />
            <button
              type="submit"
              disabled={!input.trim() || loading}
              className="pressable bg-undp-blue text-white px-4 py-2 rounded-lg text-sm font-medium hover:bg-undp-blue-light disabled:opacity-50 transition-colors"
            >
              Send
            </button>
          </form>
        </div>
      </motion.div>
    </>
  );
}
