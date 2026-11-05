import { useState } from 'react'
import { countdown, kickoff, statusLabel } from '../format'
import { useApi } from '../useApi'

type Sport = { code: string; name: string; live: boolean }
type Team = { id: string; name: string }
export type MatchCard = {
  id: string
  tournament_id: string
  tournament: string
  sport: string
  home_team: Team
  away_team: Team
  venue: string | null
  scheduled_start: string
  status: string
  lineup_out: boolean
  locked: boolean
  seconds_to_lock: number
}

const HIDE = ['abandoned']

export default function Lobby() {
  const { data: sports } = useApi<Sport[]>('/sports')
  const { data: matches, error } = useApi<MatchCard[]>('/matches')
  const [sport, setSport] = useState<string | null>(null)

  const visible = (matches ?? []).filter((m) => !HIDE.includes(m.status) && (!sport || m.sport === sport))
  const upcoming = visible.filter((m) => m.status !== 'confirmed')
  const finished = visible.filter((m) => m.status === 'confirmed').reverse()
  const tournaments = [...new Map((matches ?? []).map((m) => [m.tournament_id, m.tournament])).entries()]

  return (
    <section>
      <div className="chips" role="tablist" aria-label="Sports">
        <button className={sport === null ? 'chip on' : 'chip'} onClick={() => setSport(null)}>All</button>
        {sports?.map((s) => (
          <button key={s.code} className={sport === s.code ? 'chip on' : 'chip'} disabled={!s.live}
            onClick={() => setSport(s.code)} title={s.live ? undefined : 'Coming soon'}>
            {s.name}{!s.live && ' · soon'}
          </button>
        ))}
      </div>

      {error && <p className="error">{error}</p>}
      {matches && upcoming.length === 0 && <p className="muted">No upcoming matches yet. Check back soon.</p>}
      <ul className="list">{upcoming.map((m) => <MatchItem key={m.id} m={m} />)}</ul>

      {finished.length > 0 && (
        <>
          <h3>Results</h3>
          <ul className="list">{finished.map((m) => <MatchItem key={m.id} m={m} />)}</ul>
        </>
      )}

      {tournaments.length > 0 && (
        <>
          <h3>Season tables</h3>
          <ul className="list">
            {tournaments.map(([id, name]) => (
              <li key={id}><a className="match-card" href={`#/table/${id}`}><strong>{name}</strong></a></li>
            ))}
          </ul>
        </>
      )}
    </section>
  )
}

function MatchItem({ m }: { m: MatchCard }) {
  const live = m.status === 'live'
  return (
    <li>
      <a className="match-card" href={`#/match/${m.id}`}>
        <span className="muted">{m.tournament} · {kickoff(m.scheduled_start)}</span>
        <strong>{m.home_team.name} vs {m.away_team.name}</strong>
        <span className="row">
          {live && <span className="badge bad">● Live</span>}
          {!m.locked && <span className="badge">{countdown(m.seconds_to_lock)}</span>}
          {m.lineup_out && !m.locked && <span className="badge good">Line-up out</span>}
          {m.locked && !live && <span className="badge">{statusLabel(m.status)}</span>}
        </span>
      </a>
    </li>
  )
}
