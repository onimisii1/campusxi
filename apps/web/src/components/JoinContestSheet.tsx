import { api } from '../api'
import { feeLabel, type Contest } from '../contests'
import { useSession } from '../session'
import { useToast } from '../toast'
import { errorText } from '../useApi'

/** After building a team: pick a contest and enter it with one tap. */
export default function JoinContestSheet({ teamLabel, teamId, contests, fresh, onClose, onJoined }: {
  teamLabel: string; teamId: string; contests: Contest[]; fresh?: boolean; onClose: () => void; onJoined: () => void
}) {
  const { token } = useSession()
  const toast = useToast()

  async function join(c: Contest) {
    try {
      await api(`/contests/${c.id}/entries`, token, { method: 'POST', body: { fantasy_team_id: teamId } })
      toast(c.late_join ? `${teamLabel} joined ${c.name} late: points count from now` : `${teamLabel} joined ${c.name}`)
      onJoined()
    } catch (e) {
      toast(errorText(e), 'bad')
    }
  }

  return (
    <div className="sheet-backdrop" onClick={onClose}>
      <div className="sheet" role="dialog" aria-label={`Join a contest with ${teamLabel}`} onClick={(e) => e.stopPropagation()}>
        <strong>{fresh ? `✓ ${teamLabel} saved. Join a contest?` : `Join a contest with ${teamLabel}`}</strong>
        {contests.length === 0 && <p className="muted">This team is already in every open contest.</p>}
        <ul className="plain join-list">
          {contests.map((c) => (
            <li key={c.id} className="row between">
              <span>
                <strong>{c.name}</strong>
                <span className="muted small block">
                  {c.prize_text ? `🏆 ${c.prize_text} · ` : ''}{c.spots_left.toLocaleString()} spots left
                  {c.late_join ? ` · late until ${c.late_join.until_minute}′` : ''}
                </span>
              </span>
              <button className="join-btn" onClick={() => join(c)}>{c.late_join ? `Join late · ${feeLabel(c)}` : feeLabel(c)}</button>
            </li>
          ))}
        </ul>
        <button className="sheet-btn" onClick={onClose}>{fresh ? 'Not now' : 'Close'}</button>
      </div>
    </div>
  )
}
