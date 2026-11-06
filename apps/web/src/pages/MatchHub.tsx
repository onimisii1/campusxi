import MatchCard, { type MatchCardData } from '../components/MatchCard'
import PageHeader from '../components/PageHeader'
import { useApi } from '../useApi'

type SquadAthlete = { id: string; name: string; position: string; lineup: 'starting' | 'bench' | null }
type Detail = MatchCardData & { squads: { home: SquadAthlete[]; away: SquadAthlete[] } }

export default function MatchHub({ matchId }: { matchId: string }) {
  const { data: m, error } = useApi<Detail>(`/matches/${matchId}`)
  if (error) return <p className="error">{error}</p>
  if (!m) return <p className="muted">Loading…</p>
  const lineupOut = m.squads.home.some((a) => a.lineup) || m.squads.away.some((a) => a.lineup)

  return (
    <section>
      <PageHeader title="Match" back="#/" />
      <MatchCard match={m} />
      <h3>{lineupOut ? 'Line-ups' : 'Squads'}</h3>
      <div className="sides">
        {(['home', 'away'] as const).map((side) => (
          <div key={side}>
            <h4>{side === 'home' ? m.home_team.name : m.away_team.name}</h4>
            <ul className="plain small">
              {m.squads[side]
                .filter((a) => !lineupOut || a.lineup)
                .sort((a, b) => Number(b.lineup === 'starting') - Number(a.lineup === 'starting'))
                .map((a) => (
                  <li key={a.id} className={a.lineup === 'bench' ? 'muted' : ''}>
                    {a.name} <span className="muted">{a.position}{a.lineup === 'bench' ? ' · bench' : ''}</span>
                  </li>
                ))}
            </ul>
          </div>
        ))}
      </div>
    </section>
  )
}
