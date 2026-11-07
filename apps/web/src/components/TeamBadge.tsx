import { teamCode, teamColour } from '../teamStyle'

/** A team's round badge, as in the design: the crest in a white circle, or (no crest yet) the jersey
 *  colour with the team code. */
export default function TeamBadge({ name, colour, logo, small = false }: {
  name: string; colour?: string | null; logo?: string | null; small?: boolean
}) {
  if (logo) {
    return (
      <span className={`team-badge crest ${small ? 'small' : ''}`} aria-hidden>
        <img src={logo} alt="" loading="lazy" referrerPolicy="no-referrer" />
      </span>
    )
  }
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
