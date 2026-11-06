import { useState } from 'react'
import type { MatchCardData } from '../components/MatchCard'
import PageHeader from '../components/PageHeader'
import Skeleton from '../components/Skeleton'
import { kickoff, points } from '../format'
import { sideColours, teamCode } from '../teamStyle'
import { shareCard, type CardSpec } from '../shareCard'
import { useToast } from '../toast'
import { useApi } from '../useApi'

type TeamRef = { id: string; name: string; colour: string | null }
type Tournament = { id: string; name: string; sport: string; teams: TeamRef[] }
type Card = MatchCardData & {
  code: string | null; stage: string
  score: { home: number; away: number; walkover: boolean; final: boolean } | null
}
type Standing = { rank: number; shared: boolean; team: TeamRef; played: number; won: number; drawn: number; lost: number
  for: number; against: number; difference: number; points: number; form: string[] }
type Player = { rank: number; shared: boolean; athlete_id: string; name: string; team: TeamRef; matches: number
  goals?: number; assists?: number; points?: number; rebounds?: number; steals?: number; blocks?: number
  total?: string; average?: string }
type Stats = { kind: 'golden_boot' | 'mvp'; players: Player[] }
type Tie = { code: string | null; home: string; away: string; home_score?: number | null; away_score?: number | null
  winner?: string | null; placeholder: boolean; scheduled_start?: string; projected?: (string | null)[] }
type Bracket = { semis: Tie[]; final: Tie; third_place: Tie | null }

const TABS = ['Fixtures', 'Table', 'Stats', 'Bracket'] as const
type Tab = (typeof TABS)[number]

/** A competition at a glance: fixtures and results, league table, golden boot / MVP, knockouts. */
export default function TournamentPage({ tournamentId }: { tournamentId: string }) {
  const { data: t, error } = useApi<Tournament>(`/tournaments/${tournamentId}`)
  const [tab, setTab] = useState<Tab>('Table')
  if (error) return <p className="error">{error}</p>
  if (!t) return <Skeleton rows={6} />
  const statsLabel = t.sport === 'basketball' ? 'MVP' : t.sport === 'football' ? 'Golden boot' : 'Stats'
  const colours = Object.fromEntries(t.teams.map((x) => [x.name, x.colour]))
  return (
    <section>
      <PageHeader title={t.name} back="#/" subtitle={`${t.teams.length} teams · ${t.sport}`} />
      <div className="tabs" role="tablist">
        {TABS.map((x) => (
          <button key={x} role="tab" aria-selected={tab === x} className={tab === x ? 'tab on' : 'tab'}
            onClick={() => setTab(x)}>{x === 'Stats' ? statsLabel : x}</button>
        ))}
      </div>
      {tab === 'Fixtures' && <Fixtures tournamentId={t.id} name={t.name} />}
      {tab === 'Table' && <LeagueTable tournamentId={t.id} sport={t.sport} name={t.name} />}
      {tab === 'Stats' && <PlayerStats tournamentId={t.id} name={t.name} />}
      {tab === 'Bracket' && <BracketView tournamentId={t.id} colours={colours} />}
      <a className="row-card" href={`#/table/${t.id}`}><strong>Fantasy season table</strong><span aria-hidden>→</span></a>
    </section>
  )
}

function chipColour(team: { name: string; colour?: string | null }): string {
  return sideColours(team, { name: '' }).home
}

const shortDate = (iso: string) => new Date(iso).toLocaleDateString(undefined, { weekday: 'short', day: 'numeric', month: 'short' })

function ShareButton({ spec, filename }: { spec: () => CardSpec; filename: string }) {
  const toast = useToast()
  async function go() {
    try {
      if (await shareCard(spec(), filename) === 'downloaded') toast('Image saved: post it on WhatsApp or your status')
    } catch {
      toast('Could not make the image', 'bad')
    }
  }
  return <button className="share-btn" onClick={go}>⤴ Share as image</button>
}

function TeamChip({ team }: { team: { name: string; colour?: string | null } }) {
  const { home } = sideColours(team, { name: '' })
  const [r, g, b] = [1, 3, 5].map((i) => parseInt(home.slice(i, i + 2), 16))
  const light = 0.299 * r + 0.587 * g + 0.114 * b > 170     // white or yellow shirts get dark text
  return <span className={`team-chip ${light ? 'light' : ''}`} style={{ ['--chip' as string]: home }}>{teamCode(team.name)}</span>
}

function Fixtures({ tournamentId, name }: { tournamentId: string; name: string }) {
  const { data } = useApi<Card[]>(`/matches?tournament_id=${tournamentId}`, 60_000)
  if (!data) return <Skeleton rows={5} />
  const finished = data.filter((m) => m.score?.final)
  const lastDay = finished.length ? shortDate(finished[finished.length - 1].scheduled_start) : null
  const resultsSpec = (): CardSpec => ({
    title: 'Results', kicker: name, badge: lastDay ?? undefined, headers: ['', 'Score', ''],
    rows: finished.filter((m) => shortDate(m.scheduled_start) === lastDay).map((m) => ({
      rank: m.code ?? '', chip: { code: teamCode(m.home_team.name), colour: chipColour(m.home_team) },
      text: `v ${m.away_team.name}`, sub: m.score?.walkover ? 'Walkover' : 'Full time',
      cells: ['', m.score?.walkover ? 'Voided' : `${m.score!.home}–${m.score!.away}`, ''] })),
  })
  const days = new Map<string, Card[]>()
  for (const m of data) {
    const day = new Date(m.scheduled_start).toLocaleDateString(undefined, { weekday: 'long', day: 'numeric', month: 'long' })
    days.set(day, [...(days.get(day) ?? []), m])
  }
  return (
    <div>
      {lastDay && <ShareButton spec={resultsSpec} filename="results.png" />}
      {[...days].map(([day, list]) => (
        <div key={day}>
          <h3>{day}</h3>
          <ul className="plain fixture-list">
            {list.map((m) => (
              <li key={m.id}>
                <a href={`#/match/${m.id}`} className="fixture">
                  <span className="fx-code">{m.code ?? ''}</span>
                  <TeamChip team={m.home_team} />
                  <span className="fx-mid">
                    {m.score?.walkover
                      ? <b className="voided">Voided</b>
                      : m.score
                      ? <b className={m.score.final ? '' : 'live'}>{m.score.home} – {m.score.away}</b>
                      : <span>{new Date(m.scheduled_start).toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' })}</span>}
                  </span>
                  <TeamChip team={m.away_team} />
                  <span className="fx-note small muted">
                    {m.score?.walkover ? 'Walkover' : m.status === 'live' ? '● Live' : m.score?.final ? 'FT'
                      : m.stage !== 'league' ? m.stage.replace('_', ' ') : ''}
                  </span>
                </a>
              </li>
            ))}
          </ul>
        </div>
      ))}
    </div>
  )
}

function LeagueTable({ tournamentId, sport, name }: { tournamentId: string; sport: string; name: string }) {
  const { data } = useApi<{ rows: Standing[] }>(`/tournaments/${tournamentId}/standings`, 60_000)
  if (!data) return <Skeleton rows={6} />
  const football = sport === 'football'
  const played = data.rows.reduce((n, r) => n + r.played, 0) / 2
  const spec = (): CardSpec => ({
    title: 'League table', kicker: name, badge: `${played} ${played === 1 ? 'match' : 'matches'} played`,
    headers: football ? ['P', 'W', 'D', 'L', 'GD', 'Pts'] : ['P', 'W', 'L', 'PD', 'Pts'],
    rows: data.rows.map((r) => ({
      rank: `${r.rank}${r.shared ? '=' : ''}`, chip: { code: teamCode(r.team.name), colour: chipColour(r.team) },
      text: '', highlight: r.rank <= 4,
      cells: [String(r.played), String(r.won), ...(football ? [String(r.drawn)] : []), String(r.lost),
        r.difference > 0 ? `+${r.difference}` : String(r.difference), String(r.points)] })),
    note: 'Shaded: top 4 reach the semi-finals',
  })
  return (
    <div>
      <ShareButton spec={spec} filename="league-table.png" />
      <div className="table-scroll">
        <table className="board league">
          <thead>
            <tr><th>#</th><th>Team</th><th>P</th><th>W</th>{football && <th>D</th>}<th>L</th>
              <th>{football ? 'GD' : 'PD'}</th><th>Pts</th></tr>
          </thead>
          <tbody>
            {data.rows.map((r) => (
              <tr key={r.team.id} className={r.rank <= 4 ? 'qualify' : ''}>
                <td>{r.rank}{r.shared ? '=' : ''}</td>
                <td><span className="row-team"><TeamChip team={r.team} />
                  <span className="form">{r.form.map((f, i) => <i key={i} className={`f-${f}`} title={f} />)}</span></span></td>
                <td>{r.played}</td><td>{r.won}</td>{football && <td>{r.drawn}</td>}<td>{r.lost}</td>
                <td>{r.difference > 0 ? `+${r.difference}` : r.difference}</td>
                <td><b>{r.points}</b></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="muted small">Shaded: top 4 reach the semi-finals. {football ? 'Win 3 · Draw 1 · Loss 0' : 'Win 2 · Loss 0'}.
        {' '}“=” means level on every tiebreak.</p>
    </div>
  )
}

function PlayerStats({ tournamentId, name }: { tournamentId: string; name: string }) {
  const { data } = useApi<Stats>(`/tournaments/${tournamentId}/stats`, 60_000)
  if (!data) return <Skeleton rows={5} />
  if (data.players.length === 0) return <p className="muted">No stats yet: they appear once results are confirmed.</p>
  const mvp = data.kind === 'mvp'
  const spec = (): CardSpec => ({
    title: mvp ? 'Basketball MVP' : 'Golden boot', kicker: name, badge: `Top ${Math.min(10, data.players.length)}`,
    headers: mvp ? ['PTS', 'REB', 'AST', 'Total'] : ['MP', 'Ast', 'Goals'],
    rows: data.players.slice(0, 10).map((p) => ({
      rank: `${p.rank}${p.shared ? '=' : ''}`, chip: { code: teamCode(p.team.name), colour: chipColour(p.team) },
      text: p.name, highlight: p.rank === 1,
      cells: mvp ? [String(p.points), String(p.rebounds), String(p.assists), points(p.total ?? 0)]
        : [String(p.matches), String(p.assists), String(p.goals)] })),
    note: mvp ? 'Points ×1 · Rebounds ×1.2 · Assists ×1.5 · Steals ×2.5 · Blocks ×2'
      : 'Most goals, then assists, then fewer matches',
  })
  return (
    <div>
      <ShareButton spec={spec} filename={mvp ? 'mvp.png' : 'golden-boot.png'} />
      <p className="muted small">{mvp ? 'Points ×1 · Rebounds ×1.2 · Assists ×1.5 · Steals ×2.5 · Blocks ×2'
        : 'Most goals, then assists, then fewer matches'}</p>
      <div className="table-scroll">
        <table className="board league">
          <thead>
            <tr><th>#</th><th>Player</th><th>{mvp ? 'GP' : 'MP'}</th>
              {mvp ? <><th>PTS</th><th>REB</th><th>AST</th><th>STL</th><th>BLK</th><th>Total</th></>
                : <><th>Ast</th><th>Goals</th></>}</tr>
          </thead>
          <tbody>
            {data.players.map((p) => (
              <tr key={p.athlete_id}>
                <td>{p.rank}{p.shared ? '=' : ''}</td>
                <td><a className="row-team plain-link" href={`#/player/${p.athlete_id}`}><TeamChip team={p.team} />
                  <span className="ellipsis">{p.name}</span></a></td>
                <td>{p.matches}</td>
                {mvp
                  ? <><td>{p.points}</td><td>{p.rebounds}</td><td>{p.assists}</td><td>{p.steals}</td><td>{p.blocks}</td>
                    <td><b>{points(p.total ?? 0)}</b></td></>
                  : <><td>{p.assists}</td><td><b>{p.goals}</b></td></>}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function BracketView({ tournamentId, colours }: { tournamentId: string; colours: Record<string, string | null> }) {
  const { data } = useApi<Bracket>(`/tournaments/${tournamentId}/bracket`, 60_000)
  if (!data) return <Skeleton rows={3} />
  const side = (name: string, score?: number | null, won?: boolean) => (
    <div className={`tie-side ${won ? 'won' : ''}`}>
      {name in colours ? <TeamChip team={{ name, colour: colours[name] }} /> : <span className="muted small">{name}</span>}
      {score !== undefined && score !== null && <b>{score}</b>}
    </div>
  )
  const tie = (t: Tie, label: string) => (
    <div className={`tie card ${t.placeholder ? 'placeholder' : ''}`}>
      <span className="small muted">{t.code ?? label}{t.scheduled_start ? ` · ${kickoff(t.scheduled_start)}` : ''}</span>
      {side(t.home, t.home_score, !!t.winner && t.winner === t.home)}
      {side(t.away, t.away_score, !!t.winner && t.winner === t.away)}
      {t.projected && <span className="small muted">If it ended now: {t.projected.map((p) => p ?? '?').join(' v ')}</span>}
    </div>
  )
  return (
    <div className="bracket">
      <div><h3>Semi-finals</h3>{data.semis.map((s, i) => <div key={i}>{tie(s, `SF${i + 1}`)}</div>)}</div>
      <div><h3>Final</h3>{tie(data.final, 'Final')}{data.third_place && <>{tie(data.third_place, '3rd place')}</>}</div>
    </div>
  )
}
