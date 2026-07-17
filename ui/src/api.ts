/**
 * API client for Custos. Handles SSE streaming with AbortController.
 */

import type { Citation, PendingConfirmation, ToolUseEvent } from "./types";

const API_BASE = import.meta.env.VITE_API_URL ?? "http://127.0.0.1:8000";

export interface StreamCallbacks {
  onToken: (text: string) => void;
  onCitations: (citations: Citation[]) => void;
  onToolUse: (event: ToolUseEvent) => void;
  onConfirmAction: (pending: PendingConfirmation) => void;
  onRefused: (text: string) => void;
  onError: (detail: string) => void;
  onDone: () => void;
}

/**
 * Stream a chat response via SSE. Returns an AbortController the caller
 * can use to cancel the request.
 */
export function streamChat(
  query: string,
  userPermissions: string[],
  sessionId: string,
  callbacks: StreamCallbacks,
): AbortController {
  const controller = new AbortController();

  const body = JSON.stringify({
    query,
    user_permissions: userPermissions,
    session_id: sessionId,
  });

  fetch(`${API_BASE}/api/chat/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body,
    signal: controller.signal,
  })
    .then(async (response) => {
      if (!response.ok) {
        callbacks.onError(`Server returned ${response.status}`);
        callbacks.onDone();
        return;
      }

      const reader = response.body?.getReader();
      if (!reader) {
        callbacks.onError("No response body");
        callbacks.onDone();
        return;
      }

      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() ?? "";

        let currentEvent = "";
        for (const line of lines) {
          if (line.startsWith("event:")) {
            currentEvent = line.slice(6).trim();
          } else if (line.startsWith("data:")) {
            const dataStr = line.slice(5).trim();
            handleSSEEvent(currentEvent, dataStr, callbacks);
          }
        }
      }

      // Process remaining buffer
      if (buffer.trim()) {
        const lines = buffer.split("\n");
        let currentEvent = "";
        for (const line of lines) {
          if (line.startsWith("event:")) {
            currentEvent = line.slice(6).trim();
          } else if (line.startsWith("data:")) {
            const dataStr = line.slice(5).trim();
            handleSSEEvent(currentEvent, dataStr, callbacks);
          }
        }
      }

      callbacks.onDone();
    })
    .catch((err) => {
      if (err instanceof DOMException && err.name === "AbortError") {
        callbacks.onDone();
        return;
      }
      callbacks.onError(
        err instanceof Error ? err.message : "Connection failed",
      );
      callbacks.onDone();
    });

  return controller;
}

export interface ConfirmResult {
  status: string;
  tool_name: string;
  output: string;
  simulated: boolean;
}

/**
 * Approve or reject a pending side-effectful action.
 */
export async function confirmAction(
  actionId: string,
  sessionId: string,
  approved: boolean,
): Promise<ConfirmResult> {
  const resp = await fetch(`${API_BASE}/api/chat/confirm`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      action_id: actionId,
      session_id: sessionId,
      approved,
    }),
  });

  if (!resp.ok) {
    const detail = await resp.text();
    throw new Error(detail);
  }

  return resp.json();
}

function handleSSEEvent(
  event: string,
  dataStr: string,
  callbacks: StreamCallbacks,
): void {
  if (!dataStr) return;
  try {
    const data = JSON.parse(dataStr);
    switch (event) {
      case "token":
        callbacks.onToken(data.text ?? "");
        break;
      case "citations":
        callbacks.onCitations(data.citations ?? []);
        break;
      case "tool_use":
        callbacks.onToolUse({
          tool_name: data.tool_name ?? "",
          simulated: data.simulated,
        });
        break;
      case "confirm_action":
        callbacks.onConfirmAction({
          actionId: data.action_id ?? "",
          toolName: data.tool_name ?? "",
          arguments: data.arguments ?? {},
        });
        break;
      case "refused":
        callbacks.onRefused(data.text ?? "");
        break;
      case "error":
        callbacks.onError(data.detail ?? "Unknown error");
        break;
      case "done":
        break;
    }
  } catch {
    // Ignore malformed SSE data
  }
}
