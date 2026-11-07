import { useEffect, useRef, useState } from 'react'
import { api } from '../api'
import ContestCard from '../components/ContestCard'
import JoinContestSheet from '../components/JoinContestSheet'
import MyBetRow, { type MyBet } from '../components/MyBetRow'
import { openFor, type Contest } from '../contests'
import { naira, newIdempotencyKey, payLine, split, useWallet } from '../money'
import PageHeader from '../components/PageHeader'
import Shirt from '../components/Shirt'
import TeamBadge from '../components/TeamBadge'
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
  home_team: { id: string; name: string; colour: string | null; logo?: string | null }
  away_team: { id: string; name: string; colour: string | null; logo?: string | null }
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
type BoardBet = { id: string; kind: 'fantasy_h2h' | 'match_result'; stake_kobo: number; unmatched_kobo: number
  side: 'home' | 'away' | null; your_side: 'home' | 'away' | null; win_up_to_kobo: number; quote_kobo: number
  creator: { team_name: string; record: { won: number; lost: number; tied: number } }; is_mine: boolean }

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

  // Straight after building a team, offer (once) to enter it in a contest.
  const offered = useRef(false)
  useEffect(() => {
    const team = focus ? teams?.find((t) => t.id === focus) : undefined
    if (!team || !contests || offered.current) return
    offered.current = true
    if (openFor(contests, team.id).length > 0) setSheet({ team, fresh: true })
    window.history.replaceState(null, '', `#/match/${match.id}/teams`)
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

const STAKES = [0, 100_000, 200_000, 500_000]

function ChallengesTab({ match }: { match: Match }) {
  const { status, token } = useSession()
  const { data: board, reload: reloadBoard } = useApi<BoardBet[]>(`/matches/${match.id}/bets`)
  const { data: teams } = useApi<Team[]>(status === 'ready' ? `/me/teams?match_id=${match.id}` : null)
  const { data: mine, reload: reloadMine } = useApi<MyBet[]>(status === 'ready' ? '/me/bets' : null)
  const { data: w, reload: reloadWallet } = useWallet()
  const [team, setTeam] = useState('')
  const [stake, setStake] = useState(0)
  const [direct, setDirect] = useState(false)
  const [link, setLink] = useState<string | null>(null)
  const [msg, setMsg] = useState<string | null>(null)
  const [side, setSide] = useState<'home' | 'away' | null>(null)
  const [betStake, setBetStake] = useState(200_000)
  const [slice, setSlice] = useState<Record<string, string>>({})
  const toast = useToast()
  const myHere = (mine ?? []).filter((b) => b.match.id === match.id)
  const paid = !!w?.paid_play_enabled && w.kyc_status === 'verified'
  const resultBets = paid && !!w?.result_bets_enabled

  const refresh = () => { reloadBoard(); reloadMine(); reloadWallet() }
  const afford = (amount: number) => !amount || (w ? split(w, amount).short === 0 : false)
  const winFor = (amount: number) => 2 * amount - amount / 10

  async function create() {
    try {
      const bet = await api<{ invite_path: string }>('/bets', token, {
        method: 'POST', idempotencyKey: newIdempotencyKey(),
        body: { match_id: match.id, fantasy_team_id: team, stake_kobo: stake, visibility: direct ? 'direct' : 'board' } })
      setLink(`${window.location.origin}${window.location.pathname}${bet.invite_path}`)
      setMsg(null)
      toast(direct ? 'Challenge created: share the link' : 'Challenge posted on the board')
      refresh()
    } catch (e) {
      setMsg(errorText(e))
    }
  }

  async function createResultBet() {
    try {
      await api('/bets', token, { method: 'POST', idempotencyKey: newIdempotencyKey(),
        body: { kind: 'match_result', match_id: match.id, side, stake_kobo: betStake, visibility: 'board' } })
      toast(`Bet posted: ${side === 'home' ? match.home_team.name : match.away_team.name} to win`)
      setSide(null)
      refresh()
    } catch (e) {
      toast(errorText(e), 'bad')
    }
  }

  async function accept(b: BoardBet) {
    try {
      const body = b.kind === 'match_result'
        ? { amount_kobo: slice[b.id] ? Math.round(Number(slice[b.id]) * 100) : b.unmatched_kobo }
        : { fantasy_team_id: team }
      await api(`/bets/${b.id}/fills`, token, { method: 'POST', body, idempotencyKey: newIdempotencyKey() })
      setMsg(null)
      toast(b.kind === 'match_result' ? 'Bet taken. Good luck!' : 'Challenge accepted. Good luck!')
      refresh()
    } catch (e) {
      setMsg(errorText(e))
    }
  }

  async function cancel(betId: string) {
    try {
      await api(`/bets/${betId}/cancel`, token, { method: 'POST' })
      toast('Withdrawn: any stake is back in your wallet')
    } catch (e) {
      toast(errorText(e), 'bad')
    } finally {
      refresh()
    }
  }

  const teamName = (s: 'home' | 'away' | null) => (s === 'home' ? match.home_team.name : match.away_team.name)
  const h2h = (board ?? []).filter((b) => b.kind !== 'match_result')
  const results = (board ?? []).filter((b) => b.kind === 'match_result')

  return (
    <div>
      <p className="muted">Head-to-head: your team against someone else's, {paid
        ? 'for bragging rights or a stake (10% commission on winnings).' : 'for bragging rights.'}</p>
      {status === 'signed_out' && <NeedSignIn what="challenge other fans" />}
      {status === 'ready' && w && w.paid_play_enabled && w.kyc_status !== 'verified' && (
        <a className="notice block-link" href="#/verify">🪪 Verify your ID to play challenges for cash →</a>
      )}
      {status === 'ready' && !match.locked && (
        teams && teams.length > 0 ? (
          <div className="glass-card">
            <label>Your team for challenges<TeamPicker teams={teams} value={team} onChange={setTeam} /></label>
            {paid && (
              <div className="chip-row" role="group" aria-label="Stake">
                {STAKES.map((s) => (
                  <button key={s} className={`chip ${stake === s ? 'on' : ''}`} onClick={() => setStake(s)}>{s ? naira(s) : 'Free'}</button>
                ))}
              </div>
            )}
            {stake > 0 && w && <p className="small muted">Win {naira(winFor(stake))} · pays {payLine(w, stake)}</p>}
            <label className="inline"><input type="checkbox" checked={direct} onChange={(e) => setDirect(e.target.checked)} />
              Link only (don't post on the open board)</label>
            <button className="primary" disabled={!team || !afford(stake)} onClick={create}>
              {afford(stake) ? 'Create challenge' : 'Not enough in your wallet'}</button>
            {link && (
              <p className="small">Share this link: <code>{link}</code>{' '}
                <button className="link" onClick={() => navigator.clipboard?.writeText(link)}>Copy</button></p>
            )}
          </div>
        ) : <p><a href={`#/build/${match.id}`}>Build a team</a> to challenge someone.</p>
      )}
      {msg && <p className="error">{msg}</p>}

      <h3>Open board</h3>
      {h2h.length === 0 && <p className="muted">No open challenges right now.</p>}
      <ul className="plain">
        {h2h.map((b) => (
          <li key={b.id} className="glass-card row between">
            <span><strong>{b.creator.team_name}</strong>{' '}
              <small className="muted">{b.creator.record.won}W {b.creator.record.lost}L {b.creator.record.tied}T</small>
              <span className="small block">{b.stake_kobo ? `Stake ${naira(b.stake_kobo)} · win ${naira(b.win_up_to_kobo)}` : 'Free'}</span></span>
            {b.is_mine ? <button className="link" onClick={() => cancel(b.id)}>Withdraw</button>
              : status === 'ready' && !match.locked && (
                <button className="primary narrow" disabled={!team || !afford(b.stake_kobo)} onClick={() => accept(b)}
                  title={team ? '' : 'Choose your team above'}>Accept</button>)}
          </li>
        ))}
      </ul>

      {resultBets && (
        <>
          <h3>Who wins? (Home / Away bets)</h3>
          <p className="small muted">Back a side; others take the opposite side in slices. A draw refunds everyone. 10% commission on winnings.</p>
          {!match.locked && (
            <div className="glass-card">
              <div className="row gap">
                {(['home', 'away'] as const).map((s) => (
                  <button key={s} className={`side-btn ${side === s ? 'on' : ''}`} onClick={() => setSide(s)}>
                    <TeamBadge name={teamName(s)} colour={(s === 'home' ? match.home_team : match.away_team).colour}
                      logo={(s === 'home' ? match.home_team : match.away_team).logo} small />
                    <span>{teamName(s)}<small className="block">to win</small></span></button>
                ))}
              </div>
              {side && (
                <>
                  <div className="chip-row">
                    {STAKES.slice(1).map((s) => <button key={s} className={`chip ${betStake === s ? 'on' : ''}`} onClick={() => setBetStake(s)}>{naira(s)}</button>)}
                  </div>
                  <button className="primary" disabled={!afford(betStake)} onClick={createResultBet}>
                    {teamName(side)} to win · stake {naira(betStake)} → up to {naira(winFor(betStake))}</button>
                </>
              )}
            </div>
          )}
          <ul className="plain">
            {results.map((b) => (
              <li key={b.id} className="glass-card">
                <div className="row between">
                  <span><strong>{b.creator.team_name}</strong> backs {teamName(b.side)}
                    <span className="small block">{naira(b.unmatched_kobo)} left of {naira(b.stake_kobo)}</span></span>
                  {b.is_mine && b.unmatched_kobo === b.stake_kobo && <button className="link" onClick={() => cancel(b.id)}>Withdraw</button>}
                </div>
                {!b.is_mine && status === 'ready' && !match.locked && (
                  <div className="row gap">
                    <input inputMode="numeric" placeholder={String(b.unmatched_kobo / 100)} value={slice[b.id] ?? ''}
                      onChange={(e) => setSlice({ ...slice, [b.id]: e.target.value })} aria-label="Your stake in naira" />
                    <button className="primary narrow" onClick={() => accept(b)}>Take {teamName(b.your_side)}</button>
                  </div>
                )}
              </li>
            ))}
            {results.length === 0 && <li className="muted">No Home/Away bets yet.</li>}
          </ul>
        </>
      )}

      {myHere.length > 0 && (
        <>
          <h3>Your challenges</h3>
          <ul className="plain">{myHere.map((b) => <MyBetRow key={b.id} b={b} onCancel={cancel} />)}</ul>
        </>
      )}
    </div>
  )
}
