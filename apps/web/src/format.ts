export function kickoff(iso: string): string {
  return new Date(iso).toLocaleString(undefined, { weekday: 'short', day: 'numeric', month: 'short',
    hour: '2-digit', minute: '2-digit' })
}

/** "Fri 6 Nov at 19:30" */
export function deadline(iso: string): string {
  const d = new Date(iso)
  const day = d.toLocaleDateString(undefined, { weekday: 'short', day: 'numeric', month: 'short' })
  const time = d.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' })
  return `${day} at ${time}`
}

export function countdown(seconds: number): string {
  if (seconds <= 0) return 'Locked'
  const d = Math.floor(seconds / 86400)
  const h = Math.floor((seconds % 86400) / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  if (d > 0) return `Locks in ${d}d ${h}h`
  if (h > 0) return `Locks in ${h}h ${m}m`
  return `Locks in ${m}m`
}

export function points(value: number | string | null | undefined): string {
  if (value === null || value === undefined) return '–'
  const n = Number(value)
  return Number.isInteger(n) ? String(n) : n.toFixed(1)
}

export function statusLabel(status: string): string {
  return ({ lineup_out: 'Line-up out', final_pending: 'Awaiting result', confirmed: 'Final' } as Record<string, string>)[
    status] ?? status.charAt(0).toUpperCase() + status.slice(1)
}
