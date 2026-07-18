import { useState, type FormEvent, type KeyboardEvent } from "react";

import type { ChatStatus } from "../types";

interface ChatInputProps {
  status: ChatStatus;
  onSend: (query: string) => void;
  onCancel: () => void;
}

export function ChatInput({ status, onSend, onCancel }: ChatInputProps) {
  const [input, setInput] = useState("");
  const isStreaming = status === "streaming";
  const canSend = input.trim().length > 0 && !isStreaming;

  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (!canSend) return;
    onSend(input.trim());
    setInput("");
  }

  function handleKeyDown(e: KeyboardEvent) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      if (canSend) {
        onSend(input.trim());
        setInput("");
      }
    }
  }

  return (
    <form className="composer" onSubmit={handleSubmit}>
      <input
        value={input}
        onChange={(e) => setInput(e.target.value)}
        onKeyDown={handleKeyDown}
        placeholder={isStreaming ? "Type your next question\u2026" : "Ask about the documents\u2026"}
        aria-label="Chat message input"
      />
      {isStreaming ? (
        <button
          type="button"
          className="cancel-btn"
          onClick={onCancel}
          aria-label="Cancel response"
        >
          Cancel
        </button>
      ) : (
        <button
          type="submit"
          className="send-btn"
          disabled={!canSend}
          aria-label="Send message"
        >
          Send
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" aria-hidden="true">
            <path
              d="M4 12h16M14 6l6 6-6 6"
              stroke="#fff"
              strokeWidth="2.2"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </svg>
        </button>
      )}
    </form>
  );
}
