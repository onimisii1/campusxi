import PageHeader from '../components/PageHeader'
import Shirt from '../components/Shirt'
import Skeleton from '../components/Skeleton'
import { kickoff, points } from '../format'
import { sideColours } from '../teamStyle'
import { useApi } from '../useApi'

type Profile = {
  id: string
  name: string
  position: string
  team: { id: string; name: string; colour: string | null }
  tournament: { id: string; name: string; sport: string }
  stats_kind: 'golden_boot' | 'mvp'
  stats: null | { rank: number; shared: boolean; matches: number; goals?: number; assists?: number; points?: number
    rebounds?: number; steals?: number; blocks?: number; total?: string; average?: string }
  matches: { match_id: string; code: string | null; scheduled_start: string; opponent: string; score: string; played: boolean
    points: string | number; breakdown: { label: string; points: string | number }[]; picked_pct: number | null }[]
  total_points: string | number
}

const POSITION: Record<string, string> = { GK: 'Goalkeeper', DEF: 'Defender', MID: 'Midfielder', FWD: 'Forward',
  G: 'Guard', F: 'Forward', C: 'Centre', P: 'Player' }

/** A player's page: their tournament numbers and fantasy points match by match. */
export default function PlayerPage({ athleteId }: { athleteId: string }) {
  const { data: p, error } = useApi<Profile>(`/athletes/${athleteId}`)
  if (error) return <p className="error">{error}</p>
  if (!p) return <Skeleton hero rows={3} />
  const colour = sideColours(p.team, { name: '' }).home
  const s = p.stats
  const tiles: [string, string | number][] = p.stats_kind === 'mvp'
    ? [['MVP rank', s ? `${s.rank}${s.shared ? '=' : ''}` : '–'], ['PTS', s?.points ?? 0], ['REB', s?.rebounds ?? 0],
      ['AST', s?.assists ?? 0], ['MVP avg', s ? points(s.average ?? 0) : '–']]
    : [['Goals', s?.goals ?? 0], ['Assists', s?.assists ?? 0], ['Matches', s?.matches ?? p.matches.filter((m) => m.played).length],
      ['Golden boot', s ? `${s.rank}${s.shared ? '=' : ''}` : '–']]
  return (
    <section>
      <PageHeader title={p.name} back={`#/tournament/${p.tournament.id}`} subtitle={p.tournament.name} />
      <div className="player-hero">
        <Shirt colour={colour} size={64} />
        <div>
          <strong>{p.name}</strong>
          <span className="muted block">{p.team.name} · {POSITION[p.position] ?? p.position}</span>
          <span className="block"><b>{points(p.total_points)}</b> fantasy points this tournament</span>
        </div>
      </div>
      <div className="stat-tiles">
        {tiles.map(([label, value]) => <div key={label}><b>{value}</b><span>{label}</span></div>)}
      </div>
      <h3>Match by match</h3>
      {p.matches.length === 0 && <p className="muted">No finished matches yet.</p>}
      <ul className="plain">
        {p.matches.map((m) => (
          <li key={m.match_id} className="card">
            <a className="row between plain-link" href={`#/match/${m.match_id}`}>
              <span><strong>{m.code ? `${m.code} · ` : ''}v {m.opponent}</strong>
                <span className="muted small block">{kickoff(m.scheduled_start)} · {m.score}
                  {m.picked_pct !== null ? ` · picked by ${m.picked_pct}%` : ''}</span></span>
              <strong className="pts-big">{m.played ? points(m.points) : 'DNP'}</strong>
            </a>
            {m.breakdown.length > 0 && (
              <p className="small muted">{m.breakdown.map((b) => `${b.label} ${Number(b.points) > 0 ? '+' : ''}${points(b.points)}`).join(' · ')}</p>
            )}
          </li>
        ))}
      </ul>
    </section>
  )
}
