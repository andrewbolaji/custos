/**
 * Unit tests for the useChat hook state machine.
 *
 * Tests the "never stuck" invariant: every transition from streaming,
 * error, cancel, awaiting_confirmation, or completion returns the UI
 * to a state where the user can send another message.
 *
 * These test the state machine logic, not the SSE transport.
 */

import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { StreamCallbacks } from "../api";
import { useChat } from "../hooks/useChat";

// Capture the callbacks passed to streamChat so we can simulate events
let lastCallbacks: StreamCallbacks | null = null;
let lastController: AbortController | null = null;

// Track confirmAction calls
let confirmActionCalls: Array<{
  actionId: string;
  sessionId: string;
  approved: boolean;
}> = [];

vi.mock("../api", () => ({
  streamChat: (
    _query: string,
    _perms: string[],
    _sessionId: string,
    callbacks: StreamCallbacks,
  ) => {
    lastCallbacks = callbacks;
    lastController = new AbortController();
    return lastController;
  },
  confirmAction: (actionId: string, sessionId: string, approved: boolean) => {
    confirmActionCalls.push({ actionId, sessionId, approved });
    return Promise.resolve({
      status: approved ? "executed" : "rejected",
      tool_name: "send_email",
      output: 'Email sent. (simulated)',
      simulated: true,
    });
  },
}));

describe("useChat: never-stuck invariant", () => {
  beforeEach(() => {
    lastCallbacks = null;
    lastController = null;
    confirmActionCalls = [];
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it("starts in idle state", () => {
    const { result } = renderHook(() => useChat());
    expect(result.current.state.status).toBe("idle");
    expect(result.current.state.messages).toHaveLength(0);
  });

  it("exposes a stable sessionId", () => {
    const { result, rerender } = renderHook(() => useChat());
    const id1 = result.current.sessionId;
    rerender();
    expect(result.current.sessionId).toBe(id1);
  });

  it("transitions to streaming when a message is sent", () => {
    const { result } = renderHook(() => useChat());

    act(() => {
      result.current.sendMessage("test question");
    });

    expect(result.current.state.status).toBe("streaming");
    expect(result.current.state.messages).toHaveLength(2); // user + assistant
  });

  it("returns to idle after successful completion", () => {
    const { result } = renderHook(() => useChat());

    act(() => {
      result.current.sendMessage("test question");
    });

    expect(result.current.state.status).toBe("streaming");

    // Simulate tokens arriving
    act(() => {
      lastCallbacks!.onToken("Hello ");
      lastCallbacks!.onToken("world.");
    });

    // Simulate completion
    act(() => {
      lastCallbacks!.onDone();
    });

    expect(result.current.state.status).toBe("idle");
  });

  it("returns to idle after cancel with no stale messages", () => {
    const { result } = renderHook(() => useChat());

    act(() => {
      result.current.sendMessage("test question");
    });

    expect(result.current.state.status).toBe("streaming");
    expect(result.current.state.messages).toHaveLength(2);

    act(() => {
      result.current.cancelStream();
    });

    expect(result.current.state.status).toBe("idle");
    // Cancel removes the in-flight user + assistant pair
    expect(result.current.state.messages).toHaveLength(0);
  });

  it("cancel does not resurface a stale query on next send", () => {
    const { result } = renderHook(() => useChat());

    // Send first question, then cancel
    act(() => {
      result.current.sendMessage("who won");
    });
    act(() => {
      result.current.cancelStream();
    });

    expect(result.current.state.status).toBe("idle");
    expect(result.current.state.messages).toHaveLength(0);

    // Send a new question
    act(() => {
      result.current.sendMessage("PTO policy");
    });

    // Only the new question should appear, not "who won"
    expect(result.current.state.messages).toHaveLength(2);
    expect(result.current.state.messages[0].content).toBe("PTO policy");
    expect(result.current.state.messages[0].role).toBe("user");
  });

  it("transitions to error state on error, not stuck", () => {
    const { result } = renderHook(() => useChat());

    act(() => {
      result.current.sendMessage("test question");
    });

    act(() => {
      lastCallbacks!.onError("Connection refused");
      lastCallbacks!.onDone();
    });

    expect(result.current.state.status).toBe("error");
    expect(result.current.state.errorMessage).toBe("Connection refused");
  });

  it("error state returns to idle via clearError", () => {
    const { result } = renderHook(() => useChat());

    act(() => {
      result.current.sendMessage("test question");
    });

    act(() => {
      lastCallbacks!.onError("Connection refused");
      lastCallbacks!.onDone();
    });

    expect(result.current.state.status).toBe("error");

    act(() => {
      result.current.clearError();
    });

    expect(result.current.state.status).toBe("idle");
    expect(result.current.state.errorMessage).toBeNull();
  });

  it("error state returns to streaming via retry", async () => {
    const { result } = renderHook(() => useChat());

    act(() => {
      result.current.sendMessage("test question");
    });

    act(() => {
      lastCallbacks!.onError("timeout");
      lastCallbacks!.onDone();
    });

    expect(result.current.state.status).toBe("error");

    // Retry re-sends the same query
    act(() => {
      result.current.retry();
    });

    // Wait for the setTimeout in retry
    await act(async () => {
      await new Promise((r) => setTimeout(r, 10));
    });

    expect(result.current.state.status).toBe("streaming");
  });

  it("accumulates tokens in the assistant message", () => {
    const { result } = renderHook(() => useChat());

    act(() => {
      result.current.sendMessage("test");
    });

    act(() => {
      lastCallbacks!.onToken("A");
      lastCallbacks!.onToken("B");
      lastCallbacks!.onToken("C");
    });

    const assistantMsg = result.current.state.messages[1];
    expect(assistantMsg.content).toBe("ABC");
    expect(assistantMsg.role).toBe("assistant");
  });

  it("handles refused response correctly", () => {
    const { result } = renderHook(() => useChat());

    act(() => {
      result.current.sendMessage("What is the weather?");
    });

    act(() => {
      lastCallbacks!.onRefused("I don't have information about that.");
      lastCallbacks!.onDone();
    });

    expect(result.current.state.status).toBe("idle");
    const assistantMsg = result.current.state.messages[1];
    expect(assistantMsg.refused).toBe(true);
    expect(assistantMsg.content).toBe(
      "I don't have information about that.",
    );
  });

  it("attaches citations from the citations event", () => {
    const { result } = renderHook(() => useChat());

    act(() => {
      result.current.sendMessage("PTO policy");
    });

    const mockCitations = [
      {
        doc_id: "handbook-001",
        doc_name: "Employee Handbook",
        section_path: ["PTO Policy"],
        char_start: 100,
        char_end: 200,
        snippet: "10 days per year...",
      },
    ];

    act(() => {
      lastCallbacks!.onToken("You get 10 days.");
      lastCallbacks!.onCitations(mockCitations);
      lastCallbacks!.onDone();
    });

    expect(result.current.state.status).toBe("idle");
    const assistantMsg = result.current.state.messages[1];
    expect(assistantMsg.citations).toHaveLength(1);
    expect(assistantMsg.citations[0].doc_id).toBe("handbook-001");
  });
});

describe("useChat: confirmation flow", () => {
  beforeEach(() => {
    lastCallbacks = null;
    lastController = null;
    confirmActionCalls = [];
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it("transitions to awaiting_confirmation on confirm_action event", () => {
    const { result } = renderHook(() => useChat());

    act(() => {
      result.current.sendMessage("send an email");
    });

    act(() => {
      lastCallbacks!.onConfirmAction({
        actionId: "uuid-123",
        toolName: "send_email",
        arguments: { to: "a@b.com" },
      });
      lastCallbacks!.onDone();
    });

    expect(result.current.state.status).toBe("awaiting_confirmation");
    const msg = result.current.state.messages[1];
    expect(msg.pendingConfirmation).not.toBeNull();
    expect(msg.pendingConfirmation!.actionId).toBe("uuid-123");
    expect(msg.pendingConfirmation!.toolName).toBe("send_email");
  });

  it("approveAction calls confirmAction and returns to idle", async () => {
    const { result } = renderHook(() => useChat());

    act(() => {
      result.current.sendMessage("send an email");
    });

    act(() => {
      lastCallbacks!.onConfirmAction({
        actionId: "uuid-123",
        toolName: "send_email",
        arguments: { to: "a@b.com" },
      });
      lastCallbacks!.onDone();
    });

    expect(result.current.state.status).toBe("awaiting_confirmation");

    await act(async () => {
      result.current.approveAction("uuid-123");
      await new Promise((r) => setTimeout(r, 10));
    });

    expect(confirmActionCalls).toHaveLength(1);
    expect(confirmActionCalls[0].approved).toBe(true);
    expect(result.current.state.status).toBe("idle");
    // Pending confirmation is cleared
    const msg = result.current.state.messages[1];
    expect(msg.pendingConfirmation).toBeNull();
  });

  it("rejectAction calls confirmAction with approved=false", async () => {
    const { result } = renderHook(() => useChat());

    act(() => {
      result.current.sendMessage("send an email");
    });

    act(() => {
      lastCallbacks!.onConfirmAction({
        actionId: "uuid-456",
        toolName: "send_email",
        arguments: { to: "a@b.com" },
      });
      lastCallbacks!.onDone();
    });

    await act(async () => {
      result.current.rejectAction("uuid-456");
      await new Promise((r) => setTimeout(r, 10));
    });

    expect(confirmActionCalls).toHaveLength(1);
    expect(confirmActionCalls[0].approved).toBe(false);
    expect(result.current.state.status).toBe("idle");
  });
});
