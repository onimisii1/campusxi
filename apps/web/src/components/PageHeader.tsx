import type { ReactNode } from 'react'

/** The design's screen header: round back button, centred title, round "more" button (the menu). */
export default function PageHeader({ title, back, subtitle, action }: {
  title: string; back: string; subtitle?: string; action?: ReactNode
}) {
  return (
    <div className="page-header">
      <a className="round-btn" href={back} aria-label="Back">
        <svg width="18" height="18" viewBox="0 0 24 24" aria-hidden><path d="M15 5l-7 7 7 7" fill="none"
          stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" /></svg>
      </a>
      <div className="page-title">
        <h2>{title}</h2>
        {subtitle && <p className="muted small">{subtitle}</p>}
      </div>
      {action ?? (
        <a className="round-btn" href="#/me" aria-label="Menu">
          <svg width="18" height="18" viewBox="0 0 24 24" aria-hidden><g fill="currentColor"><circle cx="12" cy="5" r="2" />
            <circle cx="12" cy="12" r="2" /><circle cx="12" cy="19" r="2" /></g></svg>
        </a>
      )}
    </div>
  )
}
