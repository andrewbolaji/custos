import type { Message as MessageType } from "../types";

import { Citation } from "./Citation";

interface MessageProps {
  message: MessageType;
  isStreaming: boolean;
}

export function Message({ message, isStreaming }: MessageProps) {
  const isUser = message.role === "user";

  return (
    <div className={`message ${isUser ? "message-user" : "message-assistant"}`}>
      <div className={`message-bubble ${isUser ? "bubble-user" : "bubble-assistant"}`}>
        <p className="message-text">
          {message.content}
          {isStreaming && !isUser && <span className="typing-cursor" />}
        </p>
        {message.refused && !isUser && (
          <p className="message-refused">
            The assistant could not find relevant information in the available documents.
          </p>
        )}
      </div>
      {message.citations.length > 0 && (
        <div className="citations-list">
          <p className="citations-header">Sources</p>
          {message.citations.map((cit, i) => (
            <Citation key={`${cit.doc_id}-${cit.char_start}`} citation={cit} index={i} />
          ))}
        </div>
      )}
    </div>
  );
}
