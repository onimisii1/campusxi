import type { ReactNode } from 'react'

/** A feature that's built but not switched on yet, or has no data yet: shown, not hidden. */
export default function ComingSoon({ icon = '✨', title, children }: { icon?: string; title: string; children?: ReactNode }) {
  return (
    <div className="soon" role="note">
      <span className="soon-icon" aria-hidden>{icon}</span>
      <span>
        <strong>{title}</strong><span className="soon-badge">Soon</span>
        {children && <span className="muted small block">{children}</span>}
      </span>
    </div>
  )
}

export function SoonBadge() {
  return <span className="soon-badge">Soon</span>
}
