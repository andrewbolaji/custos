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
    <form className="chat-input-form" onSubmit={handleSubmit}>
      <textarea
        className="chat-input"
        value={input}
        onChange={(e) => setInput(e.target.value)}
        onKeyDown={handleKeyDown}
        placeholder={isStreaming ? "Waiting for response..." : "Ask a question about the documents..."}
        disabled={isStreaming}
        rows={1}
        aria-label="Chat message input"
      />
      {isStreaming ? (
        <button
          type="button"
          className="btn btn-cancel"
          onClick={onCancel}
          aria-label="Cancel response"
        >
          Cancel
        </button>
      ) : (
        <button
          type="submit"
          className="btn btn-send"
          disabled={!canSend}
          aria-label="Send message"
        >
          Send
        </button>
      )}
    </form>
  );
}
