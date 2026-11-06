import { useState } from 'react'
import { api, ApiError } from '../../api'
import PageHeader from '../../components/PageHeader'
import Skeleton from '../../components/Skeleton'
import { kickoff } from '../../format'
import { useSession } from '../../session'
import { useToast } from '../../toast'
import { errorText, useApi } from '../../useApi'
import { matchLabel, nextStep, STATUS_LABEL, type AdminMatch, type AdminMatches } from './adminTypes'

const TABS = ['Matches', 'Squads', 'Imports', 'Knockouts'] as const
type Tab = (typeof TABS)[number]

export default function AdminTournament({ tournamentId }: { tournamentId: string }) {
  const { data, error, reload } = useApi<AdminMatches>(`/admin/tournaments/${tournamentId}/matches`, 30_000)
  const [tab, setTab] = useState<Tab>('Matches')
  if (error) return <p className="error">{error}</p>
  if (!data) return <Skeleton rows={5} />
  const t = data.tournament
  return (
    <section>
      <PageHeader title={t.name} back="#/admin" subtitle={`${t.sport} · ${t.status}`} />
      <div className="tabs" role="tablist">
        {TABS.map((x) => (
          <button key={x} role="tab" aria-selected={tab === x} className={tab === x ? 'tab on' : 'tab'}
            onClick={() => setTab(x)}>{x}</button>
        ))}
      </div>
      {tab === 'Matches' && <Matches data={data} />}
      {tab === 'Squads' && <Squads tournamentId={t.id} />}
      {tab === 'Imports' && <MatchLength tournamentId={t.id} minutes={t.match_minutes} onDone={reload} />}
      {tab === 'Imports' && <Imports tournamentId={t.id} published={t.status === 'published'} onDone={reload} />}
      {tab === 'Knockouts' && <Knockouts tournamentId={t.id} published={t.status === 'published'} onDone={reload} />}
    </section>
  )
}

function Matches({ data }: { data: AdminMatches }) {
  const now = new Date(data.now).getTime()
  const open = data.matches.filter((m) => !['confirmed', 'abandoned'].includes(m.status))
  const today = open.filter((m) => new Date(m.scheduled_start).getTime() - now < 12 * 3600_000)
  const later = open.filter((m) => !today.includes(m))
  const done = data.matches.filter((m) => !open.includes(m))
  const group = (title: string, list: AdminMatch[]) => list.length > 0 && (
    <>
      <h3>{title}</h3>
      <ul className="plain">{list.map((m) => <MatchRow key={m.id} m={m} tournamentId={data.tournament.id} />)}</ul>
    </>
  )
  return (
    <div>
      {data.matches.length === 0 && <p className="muted">No matches yet: import fixtures first.</p>}
      {group('Today and overdue', today)}
      {group('Coming up', later)}
      {group('Finished', done)}
    </div>
  )
}

function MatchRow({ m, tournamentId }: { m: AdminMatch; tournamentId: string }) {
  const step = nextStep(m)
  return (
    <li>
      <a className="card admin-row" href={`#/admin/m/${tournamentId}/${m.id}`}>
        <div className="row between">
          <strong>{matchLabel(m)}</strong>
          {m.home_score !== null
            ? <strong>{m.walkover ? 'Walkover · voided' : `${m.home_score}–${m.away_score}`}</strong>
            : <span className={`badge ${m.status === 'live' ? 'bad' : ''}`}>{STATUS_LABEL[m.status] ?? m.status}</span>}
        </div>
        <div className="row between small muted">
          <span>{kickoff(m.scheduled_start)}{m.stage !== 'league' ? ` · ${m.stage.replace('_', ' ')}` : ''}</span>
          {step && <span className="next-step">Next: {step} →</span>}
        </div>
      </a>
    </li>
  )
}

const IMPORTS = [
  { kind: 'squads', label: 'Squads', help: 'team, athlete, position, jersey' },
  { kind: 'fixtures', label: 'Fixtures', help: 'home_team, away_team, scheduled_start, venue, code, stage' },
  { kind: 'results', label: 'Past results', help: 'code, home_team, away_team, home_score, away_score, played_at' },
  { kind: 'result-stats', label: 'Past stat lines', help: 'code, team, athlete, goals, assists (or pts, reb, ast, stl, blk)' },
] as const

type RowError = { row: number | null; message: string }

function Imports({ tournamentId, published, onDone }: { tournamentId: string; published: boolean; onDone: () => void }) {
  const { token } = useSession()
  const toast = useToast()
  const [errors, setErrors] = useState<RowError[] | null>(null)

  async function upload(kind: string, file: File | undefined) {
    if (!file) return
    setErrors(null)
    try {
      const res = await api<Record<string, number>>(`/admin/tournaments/${tournamentId}/${kind}`, token,
        { method: 'POST', csv: await file.text() })
      toast(`Imported: ${Object.entries(res).map(([k, v]) => `${v} ${k.replace(/_/g, ' ')}`).join(', ')}`)
      onDone()
    } catch (e) {
      if (e instanceof ApiError && Array.isArray(e.details)) setErrors(e.details as RowError[])
      toast(errorText(e), 'bad')
    }
  }

  async function publish() {
    try {
      await api(`/admin/tournaments/${tournamentId}/publish`, token, { method: 'POST' })
      toast('Published: fans can see it now')
      onDone()
    } catch (e) {
      toast(errorText(e), 'bad')
    }
  }

  return (
    <div>
      <p className="muted small">Upload a CSV (UTF-8, with a header row). A file with any bad row is rejected whole.</p>
      {IMPORTS.map((x) => (
        <label key={x.kind} className="card upload">
          <strong>{x.label}</strong>
          <span className="muted small block">{x.help}</span>
          <input type="file" accept=".csv,text/csv" onChange={(e) => { upload(x.kind, e.target.files?.[0]); e.target.value = '' }} />
        </label>
      ))}
      {errors && (
        <div className="card warn">
          <strong>Nothing was imported. Fix these rows:</strong>
          <ul className="small">{errors.map((er, i) => <li key={i}>{er.row ? `Row ${er.row}: ` : ''}{er.message}</li>)}</ul>
        </div>
      )}
      {!published && <button className="primary" onClick={publish}>Publish tournament</button>}
    </div>
  )
}

type Team = { id: string; name: string }
type Bracket = { suggested_semis: ([Team | null, Team | null])[] }

function Knockouts({ tournamentId, published, onDone }: { tournamentId: string; published: boolean; onDone: () => void }) {
  const { token } = useSession()
  const toast = useToast()
  const { data: t } = useApi<{ teams: Team[] }>(published ? `/tournaments/${tournamentId}` : null)
  const { data: b, reload } = useApi<Bracket>(published ? `/tournaments/${tournamentId}/bracket` : null)
  const [form, setForm] = useState({ stage: 'semi', home: '', away: '', start: '', code: '', venue: '' })
  if (!published) return <p className="muted">Publish the tournament first.</p>
  const set = (k: keyof typeof form) => (e: { target: { value: string } }) => setForm({ ...form, [k]: e.target.value })

  async function add() {
    try {
      await api(`/admin/tournaments/${tournamentId}/knockout`, token, { method: 'POST', body: {
        stage: form.stage, home_team_id: form.home, away_team_id: form.away, code: form.code || null,
        venue: form.venue || null, scheduled_start: new Date(form.start).toISOString() } })
      toast(`${form.code || 'Knockout match'} added`)
      setForm({ ...form, home: '', away: '', code: '' })
      reload()
      onDone()
    } catch (e) {
      toast(errorText(e), 'bad')
    }
  }

  return (
    <div>
      {b && (
        <div className="card">
          <strong>Suggested from the table</strong>
          <ul className="small">
            {b.suggested_semis.map(([h, a], i) => (
              <li key={i}>SF{i + 1}: {h?.name ?? '?'} v {a?.name ?? '?'}{' '}
                {h && a && <button className="link" onClick={() => setForm({ ...form, stage: 'semi', home: h.id, away: a.id,
                  code: `SF${i + 1}` })}>Use</button>}</li>
            ))}
          </ul>
          <p className="muted small">The pairing rule isn't fixed: you choose the real pairs.</p>
        </div>
      )}
      <div className="card form-grid">
        <label>Stage
          <select value={form.stage} onChange={set('stage')}>
            <option value="semi">Semi-final</option><option value="final">Final</option>
            <option value="third_place">3rd place</option>
          </select>
        </label>
        <label>Code<input value={form.code} onChange={set('code')} placeholder="SF1" maxLength={12} /></label>
        <label>Home
          <select value={form.home} onChange={set('home')}>
            <option value="">Choose</option>{t?.teams.map((x) => <option key={x.id} value={x.id}>{x.name}</option>)}
          </select>
        </label>
        <label>Away
          <select value={form.away} onChange={set('away')}>
            <option value="">Choose</option>{t?.teams.map((x) => <option key={x.id} value={x.id}>{x.name}</option>)}
          </select>
        </label>
        <label>Kick-off<input type="datetime-local" value={form.start} onChange={set('start')} /></label>
        <label>Venue<input value={form.venue} onChange={set('venue')} /></label>
        <button className="primary" disabled={!form.home || !form.away || !form.start} onClick={add}>Add match</button>
      </div>
    </div>
  )
}

function MatchLength({ tournamentId, minutes, onDone }: { tournamentId: string; minutes: number; onDone: () => void }) {
  const { token } = useSession()
  const toast = useToast()
  const [value, setValue] = useState(String(minutes))
  async function save() {
    try {
      const r = await api<{ matches_updated: number }>(`/admin/tournaments/${tournamentId}`, token,
        { method: 'PATCH', body: { match_minutes: Number(value) } })
      toast(`Match length ${value} min: ${r.matches_updated} upcoming matches updated`)
      onDone()
    } catch (e) {
      toast(errorText(e), 'bad')
    }
  }
  return (
    <div className="card form-grid">
      <label>Match length (minutes)<input inputMode="numeric" value={value} onChange={(e) => setValue(e.target.value)} /></label>
      <button className="primary" disabled={!value || Number(value) === minutes} onClick={save}>Save length</button>
      <p className="muted small" style={{ gridColumn: '1 / -1' }}>Sets the late-join cutoff (67%) and clean-sheet minutes.
        Matches already under way keep their length.</p>
    </div>
  )
}

type SquadRow = { id: string; display_name: string; position: string; active: boolean; team: string; has_played: boolean }

function Squads({ tournamentId }: { tournamentId: string }) {
  const { data, reload } = useApi<{ positions: string[]; athletes: SquadRow[] }>(`/admin/tournaments/${tournamentId}/squads`)
  const [team, setTeam] = useState('')
  if (!data) return <Skeleton rows={6} />
  const teams = [...new Set(data.athletes.map((a) => a.team))]
  const shown = data.athletes.filter((a) => a.team === (team || teams[0]))
  return (
    <div>
      <p className="muted small">Check names and positions against the team sheets. Positions lock once a player has played.</p>
      <div className="chip-row sort-row">
        {teams.map((t) => (
          <button key={t} className={`chip ${(team || teams[0]) === t ? 'on' : ''}`} onClick={() => setTeam(t)}>{t}</button>
        ))}
      </div>
      <ul className="plain">{shown.map((a) => <SquadEditRow key={a.id} a={a} positions={data.positions} onDone={reload} />)}</ul>
    </div>
  )
}

function SquadEditRow({ a, positions, onDone }: { a: SquadRow; positions: string[]; onDone: () => void }) {
  const { token } = useSession()
  const toast = useToast()
  const [name, setName] = useState(a.display_name)
  const [pos, setPos] = useState(a.position)
  const dirty = name.trim() !== a.display_name || pos !== a.position
  async function save(body: Record<string, unknown>) {
    try {
      await api(`/admin/athletes/${a.id}`, token, { method: 'PATCH', body })
      toast(`${name} updated`)
      onDone()
    } catch (e) {
      toast(errorText(e), 'bad')
    }
  }
  return (
    <li className={`squad-edit ${a.active ? '' : 'inactive'}`}>
      <input value={name} onChange={(e) => setName(e.target.value)} aria-label="Name" />
      <select value={pos} onChange={(e) => setPos(e.target.value)} disabled={a.has_played} aria-label="Position"
        title={a.has_played ? 'Fixed: this player has played' : undefined}>
        {positions.map((p) => <option key={p} value={p}>{p}</option>)}
      </select>
      {dirty
        ? <button className="join-btn" onClick={() => save({ display_name: name, position: pos })}>Save</button>
        : <button className="link" onClick={() => save({ active: !a.active })}>{a.active ? 'Remove' : 'Restore'}</button>}
    </li>
  )
}
