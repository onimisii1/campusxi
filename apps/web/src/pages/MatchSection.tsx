import { useEffect, useState } from 'react'
import { api } from '../api'
import ContestCard from '../components/ContestCard'
import JoinContestSheet from '../components/JoinContestSheet'
import MyBetRow, { type MyBet } from '../components/MyBetRow'
import { openFor, type Contest } from '../contests'
import PageHeader from '../components/PageHeader'
import Shirt from '../components/Shirt'
import { kickoff, points, statusLabel } from '../format'
import { signInThenReturn } from '../router'
import { TEAM_RULES } from '../rules'
import { useSession } from '../session'
import Skeleton from '../components/Skeleton'
import UpdatedStamp from '../components/UpdatedStamp'
import { shortName, sideColours, teamCode } from '../teamStyle'
import { useToast } from '../toast'
import { errorText, LIVE_REFRESH_MS, useApi } from '../useApi'

type Match = {
  id: string
  sport: string
  tournament: string
  home_team: { id: string; name: string; colour: string | null }
  away_team: { id: string; name: string; colour: string | null }
  scheduled_start: string
  venue: string | null
  status: string
  locked: boolean
  seconds_to_lock: number
  late_join_until: number | null
  score?: { home: number; away: number; walkover: boolean; final: boolean } | null
}
type Pick = { athlete_id: string; display_name: string; role: string; position: string; team_id: string; points?: number }
type Team = { id: string; label: string; picks: Pick[] }
type Breakdown = { total_points: number; picks: Pick[] }
type LiveAthlete = { id: string; name: string; position: string; side: string; points: number;
  breakdown: { label: string; points: number }[] }
type Live = { source: string | null; result: { home_score: number; away_score: number } | null; athletes: LiveAthlete[] }
type BoardBet = { id: string; creator: { team_name: string; record: { won: number; lost: number; tied: number } }; is_mine: boolean }

// Each section of a match is its own page, reached from the match card's pill buttons.
export const SECTIONS = {
  teams: 'Pick Team',
  contests: 'Contests',
  challenges: 'Challenges',
  live: 'Live points',
} as const
export type Section = keyof typeof SECTIONS

export default function MatchSection({ matchId, section, focus }: { matchId: string; section: Section; focus?: string }) {
  const { data: match, error } = useApi<Match>(`/matches/${matchId}`)

  if (error) return <p className="error">{error}</p>
  if (!match) return <Skeleton rows={4} />

  return (
    <section>
      <PageHeader title={section === 'teams' && match.locked ? 'My teams' : SECTIONS[section]} back={`#/match/${matchId}`}
        subtitle={`${match.home_team.name} ${match.score?.walkover ? 'v (walkover, voided)' : match.score ? `${match.score.home}–${match.score.away}` : 'vs'} ${
          match.away_team.name} · ${match.locked ? statusLabel(match.status) : `Deadline ${kickoff(match.scheduled_start)}`}`} />
      {section === 'contests' && <ContestsTab match={match} />}
      {section === 'teams' && <TeamsTab match={match} focus={focus} />}
      {section === 'live' && <LiveTab match={match} />}
      {section === 'challenges' && <ChallengesTab match={match} />}
    </section>
  )
}

function NeedSignIn({ what }: { what: string }) {
  return <p className="card">Sign in to {what}. <button className="link" onClick={signInThenReturn}>Sign in</button></p>
}

function TeamPicker({ teams, value, onChange, exclude = [] }: {
  teams: Team[]; value: string; onChange: (id: string) => void; exclude?: string[]
}) {
  const options = teams.filter((t) => !exclude.includes(t.id))
  return (
    <select value={value} onChange={(e) => onChange(e.target.value)} aria-label="Choose a team">
      <option value="">Choose a team</option>
      {options.map((t) => <option key={t.id} value={t.id}>{t.label}</option>)}
    </select>
  )
}

const CONTEST_VIEWS = ['all', 'mine', 'teams'] as const
type ContestView = (typeof CONTEST_VIEWS)[number]
const SORTS = { default: 'Featured', fee: 'Entry fee', spots: 'Spots', pool: 'Prize pool' } as const
type Sort = keyof typeof SORTS

/** FantasyFi-style groups: who a contest is for. */
function contestGroup(c: Contest): string {
  if (c.entry_fee_kobo === 0) return 'Free'
  if (c.entry_fee_kobo === 40_000) return 'Mini ₦400'
  if (c.capacity <= 5) return 'Head-to-head'
  if (c.capacity >= 100) return 'Mega'
  return 'Small contests'
}
const GROUP_ORDER = ['Free', 'Mega', 'Small contests', 'Head-to-head', 'Mini ₦400']
const GROUP_BLURB: Record<string, string> = {
  Free: 'No entry fee: play for bragging rights and the season table.',
  Mega: 'Big pools, the most entrants.',
  'Head-to-head': 'Beat a handful of players.',
  'Mini ₦400': 'Small stakes, same game.',
}

function ContestsTab({ match }: { match: Match }) {
  const { status } = useSession()
  const { data: contests, reload } = useApi<Contest[]>(`/matches/${match.id}/contests`)
  const { data: teams } = useApi<Team[]>(status === 'ready' ? `/me/teams?match_id=${match.id}` : null)
  const [view, setView] = useState<ContestView>('all')
  const [sort, setSort] = useState<Sort>('default')
  if (!contests) return <Skeleton rows={2} />
  const late = contests.find((c) => c.late_join)?.late_join
  const mine = contests.filter((c) => c.my_entries.length > 0)
  const value: Record<Sort, (c: Contest) => number> = {
    default: () => 0, fee: (c) => c.entry_fee_kobo, spots: (c) => -c.capacity,
    pool: (c) => -(c.entry_fee_kobo * c.capacity),
  }
  const sorted = [...(view === 'mine' ? mine : contests)].sort((a, b) => value[sort](a) - value[sort](b))
  const groups = GROUP_ORDER.map((g) => [g, sorted.filter((c) => contestGroup(c) === g)] as const).filter(([, l]) => l.length)
  const label = { all: 'All contests', mine: `My contests (${mine.length})`, teams: `My teams (${teams?.length ?? 0})` }

  return (
    <div>
      <div className="tabs" role="tablist">
        {CONTEST_VIEWS.map((v) => (
          <button key={v} role="tab" aria-selected={view === v} className={view === v ? 'tab on' : 'tab'}
            onClick={() => setView(v)}>{label[v]}</button>
        ))}
      </div>
      {view === 'teams' ? <TeamsTab match={match} /> : (
        <>
          {late && (
            <p className="notice">⏱ Late joining is open until minute {late.until_minute}. Points recorded before you
              join don't count.</p>
          )}
          {contests.length > 1 && (
            <div className="chip-row sort-row" role="group" aria-label="Sort contests">
              <span className="small muted">Sort</span>
              {(Object.keys(SORTS) as Sort[]).map((k) => (
                <button key={k} className={`chip ${sort === k ? 'on' : ''}`} onClick={() => setSort(k)}>{SORTS[k]}</button>
              ))}
            </div>
          )}
          {view === 'mine' && mine.length === 0 && (
            <p className="muted">You haven't joined a contest for this match yet.</p>
          )}
          {groups.map(([g, list]) => (
            <div key={g}>
              {(groups.length > 1 || g !== 'Free') && (
                <div className="contest-group"><strong>{g}</strong><span className="muted small">{GROUP_BLURB[g] ?? ''}</span></div>
              )}
              {list.map((c) => <ContestCard key={c.id} contest={c} matchId={match.id} teams={teams} onChanged={reload} />)}
            </div>
          ))}
        </>
      )}
    </div>
  )
}

function TeamsTab({ match, focus }: { match: Match; focus?: string }) {
  const { status } = useSession()
  const { data: teams } = useApi<Team[]>(status === 'ready' ? `/me/teams?match_id=${match.id}` : null)
  const { data: contests, reload } = useApi<Contest[]>(`/matches/${match.id}/contests`)
  const [sheet, setSheet] = useState<{ team: Team; fresh: boolean } | null>(null)

  // Straight after building a team, offer to enter it in a contest.
  useEffect(() => {
    const team = focus ? teams?.find((t) => t.id === focus) : undefined
    if (team && contests && openFor(contests, team.id).length > 0) setSheet({ team, fresh: true })
    if (focus && team) window.history.replaceState(null, '', `#/match/${match.id}/teams`)
  }, [focus, teams, contests, match.id])

  if (status === 'signed_out') return <NeedSignIn what="build teams" />
  return (
    <div>
      {teams?.length === 0 && <p className="muted">You have no teams for this match yet.</p>}
      {teams?.map((t) => (
        <TeamCard key={t.id} team={t} match={match} contests={contests}
          onJoin={() => setSheet({ team: t, fresh: false })} />
      ))}
      {(!match.locked || match.late_join_until !== null) && (teams?.length ?? 0) < 10 && (
        <a className="primary as-button" href={`#/build/${match.id}`}>
          {match.locked ? `+ New late team (points count from now, until ${match.late_join_until}′)` : '+ New team'}
        </a>
      )}
      {sheet && (
        <JoinContestSheet teamId={sheet.team.id} teamLabel={sheet.team.label} fresh={sheet.fresh}
          contests={openFor(contests, sheet.team.id)} onClose={() => setSheet(null)}
          onJoined={() => { setSheet(null); reload() }} />
      )}
    </div>
  )
}

const BADGE: Record<string, string> = { captain: 'C', vice_captain: 'V', key: 'K' }

/** A saved team on a small pitch; after kick-off each nameplate shows the player's points. */
function TeamCard({ team, match, contests, onJoin }: {
  team: Team; match: Match; contests: Contest[] | null; onJoin: () => void
}) {
  const { data: bd } = useApi<Breakdown>(match.locked ? `/teams/${team.id}/breakdown` : null)
  const picks: Pick[] = bd?.picks ?? team.picks
  const colours = sideColours(match.home_team, match.away_team)
  const rules = TEAM_RULES[match.sport]
  return (
    <div className="card">
      <div className="row between">
        <strong>{team.label}</strong>
        {bd ? <strong>{points(bd.total_points)} pts</strong>
          : !match.locked && <a href={`#/build/${match.id}/${team.id}`}>Edit</a>}
      </div>
      <div className={`pitch mini ${match.sport}`}>
        {rules.groups.map((g) => (
          <div key={g.name} className="pitch-row">
            {picks.filter((p) => g.positions.includes(p.position)).map((p) => {
              const home = p.team_id === match.home_team.id
              const name = home ? match.home_team.name : match.away_team.name
              return (
                <div key={p.athlete_id} className="player" aria-label={`${p.display_name}${p.points !== undefined ? `, ${points(p.points)} points` : ''}`}>
                  {BADGE[p.role] && <span className="role-badge">{BADGE[p.role]}</span>}
                  <Shirt colour={home ? colours.home : colours.away} size={34} />
                  <span className="nameplate">
                    <b>{shortName(p.display_name)}</b>
                    <small>{p.points !== undefined ? points(p.points) : `${teamCode(name)} · ${p.position}`}</small>
                  </span>
                </div>
              )
            })}
          </div>
        ))}
      </div>
      <TeamContests team={team} contests={contests} onJoin={onJoin} />
    </div>
  )
}

/** Which contests a team is in, and a button to enter more. */
function TeamContests({ team, contests, onJoin }: { team: Team; contests: Contest[] | null; onJoin: () => void }) {
  if (!contests) return null
  const inIt = contests.filter((c) => c.my_entries.some((e) => e.fantasy_team_id === team.id))
  const open = openFor(contests, team.id)
  return (
    <div className="team-contests">
      <span className="small muted">{inIt.length ? `In: ${inIt.map((c) => c.name).join(', ')}` : 'Not in a contest yet'}</span>
      {open.length > 0 && (
        <button className="join-btn" onClick={onJoin}>{inIt.length ? '+ Join another' : 'Join a contest'}</button>
      )}
    </div>
  )
}

function LiveTab({ match }: { match: Match }) {
  const isLive = match.status === 'live' || match.status === 'final_pending'
  const { data: live, reload, updatedAt, stale } = useApi<Live>(`/matches/${match.id}/live`, isLive ? LIVE_REFRESH_MS : undefined)
  const [open, setOpen] = useState<string | null>(null)
  if (!match.locked) return <p className="muted">Live points appear once the match kicks off.</p>
  if (!live) return <Skeleton rows={6} />
  return (
    <div>
      <div className="row between">
        <span className="muted small">{live.source === 'official' ? 'Final, official stats' : 'Live from the sideline scorer'}
          {isLive && <UpdatedStamp at={updatedAt} stale={stale} />}</span>
        <button className="link" onClick={reload}>Refresh</button>
      </div>
      {live?.result && <p><strong>Final score {live.result.home_score}–{live.result.away_score}</strong></p>}
      <ol className="log">
        {live?.athletes.map((a) => (
          <li key={a.id} onClick={() => setOpen(open === a.id ? null : a.id)}>
            <span>{a.name} <small className="muted">{a.position} · {a.side === 'home' ? match.home_team.name : match.away_team.name}</small>
              {open === a.id && <small className="muted block">{a.breakdown.map((b) => `${b.label} ${b.points > 0 ? '+' : ''}${points(b.points)}`).join(', ') || 'No points yet'}
                {' '}<a href={`#/player/${a.id}`} onClick={(e) => e.stopPropagation()}>Profile →</a></small>}
            </span>
            <strong>{points(a.points)}</strong>
          </li>
        ))}
      </ol>
    </div>
  )
}

function ChallengesTab({ match }: { match: Match }) {
  const { status, token } = useSession()
  const { data: board, reload: reloadBoard } = useApi<BoardBet[]>(`/matches/${match.id}/bets`)
  const { data: teams } = useApi<Team[]>(status === 'ready' ? `/me/teams?match_id=${match.id}` : null)
  const { data: mine, reload: reloadMine } = useApi<MyBet[]>(status === 'ready' ? '/me/bets' : null)
  const [team, setTeam] = useState('')
  const [direct, setDirect] = useState(false)
  const [link, setLink] = useState<string | null>(null)
  const [msg, setMsg] = useState<string | null>(null)
  const toast = useToast()
  const myHere = (mine ?? []).filter((b) => b.match.id === match.id)

  const refresh = () => { reloadBoard(); reloadMine() }

  async function create() {
    try {
      const bet = await api<{ invite_path: string }>('/bets', token, {
        method: 'POST', body: { match_id: match.id, fantasy_team_id: team, visibility: direct ? 'direct' : 'board' } })
      setLink(`${window.location.origin}${window.location.pathname}${bet.invite_path}`)
      setMsg(null)
      toast(direct ? 'Challenge created: share the link' : 'Challenge posted on the board')
      refresh()
    } catch (e) {
      setMsg(errorText(e))
    }
  }

  async function accept(betId: string) {
    try {
      await api(`/bets/${betId}/fills`, token, { method: 'POST', body: { fantasy_team_id: team } })
      setMsg(null)
      toast('Challenge accepted. Good luck!')
      refresh()
    } catch (e) {
      setMsg(errorText(e))
    }
  }

  async function cancel(betId: string) {
    try {
      await api(`/bets/${betId}/cancel`, token, { method: 'POST' })
      toast('Challenge withdrawn')
    } catch (e) {
      toast(errorText(e), 'bad')
    } finally {
      refresh()
    }
  }

  return (
    <div>
      <p className="muted">Free head-to-head: your team against someone else's for bragging rights. No money involved.</p>
      {status === 'signed_out' && <NeedSignIn what="challenge other fans" />}
      {status === 'ready' && !match.locked && (
        teams && teams.length > 0 ? (
          <div className="card">
            <label>Your team for challenges<TeamPicker teams={teams} value={team} onChange={setTeam} /></label>
            <label className="inline"><input type="checkbox" checked={direct} onChange={(e) => setDirect(e.target.checked)} />
              Link only (don't post on the open board)</label>
            <button className="primary" disabled={!team} onClick={create}>Create challenge</button>
            {link && (
              <p className="small">Share this link: <code>{link}</code>{' '}
                <button className="link" onClick={() => navigator.clipboard?.writeText(link)}>Copy</button></p>
            )}
          </div>
        ) : <p><a href={`#/build/${match.id}`}>Build a team</a> to challenge someone.</p>
      )}
      {msg && <p className="error">{msg}</p>}

      <h3>Open board</h3>
      {board?.length === 0 && <p className="muted">No open challenges right now.</p>}
      <ul className="plain">
        {board?.map((b) => (
          <li key={b.id} className="card row between">
            <span><strong>{b.creator.team_name}</strong>{' '}
              <small className="muted">{b.creator.record.won}W {b.creator.record.lost}L {b.creator.record.tied}T</small></span>
            {b.is_mine ? <button className="link" onClick={() => cancel(b.id)}>Withdraw</button>
              : status === 'ready' && !match.locked && (
                <button className="primary narrow" disabled={!team} onClick={() => accept(b.id)} title={team ? '' : 'Choose your team above'}>Accept</button>)}
          </li>
        ))}
      </ul>

      {myHere.length > 0 && (
        <>
          <h3>Your challenges</h3>
          <ul className="plain">{myHere.map((b) => <MyBetRow key={b.id} b={b} onCancel={cancel} />)}</ul>
        </>
      )}
    </div>
  )
}

