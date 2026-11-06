// Generated team identity: a shirt colour and a three-letter code from the team name.
// No greens or browns: shirts must stand out on a green pitch and an orange court.
const PALETTE = ['#1565C0', '#C62828', '#FAFAFA', '#6A1B9A', '#212121', '#00838F', '#AD1457', '#FDD835', '#283593', '#EF6C00']

export function teamColour(name: string): string {
  let h = 0
  for (const ch of name) h = (h * 31 + ch.charCodeAt(0)) >>> 0
  return PALETTE[h % PALETTE.length]
}

type Side = { name: string; colour?: string | null }

/**
 * Shirt colours for a match: each team's real jersey when the admin imported one, otherwise a
 * generated colour. Two sides never share a colour, so the away side shifts if they clash.
 */
export function sideColours(home: Side, away: Side): { home: string; away: string } {
  const h = (home.colour || teamColour(home.name)).toUpperCase()
  let a = (away.colour || teamColour(away.name)).toUpperCase()
  if (a === h) {
    const i = PALETTE.indexOf(h)
    a = PALETTE[(i < 0 ? 0 : i + 3) % PALETTE.length]
    if (a === h) a = PALETTE[1]
  }
  return { home: h, away: a }
}

export function teamCode(name: string): string {
  return name.replace(/[^A-Za-z]/g, '').slice(0, 3).toUpperCase()
}

/** "Engineering FWD 1" -> "FWD 1"; real names keep their last word ("Tunde Bello" -> "Bello"). */
export function shortName(name: string): string {
  const parts = name.trim().split(/\s+/)
  if (parts.length >= 2 && /^\d+$/.test(parts[parts.length - 1])) return parts.slice(-2).join(' ')
  return parts[parts.length - 1]
}
