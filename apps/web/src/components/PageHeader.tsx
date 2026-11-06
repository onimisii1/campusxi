export default function PageHeader({ title, back, subtitle }: { title: string; back: string; subtitle?: string }) {
  return (
    <div className="page-header">
      <a className="round-btn" href={back} aria-label="Back">←</a>
      <div>
        <h2>{title}</h2>
        {subtitle && <p className="muted small">{subtitle}</p>}
      </div>
    </div>
  )
}
