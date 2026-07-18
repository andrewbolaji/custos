import { useCallback, useEffect, useRef, useState } from "react";

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
  const [following, setFollowing] = useState(true);
  const lastScrollTopRef = useRef(0);
  const programmaticScrollRef = useRef(false);
  const prevUserCountRef = useRef(
    messages.filter((m) => m.role === "user").length,
  );

  // Detect genuine user scroll-up by tracking scroll DIRECTION.
  const handleScroll = useCallback(() => {
    const el = scrollRef.current;
    if (!el) return;

    const current = el.scrollTop;
    const prev = lastScrollTopRef.current;
    lastScrollTopRef.current = current;

    if (programmaticScrollRef.current) {
      programmaticScrollRef.current = false;
      return;
    }

    // User scrolled UP: genuine upward direction
    if (current < prev - 2) {
      setFollowing(false);
    }

    // User returned near bottom: resume following
    const atBottom = el.scrollHeight - current - el.clientHeight < 80;
    if (atBottom && !following) {
      setFollowing(true);
    }
  }, [following]);

  // Wheel and touchmove are explicit user intent
  const handleUserIntent = useCallback(() => {
    const el = scrollRef.current;
    if (!el) return;
    const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
    if (!atBottom) {
      setFollowing(false);
    }
  }, []);

  // Reset following when a NEW USER MESSAGE is added.
  // Track user message count rather than inspecting the last element,
  // because sendMessage appends both a user and an assistant placeholder
  // in one update (so messages[last] is always the assistant).
  useEffect(() => {
    const userCount = messages.filter((m) => m.role === "user").length;
    if (userCount > prevUserCountRef.current) {
      setFollowing(true);
    }
    prevUserCountRef.current = userCount;
  }, [messages.length]);

  // Follow bottom while following is true
  useEffect(() => {
    if (!following) return;
    const el = scrollRef.current;
    if (!el) return;

    if (status === "streaming") {
      programmaticScrollRef.current = true;
      el.scrollTop = el.scrollHeight;
    } else {
      endRef.current?.scrollIntoView({ behavior: "smooth" });
    }
  }, [messages, messages[messages.length - 1]?.content, status, following]);

  const jumpToLatest = useCallback(() => {
    setFollowing(true);
    const el = scrollRef.current;
    if (el) {
      programmaticScrollRef.current = true;
      el.scrollTop = el.scrollHeight;
    }
  }, []);

  return (
    <div
      className="message-list-scroll"
      ref={scrollRef}
      onScroll={handleScroll}
      onWheel={handleUserIntent}
      onTouchMove={handleUserIntent}
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
      {!following && (
        <button
          className="jump-btn"
          onClick={jumpToLatest}
          aria-label="Jump to latest"
        >
          Jump to latest
        </button>
      )}
    </div>
  );
}
