import { useRef, useState, type KeyboardEvent } from "react";

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

  // Guard against the cancel-to-send race: after cancel, block sends
  // for a short window so a pointer event that started on Cancel
  // cannot activate a freshly-mounted Send button.
  const justCancelledRef = useRef(false);

  function handleSend() {
    if (!canSend || justCancelledRef.current) return;
    onSend(input.trim());
    setInput("");
  }

  function handleCancel() {
    justCancelledRef.current = true;
    onCancel();
    // Clear the guard after the current event cycle completes
    setTimeout(() => {
      justCancelledRef.current = false;
    }, 100);
  }

  function handleKeyDown(e: KeyboardEvent) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  }

  return (
    <div className="composer">
      <input
        value={input}
        onChange={(e) => setInput(e.target.value)}
        onKeyDown={handleKeyDown}
        placeholder={isStreaming ? "Type your next question\u2026" : "Ask about the documents\u2026"}
        aria-label="Chat message input"
      />
      {isStreaming ? (
        <button
          key="cancel"
          type="button"
          className="cancel-btn"
          onClick={handleCancel}
          aria-label="Cancel response"
        >
          Cancel
        </button>
      ) : (
        <button
          key="send"
          type="button"
          className="send-btn"
          disabled={!canSend}
          onClick={handleSend}
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
    </div>
  );
}
