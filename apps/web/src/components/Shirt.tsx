// A plain generated shirt in the team's colour (see teamStyle.ts).
export default function Shirt({ colour, size = 44, label }: { colour: string; size?: number; label?: string }) {
  return (
    <svg width={size} height={size} viewBox="0 0 48 48" role={label ? 'img' : undefined} aria-label={label}
      aria-hidden={label ? undefined : true}>
      <path d="M16 6 L8 10 L3 20 L10 24 L12 20 L12 43 L36 43 L36 20 L38 24 L45 20 L40 10 L32 6 C30 10 18 10 16 6 Z"
        fill={colour} stroke="rgba(0,0,0,0.35)" strokeWidth="1.2" strokeLinejoin="round" />
      <path d="M16 6 C18 10 30 10 32 6" fill="none" stroke="rgba(255,255,255,0.7)" strokeWidth="1.6" />
    </svg>
  )
}
