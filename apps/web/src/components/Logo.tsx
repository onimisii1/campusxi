/** The CampusXI mark: dark "XI" on a lime tile with a light top sheen (same art as public/icon.svg). */
export default function Logo({ size = 44 }: { size?: number }) {
  return (
    <svg className="logo-mark" width={size} height={size} viewBox="0 0 64 64" aria-hidden>
      <defs>
        <linearGradient id="cx-sheen" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#fff" stopOpacity="0.55" />
          <stop offset="0.5" stopColor="#fff" stopOpacity="0" />
        </linearGradient>
      </defs>
      <rect width="64" height="64" rx="18" fill="#cdf54a" />
      <rect width="64" height="64" rx="18" fill="url(#cx-sheen)" />
      <text x="32" y="43" textAnchor="middle" fontFamily="Poppins, Arial, sans-serif" fontSize="28" fontWeight="800"
        fontStyle="italic" fill="#11130e" letterSpacing="-1">XI</text>
    </svg>
  )
}
