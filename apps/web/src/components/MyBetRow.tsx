import { points } from '../format'

export type MyBet = {
  id: string
  status: string
  visibility: string
  invite_path: string
  match: { id: string; home_team: string; away_team: string; scheduled_start: string; status: string }
  my_side: string
  my_team: string
  opponent: string | null
  my_points: number | null
  opponent_points: number | null
  result: 'won' | 'lost' | 'tie' | null
}

const STATUS: Record<string, string> = {
  open: 'Waiting for a taker', matched: 'Accepted', cancelled: 'Cancelled', void: 'Void',
}

export default function MyBetRow({ b, onCancel, showMatch = false }: {
  b: MyBet; onCancel?: (id: string) => void; showMatch?: boolean
}) {
  const label = b.result ? { won: 'Won', lost: 'Lost', tie: 'Tied' }[b.result] : STATUS[b.status] ?? b.status
  return (
    <li className="card">
      {showMatch && <a href={`#/match/${b.match.id}`} className="small">{b.match.home_team} vs {b.match.away_team}</a>}
      <div className="row between">
        <span>Your {b.my_team} vs {b.opponent ?? '…'}</span>
        <span className={`badge ${b.result === 'won' ? 'good' : b.result === 'lost' ? 'bad' : ''}`}>{label}</span>
      </div>
      {b.my_points !== null && <p className="small">{points(b.my_points)} – {points(b.opponent_points)} pts</p>}
      {b.status === 'open' && b.my_side === 'creator' && onCancel && (
        <button className="link" onClick={() => onCancel(b.id)}>Withdraw</button>
      )}
    </li>
  )
}
