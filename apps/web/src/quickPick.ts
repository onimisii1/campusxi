import type { Role, TeamRules } from './rules'

export type Candidate = { id: string; position: string; side: 'home' | 'away'; lineup: 'starting' | 'bench' | null }

const ROLE_ORDER = ['captain', 'vice_captain', 'key'] as const
const ATTACK: Record<string, number> = { FWD: 0, MID: 1, DEF: 2, GK: 3 }

/** Does this set of picks meet every rule (size, position min/max, per-side cap, one C/VC/Key)? */
export function isValidTeam(pool: Candidate[], rules: TeamRules, picks: Map<string, Role>): boolean {
  const byId = new Map(pool.map((c) => [c.id, c]))
  const chosen = [...picks.keys()].map((id) => byId.get(id))
  if (chosen.length !== rules.size || chosen.some((c) => !c)) return false
  const list = chosen as Candidate[]
  for (const g of rules.groups) {
    const n = list.filter((c) => g.positions.includes(c.position)).length
    if (n < g.min || (g.max !== undefined && n > g.max)) return false
  }
  if (list.filter((c) => c.side === 'home').length > rules.maxPerSide) return false
  if (list.filter((c) => c.side === 'away').length > rules.maxPerSide) return false
  const roles = [...picks.values()]
  return ROLE_ORDER.every((r) => roles.filter((x) => x === r).length === 1)
}

function attempt(pool: Candidate[], rules: TeamRules, existing: Map<string, Role>, random: () => number): Map<string, Role> {
  const picks = new Map(existing)
  const byId = new Map(pool.map((c) => [c.id, c]))
  const groupIndex = (c: Candidate) => rules.groups.findIndex((g) => g.positions.includes(c.position))
  const chosen = () => [...picks.keys()].map((id) => byId.get(id)).filter(Boolean) as Candidate[]
  const inGroup = (gi: number) => chosen().filter((c) => groupIndex(c) === gi).length
  const onSide = (side: string) => chosen().filter((c) => c.side === side).length

  function canAdd(c: Candidate): boolean {
    const gi = groupIndex(c)
    const g = rules.groups[gi]
    return !picks.has(c.id) && gi >= 0 && picks.size < rules.size
      && (g.max === undefined || inGroup(gi) < g.max) && onSide(c.side) < rules.maxPerSide
  }

  // Starters are preferred loosely, so teams still vary; the scarcest positions are filled first.
  const rank = (c: Candidate) => (c.lineup === 'starting' ? 0 : c.lineup === null ? 0.6 : 1.2)
  const order = pool.map((c) => ({ c, r: rank(c) + random() * 1.5 })).sort((a, b) => a.r - b.r).map((x) => x.c)
  const scarce = rules.groups.map((_, gi) => ({ gi, n: pool.filter((c) => groupIndex(c) === gi).length + random() }))
    .sort((a, b) => a.n - b.n)
  for (const { gi } of scarce) {
    for (const c of order) {
      if (inGroup(gi) >= rules.groups[gi].min) break
      if (groupIndex(c) === gi && canAdd(c)) picks.set(c.id, 'none')
    }
  }
  for (const c of order) {
    if (picks.size >= rules.size) break
    if (canAdd(c)) picks.set(c.id, 'none')
  }

  // Missing C/VC/Key lean towards attackers, with some chance, so captains vary between players.
  const taken = new Set(picks.values())
  const free = chosen().filter((c) => picks.get(c.id) === 'none')
    .map((c) => ({ c, r: (ATTACK[c.position] ?? 1) + random() * 2.5 })).sort((a, b) => a.r - b.r).map((x) => x.c)
  for (const role of ROLE_ORDER) {
    if (taken.has(role)) continue
    const next = free.shift()
    if (next) picks.set(next.id, role)
  }
  return picks
}

/**
 * Fill (or complete) a valid team, keeping existing picks and roles. This is the offline fallback for
 * the server's Quick pick (POST /matches/{id}/quick-pick), which also avoids other players' teams.
 * Each try fills the scarcest positions first and is checked against every rule; a try that paints
 * itself into a corner (e.g. no room left for a forward when one side is all midfielders) is
 * thrown away and retried in a new random order.
 */
export function quickPick(pool: Candidate[], rules: TeamRules, existing: Map<string, Role>,
  random: () => number = Math.random): Map<string, Role> {
  let last = existing
  for (let i = 0; i < 400; i++) {
    last = attempt(pool, rules, existing, random)
    if (isValidTeam(pool, rules, last)) return last
  }
  return last
}
