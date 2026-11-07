import PageHeader from '../components/PageHeader'
import Skeleton from '../components/Skeleton'
import { useApi } from '../useApi'
import { Table } from './ContestBoard'

type Season = {
  name: string
  matches_confirmed: number
  entries: { rank: number; shared?: boolean; team_name: string; points: number; matches: number; is_me: boolean }[]
}

export default function SeasonTable({ tournamentId }: { tournamentId: string }) {
  const { data, error } = useApi<Season>(`/tournaments/${tournamentId}/leaderboard`)
  if (error) return <p className="error">{error}</p>
  if (!data) return <Skeleton rows={6} />
  return (
    <section>
      <PageHeader title={data.name} back={`#/tournament/${tournamentId}`} subtitle="Fantasy season table" />
      <p className="muted">Season table: your best team from each finished match, added up.
        {' '}{data.matches_confirmed} match{data.matches_confirmed === 1 ? '' : 'es'} counted so far.</p>
      <Table rows={data.entries.map((e) => ({ key: e.team_name, rank: e.rank, shared: e.shared, name: e.team_name, points: e.points,
        me: e.is_me, note: `${e.matches} played` }))} />
    </section>
  )
}
