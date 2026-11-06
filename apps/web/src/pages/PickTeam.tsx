import { useEffect, useMemo, useRef, useState } from 'react'
import { api, ApiError } from '../api'
import PageHeader from '../components/PageHeader'
import Shirt from '../components/Shirt'
import { deadline } from '../format'
import { go, signInThenReturn } from '../router'
import { ROLES, TEAM_RULES, type Group, type Role } from '../rules'
import { useSession } from '../session'
import { shortName, sideColours, teamCode } from '../teamStyle'
import { errorText, useApi } from '../useApi'

type SquadAthlete = { id: string; name: string; position: string; lineup: 'starting' | 'bench' | null }
type MatchDetail = {
  id: string
  sport: string
  locked: boolean
  scheduled_start: string
  home_team: { id: string; name: string }
  away_team: { id: string; name: string }
  squads: { home: SquadAthlete[]; away: SquadAthlete[] }
}
type Team = { id: string; label: string; picks: { athlete_id: string; role: Role }[] }
type Athlete = SquadAthlete & { side: 'home' | 'away'; teamName: string; colour: string; code: string }

const BADGE: Record<Role, string> = { none: '', captain: 'C', vice_captain: 'V', key: 'K' }

export default function PickTeam({ matchId, teamId }: { matchId: string; teamId?: string }) {
  const { status, token } = useSession()
  const { data: match, error } = useApi<MatchDetail>(`/matches/${matchId}`)
  const { data: myTeams } = useApi<Team[]>(status === 'ready' && teamId ? `/me/teams?match_id=${matchId}` : null)
  const [picks, setPicks] = useState<Map<string, Role>>(new Map())
  const [view, setView] = useState<'pitch' | 'list'>('pitch')
  const [sheet, setSheet] = useState<string | null>(null)
  const [groupFilter, setGroupFilter] = useState<string | null>(null)
  const [sideFilter, setSideFilter] = useState<'all' | 'home' | 'away'>('all')
  const [errors, setErrors] = useState<string[]>([])
  const [busy, setBusy] = useState(false)
  const poolRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const team = myTeams?.find((t) => t.id === teamId)
    if (team) setPicks(new Map(team.picks.map((p) => [p.athlete_id, p.role])))
  }, [myTeams, teamId])

  const athletes: Athlete[] = useMemo(() => {
    if (!match) return []
    const colours = sideColours(match.home_team.name, match.away_team.name)
    return (['home', 'away'] as const).flatMap((side) => {
      const teamName = side === 'home' ? match.home_team.name : match.away_team.name
      return match.squads[side].map((a) => ({ ...a, side, teamName, colour: colours[side], code: teamCode(teamName) }))
    })
  }, [match])

  const back = `#/match/${matchId}/teams`
  if (status === 'signed_out') {
    return (
      <section>
        <PageHeader title="Pick Team" back={`#/match/${matchId}`} />
        <p className="card">Sign in to pick a team. <button className="link" onClick={signInThenReturn}>Sign in</button></p>
      </section>
    )
  }
  if (error) return <p className="error">{error}</p>
  if (!match) return <p className="muted">Loading…</p>
  if (match.locked) {
    return (
      <section>
        <PageHeader title="Pick Team" back={back} />
        <p className="card">This match has locked, so teams can't change.</p>
      </section>
    )
  }

  const rules = TEAM_RULES[match.sport]
  const chosen = athletes.filter((a) => picks.has(a.id))
  const full = chosen.length >= rules.size
  const inGroup = (g: Group, list: Athlete[]) => list.filter((a) => g.positions.includes(a.position))
  const groupOf = (a: Athlete) => rules.groups.find((g) => g.positions.includes(a.position))!
  const sideCount = (side: 'home' | 'away') => chosen.filter((a) => a.side === side).length

  function blockReason(a: Athlete): string | null {
    if (picks.has(a.id)) return null
    if (full) return 'Team is full'
    const g = groupOf(a)
    if (g.max !== undefined && inGroup(g, chosen).length >= g.max) return `Max ${g.max} ${g.name.toLowerCase()}`
    if (sideCount(a.side) >= rules.maxPerSide) return `Max ${rules.maxPerSide} from ${a.teamName}`
    return null
  }

  function add(id: string) {
    setPicks(new Map(picks).set(id, 'none'))
  }

  function remove(id: string) {
    const next = new Map(picks)
    next.delete(id)
    setPicks(next)
    setSheet(null)
  }

  function assign(id: string, role: Role) {
    const next = new Map(picks)
    for (const [a, r] of next) if (r === role) next.set(a, 'none')
    next.set(id, picks.get(id) === role ? 'none' : role)
    setPicks(next)
    setSheet(null)
  }

  function needMore(g: Group) {
    setGroupFilter(g.name)
    poolRef.current?.scrollIntoView({ behavior: 'smooth' })
  }

  async function save() {
    setBusy(true)
    setErrors([])
    const body = { picks: [...picks].map(([athlete_id, role]) => ({ athlete_id, role })) }
    try {
      if (teamId) await api(`/teams/${teamId}`, token, { method: 'PUT', body })
      else await api(`/matches/${matchId}/teams`, token, { method: 'POST', body })
      go(`/match/${matchId}/teams`)
    } catch (e) {
      setErrors(e instanceof ApiError && Array.isArray(e.details) ? e.details.map(String) : [errorText(e)])
    } finally {
      setBusy(false)
    }
  }

  const pool = athletes.filter((a) => !picks.has(a.id)
    && (!groupFilter || groupOf(a).name === groupFilter)
    && (sideFilter === 'all' || a.side === sideFilter))
  const sheetAthlete = athletes.find((a) => a.id === sheet)
  const rolesSet = ROLES.filter((r) => [...picks.values()].includes(r.role)).length

  return (
    <section className="pick-team">
      <PageHeader title={teamId ? 'Edit team' : 'Pick Team'} back={back}
        subtitle={`${match.home_team.name} vs ${match.away_team.name} · Deadline ${deadline(match.scheduled_start)}`} />

      <div className="chip-row" aria-live="polite">
        <span className={`chip ${chosen.length === rules.size ? 'ok' : ''}`}>{chosen.length}/{rules.size} players</span>
        <span className={`chip ${rolesSet === 3 ? 'ok' : ''}`}>C · VC · K {rolesSet}/3</span>
        <span className="chip">{teamCode(match.home_team.name)} {sideCount('home')}/{rules.maxPerSide}</span>
        <span className="chip">{teamCode(match.away_team.name)} {sideCount('away')}/{rules.maxPerSide}</span>
      </div>

      <div className="toggle" role="tablist" aria-label="View">
        <button role="tab" aria-selected={view === 'pitch'} className={view === 'pitch' ? 'on' : ''} onClick={() => setView('pitch')}>Pitch</button>
        <button role="tab" aria-selected={view === 'list'} className={view === 'list' ? 'on' : ''} onClick={() => setView('list')}>List</button>
      </div>

      {view === 'pitch' ? (
        <div className={`pitch ${match.sport}`}>
          {rules.groups.map((g) => {
            const here = inGroup(g, chosen)
            const empty = Math.max(0, g.min - here.length)
            return (
              <div key={g.name} className="pitch-row" aria-label={`${g.name}: ${here.length} picked`}>
                {here.map((a) => (
                  <button key={a.id} className="player" onClick={() => setSheet(a.id)}
                    aria-label={`${a.name}, ${a.teamName}${picks.get(a.id) !== 'none' ? `, ${ROLES.find((r) => r.role === picks.get(a.id))?.label}` : ''}`}>
                    {picks.get(a.id) !== 'none' && <span className="role-badge">{BADGE[picks.get(a.id)!]}</span>}
                    <Shirt colour={a.colour} />
                    <span className="nameplate"><b>{shortName(a.name)}</b><small>{a.code} ({a.side === 'home' ? 'H' : 'A'})</small></span>
                  </button>
                ))}
                {Array.from({ length: empty }, (_, i) => (
                  <button key={`empty-${i}`} className="player empty" onClick={() => needMore(g)}
                    aria-label={`Add ${g.name.toLowerCase()}`}>
                    <span className="slot">+</span>
                    <span className="nameplate"><small>{g.name}</small></span>
                  </button>
                ))}
              </div>
            )
          })}
        </div>
      ) : (
        <ul className="plain picked-list">
          {rules.groups.flatMap((g) => inGroup(g, chosen)).map((a) => (
            <li key={a.id} className="row between">
              <span className="row"><Shirt colour={a.colour} size={28} />
                <span>{a.name} <span className="muted small">{a.code} · {a.position}</span></span></span>
              <span className="row">
                {picks.get(a.id) !== 'none' && <span className="role-badge static">{BADGE[picks.get(a.id)!]}</span>}
                <button className="link" onClick={() => setSheet(a.id)}>Options</button>
              </span>
            </li>
          ))}
          {chosen.length === 0 && <li className="muted">No players yet. Add them below.</li>}
        </ul>
      )}

      <div className="pool" ref={poolRef}>
        <h3>Add players</h3>
        <div className="chip-row">
          <button className={`chip ${groupFilter === null ? 'on' : ''}`} onClick={() => setGroupFilter(null)}>All</button>
          {rules.groups.map((g) => (
            <button key={g.name} className={`chip ${groupFilter === g.name ? 'on' : ''}`} onClick={() => setGroupFilter(g.name)}>
              {g.name} {inGroup(g, chosen).length}/{g.min}{g.max ? `–${g.max}` : '+'}
            </button>
          ))}
        </div>
        <div className="chip-row">
          {(['all', 'home', 'away'] as const).map((s) => (
            <button key={s} className={`chip ${sideFilter === s ? 'on' : ''}`} onClick={() => setSideFilter(s)}>
              {s === 'all' ? 'Both sides' : s === 'home' ? match.home_team.name : match.away_team.name}
            </button>
          ))}
        </div>
        <ul className="plain">
          {pool.map((a) => {
            const reason = blockReason(a)
            return (
              <li key={a.id} className="pool-row">
                <Shirt colour={a.colour} size={30} />
                <span className="grow">
                  {a.name}
                  <span className="muted small block">{a.teamName} · {a.position}{a.lineup ? ` · ${a.lineup}` : ''}</span>
                </span>
                <button className="add" disabled={!!reason} title={reason ?? undefined} onClick={() => add(a.id)}
                  aria-label={`Add ${a.name}, ${a.teamName}, ${a.position}`}>+</button>
              </li>
            )
          })}
          {pool.length === 0 && <li className="muted">No more players match these filters.</li>}
        </ul>
      </div>

      <div className="save-bar">
        {errors.length > 0 && <ul className="error">{errors.map((e) => <li key={e}>{e}</li>)}</ul>}
        <button className="primary" disabled={busy || chosen.length !== rules.size} onClick={save}>
          {chosen.length !== rules.size ? `Pick ${rules.size - chosen.length} more` : teamId ? 'Save changes' : 'Save team'}
        </button>
      </div>

      {sheetAthlete && (
        <div className="sheet-backdrop" onClick={() => setSheet(null)}>
          <div className="sheet" role="dialog" aria-label={sheetAthlete.name} onClick={(e) => e.stopPropagation()}>
            <div className="row"><Shirt colour={sheetAthlete.colour} size={36} />
              <div><strong>{sheetAthlete.name}</strong><span className="muted small block">{sheetAthlete.teamName} · {sheetAthlete.position}</span></div></div>
            {ROLES.map((r) => (
              <button key={r.role} className={picks.get(sheetAthlete.id) === r.role ? 'sheet-btn on' : 'sheet-btn'}
                onClick={() => assign(sheetAthlete.id, r.role)}>
                {picks.get(sheetAthlete.id) === r.role ? `Remove as ${r.label}` : `Make ${r.label}`} <span className="muted">{r.multiplier}</span>
              </button>
            ))}
            <button className="sheet-btn danger" onClick={() => remove(sheetAthlete.id)}>Remove from team</button>
            <button className="sheet-btn" onClick={() => setSheet(null)}>Close</button>
          </div>
        </div>
      )}
    </section>
  )
}
