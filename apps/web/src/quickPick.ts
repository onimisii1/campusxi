import type { Role, TeamRules } from './rules'

export type Candidate = { id: string; position: string; side: 'home' | 'away'; lineup: 'starting' | 'bench' | null }

/**
 * Fill (or complete) a valid team: meet every position minimum first, then fill to size,
 * preferring announced starters, never breaking a position maximum or the per-side cap.
 * Missing C/VC/Key roles go to the most attacking picks. Existing picks and roles are kept.
 */
export function quickPick(pool: Candidate[], rules: TeamRules, existing: Map<string, Role>,
  random: () => number = Math.random): Map<string, Role> {
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

  const rank = (c: Candidate) => (c.lineup === 'starting' ? 0 : c.lineup === null ? 1 : 2)
  const order = pool.map((c) => ({ c, r: random() })).sort((a, b) => rank(a.c) - rank(b.c) || a.r - b.r).map((x) => x.c)

  rules.groups.forEach((g, gi) => {
    for (const c of order) {
      if (inGroup(gi) >= g.min) break
      if (groupIndex(c) === gi && canAdd(c)) picks.set(c.id, 'none')
    }
  })
  for (const c of order) {
    if (picks.size >= rules.size) break
    if (canAdd(c)) picks.set(c.id, 'none')
  }

  const taken = new Set(picks.values())
  const forRoles = chosen().filter((c) => picks.get(c.id) === 'none')
    .sort((a, b) => groupIndex(b) - groupIndex(a) || rank(a) - rank(b))
  for (const role of ['captain', 'vice_captain', 'key'] as const) {
    if (taken.has(role)) continue
    const next = forRoles.shift()
    if (next) picks.set(next.id, role)
  }
  return picks
}
