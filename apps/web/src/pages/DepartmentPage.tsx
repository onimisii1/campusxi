import { useState } from 'react'
import PageHeader from '../components/PageHeader'
import Skeleton from '../components/Skeleton'
import TeamBadge from '../components/TeamBadge'
import { kickoff } from '../format'
import { useApi } from '../useApi'

type TeamRef = { name: string; colour: string | null; logo: string | null }
type Fixture = {
  id: string; code: string | null; stage: string | null; scheduled_start: string; status: string; home: boolean
  opponent: TeamRef; locked: boolean; score: { for: number; against: number } | null; outcome: 'W' | 'D' | 'L' | null
  walkover: boolean
}
type Player = { athlete_id: string; name: string; matches: number; goals?: number; assists?: number; points?: number
  rebounds?: number; total?: string }
export type SportBlock = {
  team_id: string; sport: string; tournament: { id: string; name: string }
  table: { rank: number; shared: boolean; played: number; won: number; drawn: number; lost: number; points: number
    form: string[] } | null
  squad: { id: string; name: string; position: string; is_captain: boolean }[]
  captain: string | null; results: Fixture[]; next: Fixture | null; upcoming: Fixture[]; top_players: Player[]
}
type Department = { name: string; colour: string | null; logo: string | null; sports: SportBlock[] }

const SPORT_LABEL: Record<string, string> = { football: '⚽ Football', basketball: '🏀 Basketball', volleyball: '🏐 Volleyball' }

/** A department (CPE, EEE, ...): every sport it plays, with table place, form, fixtures, results,
 *  top performers and the squad (captain first). */
export default function DepartmentPage({ teamId }: { teamId: string }) {
  const { data, error } = useApi<Department>(`/teams/${teamId}/department`, 60_000)
  const [pick, setPick] = useState<string | null>(null)
  if (error) return <section><PageHeader title="Department" back="#/" /><p className="error">{error}</p></section>
  if (!data) return <section><PageHeader title="Department" back="#/" /><Skeleton hero rows={4} /></section>
  const block = data.sports.find((s) => s.sport === pick)
    ?? data.sports.find((s) => s.team_id === teamId) ?? data.sports[0]
  const t = block.table

  return (
    <section>
      <PageHeader title={data.name} back={`#/tournament/${block.tournament.id}`} subtitle="Department" />
      <div className="dept-hero glass-card">
        <TeamBadge name={data.name} logo={data.logo} />
        <div className="dept-hero-text">
          <strong className="dept-name">{data.name}</strong>
          {block.captain && <span className="muted small">Captain · {block.captain}</span>}
          {t && t.form.length > 0 && <span className="form">{t.form.map((f, i) => <i key={i} className={`f-${f}`} title={f} />)}</span>}
        </div>
      </div>

      {data.sports.length > 1 && (
        <div className="chip-row" role="group" aria-label="Sport">
          {data.sports.map((s) => (
            <button key={s.sport} className={`chip ${s === block ? 'on' : ''}`} onClick={() => setPick(s.sport)}>
              {SPORT_LABEL[s.sport] ?? s.sport}</button>
          ))}
        </div>
      )}

      {t && (
        <div className="dept-stats">
          <span><b>{t.rank}{t.shared ? '=' : ''}</b><small>Position</small></span>
          <span><b>{t.played}</b><small>Played</small></span>
          <span><b>{t.won}-{block.sport === 'football' ? `${t.drawn}-` : ''}{t.lost}</b><small>{block.sport === 'football' ? 'W-D-L' : 'W-L'}</small></span>
          <span className="lime"><b>{t.points}</b><small>Points</small></span>
        </div>
      )}

      {block.next && (
        <>
          <div className="section-head"><h3>Next match</h3></div>
          <FixtureRow f={block.next} me={data.name} />
        </>
      )}

      <div className="section-head"><h3>Results</h3>
        <a href={`#/tournament/${block.tournament.id}`}>Table</a></div>
      {block.results.length === 0 && <p className="muted">No results yet.</p>}
      <ul className="plain dept-list">{block.results.map((f) => <li key={f.id}><FixtureRow f={f} me={data.name} /></li>)}</ul>

      {block.top_players.length > 0 && (
        <>
          <div className="section-head"><h3>{block.sport === 'basketball' ? 'Top performers' : 'Top scorers'}</h3></div>
          <ul className="plain glass-card dept-players">
            {block.top_players.map((p) => (
              <li key={p.athlete_id}><a className="plain-link grow" href={`#/player/${p.athlete_id}`}>{p.name}</a>
                <span className="muted small">{block.sport === 'basketball'
                  ? `${p.points ?? 0} pts · ${p.rebounds ?? 0} reb`
                  : `${p.goals ?? 0} goal${p.goals === 1 ? '' : 's'} · ${p.assists ?? 0} ast`}</span></li>
            ))}
          </ul>
        </>
      )}

      <div className="section-head"><h3>Squad</h3><span className="muted small">{block.squad.length} players</span></div>
      <ul className="plain glass-card dept-squad">
        {block.squad.map((a) => (
          <li key={a.id}>
            <span className="pos-tag">{a.position}</span>
            <a className="plain-link grow" href={`#/player/${a.id}`}>{a.name}</a>
            {a.is_captain && <span className="captain-tag" title="Captain">C</span>}
          </li>
        ))}
      </ul>
    </section>
  )
}

function FixtureRow({ f, me }: { f: Fixture; me: string }) {
  return (
    <a className="dept-fixture glass-card" href={`#/match/${f.id}`}>
      <span className={`dept-outcome ${f.outcome ?? 'next'}`}>{f.outcome ?? (f.code ?? 'vs')}</span>
      <span className="grow">
        <strong>{f.home ? `${me} v ${f.opponent.name}` : `${f.opponent.name} v ${me}`}</strong>
        <span className="muted small block">{kickoff(f.scheduled_start)}{f.code ? ` · ${f.code}` : ''}
          {f.walkover ? ' · walkover' : ''}</span>
      </span>
      {f.score && <b className="dept-score">{f.score.for}–{f.score.against}</b>}
      {!f.score && <TeamBadge name={f.opponent.name} logo={f.opponent.logo} small />}
    </a>
  )
}
