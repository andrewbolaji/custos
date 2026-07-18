import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

// Disable GFM autolink: answer text derives from untrusted documents,
// so emails/URLs must render as plain text, not clickable links.
const gfmOptions = { singleTilde: false };

import type { Message as MessageType } from "../types";

import { Citation } from "./Citation";
import { ConfirmationCard } from "./ConfirmationCard";
import { ShieldIcon } from "./ShieldIcon";

const PERMISSION_LABELS: Record<string, string> = {
  general: "Standard",
  hr: "HR",
  finance: "Finance",
  admin: "Admin",
};

function getAccessLabel(permissions?: string[]): string {
  if (!permissions || permissions.length === 0) return "Standard";
  // Use the highest-privilege permission for the label
  for (const p of ["admin", "finance", "hr"]) {
    if (permissions.includes(p)) return PERMISSION_LABELS[p] ?? p;
  }
  return PERMISSION_LABELS[permissions[0]] ?? "Standard";
}

const TOOL_LABELS: Record<string, string> = {
  search_documents: "Searched documents",
  summarize_section: "Summarized section",
  send_email: "Send email",
  file_ticket: "File ticket",
};

interface MessageProps {
  message: MessageType;
  isStreaming: boolean;
  onApprove?: (actionId: string) => void;
  onReject?: (actionId: string) => void;
}

export function Message({ message, isStreaming, onApprove, onReject }: MessageProps) {
  const isUser = message.role === "user";

  if (isUser) {
    return (
      <div className="row-user">
        <div className="bubble-user">{message.content}</div>
      </div>
    );
  }

  return (
    <div className="row-assistant">
      <div className="avatar">
        <ShieldIcon size={15} />
      </div>
      <div className="bubble-assistant">
        <div className="md-content">
          <ReactMarkdown
            remarkPlugins={[[remarkGfm, gfmOptions]]}
            components={{
              // Render links as plain text (no clickable links from untrusted content)
              a: ({ children }) => <span>{children}</span>,
            }}
          >
            {message.content}
          </ReactMarkdown>
          {isStreaming && <span className="typing-cursor" />}
        </div>
        {message.refused && (
          <p className="message-refused">
            The assistant could not find relevant information in the available documents.
          </p>
        )}
        {message.toolUses.length > 0 && (
          <div className="tool-uses">
            {message.toolUses.map((tu, i) => (
              <span key={i} className="tool-use-badge">
                {TOOL_LABELS[tu.tool_name] ?? tu.tool_name}
                {tu.simulated && " (simulated)"}
              </span>
            ))}
          </div>
        )}
        {message.citations.length > 0 && !message.pendingConfirmation && (
          <div className="src-row">
            {message.citations.map((cit, i) => (
              <Citation key={`${cit.doc_id}-${cit.char_start}`} citation={cit} index={i} />
            ))}
            <span className="scoped-tag" tabIndex={0}>
              <ShieldIcon size={11} stroke="#11996b" strokeWidth={2.4} />
              Access: {getAccessLabel(message.permissions)}
              <span className="tooltip">
                This answer used only documents your access level is permitted to see.
              </span>
            </span>
          </div>
        )}
        {message.pendingConfirmation && onApprove && onReject && (
          <ConfirmationCard
            pending={message.pendingConfirmation}
            onApprove={onApprove}
            onReject={onReject}
            disabled={isStreaming}
          />
        )}
      </div>
    </div>
  );
}
