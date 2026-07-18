import { useCallback, useEffect, useRef } from "react";

import type { ChatStatus, Message as MessageType } from "../types";

import { Message } from "./Message";

interface MessageListProps {
  messages: MessageType[];
  status: ChatStatus;
  onApprove?: (actionId: string) => void;
  onReject?: (actionId: string) => void;
}

export function MessageList({ messages, status, onApprove, onReject }: MessageListProps) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const endRef = useRef<HTMLDivElement>(null);
  const userScrolledRef = useRef(false);

  // Detect user scroll-up: if the user scrolls away from the bottom,
  // stop auto-scrolling so controls aren't moving targets.
  const handleScroll = useCallback(() => {
    const el = scrollRef.current;
    if (!el) return;
    const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 60;
    userScrolledRef.current = !atBottom;
  }, []);

  // Re-enable auto-scroll when streaming stops (new answer complete)
  useEffect(() => {
    if (status !== "streaming") {
      userScrolledRef.current = false;
    }
  }, [status]);

  // Smooth auto-scroll during streaming (only if user hasn't scrolled up)
  useEffect(() => {
    if (!userScrolledRef.current) {
      endRef.current?.scrollIntoView({ behavior: "smooth" });
    }
  }, [messages, messages[messages.length - 1]?.content]);

  return (
    <div
      className="message-list-scroll"
      ref={scrollRef}
      onScroll={handleScroll}
    >
      <div className="message-list">
        {messages.map((msg) => (
          <Message
            key={msg.id}
            message={msg}
            isStreaming={
              status === "streaming" &&
              msg.role === "assistant" &&
              msg === messages[messages.length - 1]
            }
            onApprove={onApprove}
            onReject={onReject}
          />
        ))}
        <div ref={endRef} />
      </div>
    </div>
  );
}
