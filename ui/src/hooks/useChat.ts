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

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

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

export type AccessGroup = "general" | "hr" | "finance";

export interface UseChatReturn {
  state: ChatState;
  sessionId: string;
  accessGroup: AccessGroup;
  setAccessGroup: (group: AccessGroup) => void;
  sendMessage: (query: string, permissions?: string[]) => void;
  cancelStream: () => void;
  retry: () => void;
  clearError: () => void;
  approveAction: (actionId: string) => void;
  rejectAction: (actionId: string) => void;
}

export function useChat(): UseChatReturn {
  const [state, setState] = useState<ChatState>(INITIAL_STATE);
  const [accessGroup, setAccessGroupState] = useState<AccessGroup>("general");
  const controllerRef = useRef<AbortController | null>(null);
  const lastQueryRef = useRef<{ query: string; permissions: string[] } | null>(
    null,
  );
  const assistantIdRef = useRef<string>("");
  const messagesRef = useRef<Message[]>([]);
  messagesRef.current = state.messages;
  const accessGroupRef = useRef<AccessGroup>(accessGroup);
  accessGroupRef.current = accessGroup;
  // Stable session ID: generated once per hook mount (per browser session)
  const sessionId = useMemo(() => makeId(), []);

  // Streaming buffer: tokens accumulate in pendingRef at SSE speed.
  // A rAF loop reveals them at a time-based pace (frame-rate independent)
  // using incremental per-frame accumulation with a fractional carry.
  // The drain stops accruing when starved (shownRef == pending.length)
  // so a slow token arrival cannot build a backlog that dumps on burst.
  const pendingRef = useRef("");     // full received text
  const shownRef = useRef(0);        // how many chars revealed so far
  const rafRef = useRef<number | null>(null);
  const lastCommitRef = useRef(0);   // last setState timestamp
  const lastFrameRef = useRef(0);    // timestamp of last drain frame
  const carryRef = useRef(0);        // fractional char accumulator
  // Perceptual tuning knob: characters per second. Frame-rate independent.
  const CHARS_PER_SEC = 50;
  const COMMIT_INTERVAL = 33;        // ~30fps
  const MAX_DT = 100;                // clamp dt so a backgrounded tab can't dump

  const startStreamSync = useCallback(() => {
    if (rafRef.current !== null) {
      cancelAnimationFrame(rafRef.current);
      rafRef.current = null;
    }
    lastFrameRef.current = performance.now();
    carryRef.current = 0;

    const drain = () => {
      const pending = pendingRef.current;
      const now = performance.now();
      const dt = Math.min(now - lastFrameRef.current, MAX_DT);
      lastFrameRef.current = now;

      if (shownRef.current < pending.length) {
        // Accumulate fractional chars from elapsed time
        carryRef.current += dt * CHARS_PER_SEC / 1000;
        const whole = Math.floor(carryRef.current);
        carryRef.current -= whole;
        const next = Math.min(shownRef.current + whole, pending.length);

        if (next > shownRef.current) {
          shownRef.current = next;

          if (now - lastCommitRef.current >= COMMIT_INTERVAL || next >= pending.length) {
            lastCommitRef.current = now;
            const content = pending.slice(0, next);
            const id = assistantIdRef.current;
            setState((prev) => ({
              ...prev,
              messages: prev.messages.map((m) =>
                m.id === id ? { ...m, content } : m,
              ),
            }));
          }
        }
      } else {
        // Starved: reset carry so no backlog builds while waiting
        carryRef.current = 0;
      }

      rafRef.current = requestAnimationFrame(drain);
    };
    rafRef.current = requestAnimationFrame(drain);
  }, []);

  // Hard stop: cancel the loop outright (for cancel/error where the
  // message is being removed -- draining it is wasted work).
  const stopStreamSync = useCallback(() => {
    if (rafRef.current !== null) {
      cancelAnimationFrame(rafRef.current);
      rafRef.current = null;
    }
  }, []);

  // Completion drain: continue revealing at the same incremental rate.
  // Used by onDone only.
  const finishStreamDrain = useCallback(() => {
    if (rafRef.current !== null) {
      cancelAnimationFrame(rafRef.current);
      rafRef.current = null;
    }
    lastFrameRef.current = performance.now();
    carryRef.current = 0;

    const drainRemaining = () => {
      const pending = pendingRef.current;
      const now = performance.now();
      const dt = Math.min(now - lastFrameRef.current, MAX_DT);
      lastFrameRef.current = now;

      carryRef.current += dt * CHARS_PER_SEC / 1000;
      const whole = Math.floor(carryRef.current);
      carryRef.current -= whole;
      const next = Math.min(shownRef.current + whole, pending.length);

      if (next > shownRef.current) {
        shownRef.current = next;
        const content = pending.slice(0, next);
        const id = assistantIdRef.current;
        setState((prev) => ({
          ...prev,
          messages: prev.messages.map((m) =>
            m.id === id ? { ...m, content } : m,
          ),
        }));
      }

      if (shownRef.current < pending.length) {
        rafRef.current = requestAnimationFrame(drainRemaining);
      } else {
        rafRef.current = null;
      }
    };
    rafRef.current = requestAnimationFrame(drainRemaining);
  }, []);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      if (rafRef.current !== null) cancelAnimationFrame(rafRef.current);
    };
  }, []);

  const sendMessage = useCallback(
    (query: string, permissions?: string[]) => {
      const perms = permissions ?? [accessGroupRef.current];
      // Save for retry
      lastQueryRef.current = { query, permissions: perms };

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
        permissions: perms,
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
        .slice(-20);

      // Reset stream buffer for this message
      pendingRef.current = "";
      shownRef.current = 0;
      lastCommitRef.current = 0;
      carryRef.current = 0;
      startStreamSync();

      const controller = streamChat(query, perms, sessionId, {
        onToken(text: string) {
          // Append to pending ref (fast, no React re-render).
          // The rAF drain loop reveals characters at a smooth pace.
          pendingRef.current += text;
        },
        onTextReplace(text: string) {
          // Reconciliation: update pending, clamp shown to the new
          // length (if the corrected text is shorter, e.g. artifact
          // stripped), and commit the visible prefix immediately so
          // the correction is rendered. The drain continues normally
          // for any remaining characters.
          pendingRef.current = text;
          shownRef.current = Math.min(shownRef.current, text.length);
          const visible = text.slice(0, shownRef.current);
          setState((prev) => ({
            ...prev,
            messages: prev.messages.map((m) =>
              m.id === assistantId ? { ...m, content: visible } : m,
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
        onGuardrail() {
          setState((prev) => ({
            ...prev,
            messages: prev.messages.map((m) =>
              m.id === assistantId
                ? { ...m, guardrailDetected: true }
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
          finishStreamDrain();
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
    stopStreamSync();
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

  const setAccessGroup = useCallback((group: AccessGroup) => {
    // Security: clear conversation on access change to prevent
    // cross-level carryover through client-supplied history.
    controllerRef.current?.abort();
    controllerRef.current = null;
    stopStreamSync();
    pendingRef.current = "";
    shownRef.current = 0;
    lastQueryRef.current = null;
    assistantIdRef.current = "";
    setAccessGroupState(group);
    setState(INITIAL_STATE);
  }, [stopStreamSync]);

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
    accessGroup,
    setAccessGroup,
    sendMessage,
    cancelStream,
    retry,
    clearError,
    approveAction,
    rejectAction,
  };
}
