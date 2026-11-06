export type Contest = {
  id: string
  name: string
  prize_text: string | null
  entry_fee_kobo: number
  capacity: number
  entries: number
  spots_left: number
  team_cap: number
  status: string
  locked: boolean
  late_join: { until_minute: number; minute: number; entry_fee_kobo: number } | null
  my_entries: { entry_id: string; fantasy_team_id: string; label: string; final_rank: number | null }[]
}

export type TeamOption = { id: string; label: string }

export function naira(kobo: number): string {
  return `₦${(kobo / 100).toLocaleString()}`
}

export function feeLabel(c: Contest): string {
  const fee = c.late_join ? c.late_join.entry_fee_kobo : c.entry_fee_kobo
  return fee === 0 ? 'Free' : naira(fee)
}

/** Can this contest be joined right now (before kick-off, or in the late-join window)? */
export function joinable(c: Contest): boolean {
  return c.status === 'open' && c.spots_left > 0 && (!c.locked || c.late_join !== null)
}
