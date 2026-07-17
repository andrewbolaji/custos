/**
 * Chat state machine hook.
 *
 * States: idle, streaming, error.
 *
 * The "never stuck" invariant:
 * - idle: user can send a message
 * - streaming: user can cancel (which returns to idle)
 * - error: user can retry or send a new message (both return to idle/streaming)
 *
 * There is no reachable state where the user cannot send another message.
 * Every terminal transition returns to idle.
 */

import { useCallback, useMemo, useRef, useState } from "react";

import { streamChat } from "../api";
import type { ChatState, Citation, Message, ToolUseEvent } from "../types";

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
}

export function useChat(): UseChatReturn {
  const [state, setState] = useState<ChatState>(INITIAL_STATE);
  const controllerRef = useRef<AbortController | null>(null);
  const lastQueryRef = useRef<{ query: string; permissions: string[] } | null>(
    null,
  );
  const assistantIdRef = useRef<string>("");
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
        timestamp: Date.now(),
      };

      setState((prev) => ({
        messages: [...prev.messages, userMessage, assistantMessage],
        status: "streaming",
        errorMessage: null,
      }));

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
          }));
        },
        onDone() {
          setState((prev) => ({
            ...prev,
            status: prev.status === "error" ? "error" : "idle",
          }));
        },
      });

      controllerRef.current = controller;
    },
    [],
  );

  const cancelStream = useCallback(() => {
    controllerRef.current?.abort();
    controllerRef.current = null;
    // Invariant: cancel always returns to idle
    setState((prev) => ({
      ...prev,
      status: "idle",
    }));
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

  return { state, sessionId, sendMessage, cancelStream, retry, clearError };
}
