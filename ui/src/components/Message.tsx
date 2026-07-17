import type { Message as MessageType } from "../types";

import { Citation } from "./Citation";
import { ConfirmationCard } from "./ConfirmationCard";

interface MessageProps {
  message: MessageType;
  isStreaming: boolean;
  onApprove?: (actionId: string) => void;
  onReject?: (actionId: string) => void;
}

export function Message({ message, isStreaming, onApprove, onReject }: MessageProps) {
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
        {message.toolUses.length > 0 && !isUser && (
          <div className="tool-uses">
            {message.toolUses.map((tu, i) => (
              <span key={i} className="tool-use-badge">
                {tu.tool_name}
                {tu.simulated && " (simulated)"}
              </span>
            ))}
          </div>
        )}
        {message.pendingConfirmation && !isUser && onApprove && onReject && (
          <ConfirmationCard
            pending={message.pendingConfirmation}
            onApprove={onApprove}
            onReject={onReject}
            disabled={isStreaming}
          />
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
