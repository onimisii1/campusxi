import { points } from '../format'
import { useApi } from '../useApi'

type Board = {
  name: string
  status: string
  source: 'live' | 'final' | 'not_started'
  entries: { rank: number; entry_id: string; team_name: string; label: string; points: number; is_me: boolean }[]
}

const SOURCE = { live: 'Live: ranks change as the match goes on', final: 'Final standings', not_started: 'Ranks start at kick-off' }

export default function ContestBoard({ contestId }: { contestId: string }) {
  const { data, error, reload } = useApi<Board>(`/contests/${contestId}/leaderboard`)
  if (error) return <p className="error">{error}</p>
  if (!data) return <p className="muted">Loading…</p>
  return (
    <section>
      <button className="link" onClick={() => history.back()}>← Back</button>
      <h2>{data.name}</h2>
      <div className="row between">
        <span className="muted">{SOURCE[data.source]}</span>
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
