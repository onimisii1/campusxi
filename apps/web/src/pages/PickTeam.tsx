import { useEffect, useMemo, useRef, useState } from 'react'
import { api, ApiError } from '../api'
import PageHeader from '../components/PageHeader'
import Shirt from '../components/Shirt'
import Skeleton from '../components/Skeleton'
import { quickPick } from '../quickPick'
import { useToast } from '../toast'
import { deadline, points } from '../format'
import { go, signInThenReturn } from '../router'
import { ROLES, TEAM_RULES, type Group, type Role } from '../rules'
import { useSession } from '../session'
import { shortName, sideColours, teamCode } from '../teamStyle'
import { errorText, useApi } from '../useApi'

type SquadAthlete = { id: string; name: string; position: string; lineup: 'starting' | 'bench' | null
  last_points?: number | string | null; played_last?: boolean; picked_pct?: number | null }
type MatchDetail = {
  id: string
  sport: string
  locked: boolean
  scheduled_start: string
  home_team: { id: string; name: string; colour: string | null }
  away_team: { id: string; name: string; colour: string | null }
  squads: { home: SquadAthlete[]; away: SquadAthlete[] }
  late_join_until: number | null
}
type Team = { id: string; label: string; picks: { athlete_id: string; role: Role }[] }
type Athlete = SquadAthlete & { side: 'home' | 'away'; teamName: string; colour: string; code: string }

const BADGE: Record<Role, string> = { none: '', captain: 'C', vice_captain: 'V', key: 'K' }
const LINEUPS = '__lineups'

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
  const [search, setSearch] = useState('')
  const poolRef = useRef<HTMLDivElement>(null)
  const toast = useToast()

  useEffect(() => {
    const team = myTeams?.find((t) => t.id === teamId)
    if (team) setPicks(new Map(team.picks.map((p) => [p.athlete_id, p.role])))
  }, [myTeams, teamId])

  const athletes: Athlete[] = useMemo(() => {
    if (!match) return []
    const colours = sideColours(match.home_team, match.away_team)
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
  if (!match) return <Skeleton hero rows={3} />
  // After kick-off: no edits, but a new team can still be built in the late-join window.
  const lateBuild = match.locked && !teamId && match.late_join_until !== null
  if (match.locked && !lateBuild) {
    return (
      <section>
        <PageHeader title="Pick Team" back={back} />
        <p className="card">{teamId ? "The match has started, so this team can't change." : 'This match has locked and late joining has closed.'}</p>
      </section>
    )
  }

  const rules = TEAM_RULES[match.sport]
  const chosen = athletes.filter((a) => picks.has(a.id))
  const full = chosen.length >= rules.size
  const inGroup = (g: Group, list: Athlete[]) => list.filter((a) => g.positions.includes(a.position))
  const groupOf = (a: Athlete) => rules.groups.find((g) => g.positions.includes(a.position))!
  const sideCount = (side: 'home' | 'away') => chosen.filter((a) => a.side === side).length
  const rolesSet = ROLES.filter((r) => [...picks.values()].includes(r.role)).length

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
      if (teamId) {
        await api(`/teams/${teamId}`, token, { method: 'PUT', body })
        toast('Team updated')
        go(`/match/${matchId}/teams`)
      } else {
        // A new team goes straight to "join a contest" with it.
        const created = await api<{ id: string }>(`/matches/${matchId}/teams`, token, { method: 'POST', body })
        go(`/match/${matchId}/teams/${created.id}`)
      }
    } catch (e) {
      setErrors(e instanceof ApiError && Array.isArray(e.details) ? e.details.map(String) : [errorText(e)])
    } finally {
      setBusy(false)
    }
  }

  // Quick pick asks the server for a team that differs from everyone else's; offline, it's picked here.
  async function autoFill() {
    const done = picks.size ? 'Team completed: tap any player to change' : 'Team picked for you: tap any player to change'
    try {
      const res = await api<{ picks: { athlete_id: string; role: Role }[] }>(`/matches/${matchId}/quick-pick`, token, {
        method: 'POST', body: { picks: [...picks].map(([athlete_id, role]) => ({ athlete_id, role })), team_id: teamId ?? null } })
      setPicks(new Map(res.picks.map((p) => [p.athlete_id, p.role])))
      toast(done)
    } catch (e) {
      if (e instanceof ApiError) {
        toast(errorText(e), 'bad')
        return
      }
      setPicks(quickPick(athletes, rules, picks))
      toast(done)
    }
  }

  // The open position tab: the one tapped, else the first position still short of its minimum.
  const activeGroup = groupFilter === LINEUPS ? null
    : rules.groups.find((g) => g.name === groupFilter)
      ?? rules.groups.find((g) => inGroup(g, chosen).length < g.min) ?? rules.groups[0]
  const fullSides = (['home', 'away'] as const).filter((s) => sideCount(s) >= rules.maxPerSide)
  const guide = full
    ? (rolesSet < 3 ? 'Team complete: tap players on the pitch to choose C, VC and Key.' : 'Ready to save.')
    : [activeGroup && `Pick ${activeGroup.min}${activeGroup.max ? `–${activeGroup.max}` : '+'} ${activeGroup.name.toLowerCase()}`,
       ...fullSides.map((s) => `Max ${rules.maxPerSide} players from ${s === 'home' ? match.home_team.name : match.away_team.name}`)]
      .filter(Boolean).join(' · ') || `Pick ${rules.size} players`
  const lineupRank = (a: Athlete) => (a.lineup === 'starting' ? 0 : a.lineup === null ? 1 : 2)

  const q = search.trim().toLowerCase()
  const pool = athletes.filter((a) => !picks.has(a.id)
    && (!activeGroup || groupOf(a) === activeGroup)
    && (sideFilter === 'all' || a.side === sideFilter)
    && (!q || a.name.toLowerCase().includes(q) || a.teamName.toLowerCase().includes(q)))
    .sort((a, b) => lineupRank(a) - lineupRank(b))
  const sheetAthlete = athletes.find((a) => a.id === sheet)

  return (
    <section className="pick-team">
      <PageHeader title={teamId ? 'Edit team' : lateBuild ? 'Late team' : 'Pick Team'} back={back}
        subtitle={`${match.home_team.name} vs ${match.away_team.name} · ${lateBuild
          ? `late joining until minute ${match.late_join_until}` : `Deadline ${deadline(match.scheduled_start)}`}`} />
      {lateBuild && (
        <p className="notice small">⏱ The match is on. This team only earns points recorded after you save it, and it
          can't be edited afterwards.</p>
      )}

      <div className="chip-row" aria-live="polite">
        <span className={`chip ${chosen.length === rules.size ? 'ok' : ''}`}>{chosen.length}/{rules.size} players</span>
        <span className={`chip ${rolesSet === 3 ? 'ok' : ''}`}>C · VC · K {rolesSet}/3</span>
        <span className="chip">{teamCode(match.home_team.name)} {sideCount('home')}/{rules.maxPerSide}</span>
        <span className="chip">{teamCode(match.away_team.name)} {sideCount('away')}/{rules.maxPerSide}</span>
      </div>

      <div className="row between toolbar">
        <div className="toggle" role="tablist" aria-label="View">
          <button role="tab" aria-selected={view === 'pitch'} className={view === 'pitch' ? 'on' : ''} onClick={() => setView('pitch')}>Pitch</button>
          <button role="tab" aria-selected={view === 'list'} className={view === 'list' ? 'on' : ''} onClick={() => setView('list')}>List</button>
        </div>
        <div className="row">
          {picks.size > 0 && <button className="ghost-btn" onClick={() => setPicks(new Map())}>Clear</button>}
          {(!full || rolesSet < 3) && <button className="ghost-btn accent" onClick={autoFill}>⚡ Quick pick</button>}
        </div>
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
        <div className="pos-tabs" role="tablist" aria-label="Positions">
          {rules.groups.map((g) => (
            <button key={g.name} role="tab" aria-selected={activeGroup?.name === g.name}
              className={activeGroup?.name === g.name ? 'on' : ''} onClick={() => setGroupFilter(g.name)}>
              {g.positions.join('/')} <span>[{inGroup(g, chosen).length}]</span>
            </button>
          ))}
          <button role="tab" aria-selected={groupFilter === LINEUPS} className={groupFilter === LINEUPS ? 'on' : ''}
            onClick={() => setGroupFilter(LINEUPS)}>Line-ups</button>
        </div>
        <p className="guide" aria-live="polite">{guide}</p>
        {groupFilter === LINEUPS ? (
          <div className="lineups">
            {(['home', 'away'] as const).map((side) => (
              <div key={side}>
                <h4 className="row"><Shirt colour={athletes.find((a) => a.side === side)?.colour ?? '#999'} size={22} />
                  {side === 'home' ? match.home_team.name : match.away_team.name}</h4>
                <ol className="plain">
                  {athletes.filter((a) => a.side === side)
                    .sort((a, b) => lineupRank(a) - lineupRank(b) || rules.groups.indexOf(groupOf(a)) - rules.groups.indexOf(groupOf(b)))
                    .map((a) => {
                      const on = picks.has(a.id)
                      const reason = blockReason(a)
                      return (
                        <li key={a.id} className={`lu-row ${on ? 'on' : ''}`}>
                          <span className="grow">{shortName(a.name)}
                            <small className="muted block">{a.position}{a.lineup === 'bench' ? ' · bench' : a.lineup ? '' : ' · squad'}
                              {a.last_points !== null && a.last_points !== undefined ? ` · ${points(a.last_points)} last` : ''}</small></span>
                          <button className={on ? 'add on' : 'add'} disabled={!on && !!reason} title={reason ?? undefined}
                            onClick={() => (on ? remove(a.id) : add(a.id))}
                            aria-label={`${on ? 'Remove' : 'Add'} ${a.name}, ${a.teamName}, ${a.position}`}>{on ? '✓' : '+'}</button>
                        </li>
                      )
                    })}
                </ol>
              </div>
            ))}
          </div>
        ) : (
        <>
        <input className="search" type="search" placeholder="Search players or teams" value={search}
          onChange={(e) => setSearch(e.target.value)} aria-label="Search players" />
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
                  {a.played_last && <span className="played-badge">▶ Played last match</span>}
                </span>
                <span className="last-pts" title="Fantasy points in their team's last match">
                  {a.last_points !== null && a.last_points !== undefined ? points(a.last_points) : '–'}
                  <small>last</small>
                </span>
                <button className="add" disabled={!!reason} title={reason ?? undefined} onClick={() => add(a.id)}
                  aria-label={`Add ${a.name}, ${a.teamName}, ${a.position}`}>+</button>
              </li>
            )
          })}
          {pool.length === 0 && <li className="muted">No more players match these filters.</li>}
        </ul>
        </>
        )}
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
