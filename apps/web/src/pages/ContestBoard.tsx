import { useEffect, useState } from 'react'
import { api } from '../api'
import ContestCard from '../components/ContestCard'
import PageHeader from '../components/PageHeader'
import Skeleton from '../components/Skeleton'
import UpdatedStamp from '../components/UpdatedStamp'
import { naira, type Contest } from '../contests'
import { points } from '../format'
import { useSession } from '../session'
import { useToast } from '../toast'
import { errorText, LIVE_REFRESH_MS, useApi } from '../useApi'

type Entry = { rank: number; shared?: boolean; entry_id: string; team_name: string; label: string; points: number; is_me: boolean;
  joined_minute: number | null }
type Board = { match_id: string; name: string; status: string; source: 'live' | 'final' | 'not_started'; entries: Entry[] }
type Payout = {
  free: boolean
  prize_text: string | null
  min_entries: number
  max_entries: number
  entries: number
  maximum: Table | null
  current: Table | null
}
type Table = { entries: number; pool_kobo: number; ranks_paid: number; rows: { from: number; to: number; prize_kobo: number }[] }
type Rules = {
  team_size: number
  max_per_side: number
  max_teams_per_match: number
  multipliers: { captain: number; vice_captain: number; key: number }
  positions: { name: string; min: number; max: number | null }[]
  late_join: { until_share: number; fee_multiplier: number }
  scoring: { event: string; points: number }[]
}
type MatchInfo = { id: string; sport: string; home_team: { name: string }; away_team: { name: string }; status: string }

const TABS = ['Winnings', 'Rules', 'Entries'] as const
type Tab = (typeof TABS)[number]

/** Contest page: the card with its Join button, then Winnings / Rules / Entries (Leaderboard once live). */
export default function ContestBoard({ contestId }: { contestId: string }) {
  const [poll, setPoll] = useState(true)
  const { data: board, error, reload: reloadBoard, updatedAt, stale } =
    useApi<Board>(`/contests/${contestId}/leaderboard`, poll ? LIVE_REFRESH_MS : undefined)
  const matchId = board?.match_id
  const { data: match } = useApi<MatchInfo>(matchId ? `/matches/${matchId}` : null)
  const { status } = useSession()
  const { data: contests, reload: reloadContests } = useApi<Contest[]>(matchId ? `/matches/${matchId}/contests` : null)
  const { data: teams } = useApi<{ id: string; label: string }[]>(status === 'ready' && matchId ? `/me/teams?match_id=${matchId}` : null)
  const [tab, setTab] = useState<Tab | 'Leaderboard'>('Winnings')

  useEffect(() => {
    if (board) setPoll(board.source === 'live')
  }, [board])
  useEffect(() => {
    if (board && board.source !== 'not_started') setTab((t) => (t === 'Winnings' ? 'Leaderboard' : t))
  }, [board?.source])  // eslint-disable-line react-hooks/exhaustive-deps

  if (error) return <p className="error">{error}</p>
  if (!board) return <Skeleton hero rows={4} />
  const contest = contests?.find((c) => c.id === contestId)
  const started = board.source !== 'not_started'
  const tabs: (Tab | 'Leaderboard')[] = started ? ['Leaderboard', 'Winnings', 'Rules'] : [...TABS]
  const refresh = () => { reloadBoard(); reloadContests() }

  return (
    <section>
      <PageHeader title={board.name} back={`#/match/${board.match_id}/contests`}
        subtitle={match ? `${match.home_team.name} vs ${match.away_team.name}` : undefined} />
      {contest && <ContestCard contest={contest} matchId={board.match_id} teams={teams} onChanged={refresh} />}
      <div className="tabs" role="tablist">
        {tabs.map((t) => (
          <button key={t} role="tab" aria-selected={tab === t} className={tab === t ? 'tab on' : 'tab'} onClick={() => setTab(t)}>{t}</button>
        ))}
      </div>
      {tab === 'Winnings' && <Winnings contestId={contestId} />}
      {tab === 'Rules' && match && <RulesTab sport={match.sport} />}
      {tab === 'Entries' && <Entries board={board} contest={contest} onChanged={refresh} />}
      {tab === 'Leaderboard' && (
        <>
          <div className="row between">
            <span className="muted small">{board.source === 'final' ? 'Final standings' : 'Live: ranks change as the match goes on'}
              {board.source === 'live' && <UpdatedStamp at={updatedAt} stale={stale} />}</span>
            {board.source === 'live' && <button className="link" onClick={reloadBoard}>Refresh</button>}
          </div>
          <Table rows={board.entries.map((e) => ({ key: e.entry_id, rank: e.rank, shared: e.shared, name: `${e.team_name} · ${e.label}`,
            points: e.points, me: e.is_me, note: e.joined_minute !== null ? `joined ${e.joined_minute}′` : undefined }))} />
        </>
      )}
    </section>
  )
}

function Winnings({ contestId }: { contestId: string }) {
  const { data: p } = useApi<Payout>(`/contests/${contestId}/payout-preview`)
  const [view, setView] = useState<'maximum' | 'current'>('maximum')
  if (!p) return <Skeleton rows={4} />
  const table = p[view] ?? p.maximum
  return (
    <div>
      <div className="minmax">
        <div><span>Min entries</span><b>{p.min_entries}</b></div>
        <div><span>Max entries</span><b>{p.max_entries.toLocaleString()}</b></div>
      </div>
      {p.free ? (
        <div className="card">
          <p><strong>Free contest</strong>: no entry fee.</p>
          {p.prize_text ? <p>🏆 {p.prize_text}</p> : <p>Play for bragging rights and the season table.</p>}
          <p className="muted small">The top 40% finish in the money once paid contests open; the top 25% in profit.</p>
        </div>
      ) : (
        <>
          <div className="toggle" role="tablist" aria-label="Prize table">
            <button role="tab" aria-selected={view === 'maximum'} className={view === 'maximum' ? 'on' : ''} onClick={() => setView('maximum')}>If it fills</button>
            <button role="tab" aria-selected={view === 'current'} className={view === 'current' ? 'on' : ''} disabled={!p.current}
              onClick={() => setView('current')}>Right now</button>
          </div>
          {table && (
            <>
              <p className="muted small">Prize pool {naira(table.pool_kobo)} · {table.ranks_paid} ranks paid · {table.entries} entries</p>
              <ul className="prize-list">
                {table.rows.map((r) => (
                  <li key={r.from}><span>{r.from === r.to ? r.from : `${r.from} – ${r.to}`}</span><b>{naira(r.prize_kobo)}</b></li>
                ))}
              </ul>
            </>
          )}
        </>
      )}
    </div>
  )
}

function RulesTab({ sport }: { sport: string }) {
  const { data: r } = useApi<Rules>(`/sports/${sport}/rules`)
  if (!r) return <Skeleton rows={4} />
  const pct = Math.round(r.late_join.until_share * 100)
  return (
    <div>
      <div className="rule-tiles">
        <div className="tile-a"><b>{r.team_size}</b><span>Select {r.team_size} players from both teams</span></div>
        <div className="tile-b"><b>{r.max_per_side}</b><span>At most {r.max_per_side} from one team</span></div>
      </div>
      <div className="rule-tiles">
        <div className="tile-c"><b>C ×{r.multipliers.captain}</b><span>Captain</span></div>
        <div className="tile-c"><b>VC ×{r.multipliers.vice_captain}</b><span>Vice-captain</span></div>
        <div className="tile-c"><b>K ×{r.multipliers.key}</b><span>Key player</span></div>
      </div>
      <p className="small">Positions: {r.positions.map((g) => `${g.name} ${g.min}${g.max ? `–${g.max}` : '+'}`).join(' · ')}.
        Up to {r.max_teams_per_match} teams per match.</p>
      <p className="notice small">⏱ Late joining: until {pct}% of the match. Points recorded before you join don't count;
        paid entries cost {Math.round((r.late_join.fee_multiplier - 1) * 100)}% more and are paid by the same prize table.</p>
      <h3>Scoring</h3>
      <ul className="prize-list">
        {r.scoring.map((s) => (
          <li key={s.event}><span>{s.event}</span><b className={s.points < 0 ? 'neg' : ''}>{s.points > 0 ? '+' : ''}{points(s.points)}</b></li>
        ))}
      </ul>
    </div>
  )
}

function Entries({ board, contest, onChanged }: { board: Board; contest?: Contest; onChanged: () => void }) {
  const { token } = useSession()
  const toast = useToast()
  const players = new Map<string, { teams: number; me: boolean }>()
  for (const e of board.entries) {
    const p = players.get(e.team_name) ?? { teams: 0, me: e.is_me }
    players.set(e.team_name, { teams: p.teams + 1, me: p.me || e.is_me })
  }

  async function leave(entryId: string) {
    try {
      await api(`/entries/${entryId}`, token, { method: 'DELETE' })
      toast('Left the contest')
      onChanged()
    } catch (e) {
      toast(errorText(e), 'bad')
    }
  }

  return (
    <div>
      {contest && contest.my_entries.length > 0 && !contest.locked && (
        <ul className="plain my-list">
          {contest.my_entries.map((e) => (
            <li key={e.entry_id} className="row between"><span>Your {e.label}</span>
              <button className="link" onClick={() => leave(e.entry_id)}>Leave</button></li>
          ))}
        </ul>
      )}
      {players.size === 0 && <p className="muted">No one has joined yet. Be the first.</p>}
      <ul className="entry-list">
        {[...players].map(([name, p]) => (
          <li key={name} className={p.me ? 'me' : ''}>
            <span className="avatar small" aria-hidden>{name.slice(0, 2).toUpperCase()}</span>
            <span className="grow">{name}{p.me ? ' (you)' : ''}</span>
            <span className="muted small">{p.teams} team{p.teams === 1 ? '' : 's'}</span>
          </li>
        ))}
      </ul>
    </div>
  )
}

/** Leaderboard. Equal points share a rank, shown "2=", and the next rank is skipped (1, 2=, 2=, 4). */
export function Table({ rows }: {
  rows: { key: string; rank: number; shared?: boolean; name: string; points: number; me: boolean; note?: string }[]
}) {
  if (rows.length === 0) return <p className="muted">No entries yet.</p>
  return (
    <table className="board">
      <thead><tr><th>#</th><th>Team</th><th>Pts</th></tr></thead>
      <tbody>
        {rows.map((r) => (
          <tr key={r.key} className={r.me ? 'me' : ''}>
            <td>{r.rank}{r.shared ? '=' : ''}</td>
            <td>{r.name}{r.note && <small className="muted"> {r.note}</small>}</td>
            <td>{points(r.points)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}
