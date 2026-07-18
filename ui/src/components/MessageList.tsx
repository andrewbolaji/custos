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
  const prevMsgCountRef = useRef(messages.length);

  // Detect user scroll-up: if the user scrolls away from the bottom,
  // stop auto-scrolling so controls aren't moving targets.
  const handleScroll = useCallback(() => {
    const el = scrollRef.current;
    if (!el) return;
    const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 60;
    userScrolledRef.current = !atBottom;
  }, []);

  // Re-enable auto-scroll when streaming stops
  useEffect(() => {
    if (status !== "streaming") {
      userScrolledRef.current = false;
    }
  }, [status]);

  // Auto-scroll: during streaming, set scrollTop directly (no animation
  // restart). For discrete jumps (new message added), use smooth scroll.
  useEffect(() => {
    if (userScrolledRef.current) return;
    const el = scrollRef.current;
    if (!el) return;

    const isNewMessage = messages.length !== prevMsgCountRef.current;
    prevMsgCountRef.current = messages.length;

    if (isNewMessage) {
      // Discrete jump: smooth scroll to bottom
      endRef.current?.scrollIntoView({ behavior: "smooth" });
    } else if (status === "streaming") {
      // During streaming: follow bottom directly (no animation restart)
      el.scrollTop = el.scrollHeight;
    }
  }, [messages, messages[messages.length - 1]?.content, status]);

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
