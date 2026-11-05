import { useState } from 'react'
import { api } from '../api'
import { kickoff } from '../format'
import { go, signInThenReturn } from '../router'
import { useSession } from '../session'
import { errorText, useApi } from '../useApi'

type Invite = {
  id: string
  status: string
  is_mine: boolean
  creator: { team_name: string; record: { won: number; lost: number; tied: number } }
  match: { id: string; home_team: string; away_team: string; scheduled_start: string; locked: boolean }
}
type Team = { id: string; label: string }

export default function ChallengeInvite({ token: inviteToken }: { token: string }) {
  const { status, token } = useSession()
  const { data: invite, error } = useApi<Invite>(`/bets/invite/${inviteToken}`)
  const matchId = invite?.match.id
  const { data: teams } = useApi<Team[]>(status === 'ready' && matchId ? `/me/teams?match_id=${matchId}` : null)
  const [team, setTeam] = useState('')
  const [msg, setMsg] = useState<string | null>(null)

  if (error) return <p className="error">{error}</p>
  if (!invite) return <p className="muted">Loading…</p>
  const { match, creator } = invite

  async function accept() {
    try {
      await api(`/bets/${invite!.id}/fills`, token, { method: 'POST', body: { fantasy_team_id: team } })
      go('/challenges')
    } catch (e) {
      setMsg(errorText(e))
    }
  }

  return (
    <section className="card">
      <h2>{creator.team_name} challenged you</h2>
      <p>{match.home_team} vs {match.away_team} · {kickoff(match.scheduled_start)}</p>
      <p className="muted">Their record: {creator.record.won}W {creator.record.lost}L {creator.record.tied}T.
        Free head-to-head for bragging rights. Their team stays hidden until kick-off.</p>
      {invite.status !== 'open' || match.locked ? (
        <p>This challenge is no longer open.</p>
      ) : invite.is_mine ? (
        <p>This is your own challenge. Share the link with a friend.</p>
      ) : status === 'signed_out' ? (
        <button className="primary" onClick={signInThenReturn}>Sign in to accept</button>
      ) : teams && teams.length === 0 ? (
        <p><a href={`#/build/${match.id}`}>Build a team for this match</a>, then come back to this link.</p>
      ) : (
        <>
          <label>Your team
            <select value={team} onChange={(e) => setTeam(e.target.value)}>
              <option value="">Choose a team</option>
              {teams?.map((t) => <option key={t.id} value={t.id}>{t.label}</option>)}
            </select>
          </label>
          <button className="primary" disabled={!team} onClick={accept}>Accept challenge</button>
        </>
      )}
      {msg && <p className="error">{msg}</p>}
    </section>
  )
}
