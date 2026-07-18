import type { AccessGroup } from "../hooks/useChat";

import { Logo } from "./Logo";
import { ShieldIcon } from "./ShieldIcon";

const GROUP_LABELS: Record<AccessGroup, string> = {
  general: "Standard",
  hr: "HR",
  finance: "Finance",
};

const GROUPS: AccessGroup[] = ["general", "hr", "finance"];

interface HeaderProps {
  accessGroup: AccessGroup;
  onAccessChange: (group: AccessGroup) => void;
}

export function Header({ accessGroup, onAccessChange }: HeaderProps) {
  return (
    <div className="top-header">
      <div className="brand">
        <Logo size={30} />
        <div>
          <div className="brand-name">Custos</div>
          <div className="brand-tag">Private AI over your documents</div>
        </div>
      </div>
      <div className="header-pills">
        <label className="access-switcher" title="Demo control: switch access group. Changing access starts a new conversation.">
          <ShieldIcon size={11} stroke="#11996b" strokeWidth={2.4} />
          <span className="access-label">Access:</span>
          <select
            className="access-select"
            value={accessGroup}
            onChange={(e) => onAccessChange(e.target.value as AccessGroup)}
          >
            {GROUPS.map((g) => (
              <option key={g} value={g}>{GROUP_LABELS[g]}</option>
            ))}
          </select>
        </label>
      </div>
    </div>
  );
}
