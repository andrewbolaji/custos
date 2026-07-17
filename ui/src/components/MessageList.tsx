import { useEffect, useRef } from "react";

import type { ChatStatus, Message as MessageType } from "../types";

import { Message } from "./Message";

interface MessageListProps {
  messages: MessageType[];
  status: ChatStatus;
}

export function MessageList({ messages, status }: MessageListProps) {
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
        />
      ))}
      <div ref={endRef} />
    </div>
  );
}
