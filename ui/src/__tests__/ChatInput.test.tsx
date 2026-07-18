/**
 * Tests for the ChatInput component.
 * Verifies the cancel-to-send race condition is prevented and
 * that type-ahead text is preserved across cancel.
 */

import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ChatInput } from "../components/ChatInput";

describe("ChatInput", () => {
  it("preserves typed text when cancel is clicked", () => {
    const onSend = vi.fn();
    const onCancel = vi.fn();

    const { rerender } = render(
      <ChatInput status="streaming" onSend={onSend} onCancel={onCancel} />,
    );

    // Type into the input while streaming
    const input = screen.getByLabelText("Chat message input") as HTMLInputElement;
    fireEvent.change(input, { target: { value: "my next question" } });
    expect(input.value).toBe("my next question");

    // Click cancel
    fireEvent.click(screen.getByLabelText("Cancel response"));
    expect(onCancel).toHaveBeenCalledTimes(1);

    // Re-render with idle status (simulating cancel completing)
    rerender(
      <ChatInput status="idle" onSend={onSend} onCancel={onCancel} />,
    );

    // Typed text must still be in the input
    const inputAfter = screen.getByLabelText("Chat message input") as HTMLInputElement;
    expect(inputAfter.value).toBe("my next question");

    // No message should have been sent
    expect(onSend).not.toHaveBeenCalled();
  });

  it("does not send on cancel-to-send button swap", () => {
    const onSend = vi.fn();
    const onCancel = vi.fn();

    const { rerender } = render(
      <ChatInput status="streaming" onSend={onSend} onCancel={onCancel} />,
    );

    // Type text
    const input = screen.getByLabelText("Chat message input") as HTMLInputElement;
    fireEvent.change(input, { target: { value: "typed ahead" } });

    // Click cancel
    fireEvent.click(screen.getByLabelText("Cancel response"));

    // Immediately re-render as idle (simulating the status flip)
    rerender(
      <ChatInput status="idle" onSend={onSend} onCancel={onCancel} />,
    );

    // Click the Send button that just appeared
    const sendBtn = screen.getByLabelText("Send message");
    fireEvent.click(sendBtn);

    // The just-cancelled guard should block the send
    expect(onSend).not.toHaveBeenCalled();
  });
});
