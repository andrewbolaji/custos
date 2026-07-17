/**
 * Unit tests for the useChat hook state machine.
 *
 * Tests the "never stuck" invariant: every transition from streaming,
 * error, cancel, or completion returns the UI to a state where the user
 * can send another message (status === "idle").
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
}));

describe("useChat: never-stuck invariant", () => {
  beforeEach(() => {
    lastCallbacks = null;
    lastController = null;
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it("starts in idle state", () => {
    const { result } = renderHook(() => useChat());
    expect(result.current.state.status).toBe("idle");
    expect(result.current.state.messages).toHaveLength(0);
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
    // User can send another message (idle state)
  });

  it("returns to idle after cancel", () => {
    const { result } = renderHook(() => useChat());

    act(() => {
      result.current.sendMessage("test question");
    });

    expect(result.current.state.status).toBe("streaming");

    act(() => {
      result.current.cancelStream();
    });

    expect(result.current.state.status).toBe("idle");
    // User can send another message (idle state)
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
    // Even in error, user can still interact (retry, dismiss, new message)
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
    // User can send another message (idle state)
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
    // The retry is in progress; after completion it will return to idle
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
