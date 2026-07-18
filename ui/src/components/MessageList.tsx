import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";

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

  // Position-derived stick-to-bottom. Pure read on every scroll event:
  // no React state, no re-renders, no layout changes from scrolling.
  const stickToBottomRef = useRef(true);

  // React state for the jump button only, updated with change-guard
  // to avoid render churn from scroll events.
  const [showJump, setShowJump] = useState(false);

  // Track user message count to reset stick on new send.
  const prevUserCountRef = useRef(
    messages.filter((m) => m.role === "user").length,
  );

  const handleScroll = useCallback(() => {
    const el = scrollRef.current;
    if (!el) return;
    const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
    stickToBottomRef.current = atBottom;
    // Update jump button visibility only on actual change
    setShowJump((prev) => {
      const next = !atBottom;
      return prev === next ? prev : next;
    });
  }, []);

  // Reset stick when a new user message is added.
  useEffect(() => {
    const userCount = messages.filter((m) => m.role === "user").length;
    if (userCount > prevUserCountRef.current) {
      stickToBottomRef.current = true;
      setShowJump(false);
    }
    prevUserCountRef.current = userCount;
  }, [messages.length]);

  // Follow bottom on content updates. useLayoutEffect runs before
  // paint so there is no visible jump.
  useLayoutEffect(() => {
    if (!stickToBottomRef.current) return;
    const el = scrollRef.current;
    if (el) {
      el.scrollTop = el.scrollHeight;
    }
  }, [messages, messages[messages.length - 1]?.content]);

  const jumpToLatest = useCallback(() => {
    stickToBottomRef.current = true;
    setShowJump(false);
    const el = scrollRef.current;
    if (el) {
      el.scrollTop = el.scrollHeight;
    }
  }, []);

  return (
    <>
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
      {showJump && (
        <button
          className="jump-btn"
          onClick={jumpToLatest}
          aria-label="Jump to latest"
        >
          Jump to latest
        </button>
      )}
    </>
  );
}
