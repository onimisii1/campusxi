import { useState } from 'react'
import { ScoreCard, type MatchCardData } from '../components/MatchCard'
import PageHeader from '../components/PageHeader'
import Skeleton from '../components/Skeleton'
import { LIVE_REFRESH_MS, useApi } from '../useApi'

const SPORT_ICON: Record<string, string> = { football: '⚽', basketball: '🏀', volleyball: '🏐' }
const STATUS = { all: 'All', live: 'Live', upcoming: 'Up coming', results: 'Results' } as const
type Status = keyof typeof STATUS

const dayKey = (d: Date) => d.toDateString()

function weekOf(d: Date): Date[] {
  const start = new Date(d)
  start.setHours(0, 0, 0, 0)
  start.setDate(start.getDate() - start.getDay())          // Sunday
  return Array.from({ length: 7 }, (_, i) => new Date(start.getFullYear(), start.getMonth(), start.getDate() + i))
}

/** Design screen 2: search + filter, the week strip, league chips, joined live-score cards. */
export default function LiveScore() {
  const { data } = useApi<MatchCardData[]>('/matches', LIVE_REFRESH_MS)
  const [selected, setSelected] = useState<Date | null>(null)
  const [league, setLeague] = useState<string | null>(null)
  const [q, setQ] = useState('')
  const [filters, setFilters] = useState(false)
  const [status, setStatus] = useState<Status>('all')
  const [sport, setSport] = useState<string | null>(null)
  if (!data) return <section><PageHeader title="Live Score" back="#/" /><Skeleton rows={5} /></section>

  const matches = data.filter((m) => m.status !== 'abandoned')
  const live = matches.find((m) => m.status === 'live')
  const today = new Date()
  const hasToday = matches.some((m) => dayKey(new Date(m.scheduled_start)) === dayKey(today))
  const next = matches.find((m) => new Date(m.scheduled_start) >= today)
  const day = selected ?? (live ? new Date(live.scheduled_start) : hasToday ? today
    : next ? new Date(next.scheduled_start) : today)
  const week = weekOf(day)
  const matchDays = new Set(matches.map((m) => dayKey(new Date(m.scheduled_start))))
  const term = q.trim().toLowerCase()

  const ofDay = matches.filter((m) => term
    ? `${m.home_team.name} ${m.away_team.name} ${m.tournament}`.toLowerCase().includes(term)
    : dayKey(new Date(m.scheduled_start)) === dayKey(day))
  const leagues = [...new Map(ofDay.map((m) => [m.tournament_id, m])).values()]
  const shown = ofDay.filter((m) => (!league || m.tournament_id === league) && (!sport || m.sport === sport)
    && (status === 'all' || (status === 'live' && m.status === 'live')
      || (status === 'results' && m.status === 'confirmed')
      || (status === 'upcoming' && ['scheduled', 'lineup_out', 'postponed'].includes(m.status))))
  const shiftWeek = (n: number) => setSelected(new Date(week[0].getFullYear(), week[0].getMonth(), week[0].getDate() + 7 * n))

  return (
    <section>
      <PageHeader title="Live Score" back="#/" />
      <div className="search-row">
        <label className="search-pill">
          <svg width="18" height="18" viewBox="0 0 24 24" aria-hidden><circle cx="11" cy="11" r="7" fill="none" stroke="currentColor"
            strokeWidth="2" /><path d="M20 20l-4-4" stroke="currentColor" strokeWidth="2" strokeLinecap="round" /></svg>
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search team" aria-label="Search team" />
        </label>
        <button className={`round-btn square ${filters || status !== 'all' || sport ? 'on' : ''}`} aria-label="Filters"
          onClick={() => setFilters(!filters)}>
          <svg width="20" height="20" viewBox="0 0 24 24" aria-hidden><g stroke="currentColor" strokeWidth="1.8" strokeLinecap="round">
            <path d="M4 7h10M18 7h2M4 17h4M12 17h8" /><circle cx="16" cy="7" r="2" fill="none" /><circle cx="10" cy="17" r="2" fill="none" /></g></svg>
        </button>
      </div>
      {filters && (
        <div className="glass-card filter-card">
          <div className="chip-row">
            {(Object.keys(STATUS) as Status[]).map((s) => (
              <button key={s} className={`chip ${status === s ? 'on' : ''}`} onClick={() => setStatus(s)}>{STATUS[s]}</button>
            ))}
          </div>
          <div className="chip-row">
            {[null, 'football', 'basketball', 'volleyball'].map((s) => (
              <button key={s ?? 'all'} className={`chip ${sport === s ? 'on' : ''}`} onClick={() => setSport(s)}>
                {s ? `${SPORT_ICON[s]} ${s[0].toUpperCase()}${s.slice(1)}` : 'All sports'}</button>
            ))}
          </div>
        </div>
      )}
      {!term && (
        <div className="week" role="tablist" aria-label="Day">
          <button className="week-nav" aria-label="Previous week" onClick={() => shiftWeek(-1)}>‹</button>
          {week.map((d) => {
            const on = dayKey(d) === dayKey(day)
            return (
              <button key={d.toISOString()} role="tab" aria-selected={on}
                className={`wk ${on ? 'on' : ''} ${matchDays.has(dayKey(d)) ? 'has' : ''}`}
                onClick={() => { setSelected(d); setLeague(null) }}>
                <small>{d.toLocaleDateString(undefined, { weekday: 'short' })}</small>
                <b>{d.getDate()}</b>
              </button>
            )
          })}
          <button className="week-nav" aria-label="Next week" onClick={() => shiftWeek(1)}>›</button>
        </div>
      )}
      <hr className="rule" />
      {leagues.length > 0 && (
        <div className="league-chips">
          {leagues.map((m) => (
            <button key={m.tournament_id} className={`league-chip ${league === m.tournament_id ? 'on' : ''}`}
              onClick={() => setLeague(league === m.tournament_id ? null : m.tournament_id)}>
              <span className="league-logo small" aria-hidden>{SPORT_ICON[m.sport] ?? '🏆'}</span>{m.tournament}
            </button>
          ))}
        </div>
      )}
      {shown.length === 0 && <p className="muted">No matches {term ? `for "${q}"` : 'on this day'}.</p>}
      <ul className="plain score-list">{shown.map((m) => <li key={m.id}><ScoreCard m={m} /></li>)}</ul>
    </section>
  )
}
