import { teamCode, teamColour } from '../teamStyle'

/** A team's round badge, as in the design: a white ring around the jersey colour with the team code. */
export default function TeamBadge({ name, colour, small = false }: { name: string; colour?: string | null; small?: boolean }) {
  const fill = (colour || teamColour(name)).toUpperCase()
  const [r, g, b] = [1, 3, 5].map((i) => parseInt(fill.slice(i, i + 2), 16))
  const light = 0.299 * r + 0.587 * g + 0.114 * b > 170
  return (
    <span className={`team-badge ${small ? 'small' : ''}`} aria-hidden>
      <i style={{ background: fill, color: light ? '#11130e' : '#fff', boxShadow: light ? 'inset 0 0 0 1px #d6d8cf' : undefined }}>
        {teamCode(name)}
      </i>
    </span>
  )
}
