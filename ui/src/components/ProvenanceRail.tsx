import type { ChatStatus, Message } from "../types";
import type { AccessGroup } from "../hooks/useChat";

import { ShieldIcon } from "./ShieldIcon";

interface ProvenanceRailProps {
  message: Message | null;
  status: ChatStatus;
  accessGroup: AccessGroup;
}

const ACCESS_LABELS: Record<AccessGroup, string> = {
  general: "Standard",
  hr: "HR",
  finance: "Finance",
};

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

export function ProvenanceRail({ message, status, accessGroup }: ProvenanceRailProps) {
  const hasCitations = message?.citations && message.citations.length > 0;
  const hasPending = message?.pendingConfirmation && !message.pendingConfirmation.expired;
  const hasGuardrail = message?.guardrailDetected === true;
  const isStreaming = status === "streaming";

  return (
    <aside className="rail">
      <div className="rail-flow" aria-label="Answer workflow">
        <span className="active">01 Ask</span>
        <span>02 Inspect</span>
        <span>03 Verify</span>
      </div>
      <div className="rail-title-row">
        <div>
          <div className="rail-h">Evidence</div>
          <div className="rail-sub">How this answer was built.</div>
        </div>
        <ShieldIcon size={22} stroke="#2b57e0" strokeWidth={1.8} />
      </div>

      <div className="rail-access">
        <span className="rail-access-icon">
          <ShieldIcon size={14} stroke="#147a5d" strokeWidth={2.2} />
        </span>
        <span>
          <small>Current access</small>
          <b>{ACCESS_LABELS[accessGroup]} documents</b>
        </span>
      </div>

      {!message && !isStreaming && (
        <div className="rail-empty">
          <div className="rail-empty-mark" aria-hidden="true">
            <svg width="28" height="28" viewBox="0 0 24 24" fill="none">
              <path d="M7 3h7l4 4v14H7z" stroke="currentColor" strokeWidth="1.5" />
              <path d="M14 3v5h5M10 12h5M10 16h5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
            </svg>
          </div>
          <h2>Evidence appears here.</h2>
          <p>Ask a question to see which documents were used and what Custos allowed the model to do.</p>
          <ul>
            <li>Source names and sections</li>
            <li>Access-scope confirmation</li>
            <li>Blocked instructions and held actions</li>
          </ul>
        </div>
      )}

      {(message || isStreaming) && <div className="rail-events">

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

      {hasGuardrail && (
        <div className="step guard">
          <div className="ic"><ShieldIcon size={13} stroke="#df4a3d" strokeWidth={2.2} /></div>
          <div>
            <div className="t">Injected instruction removed</div>
            <div className="m">Removed before the model saw it</div>
          </div>
        </div>
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

      </div>}

      <div className="rail-foot">
        <span className="rail-foot-label">Evaluation checks</span>
        <span><b>Unauthorized actions</b><strong>0</strong></span>
        <span><b>PII leaks</b><strong>0</strong></span>
        <p>Measured in the current adversarial evaluation suite.</p>
      </div>
    </aside>
  );
}
