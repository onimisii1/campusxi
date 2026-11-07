import { useEffect, useState } from 'react'
import { api } from '../../api'
import PageHeader from '../../components/PageHeader'
import Skeleton from '../../components/Skeleton'
import { kickoff } from '../../format'
import { MATCH_PHOTO, pickPhoto, resize, uploadImage } from '../../media'
import { useSession } from '../../session'
import { useToast } from '../../toast'
import { errorText, useApi } from '../../useApi'
import { matchLabel, nextStep, STATUS_LABEL, type AdminMatches } from './adminTypes'

type SquadPlayer = { id: string; name: string; position: string; lineup: 'starting' | 'bench' | null }
type MatchDetail = { id: string; sport: string; locked: boolean; squads: { home: SquadPlayer[]; away: SquadPlayer[] } }
type Scorer = { id: string; team_name: string }
type Reconcile = {
  status: string
  scorers: { user_id: string; role: string; team_name: string; home_score: number | null; away_score: number | null;
    submitted_at: string | null }[]
  event_mismatches: unknown[]
  points_differences: unknown[]
  agreed: boolean
}

const STARTERS = { football: 11, basketball: 5, volleyball: 7 } as Record<string, number>

/** Everything an admin does for one match on the day, top to bottom in match-day order. */
export default function AdminMatchPage({ tournamentId, matchId }: { tournamentId: string; matchId: string }) {
  const { token } = useSession()
  const toast = useToast()
  const { data: list, reload } = useApi<AdminMatches>(`/admin/tournaments/${tournamentId}/matches`, 15_000)
  const m = list?.matches.find((x) => x.id === matchId)
  const published = list?.tournament.status === 'published'
  const { data: detail, reload: reloadDetail } = useApi<MatchDetail>(published ? `/matches/${matchId}` : null)

  if (!list) return <Skeleton rows={5} />
  if (!m) return <p className="error">Match not found.</p>
  const done = m.status === 'confirmed' || m.status === 'abandoned'
  const refresh = () => { reload(); reloadDetail() }

  async function act(path: string, body: unknown, ok: string, confirmText?: string) {
    if (confirmText && !window.confirm(confirmText)) return
    try {
      await api(`/admin/matches/${matchId}/${path}`, token, { method: 'POST', body })
      toast(ok)
      refresh()
    } catch (e) {
      toast(errorText(e), 'bad')
    }
  }

  function delay(minutes: number) {
    const from = Math.max(Date.now(), new Date(m!.scheduled_start).getTime())
    act('postpone', { new_start: new Date(from + minutes * 60_000).toISOString() },
      `Kick-off moved ${minutes} minutes: teams reopen until then`)
  }

  const step = nextStep(m)
  return (
    <section>
      <PageHeader title={matchLabel(m)} back={`#/admin/t/${tournamentId}`}
        subtitle={`${kickoff(m.scheduled_start)}${m.venue ? ` · ${m.venue}` : ''}`} />
      <div className="card">
        <div className="row between">
          <span className={`badge ${m.status === 'live' ? 'bad' : done ? 'good' : ''}`}>{STATUS_LABEL[m.status] ?? m.status}</span>
          {m.home_score !== null && <strong>{m.walkover ? 'Walkover · voided' : `${m.home_score}–${m.away_score}`}</strong>}
        </div>
        {m.kicked_off_at && <p className="small muted">Kicked off {kickoff(m.kicked_off_at)}</p>}
        {step && <p className="small"><strong>Next:</strong> {step}</p>}
      </div>
      {!published && <p className="notice">Publish the tournament (Imports tab) before match day.</p>}

      {!done && published && (
        <div className="admin-actions">
          {!m.kicked_off_at && m.status !== 'postponed' && (
            <button className="primary big-action" onClick={() => act('kickoff', undefined,
              'Kicked off: the match clock is running')}>▶ Kick off now</button>
          )}
          {['scheduled', 'lineup_out'].includes(m.status) && (
            <div className="row gap">
              <button className="sheet-btn" onClick={() => delay(10)}>Delay 10 min</button>
              <button className="sheet-btn" onClick={() => delay(20)}>Delay 20 min</button>
            </div>
          )}
          <div className="row gap">
            <button className="sheet-btn" onClick={() => act('walkover', { winner: 'home' }, `Walkover to ${m.home_team}`,
              `${m.away_team} didn't turn up? ${m.home_team} gets the win; fantasy for this match is voided.`)}>
              Walkover: {m.home_team} win</button>
            <button className="sheet-btn" onClick={() => act('walkover', { winner: 'away' }, `Walkover to ${m.away_team}`,
              `${m.home_team} didn't turn up? ${m.away_team} gets the win; fantasy for this match is voided.`)}>
              Walkover: {m.away_team} win</button>
          </div>
        </div>
      )}

      {published && (
        <button className="sheet-btn photo-btn" onClick={async () => {
          const file = await pickPhoto()
          if (!file) return
          try {
            await uploadImage(`/admin/matches/${matchId}/photo`, token, await resize(file, MATCH_PHOTO))
            toast('Match photo uploaded: it shows behind the match screen')
          } catch (e) {
            toast(e instanceof Error && !('code' in e) ? e.message : errorText(e), 'bad')
          }
        }}>📷 Upload match photo</button>
      )}
      {!done && published && <Scorers matchId={matchId} assigned={m.scorers} onDone={refresh} />}
      {!done && detail && !detail.locked && <Lineup detail={detail} onDone={refresh} />}
      {['live', 'final_pending'].includes(m.status) && <Result matchId={matchId} onDone={refresh} />}
    </section>
  )
}

function Scorers({ matchId, assigned, onDone }: { matchId: string; assigned: number; onDone: () => void }) {
  const { token } = useSession()
  const toast = useToast()
  const { data: people } = useApi<Scorer[]>('/admin/users?role=scorer')
  const [pick, setPick] = useState<[string, string]>(['', ''])

  async function save() {
    try {
      await api(`/admin/matches/${matchId}/scorers`, token, { method: 'POST', body: { user_ids: pick.filter(Boolean) } })
      toast('Scorers assigned')
      onDone()
    } catch (e) {
      toast(errorText(e), 'bad')
    }
  }

  return (
    <details className="card" open={assigned === 0}>
      <summary><strong>Scorers</strong> <span className="muted small">{assigned ? `${assigned} assigned` : 'none yet'}</span></summary>
      {people?.length === 0 && <p className="muted small">Nobody at your school has the scorer role yet.</p>}
      {(['Primary (drives live points)', 'Second scorer (optional)'] as const).map((label, i) => (
        <label key={label}>{label}
          <select value={pick[i]} onChange={(e) => setPick(i === 0 ? [e.target.value, pick[1]] : [pick[0], e.target.value])}>
            <option value="">Choose</option>
            {people?.map((p) => <option key={p.id} value={p.id}>{p.team_name}</option>)}
          </select>
        </label>
      ))}
      <button className="primary" disabled={!pick[0]} onClick={save}>Assign scorers</button>
    </details>
  )
}

function Lineup({ detail, onDone }: { detail: MatchDetail; onDone: () => void }) {
  const { token } = useSession()
  const toast = useToast()
  const cap = STARTERS[detail.sport] ?? 11
  const [starting, setStarting] = useState<Set<string>>(new Set())
  useEffect(() => {
    setStarting(new Set([...detail.squads.home, ...detail.squads.away].filter((p) => p.lineup === 'starting').map((p) => p.id)))
  }, [detail])

  const toggle = (id: string) => {
    const next = new Set(starting)
    if (next.has(id)) next.delete(id)
    else next.add(id)
    setStarting(next)
  }

  async function publish() {
    const all = [...detail.squads.home, ...detail.squads.away]
    try {
      await api(`/admin/matches/${detail.id}/lineup`, token, { method: 'POST', body: {
        starters: [...starting], bench: all.filter((p) => !starting.has(p.id)).map((p) => p.id) } })
      toast('Line-up published: fans can see who starts')
      onDone()
    } catch (e) {
      toast(errorText(e), 'bad')
    }
  }

  const count = (side: SquadPlayer[]) => side.filter((p) => starting.has(p.id)).length
  return (
    <details className="card" open>
      <summary><strong>Line-up</strong> <span className="muted small">tick who starts (up to {cap} a side)</span></summary>
      <div className="lineups admin-lineups">
        {(['home', 'away'] as const).map((side) => (
          <div key={side}>
            <p className="small"><strong>{count(detail.squads[side])}</strong> starting</p>
            {detail.squads[side].map((p) => (
              <label key={p.id} className={`check-row ${starting.has(p.id) ? 'on' : ''}`}>
                <input type="checkbox" checked={starting.has(p.id)} onChange={() => toggle(p.id)} />
                <span>{p.name}</span><small className="muted">{p.position}</small>
              </label>
            ))}
          </div>
        ))}
      </div>
      <button className="primary" disabled={starting.size === 0 || count(detail.squads.home) > cap || count(detail.squads.away) > cap}
        onClick={publish}>Publish line-up</button>
    </details>
  )
}

function Result({ matchId, onDone }: { matchId: string; onDone: () => void }) {
  const { token } = useSession()
  const toast = useToast()
  const { data: r, reload } = useApi<Reconcile>(`/admin/matches/${matchId}/reconcile`, 15_000)
  const [score, setScore] = useState({ home: '', away: '', official: '' })
  useEffect(() => {
    const primary = r?.scorers.find((s) => s.role === 'primary' && s.submitted_at)
    if (primary && !score.official) {
      setScore({ home: String(primary.home_score ?? ''), away: String(primary.away_score ?? ''), official: primary.user_id })
    }
  }, [r])  // eslint-disable-line react-hooks/exhaustive-deps
  if (!r) return null

  async function confirm() {
    try {
      await api(`/admin/matches/${matchId}/confirm`, token, { method: 'POST', body: {
        home_score: Number(score.home), away_score: Number(score.away), official_scorer_id: score.official } })
      toast('Result confirmed: tables and leaderboards updated')
      onDone()
    } catch (e) {
      toast(errorText(e), 'bad')
      reload()
    }
  }

  return (
    <div className="card">
      <strong>Result</strong>
      <ul className="plain small">
        {r.scorers.map((s) => (
          <li key={s.user_id} className="row between">
            <span>{s.team_name} <span className="muted">({s.role})</span></span>
            <span>{s.submitted_at ? `${s.home_score}–${s.away_score} submitted` : 'still scoring'}</span>
          </li>
        ))}
      </ul>
      {r.scorers.length === 2 && (
        <p className={`small ${r.agreed ? '' : 'error'}`}>{r.agreed ? '✓ Both scorers agree'
          : `${r.event_mismatches.length} event and ${r.points_differences.length} points differences to check`}</p>
      )}
      {r.status === 'final_pending' && (
        <div className="form-grid">
          <label>Home<input inputMode="numeric" value={score.home} onChange={(e) => setScore({ ...score, home: e.target.value })} /></label>
          <label>Away<input inputMode="numeric" value={score.away} onChange={(e) => setScore({ ...score, away: e.target.value })} /></label>
          <label>Official stats
            <select value={score.official} onChange={(e) => setScore({ ...score, official: e.target.value })}>
              {r.scorers.filter((s) => s.submitted_at).map((s) => <option key={s.user_id} value={s.user_id}>{s.team_name}</option>)}
            </select>
          </label>
          <button className="primary" disabled={score.home === '' || score.away === '' || !score.official} onClick={confirm}>
            Confirm result</button>
        </div>
      )}
    </div>
  )
}
