/**
 * Chat state machine hook.
 *
 * States: idle, streaming, awaiting_confirmation, error.
 *
 * The "never stuck" invariant:
 * - idle: user can send a message
 * - streaming: user can cancel (which returns to idle)
 * - awaiting_confirmation: user can approve, reject, or cancel
 * - error: user can retry or send a new message (both return to idle/streaming)
 *
 * There is no reachable state where the user cannot send another message.
 * Every terminal transition returns to idle.
 */

import { useCallback, useMemo, useRef, useState } from "react";

import { confirmAction, streamChat, type HistoryEntry } from "../api";
import type {
  ChatState,
  Citation,
  Message,
  PendingConfirmation,
  ToolUseEvent,
} from "../types";

const INITIAL_STATE: ChatState = {
  messages: [],
  status: "idle",
  errorMessage: null,
};

function makeId(): string {
  return `${Date.now()}-${Math.random().toString(36).slice(2, 9)}`;
}

export interface UseChatReturn {
  state: ChatState;
  sessionId: string;
  sendMessage: (query: string, permissions?: string[]) => void;
  cancelStream: () => void;
  retry: () => void;
  clearError: () => void;
  approveAction: (actionId: string) => void;
  rejectAction: (actionId: string) => void;
}

export function useChat(): UseChatReturn {
  const [state, setState] = useState<ChatState>(INITIAL_STATE);
  const controllerRef = useRef<AbortController | null>(null);
  const lastQueryRef = useRef<{ query: string; permissions: string[] } | null>(
    null,
  );
  const assistantIdRef = useRef<string>("");
  const messagesRef = useRef<Message[]>([]);
  messagesRef.current = state.messages;
  // Stable session ID: generated once per hook mount (per browser session)
  const sessionId = useMemo(() => makeId(), []);

  const sendMessage = useCallback(
    (query: string, permissions: string[] = ["general"]) => {
      // Save for retry
      lastQueryRef.current = { query, permissions };

      const userMessage: Message = {
        id: makeId(),
        role: "user",
        content: query,
        citations: [],
        refused: false,
        toolUses: [],
        pendingConfirmation: null,
        timestamp: Date.now(),
      };

      const assistantId = makeId();
      assistantIdRef.current = assistantId;

      const assistantMessage: Message = {
        id: assistantId,
        role: "assistant",
        content: "",
        citations: [],
        refused: false,
        toolUses: [],
        pendingConfirmation: null,
        timestamp: Date.now(),
        permissions,
      };

      setState((prev) => ({
        messages: [
          // Retire any older pending cards before adding the new pair
          ...prev.messages.map((m) =>
            m.pendingConfirmation && m.role === "assistant"
              ? { ...m, pendingConfirmation: { ...m.pendingConfirmation, expired: true } }
              : m,
          ),
          userMessage,
          assistantMessage,
        ],
        status: "streaming",
        errorMessage: null,
      }));

      // Build history from completed prior turns (last 10 messages).
      // Uses messagesRef to avoid stale closure (sendMessage has [] deps).
      const history: HistoryEntry[] = messagesRef.current
        .filter((m) => m.content)
        .map((m) => ({ role: m.role, content: m.content }))
        .slice(-10);

      const controller = streamChat(query, permissions, sessionId, {
        onToken(text: string) {
          setState((prev) => ({
            ...prev,
            messages: prev.messages.map((m) =>
              m.id === assistantId ? { ...m, content: m.content + text } : m,
            ),
          }));
        },
        onCitations(citations: Citation[]) {
          setState((prev) => ({
            ...prev,
            messages: prev.messages.map((m) =>
              m.id === assistantId ? { ...m, citations } : m,
            ),
          }));
        },
        onToolUse(event: ToolUseEvent) {
          setState((prev) => ({
            ...prev,
            messages: prev.messages.map((m) =>
              m.id === assistantId
                ? { ...m, toolUses: [...m.toolUses, event] }
                : m,
            ),
          }));
        },
        onConfirmAction(pending: PendingConfirmation) {
          setState((prev) => ({
            ...prev,
            status: "awaiting_confirmation",
            messages: prev.messages.map((m) => {
              if (m.id === assistantId) {
                return { ...m, pendingConfirmation: pending };
              }
              // Retire any older pending cards so they can't be clicked
              if (m.pendingConfirmation && m.role === "assistant") {
                return {
                  ...m,
                  pendingConfirmation: { ...m.pendingConfirmation, expired: true },
                };
              }
              return m;
            }),
          }));
        },
        onRefused(text: string) {
          setState((prev) => ({
            ...prev,
            messages: prev.messages.map((m) =>
              m.id === assistantId
                ? { ...m, content: text, refused: true }
                : m,
            ),
          }));
        },
        onError(detail: string) {
          setState((prev) => ({
            ...prev,
            status: "error",
            errorMessage: detail,
            // Remove empty assistant bubble so it doesn't float next to the error banner
            messages: prev.messages.filter(
              (m) => !(m.id === assistantId && m.role === "assistant" && !m.content),
            ),
          }));
        },
        onDone() {
          setState((prev) => ({
            ...prev,
            status:
              prev.status === "error"
                ? "error"
                : prev.status === "awaiting_confirmation"
                  ? "awaiting_confirmation"
                  : "idle",
          }));
        },
      }, history);

      controllerRef.current = controller;
    },
    [],
  );

  const cancelStream = useCallback(() => {
    controllerRef.current?.abort();
    controllerRef.current = null;
    lastQueryRef.current = null;
    const cancelledAssistantId = assistantIdRef.current;
    assistantIdRef.current = "";
    // Remove the in-flight user + assistant message pair so cancel
    // never leaves a stale query or empty bubble in the history.
    setState((prev) => {
      const msgs = prev.messages.filter((m) => {
        if (m.id === cancelledAssistantId) return false;
        // Remove the user message that immediately preceded it
        const idx = prev.messages.findIndex((x) => x.id === cancelledAssistantId);
        if (idx > 0 && m === prev.messages[idx - 1] && m.role === "user") return false;
        return true;
      });
      return { ...prev, messages: msgs, status: "idle" };
    });
  }, []);

  const retry = useCallback(() => {
    if (lastQueryRef.current) {
      // Remove the failed assistant message before retrying
      setState((prev) => {
        const messages = prev.messages.slice(0, -1);
        return { ...prev, messages, status: "idle", errorMessage: null };
      });
      const { query, permissions } = lastQueryRef.current;
      // Use setTimeout to let state update before re-sending
      setTimeout(() => sendMessage(query, permissions), 0);
    }
  }, [sendMessage]);

  const clearError = useCallback(() => {
    // Invariant: clearing error returns to idle
    setState((prev) => ({
      ...prev,
      status: "idle",
      errorMessage: null,
    }));
  }, []);

  const approveAction = useCallback(
    (actionId: string) => {
      setState((prev) => ({ ...prev, status: "streaming" }));
      confirmAction(actionId, sessionId, true)
        .then((result) => {
          // Build a clean one-line result. The output from the tool
          // already contains "(simulated)" when applicable, so we
          // must not append it again.
          const resultText = result.output;
          setState((prev) => ({
            ...prev,
            status: "idle",
            messages: prev.messages.map((m) =>
              m.pendingConfirmation?.actionId === actionId
                ? {
                    ...m,
                    content: resultText,
                    pendingConfirmation: null,
                  }
                : m,
            ),
          }));
        })
        .catch(() => {
          setState((prev) => ({
            ...prev,
            status: "error",
            errorMessage: "Failed to confirm action.",
          }));
        });
    },
    [sessionId],
  );

  const rejectAction = useCallback((actionId: string) => {
    confirmAction(actionId, sessionId, false)
      .then(() => {
        setState((prev) => ({
          ...prev,
          status: "idle",
          messages: prev.messages.map((m) =>
            m.pendingConfirmation?.actionId === actionId
              ? {
                  ...m,
                  content: "Action was rejected.",
                  pendingConfirmation: null,
                }
              : m,
          ),
        }));
      })
      .catch(() => {
        setState((prev) => ({
          ...prev,
          status: "idle",
          messages: prev.messages.map((m) =>
            m.pendingConfirmation?.actionId === actionId
              ? { ...m, pendingConfirmation: null }
              : m,
          ),
        }));
      });
  }, [sessionId]);

  return {
    state,
    sessionId,
    sendMessage,
    cancelStream,
    retry,
    clearError,
    approveAction,
    rejectAction,
  };
}
