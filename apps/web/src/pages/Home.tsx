import { useState } from 'react'
import MatchCard, { type MatchCardData } from '../components/MatchCard'
import Skeleton from '../components/Skeleton'
import SportSlider, { savedSport } from '../components/SportSlider'
import { countdown, kickoff, statusLabel } from '../format'
import { useApi } from '../useApi'

/** Featured match: a live one first, then the next to lock, then the latest result. */
function featured(matches: MatchCardData[]): MatchCardData | undefined {
  return matches.find((m) => m.status === 'live')
    ?? matches.find((m) => !m.locked)
    ?? matches.find((m) => m.status === 'final_pending')
    ?? [...matches].reverse().find((m) => m.status === 'confirmed')
}

export default function Home() {
  const [sport, setSport] = useState(savedSport)
  const { data, error } = useApi<MatchCardData[]>('/matches', 60_000)

  const matches = (data ?? []).filter((m) => m.sport === sport && m.status !== 'abandoned')
  const top = featured(matches)
  const rest = matches.filter((m) => m !== top)
  const upcoming = rest.filter((m) => m.status !== 'confirmed')
  const results = rest.filter((m) => m.status === 'confirmed').reverse()
  const tournaments = [...new Map(matches.map((m) => [m.tournament_id, m.tournament])).entries()]

  return (
    <section>
      <SportSlider value={sport} onChange={setSport} />
      {error && <p className="error">{error}</p>}
      {!data && !error && <Skeleton hero rows={2} />}
      {data && !top && <p className="card muted">No {sport} events yet. Check back soon.</p>}
      {top && <MatchCard key={top.id} match={top} />}

      {upcoming.length > 0 && <h3>More events</h3>}
      <ul className="list">{upcoming.map((m) => <Row key={m.id} m={m} />)}</ul>

      {results.length > 0 && <h3>Results</h3>}
      <ul className="list">{results.map((m) => <Row key={m.id} m={m} />)}</ul>

      {tournaments.length > 0 && <h3>Tournaments</h3>}
      <ul className="list">
        {tournaments.map(([id, name]) => (
          <li key={id}><a className="row-card" href={`#/tournament/${id}`}><span><strong>{name}</strong><span className="muted small block">Table, results, top scorers, bracket</span></span><span aria-hidden>→</span></a></li>
        ))}
      </ul>
    </section>
  )
}

function Row({ m }: { m: MatchCardData }) {
  return (
    <li>
      <a className="row-card" href={`#/match/${m.id}`}>
        <span>
          <strong>{m.home_team.name} vs {m.away_team.name}</strong>
          <span className="muted small block">{kickoff(m.scheduled_start)}</span>
        </span>
        <span className={`badge ${m.status === 'live' ? 'bad' : ''}`}>
          {m.status === 'live' ? '● Live' : m.locked ? statusLabel(m.status) : countdown(m.seconds_to_lock)}
        </span>
      </a>
    </li>
  )
}
