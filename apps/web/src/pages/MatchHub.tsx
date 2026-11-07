import MatchCard, { statusPill, type MatchCardData } from '../components/MatchCard'
import { mediaUrl } from '../media'
import { sideColours } from '../teamStyle'
import TeamBadge from '../components/TeamBadge'
import Skeleton from '../components/Skeleton'
import { useApi } from '../useApi'

type SquadAthlete = { id: string; name: string; position: string; lineup: 'starting' | 'bench' | null }
type Detail = MatchCardData & { squads: { home: SquadAthlete[]; away: SquadAthlete[] } }

// Squads read back to front, like a team sheet: keeper, defence, midfield, attack.
const POSITIONS = ['GK', 'DEF', 'MID', 'FWD', 'G', 'F', 'C', 'P', 'S', 'OH', 'OPP', 'MB', 'L']
const posOrder = (p: string) => (POSITIONS.indexOf(p) + 1) || 99

export default function MatchHub({ matchId }: { matchId: string }) {
  const { data: m, error } = useApi<Detail>(`/matches/${matchId}`)
  if (error) return <p className="error">{error}</p>
  if (!m) return <Skeleton hero rows={3} />
  const lineupOut = m.squads.home.some((a) => a.lineup) || m.squads.away.some((a) => a.lineup)

  return (
    <section>
      <MatchHero m={m} />
      <MatchCard match={m} />
      <div className="section-head"><h3>{lineupOut ? 'Line-ups' : 'Squads'}</h3>
        <a href={`#/match/${m.id}/live`}>{m.locked ? 'Live points' : ''}</a></div>
      <div className="lineup-cards">
        {(['home', 'away'] as const).map((side) => {
          const team = side === 'home' ? m.home_team : m.away_team
          return (
            <div key={side} className="lineup-card">
              <div className="lineup-head"><TeamBadge name={team.name} colour={team.colour} logo={team.logo} small /><strong>{team.name}</strong></div>
              <ul className="plain">
                {m.squads[side]
                  .filter((a) => !lineupOut || a.lineup)
                  .sort((a, b) => Number(b.lineup === 'starting') - Number(a.lineup === 'starting')
                    || posOrder(a.position) - posOrder(b.position) || a.name.localeCompare(b.name))
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

/** Design screen 3's top: a full-width stage with back, the lime Live pill and close. Without a match
 *  photo the stage is drawn from the two teams' colours and crests. */
function MatchHero({ m }: { m: Detail }) {
  const colours = sideColours(m.home_team, m.away_team)
  const live = m.status === 'live'
  const photo = mediaUrl(m.photo_url)
  return (
    <div className={`match-hero ${photo ? 'has-photo' : ''}`} style={{ ['--home' as string]: colours.home,
      ['--away' as string]: colours.away, ...(photo ? { backgroundImage: `url("${photo}")` } : {}) }}>
      <div className="hero-bar">
        <a className="round-btn glassy" href="#/" aria-label="Back">
          <svg width="18" height="18" viewBox="0 0 24 24" aria-hidden><path d="M15 5l-7 7 7 7" fill="none" stroke="currentColor"
            strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" /></svg>
        </a>
        {live
          ? <span className="live-pill"><i className="live-icon">▶</i>Live</span>
          : <span className="live-pill idle">{statusPill(m).text}</span>}
        <a className="round-btn glassy" href="#/" aria-label="Close">
          <svg width="16" height="16" viewBox="0 0 24 24" aria-hidden><path d="M6 6l12 12M18 6L6 18" stroke="currentColor"
            strokeWidth="2.2" strokeLinecap="round" /></svg>
        </a>
      </div>
      {!photo && <div className="hero-crests" aria-hidden>
        <TeamBadge name={m.home_team.name} colour={m.home_team.colour} logo={m.home_team.logo} />
        <TeamBadge name={m.away_team.name} colour={m.away_team.colour} logo={m.away_team.logo} />
      </div>}
    </div>
  )
}
