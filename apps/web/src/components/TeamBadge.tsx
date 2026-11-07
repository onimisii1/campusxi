import { mediaUrl } from '../media'
import { teamCode } from '../teamStyle'

/** A team's round badge, as in the design: the crest in a white circle, or (no crest yet) the team
 *  code in dark type on the same white circle. Jersey colours stay off the badges (fewer colours);
 *  they still show on the pitch shirts, where they tell the two sides apart. */
export default function TeamBadge({ name, logo, small = false }: {
  name: string; colour?: string | null; logo?: string | null; small?: boolean
}) {
  if (logo) {
    return (
      <span className={`team-badge crest ${small ? 'small' : ''}`} aria-hidden>
        <img src={mediaUrl(logo)!} alt="" loading="lazy" referrerPolicy="no-referrer" />
      </span>
    )
  }
  return (
    <span className={`team-badge mono ${small ? 'small' : ''}`} aria-hidden>
      <i>{teamCode(name)}</i>
    </span>
  )
}
