import { Logo } from "./Logo";
import { ShieldIcon } from "./ShieldIcon";

export function Header() {
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
        <span className="pill scoped" title="This answer used only documents your access level is permitted to see.">
          <ShieldIcon size={11} stroke="#11996b" strokeWidth={2.4} />
          Access: Standard
        </span>
      </div>
    </div>
  );
}
