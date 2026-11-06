/** Placeholder blocks while a page loads, instead of a bare "Loading…". */
export default function Skeleton({ hero = false, rows = 3 }: { hero?: boolean; rows?: number }) {
  return (
    <div aria-busy="true" aria-label="Loading">
      {hero && <div className="skeleton hero-skel" />}
      {Array.from({ length: rows }, (_, i) => <div key={i} className="skeleton row-skel" />)}
    </div>
  )
}
