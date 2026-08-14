"use client";

import React, {
  createContext,
  useContext,
  useState,
  useCallback,
  useRef,
  useEffect,
} from "react";
import { api, ChatCitation, ChatSessionInfo, ChatMessageData, ChatMode } from "@/lib/api";

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  citations: ChatCitation[];
  intent?: string;
  dimension?: string | null;
  provider?: string;
  blocked?: boolean;
  reason?: string | null;
}

interface ChatContextValue {
  isOpen: boolean;
  openPanel: () => void;
  closePanel: () => void;
  togglePanel: () => void;
  workspaceId: string | null;
  setWorkspaceId: (id: string | null) => void;
  sessionId: string | null;
  /** "advisor" (analysis-aware) | "framework_qa" (knowledge-base only) */
  mode: ChatMode;
  setMode: (m: ChatMode) => void;
  findingLabel: string | null;
  findingContext: Record<string, unknown> | null;
  setFindingContext: (label: string | null, ctx: Record<string, unknown> | null) => void;
  messages: ChatMessage[];
  loading: boolean;
  sendMessage: (text: string) => Promise<void>;
  sessions: ChatSessionInfo[];
  loadSessions: () => Promise<void>;
  switchSession: (sessionId: string) => Promise<void>;
  newSession: () => void;
}

const ChatContext = createContext<ChatContextValue>(null!);

export function useChat() {
  return useContext(ChatContext);
}

export function ChatProvider({ children }: { children: React.ReactNode }) {
  const [isOpen, setIsOpen] = useState(false);
  const [workspaceId, setWorkspaceId] = useState<string | null>(null);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [mode, setModeState] = useState<ChatMode>("advisor");
  const [findingLabel, setFindingLabel] = useState<string | null>(null);
  const [findingContext, setFindingContextState] = useState<Record<string, unknown> | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [loading, setLoading] = useState(false);
  const [sessions, setSessions] = useState<ChatSessionInfo[]>([]);
  const findingContextRef = useRef<Record<string, unknown> | null>(null);

  const openPanel = useCallback(() => setIsOpen(true), []);
  const closePanel = useCallback(() => setIsOpen(false), []);
  const togglePanel = useCallback(() => setIsOpen((v) => !v), []);

  const setFinding = useCallback((label: string | null, ctx: Record<string, unknown> | null) => {
    setFindingLabel(label);
    setFindingContextState(ctx);
    findingContextRef.current = ctx;
  }, []);

  const loadSessions = useCallback(async () => {
    if (!workspaceId) return;
    try {
      const data = await api.chat.listSessions(workspaceId, mode);
      setSessions(data);
    } catch {
      // ignore
    }
  }, [workspaceId, mode]);

  const setMode = useCallback((m: ChatMode) => {
    setModeState(m);
    // Switching bots resets the active thread; sessions are per-mode.
    setSessionId(null);
    setMessages([]);
    setFindingLabel(null);
    setFindingContextState(null);
    findingContextRef.current = null;
  }, []);

  const switchSession = useCallback(async (sid: string) => {
    setSessionId(sid);
    setMessages([]);
    try {
      const data = await api.chat.getSession(sid);
      setMessages(
        data.messages.map((m: ChatMessageData) => ({
          id: m.id,
          role: m.role,
          content: m.content,
          citations: m.citations || [],
        }))
      );
    } catch {
      // ignore
    }
  }, []);

  const newSession = useCallback(() => {
    setSessionId(null);
    setMessages([]);
    setFindingLabel(null);
    setFindingContextState(null);
    findingContextRef.current = null;
  }, []);

  // Keep the per-mode session list fresh whenever the mode changes.
  useEffect(() => {
    if (isOpen && workspaceId) {
      loadSessions();
    }
  }, [mode, isOpen, workspaceId, loadSessions]);

  const sendMessage = useCallback(async (text: string) => {
    // Mode A (general) works without a workspace; other modes need one.
    if (!text.trim() || loading) return;
    if (mode !== "advisor" && !workspaceId) return;

    const userMsg: ChatMessage = {
      id: `user-${Date.now()}`,
      role: "user",
      content: text,
      citations: [],
    };
    setMessages((prev) => [...prev, userMsg]);
    setLoading(true);

    try {
      const response = await api.chat.sendMessage(
        workspaceId,
        text,
        sessionId,
        findingContextRef.current,
        mode
      );

      if (!sessionId) {
        setSessionId(response.session_id);
        loadSessions();
      }

      const assistantMsg: ChatMessage = {
        id: `assistant-${Date.now()}`,
        role: "assistant",
        content: response.reply,
        citations: response.citations || [],
        intent: response.intent,
        dimension: response.dimension,
        provider: response.provider,
        blocked: response.blocked,
        reason: response.reason,
      };
      setMessages((prev) => [...prev, assistantMsg]);
    } catch {
      const errorMsg: ChatMessage = {
        id: `error-${Date.now()}`,
        role: "assistant",
        content: "Sorry, I encountered an error processing your question.",
        citations: [],
      };
      setMessages((prev) => [...prev, errorMsg]);
    } finally {
      setLoading(false);
    }
  }, [workspaceId, sessionId, loading, loadSessions, mode]);

  return (
    <ChatContext.Provider
      value={{
        isOpen,
        openPanel,
        closePanel,
        togglePanel,
        workspaceId,
        setWorkspaceId,
        sessionId,
        mode,
        setMode,
        findingLabel,
        findingContext,
        setFindingContext: setFinding,
        messages,
        loading,
        sendMessage,
        sessions,
        loadSessions,
        switchSession,
        newSession,
      }}
    >
      {children}
    </ChatContext.Provider>
  );
}
