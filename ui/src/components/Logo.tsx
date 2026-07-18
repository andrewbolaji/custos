/**
 * Custos brand mark ("Chief"): heraldic shield with amber chief band
 * and two white message lines. Two variants:
 * - full: shield + chief + message lines (header, welcome, avatar)
 * - small: shield + chief only (favicon, anything under ~20px)
 */

interface LogoProps {
  size?: number;
  variant?: "full" | "small";
}

export function Logo({ size = 30, variant = "full" }: LogoProps) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      aria-hidden="true"
    >
      <path
        d="M4.5 3.2H19.5a1.3 1.3 0 0 1 1.3 1.3v7.1c0 4.9-3.8 8.3-8.8 10-5-1.7-8.8-5.1-8.8-10V4.5a1.3 1.3 0 0 1 1.3-1.3z"
        fill="#2b57e0"
      />
      <path
        d="M4.5 3.2H19.5a1.3 1.3 0 0 1 1.3 1.3V8.4H3.2V4.5a1.3 1.3 0 0 1 1.3-1.3z"
        fill="#f0b429"
      />
      {variant === "full" && (
        <>
          <rect x="7.6" y="11.4" width="8.8" height="1.8" rx=".9" fill="#fff" />
          <rect x="7.6" y="15" width="5.6" height="1.8" rx=".9" fill="#fff" />
        </>
      )}
    </svg>
  );
}
