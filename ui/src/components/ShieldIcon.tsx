interface ShieldIconProps {
  size?: number;
  stroke?: string;
  strokeWidth?: number;
}

export function ShieldIcon({
  size = 15,
  stroke = "#fff",
  strokeWidth = 2.2,
}: ShieldIconProps) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      aria-hidden="true"
    >
      <path
        d="M12 2l8 3v6c0 5-3.5 8.5-8 11-4.5-2.5-8-6-8-11V5l8-3z"
        stroke={stroke}
        strokeWidth={strokeWidth}
        strokeLinejoin="round"
      />
    </svg>
  );
}
