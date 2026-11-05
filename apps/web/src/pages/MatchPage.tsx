import { useState } from 'react'
import { api } from '../api'
import MyBetRow, { type MyBet } from '../components/MyBetRow'
import { countdown, kickoff, points, statusLabel } from '../format'
import { signInThenReturn } from '../router'
import { useSession } from '../session'
import { errorText, useApi } from '../useApi'

type Match = {
  id: string
  tournament: string
  home_team: { name: string }
  away_team: { name: string }
  scheduled_start: string
  venue: string | null
  status: string
  locked: boolean
  seconds_to_lock: number
}
type Contest = {
  id: string
  name: string
  prize_text: string | null
  capacity: number
  entries: number
  spots_left: number
  team_cap: number
  status: string
  locked: boolean
  my_entries: { entry_id: string; fantasy_team_id: string; label: string; final_rank: number | null }[]
}
type Team = { id: string; label: string; picks: { display_name: string; role: string }[] }
type Breakdown = { total_points: number; picks: { display_name: string; role: string; points: number }[] }
type LiveAthlete = { id: string; name: string; position: string; side: string; points: number;
  breakdown: { label: string; points: number }[] }
type Live = { source: string | null; result: { home_score: number; away_score: number } | null; athletes: LiveAthlete[] }
type BoardBet = { id: string; creator: { team_name: string; record: { won: number; lost: number; tied: number } }; is_mine: boolean }

const TABS = ['Contests', 'My teams', 'Live', 'Challenges'] as const
type Tab = (typeof TABS)[number]

export default function MatchPage({ matchId }: { matchId: string }) {
  const { data: match, error } = useApi<Match>(`/matches/${matchId}`)
  const [tab, setTab] = useState<Tab>('Contests')

  if (error) return <p className="error">{error}</p>
  if (!match) return <p className="muted">Loading…</p>

  return (
    <section>
      <a href="#/">← Matches</a>
      <p className="muted">{match.tournament} · {kickoff(match.scheduled_start)}{match.venue ? ` · ${match.venue}` : ''}</p>
      <h2>{match.home_team.name} vs {match.away_team.name}</h2>
      <p>
        {match.locked
          ? <span className="badge">{statusLabel(match.status)}</span>
          : <span className="badge">{countdown(match.seconds_to_lock)}</span>}
      </p>
      <div className="tabs" role="tablist">
        {TABS.map((t) => (
          <button key={t} role="tab" aria-selected={tab === t} className={tab === t ? 'tab on' : 'tab'}
            onClick={() => setTab(t)}>{t}</button>
        ))}
      </div>
      {tab === 'Contests' && <ContestsTab match={match} />}
      {tab === 'My teams' && <TeamsTab match={match} />}
      {tab === 'Live' && <LiveTab match={match} />}
      {tab === 'Challenges' && <ChallengesTab match={match} />}
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

function ContestsTab({ match }: { match: Match }) {
  const { status, token } = useSession()
  const { data: contests, reload } = useApi<Contest[]>(`/matches/${match.id}/contests`)
  const { data: teams } = useApi<Team[]>(status === 'ready' ? `/me/teams?match_id=${match.id}` : null)
  const [choice, setChoice] = useState<Record<string, string>>({})
  const [msg, setMsg] = useState<Record<string, string>>({})

  async function join(contestId: string) {
    try {
      await api(`/contests/${contestId}/entries`, token, { method: 'POST', body: { fantasy_team_id: choice[contestId] } })
      setMsg({ ...msg, [contestId]: '' })
      reload()
    } catch (e) {
      setMsg({ ...msg, [contestId]: errorText(e) })
    }
  }

  async function leave(entryId: string) {
    try {
      await api(`/entries/${entryId}`, token, { method: 'DELETE' })
    } finally {
      reload()
    }
  }

  return (
    <div>
      {contests?.map((c) => (
        <div key={c.id} className="card">
          <div className="row between">
            <strong>{c.name}</strong>
            <span className="badge good">Free</span>
          </div>
          {c.prize_text && <p>🏆 {c.prize_text}</p>}
          <p className="muted">{c.entries}/{c.capacity} teams · up to {c.team_cap} per player</p>
          {c.my_entries.length > 0 && (
            <ul className="plain">
              {c.my_entries.map((e) => (
                <li key={e.entry_id} className="row between">
                  <span>Your {e.label}{e.final_rank ? ` · finished #${e.final_rank}` : ''}</span>
                  {!c.locked && <button className="link" onClick={() => leave(e.entry_id)}>Leave</button>}
                </li>
              ))}
            </ul>
          )}
          {!c.locked && c.status === 'open' && (status === 'ready' ? (
            teams && teams.length > 0 ? (
              <div className="row">
                <TeamPicker teams={teams} value={choice[c.id] ?? ''} onChange={(id) => setChoice({ ...choice, [c.id]: id })}
                  exclude={c.my_entries.map((e) => e.fantasy_team_id)} />
                <button className="primary narrow" disabled={!choice[c.id]} onClick={() => join(c.id)}>Join</button>
              </div>
            ) : <p><a href={`#/build/${match.id}`}>Build a team</a> to join.</p>
          ) : status === 'signed_out' ? <NeedSignIn what="join" /> : null)}
          {msg[c.id] && <p className="error">{msg[c.id]}</p>}
          <a href={`#/contest/${c.id}`}>Leaderboard →</a>
        </div>
      ))}
    </div>
  )
}

function TeamsTab({ match }: { match: Match }) {
  const { status } = useSession()
  const { data: teams } = useApi<Team[]>(status === 'ready' ? `/me/teams?match_id=${match.id}` : null)
  if (status === 'signed_out') return <NeedSignIn what="build teams" />
  return (
    <div>
      {teams?.length === 0 && <p className="muted">You have no teams for this match yet.</p>}
      {teams?.map((t) => <TeamCard key={t.id} team={t} match={match} />)}
      {!match.locked && (teams?.length ?? 0) < 10 && (
        <a className="primary as-button" href={`#/build/${match.id}`}>+ New team</a>
      )}
    </div>
  )
}

function TeamCard({ team, match }: { team: Team; match: Match }) {
  const { data: bd } = useApi<Breakdown>(match.locked ? `/teams/${team.id}/breakdown` : null)
  const roleTag = (r: string) => ({ captain: ' (C)', vice_captain: ' (VC)', key: ' (K)' } as Record<string, string>)[r] ?? ''
  return (
    <div className="card">
      <div className="row between">
        <strong>{team.label}</strong>
        {bd ? <strong>{points(bd.total_points)} pts</strong>
          : !match.locked && <a href={`#/build/${match.id}/${team.id}`}>Edit</a>}
      </div>
      <p className="muted small">
        {(bd?.picks ?? team.picks).map((p) => `${p.display_name}${roleTag(p.role)}${'points' in p ? ` ${points((p as { points: number }).points)}` : ''}`).join(' · ')}
      </p>
    </div>
  )
}

function LiveTab({ match }: { match: Match }) {
  const { data: live, reload } = useApi<Live>(`/matches/${match.id}/live`)
  const [open, setOpen] = useState<string | null>(null)
  if (!match.locked) return <p className="muted">Live points appear once the match kicks off.</p>
  return (
    <div>
      <div className="row between">
        <span className="muted">{live?.source === 'official' ? 'Final, official stats' : 'Live from the sideline scorer'}</span>
        <button className="link" onClick={reload}>Refresh</button>
      </div>
      {live?.result && <p><strong>Final score {live.result.home_score}–{live.result.away_score}</strong></p>}
      <ol className="log">
        {live?.athletes.map((a) => (
          <li key={a.id} onClick={() => setOpen(open === a.id ? null : a.id)}>
            <span>{a.name} <small className="muted">{a.position} · {a.side === 'home' ? match.home_team.name : match.away_team.name}</small>
              {open === a.id && <small className="muted block">{a.breakdown.map((b) => `${b.label} ${b.points > 0 ? '+' : ''}${points(b.points)}`).join(', ') || 'No points yet'}</small>}
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
  const myHere = (mine ?? []).filter((b) => b.match.id === match.id)

  const refresh = () => { reloadBoard(); reloadMine() }

  async function create() {
    try {
      const bet = await api<{ invite_path: string }>('/bets', token, {
        method: 'POST', body: { match_id: match.id, fantasy_team_id: team, visibility: direct ? 'direct' : 'board' } })
      setLink(`${window.location.origin}${window.location.pathname}${bet.invite_path}`)
      setMsg(null)
      refresh()
    } catch (e) {
      setMsg(errorText(e))
    }
  }

  async function accept(betId: string) {
    try {
      await api(`/bets/${betId}/fills`, token, { method: 'POST', body: { fantasy_team_id: team } })
      setMsg(null)
      refresh()
    } catch (e) {
      setMsg(errorText(e))
    }
  }

  async function cancel(betId: string) {
    try {
      await api(`/bets/${betId}/cancel`, token, { method: 'POST' })
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

