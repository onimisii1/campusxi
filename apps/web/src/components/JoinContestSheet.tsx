import { useState } from 'react'
import { api } from '../api'
import { feeLabel, type Contest } from '../contests'
import { naira, newIdempotencyKey, paidGate, payLine, split, useWallet } from '../money'
import { useSession } from '../session'
import { useToast } from '../toast'
import { errorText } from '../useApi'

/** After building a team: pick a contest and enter it with one tap. Paid ones say how they're paid. */
export default function JoinContestSheet({ teamLabel, teamId, contests, fresh, onClose, onJoined }: {
  teamLabel: string; teamId: string; contests: Contest[]; fresh?: boolean; onClose: () => void; onJoined: () => void
}) {
  const { token } = useSession()
  const toast = useToast()
  const { data: w } = useWallet()
  const [key] = useState(newIdempotencyKey)
  const [busy, setBusy] = useState<string | null>(null)

  async function join(c: Contest) {
    setBusy(c.id)
    try {
      await api(`/contests/${c.id}/entries`, token, { method: 'POST', body: { fantasy_team_id: teamId },
        idempotencyKey: `${key}-${c.id}` })
      toast(c.late_join ? `${teamLabel} joined ${c.name} late: points count from now` : `${teamLabel} joined ${c.name}`)
      onJoined()
    } catch (e) {
      toast(errorText(e), 'bad')
    } finally {
      setBusy(null)
    }
  }

  return (
    <div className="sheet-backdrop" onClick={onClose}>
      <div className="sheet" role="dialog" aria-label={`Join a contest with ${teamLabel}`} onClick={(e) => e.stopPropagation()}>
        <strong>{fresh ? `✓ ${teamLabel} saved. Join a contest?` : `Join a contest with ${teamLabel}`}</strong>
        {contests.length === 0 && <p className="muted">This team is already in every open contest.</p>}
        <ul className="plain join-list">
          {contests.map((c) => {
            const fee = c.late_join ? c.late_join.entry_fee_kobo : c.entry_fee_kobo
            const gate = fee > 0 && w ? paidGate(w) : null
            const unverified = fee > 0 && (!w || !!gate)
            const short = fee > 0 && w ? split(w, fee).short : 0
            return (
              <li key={c.id} className="row between">
                <span>
                  <strong>{c.name}</strong>
                  <span className="muted small block">
                    {c.prize_text ? `🏆 ${c.prize_text} · ` : ''}{c.spots_left.toLocaleString()} spots left
                    {c.late_join ? ` · late until ${c.late_join.until_minute}′` : ''}
                  </span>
                  {fee > 0 && w && (unverified
                    ? <a className="small block" href={gate?.href ?? '#/wallet'}>{gate?.text ?? 'Open your wallet →'}</a>
                    : short > 0
                      ? <a className="small block" href="#/wallet">Need {naira(short)} more · Add money →</a>
                      : <span className="small block">Pays {payLine(w, fee)}</span>)}
                </span>
                <button className="join-btn" disabled={busy !== null || unverified || short > 0} onClick={() => join(c)}>
                  {busy === c.id ? '…' : c.late_join ? `Join late · ${feeLabel(c)}` : feeLabel(c)}</button>
              </li>
            )
          })}
        </ul>
        <button className="sheet-btn" onClick={onClose}>{fresh ? 'Not now' : 'Close'}</button>
      </div>
    </div>
  )
}
