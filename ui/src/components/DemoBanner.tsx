/**
 * Demo simplification notice. Honesty rule: we do not imply real auth exists.
 */
export function DemoBanner() {
  return (
    <div className="demo-banner">
      Demo mode: permissions are simulated. In production, access control is
      enforced via <b>authenticated identity</b>.
    </div>
  );
}
