import { countdown, deadline, points } from '../format'
import { LIVE_REFRESH_MS, useApi } from '../useApi'
import TeamBadge from './TeamBadge'
import UpdatedStamp from './UpdatedStamp'

export type MatchCardData = {
  id: string
  tournament_id: string
  tournament: string
  sport: string
  home_team: { id: string; name: string; colour?: string | null }
  away_team: { id: string; name: string; colour?: string | null }
  venue: string | null
  scheduled_start: string
  status: string
  lineup_out: boolean
  locked: boolean
  seconds_to_lock: number
  late_join_until?: number | null
  code?: string | null
  stage?: string
  score?: { home: number; away: number; walkover: boolean; final: boolean } | null
  minute?: number | null
  scheduled_minutes?: number
  fans?: number
  fans_preview?: string[]
}

type Summary = { players: number; teams: number; my_teams: number; my_points: number | null; average: number | null
  highest: number | null }

// eslint-disable-next-line react-refresh/only-export-components
export function statusPill(m: MatchCardData): { text: string; cls: string } {
  if (m.status === 'live') return { text: 'Ongoing', cls: 'live' }
  if (m.status === 'final_pending') return { text: 'Full time', cls: '' }
  if (m.status === 'confirmed') return { text: m.score?.walkover ? 'Walkover' : 'Ended', cls: '' }
  if (m.status === 'postponed') return { text: 'Postponed', cls: '' }
  return { text: 'Up coming', cls: '' }
}

const label = (m: MatchCardData) =>
  m.code ? `${m.stage && m.stage !== 'league' ? m.stage.replace('_', ' ') : 'Match'} ${m.code}` : m.score || m.status === 'live' ? 'Match day' : 'Kick-off'

/** Under the score: the phase, as the design writes it ("1ST HALF 58'"). */
function phase(m: MatchCardData): string {
  if (m.score?.walkover) return 'VOIDED'
  if (m.status === 'live' && m.minute != null) {
    const half = m.scheduled_minutes ? (m.minute < m.scheduled_minutes / 2 ? '1ST HALF' : '2ND HALF') : 'LIVE'
    return `${half} ${m.minute}'`
  }
  if (m.score?.final || m.status === 'final_pending') return 'FULL TIME'
  const t = new Date(m.scheduled_start)
  return t.toLocaleDateString(undefined, { weekday: 'short', day: 'numeric', month: 'short' }).toUpperCase()
}

function centre(m: MatchCardData): string {
  if (m.score?.walkover) return 'W/O'
  if (m.score) return `${m.score.home} : ${m.score.away}`
  return new Date(m.scheduled_start).toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' })
}

/** Home's compact card (design screen 1): league + status, crests, big score. Lime for the top event. */
export function EventCard({ m, lime = false, stacked = false }: { m: MatchCardData; lime?: boolean; stacked?: boolean }) {
  const pill = statusPill(m)
  return (
    <a className={`event-card ${lime ? 'lime' : ''} ${stacked ? 'stacked' : ''}`} href={`#/match/${m.id}`}
      aria-label={`${m.home_team.name} vs ${m.away_team.name}, ${pill.text}`}>
      <span className="event-top">
        <strong className="event-league">{m.tournament}</strong>
        <span className={`status-pill ${pill.cls}`}>{pill.text}</span>
      </span>
      <span className="faceoff">
        <span className="side"><TeamBadge name={m.home_team.name} colour={m.home_team.colour} />{m.home_team.name}</span>
        <span className="mid"><small>{label(m)}</small><b>{centre(m)}</b><small className="phase">{phase(m)}</small></span>
        <span className="side"><TeamBadge name={m.away_team.name} colour={m.away_team.colour} />{m.away_team.name}</span>
      </span>
    </a>
  )
}

function initials(name: string) {
  return name.split(/[\s_]+/).map((w) => w[0]).join('').slice(0, 2).toUpperCase()
}

/** "People place a bet" row: avatar stack, a lime count, the caption. */
export function FansRow({ m }: { m: MatchCardData }) {
  if (!m.fans) return <span className="fans-row muted small">Be the first to pick a team</span>
  const n = m.fans >= 1000 ? `${(m.fans / 1000).toFixed(1)}K` : String(m.fans)
  return (
    <span className="fans-row">
      <span className="avatars">
        {(m.fans_preview ?? []).map((f) => <i key={f}>{initials(f)}</i>)}
        <i className="count">{n}</i>
      </span>
      <span className="small">{m.fans === 1 ? 'fan picked a team' : 'fans picked a team'}</span>
    </span>
  )
}

/** Fixtures card (design screen 2): names over big scores, a centre pill with the clock, the fans row. */
export function ScoreCard({ m }: { m: MatchCardData }) {
  const live = m.status === 'live'
  const mid = m.score?.walkover ? 'W/O' : live && m.minute != null ? `${m.minute}'`
    : m.score?.final ? 'FT' : new Date(m.scheduled_start).toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' })
  return (
    <a className="score-card" href={`#/match/${m.id}`}>
      <span className="score-grid">
        <TeamBadge name={m.home_team.name} colour={m.home_team.colour} small />
        <span className="score-side"><small>{m.home_team.name}</small><b className={m.score && !m.score.walkover ? '' : 'empty'}>{m.score && !m.score.walkover ? m.score.home : '–'}</b></span>
        <span className="score-mid">{live && <i className="live-dot" aria-label="live" />}<small>{m.code ?? ''}</small><span>{mid}</span></span>
        <span className="score-side right"><small>{m.away_team.name}</small><b className={m.score && !m.score.walkover ? '' : 'empty'}>{m.score && !m.score.walkover ? m.score.away : '–'}</b></span>
        <TeamBadge name={m.away_team.name} colour={m.away_team.colour} small />
      </span>
      {(m.fans || !m.locked) ? <FansRow m={m} /> : null}
    </a>
  )
}

/** The match page's scoreboard (design screen 3's live panel): league, crests with scores, the clock with
 *  a lime progress knob, then your numbers and actions. */
export default function MatchCard({ match }: { match: MatchCardData }) {
  const live = match.status === 'live' || match.status === 'final_pending'
  const { data: s, updatedAt, stale } = useApi<Summary>(`/matches/${match.id}/summary`, live ? LIVE_REFRESH_MS : undefined)
  const base = `#/match/${match.id}`
  const started = s?.average !== null && s?.average !== undefined
  const total = match.scheduled_minutes || 0
  const progress = total && match.minute != null ? Math.min(100, (match.minute / total) * 100)
    : match.score?.final ? 100 : 0

  return (
    <article className="panel" aria-label={`${match.home_team.name} vs ${match.away_team.name}`}>
      <a className="panel-league" href={`#/tournament/${match.tournament_id}`}>
        <span className="league-logo" aria-hidden>{match.sport === 'basketball' ? '🏀' : match.sport === 'volleyball' ? '🏐' : '⚽'}</span>
        <span><strong>{match.tournament}</strong><small className="muted block">{label(match)}{match.venue ? ` · ${match.venue}` : ''}</small></span>
      </a>
      <div className="panel-teams">
        <span className="panel-team"><TeamBadge name={match.home_team.name} colour={match.home_team.colour} />
          {match.score && !match.score.walkover && <b className="score-bubble">{match.score.home}</b>}
          <span>{match.home_team.name}</span></span>
        <span className="vs">VS</span>
        <span className="panel-team"><TeamBadge name={match.away_team.name} colour={match.away_team.colour} />
          {match.score && !match.score.walkover && <b className="score-bubble">{match.score.away}</b>}
          <span>{match.away_team.name}</span></span>
      </div>
      <div className="clock">
        <span className="clock-time">{match.status === 'live' && match.minute != null ? `${String(match.minute).padStart(2, '0')}:00`
          : match.locked ? phase(match) : countdown(match.seconds_to_lock)}</span>
        {total > 0 && <span className="clock-total muted small">{total}′</span>}
      </div>
      <div className="track" aria-hidden><span style={{ width: `${progress}%` }} /><i style={{ left: `${progress}%` }} /></div>
      <p className="panel-note small muted">
        {match.locked
          ? <>{match.late_join_until != null ? `⏱ Late joining open until ${match.late_join_until}′` : phase(match)}
            {live && <> · <UpdatedStamp at={updatedAt} stale={stale} /></>}</>
          : <>Deadline {deadline(match.scheduled_start)}{match.lineup_out ? ' · Line-up out' : ''}</>}
      </p>
      <div className="odds">
        <div><small>{started ? 'Average' : 'Fans in'}</small><b>{started ? points(s!.average) : (s?.players ?? '–')}</b></div>
        <div><small>{started ? 'Highest' : 'Teams built'}</small><b>{started ? points(s!.highest) : (s?.teams ?? '–')}</b></div>
        <div className="on"><small>{started ? 'You' : 'Your teams'}</small>
          <b>{started ? (s!.my_points === null ? '–' : points(s!.my_points)) : (s?.my_teams ?? 0)}</b></div>
      </div>
      <nav className="actions">
        <a className="primary as-button" href={`${base}/teams`}>{match.locked ? 'My teams' : (s?.my_teams ? 'Pick Team' : 'Pick your team')}</a>
        <a className="action-pill" href={`${base}/contests`}>{match.late_join_until != null ? 'Join late' : 'Contests'}</a>
        <a className="action-pill" href={`${base}/challenges`}>Challenges</a>
        {match.locked && <a className="action-pill" href={`${base}/live`}>Live points</a>}
      </nav>
    </article>
  )
}
