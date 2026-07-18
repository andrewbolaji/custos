import { ShieldIcon } from "./ShieldIcon";

export function Header() {
  return (
    <div className="top-header">
      <div className="brand">
        <div className="logo">
          <ShieldIcon size={16} />
        </div>
        <div>
          <div className="brand-name">Custos</div>
          <div className="brand-tag">Private AI over your documents</div>
        </div>
      </div>
      <div className="header-pills">
        <span className="pill">
          <span className="dot" />
          general access
        </span>
        <span className="pill scoped" title="This answer used only documents your access level is permitted to see.">
          <ShieldIcon size={11} stroke="#11996b" strokeWidth={2.4} />
          Access: Standard
        </span>
      </div>
    </div>
  );
}
