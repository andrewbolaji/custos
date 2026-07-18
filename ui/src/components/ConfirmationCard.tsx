import type { PendingConfirmation } from "../types";

const TOOL_LABELS: Record<string, string> = {
  send_email: "Send Email",
  file_ticket: "File Ticket",
};

interface ConfirmationCardProps {
  pending: PendingConfirmation;
  onApprove: (actionId: string) => void;
  onReject: (actionId: string) => void;
  disabled?: boolean;
}

export function ConfirmationCard({
  pending,
  onApprove,
  onReject,
  disabled = false,
}: ConfirmationCardProps) {
  const label = TOOL_LABELS[pending.toolName] ?? pending.toolName;
  const args = pending.arguments;
  const isExpired = pending.expired === true;
  const isDisabled = disabled || isExpired;

  return (
    <div
      style={{
        border: `1px solid ${isExpired ? "#d1d5db" : "#b45309"}`,
        borderRadius: "8px",
        padding: "12px 16px",
        margin: "8px 0",
        backgroundColor: isExpired ? "#f3f4f6" : "#fffbeb",
        color: "#1c1917",
        opacity: isExpired ? 0.6 : 1,
      }}
    >
      <p style={{ margin: "0 0 8px", fontWeight: 600, color: isExpired ? "#6b7280" : "#78350f" }}>
        {isExpired ? "Action expired" : "Action requires your approval"}
      </p>
      <p style={{ margin: "0 0 4px", color: "#1c1917" }}>
        <strong>{label}</strong> (simulated)
      </p>
      {Object.entries(args).length > 0 && (
        <ul style={{ margin: "4px 0 12px", paddingLeft: "20px", color: "#292524" }}>
          {Object.entries(args).map(([key, value]) => (
            <li key={key}>
              <strong>{key}:</strong> {String(value)}
            </li>
          ))}
        </ul>
      )}
      {!isExpired && (
        <div style={{ display: "flex", gap: "8px" }}>
          <button
            onClick={() => onApprove(pending.actionId)}
            disabled={isDisabled}
            style={{
              padding: "6px 16px",
              borderRadius: "4px",
              border: "1px solid #16a34a",
              backgroundColor: "#16a34a",
              color: "white",
              cursor: isDisabled ? "not-allowed" : "pointer",
              opacity: isDisabled ? 0.5 : 1,
            }}
          >
            Approve
          </button>
          <button
            onClick={() => onReject(pending.actionId)}
            disabled={isDisabled}
            style={{
              padding: "6px 16px",
              borderRadius: "4px",
              border: "1px solid #dc2626",
              backgroundColor: "white",
              color: "#dc2626",
              cursor: isDisabled ? "not-allowed" : "pointer",
              opacity: isDisabled ? 0.5 : 1,
            }}
          >
            Reject
          </button>
        </div>
      )}
    </div>
  );
}
