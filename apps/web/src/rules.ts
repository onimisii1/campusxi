// Team rules mirrored from the API's engine (apps/api/app/engines/scoring/rules.py) so the
// builder can show live counters. The API remains the judge: it re-validates every save.

export type Group = { name: string; positions: string[]; min: number; max?: number }
export type TeamRules = { size: number; maxPerSide: number; groups: Group[] }

export const TEAM_RULES: Record<string, TeamRules> = {
  football: {
    size: 11,
    maxPerSide: 7,
    groups: [
      { name: 'Goalkeeper', positions: ['GK'], min: 1, max: 1 },
      { name: 'Defenders', positions: ['DEF'], min: 3, max: 5 },
      { name: 'Midfielders', positions: ['MID'], min: 3, max: 5 },
      { name: 'Forwards', positions: ['FWD'], min: 1, max: 3 },
    ],
  },
  basketball: {
    size: 8,
    maxPerSide: 5,
    groups: [
      { name: 'Guards', positions: ['G'], min: 2 },
      { name: 'Forwards', positions: ['F'], min: 2 },
      { name: 'Centres', positions: ['C'], min: 1 },
    ],
  },
  volleyball: {
    size: 7,
    maxPerSide: 4,
    groups: [
      { name: 'Setters', positions: ['S'], min: 1 },
      { name: 'Attackers', positions: ['OH', 'OPP'], min: 2 },
      { name: 'Middles', positions: ['MB'], min: 1 },
      { name: 'Liberos', positions: ['L'], min: 1 },
    ],
  },
}

export type Role = 'none' | 'captain' | 'vice_captain' | 'key'

export const ROLES: { role: Exclude<Role, 'none'>; short: string; label: string; multiplier: string }[] = [
  { role: 'captain', short: 'C', label: 'Captain', multiplier: '×2.5' },
  { role: 'vice_captain', short: 'VC', label: 'Vice-captain', multiplier: '×2' },
  { role: 'key', short: 'K', label: 'Key player', multiplier: '×1.5' },
]
