import { useEffect, useState } from 'react'
import PageHeader from '../components/PageHeader'
import Skeleton from '../components/Skeleton'
import UpdatedStamp from '../components/UpdatedStamp'
import { points } from '../format'
import { LIVE_REFRESH_MS, useApi } from '../useApi'

type Board = {
  match_id: string
  name: string
  status: string
  source: 'live' | 'final' | 'not_started'
  entries: { rank: number; entry_id: string; team_name: string; label: string; points: number; is_me: boolean }[]
}

const SOURCE = { live: 'Live: ranks change as the match goes on', final: 'Final standings', not_started: 'Ranks start at kick-off' }

export default function ContestBoard({ contestId }: { contestId: string }) {
  // Poll only while the contest is live; a final or not-yet-started board doesn't change.
  const [poll, setPoll] = useState(true)
  const { data, error, reload, updatedAt, stale } =
    useApi<Board>(`/contests/${contestId}/leaderboard`, poll ? LIVE_REFRESH_MS : undefined)
  useEffect(() => {
    if (data) setPoll(data.source === 'live')
  }, [data])
  if (error) return <p className="error">{error}</p>
  if (!data) return <Skeleton rows={6} />
  return (
    <section>
      <PageHeader title={data.name} back={`#/match/${data.match_id}/contests`} subtitle="Leaderboard" />
      <div className="row between">
        <span className="muted small">{SOURCE[data.source]}{data.source === 'live' && <UpdatedStamp at={updatedAt} stale={stale} />}</span>
        {data.source === 'live' && <button className="link" onClick={reload}>Refresh</button>}
      </div>
      <Table rows={data.entries.map((e) => ({ key: e.entry_id, rank: e.rank, name: `${e.team_name} · ${e.label}`,
        points: e.points, me: e.is_me }))} />
    </section>
  )
}

export function Table({ rows }: { rows: { key: string; rank: number; name: string; points: number; me: boolean; note?: string }[] }) {
  if (rows.length === 0) return <p className="muted">No entries yet.</p>
  return (
    <table className="board">
      <thead><tr><th>#</th><th>Team</th><th>Pts</th></tr></thead>
      <tbody>
        {rows.map((r) => (
          <tr key={r.key} className={r.me ? 'me' : ''}>
            <td>{r.rank}</td>
            <td>{r.name}{r.note && <small className="muted"> {r.note}</small>}</td>
            <td>{points(r.points)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}
