import { useEffect, useRef } from "react";

import type { ChatStatus, Message as MessageType } from "../types";

import { Message } from "./Message";

interface MessageListProps {
  messages: MessageType[];
  status: ChatStatus;
  onApprove?: (actionId: string) => void;
  onReject?: (actionId: string) => void;
}

export function MessageList({ messages, status, onApprove, onReject }: MessageListProps) {
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, messages[messages.length - 1]?.content]);

  return (
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
  );
}
