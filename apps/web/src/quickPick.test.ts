import { describe, expect, it } from 'vitest'
import { quickPick, type Candidate } from './quickPick'
import { TEAM_RULES, type Role } from './rules'

function squad(shape: [string, number][]): Candidate[] {
  return (['home', 'away'] as const).flatMap((side) =>
    shape.flatMap(([pos, n]) => Array.from({ length: n }, (_, i) => ({
      id: `${side}-${pos}-${i}`, position: pos, side, lineup: i === 0 ? 'starting' as const : null,
    }))))
}

function seeded(seed: number) {
  return () => {
    seed = (seed * 9301 + 49297) % 233280
    return seed / 233280
  }
}

function check(sport: string, pool: Candidate[], picks: Map<string, Role>) {
  const rules = TEAM_RULES[sport]
  const chosen = pool.filter((c) => picks.has(c.id))
  expect(chosen).toHaveLength(rules.size)
  for (const g of rules.groups) {
    const n = chosen.filter((c) => g.positions.includes(c.position)).length
    expect(n).toBeGreaterThanOrEqual(g.min)
    if (g.max !== undefined) expect(n).toBeLessThanOrEqual(g.max)
  }
  for (const side of ['home', 'away']) expect(chosen.filter((c) => c.side === side).length).toBeLessThanOrEqual(rules.maxPerSide)
  const roles = [...picks.values()]
  for (const r of ['captain', 'vice_captain', 'key']) expect(roles.filter((x) => x === r)).toHaveLength(1)
}

describe('quickPick', () => {
  const football = squad([['GK', 2], ['DEF', 6], ['MID', 6], ['FWD', 4]])

  it('builds a valid football team for many random seeds', () => {
    for (let s = 1; s < 60; s++) check('football', football, quickPick(football, TEAM_RULES.football, new Map(), seeded(s)))
  })

  it('builds valid basketball and volleyball teams', () => {
    const bball = squad([['G', 4], ['F', 4], ['C', 2]])
    const vball = squad([['S', 2], ['OH', 3], ['OPP', 2], ['MB', 3], ['L', 2]])
    for (let s = 1; s < 30; s++) {
      check('basketball', bball, quickPick(bball, TEAM_RULES.basketball, new Map(), seeded(s)))
      check('volleyball', vball, quickPick(vball, TEAM_RULES.volleyball, new Map(), seeded(s)))
    }
  })

  it('keeps existing picks and roles, completing the rest', () => {
    const existing = new Map<string, Role>([['home-FWD-0', 'captain'], ['away-GK-1', 'none']])
    const picks = quickPick(football, TEAM_RULES.football, existing, seeded(7))
    expect(picks.get('home-FWD-0')).toBe('captain')
    expect(picks.has('away-GK-1')).toBe(true)
    check('football', football, picks)
  })

  it('prefers announced starters', () => {
    const picks = quickPick(football, TEAM_RULES.football, new Map(), seeded(3))
    expect(picks.has('home-GK-0') || picks.has('away-GK-0')).toBe(true)
  })

  it('gives the captaincy to an attacker when none is set', () => {
    const picks = quickPick(football, TEAM_RULES.football, new Map(), seeded(11))
    const captain = [...picks].find(([, r]) => r === 'captain')![0]
    expect(captain).toContain('FWD')
  })
})
