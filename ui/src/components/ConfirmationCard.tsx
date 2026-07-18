import type { PendingConfirmation } from "../types";

const TOOL_LABELS: Record<string, string> = {
  send_email: "Send email",
  file_ticket: "File ticket",
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
    <div className={`conf-card${isExpired ? " expired" : ""}`}>
      <div className="conf-header">
        <span>
          {isExpired ? "Action expired" : `${label} \u2014 requires approval`}
        </span>
        <span className="sim-tag">(simulated)</span>
      </div>
      <div className="conf-body">
        {Object.entries(args).map(([key, value]) => (
          <div key={key} className="conf-kv">
            <span className="k">{key}</span>
            <span>{String(value)}</span>
          </div>
        ))}
      </div>
      {!isExpired && (
        <div className="conf-btns">
          <button
            className="cb ok"
            onClick={() => onApprove(pending.actionId)}
            disabled={isDisabled}
          >
            Approve
          </button>
          <button
            className="cb no"
            onClick={() => onReject(pending.actionId)}
            disabled={isDisabled}
          >
            Reject
          </button>
        </div>
      )}
    </div>
  );
}
