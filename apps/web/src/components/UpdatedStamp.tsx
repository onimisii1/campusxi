/** " · Updated 13:42" on live views, or a hint that the shown data is the last known copy. */
export default function UpdatedStamp({ at, stale }: { at: Date | null; stale: boolean }) {
  if (!at) return null
  const time = at.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' })
  return <span className={stale ? 'stale' : ''}> · {stale ? `Offline, last updated ${time}` : `Updated ${time}`}</span>
}
