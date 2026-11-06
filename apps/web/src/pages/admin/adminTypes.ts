export type AdminMatch = {
  id: string
  code: string | null
  stage: string
  status: string
  scheduled_start: string
  kicked_off_at: string | null
  venue: string | null
  home_team: string
  away_team: string
  home_score: number | null
  away_score: number | null
  walkover: boolean | null
  imported: boolean | null
  starters: number
  scorers: number
  submissions: number
}

export type AdminMatches = {
  tournament: { id: string; name: string; sport: string; status: string; match_minutes: number }
  now: string
  matches: AdminMatch[]
}

export const STATUS_LABEL: Record<string, string> = {
  scheduled: 'Scheduled', lineup_out: 'Line-up out', live: 'Live', final_pending: 'Awaiting result',
  confirmed: 'Done', abandoned: 'Abandoned', postponed: 'Postponed',
}

/** What the admin still has to do for a match, in order. */
export function nextStep(m: AdminMatch): string | null {
  if (m.status === 'confirmed' || m.status === 'abandoned') return null
  if (m.status === 'postponed') return 'Set a new date'
  if (m.scorers === 0) return 'Assign scorers'
  if (m.starters === 0) return 'Publish line-up'
  if (!m.kicked_off_at && m.status !== 'live') return 'Kick off'
  if (m.status === 'final_pending') return 'Confirm result'
  return 'Scoring'
}

export function matchLabel(m: { code: string | null; home_team: string; away_team: string }): string {
  return `${m.code ? `${m.code} · ` : ''}${m.home_team} v ${m.away_team}`
}
