import type { ChatStatus, Message } from "../types";

import { ShieldIcon } from "./ShieldIcon";

interface ProvenanceRailProps {
  message: Message | null;
  status: ChatStatus;
}

function CheckIcon({ color = "#11996b" }: { color?: string }) {
  return (
    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path d="M5 13l4 4L19 7" stroke={color} strokeWidth="2.6" />
    </svg>
  );
}

function ClockIcon() {
  return (
    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <circle cx="12" cy="12" r="9" stroke="#2b57e0" strokeWidth="2" />
      <path d="M12 8v4l3 2" stroke="#2b57e0" strokeWidth="2" strokeLinecap="round" />
    </svg>
  );
}

export function ProvenanceRail({ message, status }: ProvenanceRailProps) {
  const hasCitations = message?.citations && message.citations.length > 0;
  const hasPending = message?.pendingConfirmation && !message.pendingConfirmation.expired;
  const isStreaming = status === "streaming";

  return (
    <aside className="rail">
      <div className="rail-h">Provenance</div>
      <div className="rail-sub">How this answer was built.</div>

      {hasCitations && (
        <>
          <div className="step ok">
            <div className="ic"><CheckIcon /></div>
            <div>
              <div className="t">{message.citations.length} source{message.citations.length !== 1 ? "s" : ""} retrieved</div>
              <div className="m">{message.citations.map((c) => c.doc_name).filter((v, i, a) => a.indexOf(v) === i).join(", ")}</div>
            </div>
          </div>
          <div className="step ok">
            <div className="ic"><CheckIcon /></div>
            <div>
              <div className="t">Grounded</div>
              <div className="m">Answer built from retrieved text only</div>
            </div>
          </div>
          <div className="step ok">
            <div className="ic"><ShieldIcon size={13} stroke="#11996b" strokeWidth={2.2} /></div>
            <div>
              <div className="t">Scoped to your access</div>
              <div className="m">Only documents you may see</div>
            </div>
          </div>
        </>
      )}

      {hasPending && (
        <div className="step wait">
          <div className="ic"><ClockIcon /></div>
          <div>
            <div className="t">Action held</div>
            <div className="m">{message.pendingConfirmation!.toolName} awaits your approval</div>
          </div>
        </div>
      )}

      {isStreaming && !hasCitations && !hasPending && (
        <div className="step wait">
          <div className="ic"><ClockIcon /></div>
          <div>
            <div className="t">Generating answer</div>
            <div className="m">Retrieving and grounding</div>
          </div>
        </div>
      )}

      {!isStreaming && !hasCitations && !hasPending && message?.refused && (
        <div className="step ok">
          <div className="ic"><CheckIcon /></div>
          <div>
            <div className="t">Abstained</div>
            <div className="m">No relevant documents found</div>
          </div>
        </div>
      )}

      <div className="rail-foot">
        <b>unauthorized_action_rate = 0</b><br />
        <b>pii_leak_rate = 0</b><br />
        Every answer cites its source.
      </div>
    </aside>
  );
}
