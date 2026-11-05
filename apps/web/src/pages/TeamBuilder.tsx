import { useEffect, useMemo, useState } from 'react'
import { api, ApiError } from '../api'
import { go, signInThenReturn } from '../router'
import { ROLES, TEAM_RULES, type Role } from '../rules'
import { useSession } from '../session'
import { errorText, useApi } from '../useApi'

type SquadAthlete = { id: string; name: string; position: string; lineup: 'starting' | 'bench' | null }
type MatchDetail = {
  id: string
  sport: string
  locked: boolean
  home_team: { id: string; name: string }
  away_team: { id: string; name: string }
  squads: { home: SquadAthlete[]; away: SquadAthlete[] }
}
type Team = { id: string; label: string; picks: { athlete_id: string; role: Role }[] }

export default function TeamBuilder({ matchId, teamId }: { matchId: string; teamId?: string }) {
  const { status, token } = useSession()
  const { data: match, error } = useApi<MatchDetail>(`/matches/${matchId}`)
  const { data: myTeams } = useApi<Team[]>(status === 'ready' && teamId ? `/me/teams?match_id=${matchId}` : null)
  const [picks, setPicks] = useState<Map<string, Role>>(new Map())
  const [errors, setErrors] = useState<string[]>([])
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    const team = myTeams?.find((t) => t.id === teamId)
    if (team) setPicks(new Map(team.picks.map((p) => [p.athlete_id, p.role])))
  }, [myTeams, teamId])

  const athletes = useMemo(() => {
    if (!match) return []
    return (['home', 'away'] as const).flatMap((side) =>
      match.squads[side].map((a) => ({ ...a, side, teamName: side === 'home' ? match.home_team.name : match.away_team.name })))
  }, [match])

  if (status === 'signed_out') {
    return <p className="card">Sign in to build a team. <button className="link" onClick={signInThenReturn}>Sign in</button></p>
  }
  if (error) return <p className="error">{error}</p>
  if (!match) return <p className="muted">Loading…</p>
  if (match.locked) return <p className="card">This match has locked, so teams can't change. <a href={`#/match/${matchId}`}>Back to the match</a></p>

  const rules = TEAM_RULES[match.sport]
  const chosen = athletes.filter((a) => picks.has(a.id))
  const full = chosen.length >= rules.size
  const roleOf = (role: Role) => [...picks].find(([, r]) => r === role)?.[0]

  function toggle(id: string) {
    const next = new Map(picks)
    if (next.has(id)) next.delete(id)
    else if (!full) next.set(id, 'none')
    setPicks(next)
  }

  function assign(id: string, role: Role) {
    const next = new Map(picks)
    for (const [a, r] of next) if (r === role) next.set(a, 'none')   // one of each role
    next.set(id, next.get(id) === role ? 'none' : role)
    setPicks(next)
  }

  async function save() {
    setBusy(true)
    setErrors([])
    const body = { picks: [...picks].map(([athlete_id, role]) => ({ athlete_id, role })) }
    try {
      if (teamId) await api(`/teams/${teamId}`, token, { method: 'PUT', body })
      else await api(`/matches/${matchId}/teams`, token, { method: 'POST', body })
      go(`/match/${matchId}`)
    } catch (e) {
      if (e instanceof ApiError && Array.isArray(e.details)) setErrors(e.details.map(String))
      else setErrors([errorText(e)])
    } finally {
      setBusy(false)
    }
  }

  const sideCounts = { home: chosen.filter((a) => a.side === 'home').length, away: chosen.filter((a) => a.side === 'away').length }

  return (
    <section className="builder">
      <a href={`#/match/${matchId}`}>← {match.home_team.name} vs {match.away_team.name}</a>
      <h2>{teamId ? 'Edit team' : 'Build your team'}</h2>

      <div className="counters">
        <span className={chosen.length === rules.size ? 'ok' : ''}>{chosen.length}/{rules.size} picked</span>
        {rules.groups.map((g) => {
          const n = chosen.filter((a) => g.positions.includes(a.position)).length
          const ok = n >= g.min && (g.max === undefined || n <= g.max)
          return <span key={g.name} className={ok ? 'ok' : ''}>{g.name} {n} ({g.min}{g.max ? `–${g.max}` : '+'})</span>
        })}
        <span className={sideCounts.home <= rules.maxPerSide ? '' : 'over'}>{match.home_team.name} {sideCounts.home}/{rules.maxPerSide}</span>
        <span className={sideCounts.away <= rules.maxPerSide ? '' : 'over'}>{match.away_team.name} {sideCounts.away}/{rules.maxPerSide}</span>
      </div>
      <p className="muted small">
        {ROLES.map((r) => `${r.label} ${r.multiplier}: ${athletes.find((a) => a.id === roleOf(r.role))?.name ?? 'not chosen'}`).join(' · ')}
      </p>

      {rules.groups.map((g) => (
        <div key={g.name}>
          <h3>{g.name}</h3>
          {athletes.filter((a) => g.positions.includes(a.position)).map((a) => {
            const on = picks.has(a.id)
            return (
              <div key={a.id} className={`pick ${on ? 'on' : ''}`}>
                <button className="pick-main" onClick={() => toggle(a.id)} disabled={!on && full} aria-pressed={on}
                  aria-label={`${a.name}, ${a.teamName}, ${a.position}${a.lineup ? `, ${a.lineup}` : ''}`}>
                  <span>{a.name}</span>
                  <small>{a.teamName} · {a.position}{a.lineup === 'starting' ? ' · starting' : a.lineup === 'bench' ? ' · bench' : ''}</small>
                </button>
                {on && (
                  <span className="roles">
                    {ROLES.map((r) => (
                      <button key={r.role} className={picks.get(a.id) === r.role ? 'role on' : 'role'}
                        onClick={() => assign(a.id, r.role)} aria-label={`${r.label} ${a.name}`}>{r.short}</button>
                    ))}
                  </span>
                )}
              </div>
            )
          })}
        </div>
      ))}

      <div className="save-bar">
        {errors.length > 0 && <ul className="error">{errors.map((e) => <li key={e}>{e}</li>)}</ul>}
        <button className="primary" disabled={busy || chosen.length !== rules.size} onClick={save}>
          {teamId ? 'Save changes' : 'Save team'}
        </button>
      </div>
    </section>
  )
}
