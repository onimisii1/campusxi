import { countdown, deadline, points, statusLabel } from '../format'
import { useApi } from '../useApi'

export type MatchCardData = {
  id: string
  tournament_id: string
  tournament: string
  sport: string
  home_team: { id: string; name: string }
  away_team: { id: string; name: string }
  venue: string | null
  scheduled_start: string
  status: string
  lineup_out: boolean
  locked: boolean
  seconds_to_lock: number
}

type Summary = {
  players: number
  teams: number
  my_teams: number
  my_points: number | null
  average: number | null
  highest: number | null
}

/** The big gradient card: the match, your numbers, the deadline and the main actions. */
export default function MatchCard({ match }: { match: MatchCardData }) {
  const { data: s } = useApi<Summary>(`/matches/${match.id}/summary`)
  const base = `#/match/${match.id}`
  const started = s?.average !== null && s?.average !== undefined

  return (
    <article className="hero" aria-label={`${match.home_team.name} vs ${match.away_team.name}`}>
      <a className="hero-title" href={base}>
        <span className="small">{match.tournament}</span>
        <strong>{match.home_team.name} <span className="vs">vs</span> {match.away_team.name}</strong>
        {match.status === 'live' && <span className="pill-live">● Live</span>}
      </a>
      <hr />
      {started ? (
        <div className="stats">
          <div><b>{points(s!.average)}</b><span>Average</span></div>
          <div className="main"><b>{s!.my_points === null ? '–' : points(s!.my_points)}</b><span>Your points</span></div>
          <div><b>{points(s!.highest)}</b><span>Highest</span></div>
        </div>
      ) : (
        <div className="stats">
          <div><b>{s?.players ?? '–'}</b><span>Players in</span></div>
          <div className="main"><b>{s?.my_teams ?? 0}</b><span>Your teams</span></div>
          <div><b>{s?.teams ?? '–'}</b><span>Teams built</span></div>
        </div>
      )}
      <hr />
      <p className="deadline">
        {match.locked
          ? <>{statusLabel(match.status)}{match.venue ? ` · ${match.venue}` : ''}</>
          : <>Deadline: {deadline(match.scheduled_start)}<span className="small block">{countdown(match.seconds_to_lock)}{match.lineup_out ? ' · Line-up out' : ''}</span></>}
      </p>
      <nav className="pills">
        <a href={`${base}/teams`}>{match.locked ? 'My teams' : (s?.my_teams ? 'Pick Team' : 'Pick your team')}</a>
        <a href={`${base}/contests`}>Contests</a>
        <a href={`${base}/challenges`}>Challenges</a>
        {match.locked && <a href={`${base}/live`}>Live points</a>}
      </nav>
    </article>
  )
}
