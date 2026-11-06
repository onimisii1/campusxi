import { useState } from 'react'
import { api } from '../api'
import { feeLabel, joinable, naira, type Contest, type TeamOption } from '../contests'
import { newIdempotencyKey, payLine, split, useWallet } from '../money'
import { signInThenReturn } from '../router'
import { useSession } from '../session'
import { useToast } from '../toast'
import { errorText } from '../useApi'

/** A contest in the list: prize headline, filled-spots bar, fact strip and a Join button. */
export default function ContestCard({ contest: c, matchId, teams, onChanged }: {
  contest: Contest; matchId: string; teams: TeamOption[] | null; onChanged: () => void
}) {
  const [sheet, setSheet] = useState(false)
  const { status } = useSession()
  const paidRanks = Math.max(1, Math.floor(c.capacity * 0.4))
  const filled = Math.round((c.entries / c.capacity) * 100)

  return (
    <article className="contest-card">
      <a className="contest-main" href={`#/contest/${c.id}`}>
        <div className="row between">
          <strong className="contest-name">{c.name}</strong>
          {c.status !== 'open' && <span className="badge">{c.status}</span>}
        </div>
        <p className="contest-prize">{c.prize_text ? `🏆 ${c.prize_text}` : c.entry_fee_kobo === 0 ? 'Free to play' : 'Cash prizes'}</p>
        <div className="progress" aria-label={`${c.entries} of ${c.capacity} spots taken`}>
          <span style={{ width: `${Math.max(filled, c.entries ? 2 : 0)}%` }} />
        </div>
        <div className="row between small muted">
          <span>{c.spots_left.toLocaleString()} spots left</span>
          <span>{c.capacity.toLocaleString()} spots</span>
        </div>
      </a>
      <div className="fact-strip">
        <span title="Ranks that win">🏅 {c.entry_fee_kobo ? `${paidRanks} ranks` : 'Top 40%'}</span>
        <span title="Teams per player">👥 {c.team_cap} team{c.team_cap === 1 ? '' : 's'}</span>
        {c.late_join && <span className="late" title="Late joining">⏱ until {c.late_join.until_minute}′</span>}
        {joinable(c) && (
          <button className="join-btn" onClick={() => (status === 'ready' ? setSheet(true) : signInThenReturn())}>
            {c.late_join ? `Join late · ${feeLabel(c)}` : feeLabel(c)}
          </button>
        )}
      </div>
      {c.my_entries.length > 0 && (
        <p className="small my-entries">You're in with {c.my_entries.map((e) => e.label).join(', ')}
          {c.my_entries.some((e) => e.final_rank) && ` · best finish #${Math.min(...c.my_entries.map((e) => e.final_rank ?? Infinity))}`}</p>
      )}
      {sheet && <JoinSheet contest={c} matchId={matchId} teams={teams} onClose={() => setSheet(false)}
        onJoined={() => { setSheet(false); onChanged() }} />}
    </article>
  )
}

function JoinSheet({ contest: c, matchId, teams, onClose, onJoined }: {
  contest: Contest; matchId: string; teams: TeamOption[] | null; onClose: () => void; onJoined: () => void
}) {
  const { token } = useSession()
  const toast = useToast()
  const [team, setTeam] = useState('')
  const [error, setError] = useState<string | null>(null)
  const entered = new Set(c.my_entries.map((e) => e.fantasy_team_id))
  const options = (teams ?? []).filter((t) => !entered.has(t.id))
  const { data: w } = useWallet()
  const fee = c.late_join ? c.late_join.entry_fee_kobo : c.entry_fee_kobo
  const short = fee && w ? split(w, fee).short : 0
  const [key] = useState(newIdempotencyKey)

  async function join() {
    try {
      await api(`/contests/${c.id}/entries`, token, { method: 'POST', body: { fantasy_team_id: team },
        idempotencyKey: `${key}-${team}` })
      toast(c.late_join ? `Joined ${c.name} late: points count from now` : `Joined ${c.name}`)
      onJoined()
    } catch (e) {
      setError(errorText(e))
    }
  }

  return (
    <div className="sheet-backdrop" onClick={onClose}>
      <div className="sheet" role="dialog" aria-label={`Join ${c.name}`} onClick={(e) => e.stopPropagation()}>
        <strong>Join {c.name}</strong>
        {c.late_join && (
          <p className="notice">⏱ The match is on (minute {c.late_join.minute}). Points recorded before you join
            don't count.{c.entry_fee_kobo ? ` Late entry is ${naira(c.late_join.entry_fee_kobo)} (+50%).` : ''} Open
            until minute {c.late_join.until_minute}.</p>
        )}
        {options.length === 0 ? (
          <p className="muted">You have no team to enter yet.</p>
        ) : (
          <div className="team-options" role="radiogroup" aria-label="Choose a team">
            {options.map((t) => (
              <button key={t.id} role="radio" aria-checked={team === t.id} className={team === t.id ? 'sheet-btn on' : 'sheet-btn'}
                onClick={() => setTeam(t.id)}>{t.label}</button>
            ))}
          </div>
        )}
        <a className="sheet-btn" href={`#/build/${matchId}`}>+ Build a new team</a>
        {fee > 0 && w && (
          w.kyc_status !== 'verified'
            ? <a className="notice block-link" href="#/verify">🪪 Verify your ID to play for cash →</a>
            : short > 0
              ? <a className="notice block-link" href="#/wallet">You need {naira(short)} more · Add money →</a>
              : <p className="small muted">Pays {payLine(w, fee)}. Prizes are paid in cash 24h after the result.</p>
        )}
        {error && <p className="error">{error}</p>}
        <button className="primary" disabled={!team || short > 0} onClick={join}>
          {c.late_join ? `Join late · ${feeLabel(c)}` : `Join · ${feeLabel(c)}`}
        </button>
        <button className="sheet-btn" onClick={onClose}>Cancel</button>
      </div>
    </div>
  )
}
