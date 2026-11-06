import MatchCard, { type MatchCardData } from '../components/MatchCard'
import PageHeader from '../components/PageHeader'
import TeamBadge from '../components/TeamBadge'
import Skeleton from '../components/Skeleton'
import { useApi } from '../useApi'

type SquadAthlete = { id: string; name: string; position: string; lineup: 'starting' | 'bench' | null }
type Detail = MatchCardData & { squads: { home: SquadAthlete[]; away: SquadAthlete[] } }

export default function MatchHub({ matchId }: { matchId: string }) {
  const { data: m, error } = useApi<Detail>(`/matches/${matchId}`)
  if (error) return <p className="error">{error}</p>
  if (!m) return <Skeleton hero rows={3} />
  const lineupOut = m.squads.home.some((a) => a.lineup) || m.squads.away.some((a) => a.lineup)

  return (
    <section>
      <PageHeader title={m.status === 'live' ? 'Live Score' : 'Match'} back="#/" />
      <MatchCard match={m} />
      <div className="section-head"><h3>{lineupOut ? 'Line-ups' : 'Squads'}</h3>
        <a href={`#/match/${m.id}/live`}>{m.locked ? 'Live points' : ''}</a></div>
      <div className="lineup-cards">
        {(['home', 'away'] as const).map((side) => {
          const team = side === 'home' ? m.home_team : m.away_team
          return (
            <div key={side} className="lineup-card">
              <div className="lineup-head"><TeamBadge name={team.name} colour={team.colour} small /><strong>{team.name}</strong></div>
              <ul className="plain">
                {m.squads[side]
                  .filter((a) => !lineupOut || a.lineup)
                  .sort((a, b) => Number(b.lineup === 'starting') - Number(a.lineup === 'starting'))
                  .map((a) => (
                    <li key={a.id} className={a.lineup === 'bench' ? 'bench' : ''}>
                      <span className="pos-tag">{a.position}</span>
                      <a className="plain-link grow" href={`#/player/${a.id}`}>{a.name}</a>
                      {a.lineup === 'bench' && <small className="muted">bench</small>}
                    </li>
                  ))}
              </ul>
            </div>
          )
        })}
      </div>
    </section>
  )
}
