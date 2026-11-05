import { useApi } from '../useApi'
import { Table } from './ContestBoard'

type Season = {
  name: string
  matches_confirmed: number
  entries: { rank: number; team_name: string; points: number; matches: number; is_me: boolean }[]
}

export default function SeasonTable({ tournamentId }: { tournamentId: string }) {
  const { data, error } = useApi<Season>(`/tournaments/${tournamentId}/leaderboard`)
  if (error) return <p className="error">{error}</p>
  if (!data) return <p className="muted">Loading…</p>
  return (
    <section>
      <a href="#/">← Matches</a>
      <h2>{data.name}</h2>
      <p className="muted">Season table: your best team from each finished match, added up.
        {' '}{data.matches_confirmed} match{data.matches_confirmed === 1 ? '' : 'es'} counted so far.</p>
      <Table rows={data.entries.map((e) => ({ key: e.team_name, rank: e.rank, name: e.team_name, points: e.points,
        me: e.is_me, note: `${e.matches} played` }))} />
    </section>
  )
}
