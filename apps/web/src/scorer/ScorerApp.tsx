import { useCallback, useEffect, useState } from 'react'
import { api, ApiError, OfflineError } from '../api'
import { recall, remember } from '../cache'
import PageHeader from '../components/PageHeader'
import SignIn from '../components/SignIn'
import { useSession } from '../session'
import MatchScreen from './MatchScreen'

type AssignedMatch = {
  id: string
  sport: string
  tournament: string
  home_team: string
  away_team: string
  scheduled_start: string
  status: string
  role: 'primary' | 'secondary'
  submitted: boolean
}

export default function ScorerApp() {
  const { status, token, me, reload } = useSession()
  const [matches, setMatches] = useState<AssignedMatch[]>([])
  const [openMatch, setOpenMatch] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    if (!token || status !== 'ready') return
    try {
      setMatches(remember('scorer.matches', await api<AssignedMatch[]>('/scorer/matches', token)))
      setError(null)
    } catch (e) {
      if (e instanceof OfflineError) {
        setMatches(recall<AssignedMatch[]>('scorer.matches') ?? [])
        setError('Offline: showing your last saved matches. Events you record are kept until you reconnect.')
      } else {
        setError(e instanceof ApiError ? e.message : 'could not reach CampusXI; check your connection')
      }
    }
  }, [token, status])

  useEffect(() => {
    load()
  }, [load])

  if (status === 'loading') return null
  if (status === 'signed_out') return <SignIn title="Scorer sign-in" onSignedIn={reload} />
  if (status === 'needs_profile') return <p className="card">Finish your profile first. <a href="#/profile">Set it up</a></p>
  if (openMatch && me && token) {
    return <MatchScreen matchId={openMatch} scorerId={me.id} token={token} onBack={() => { setOpenMatch(null); load() }} />
  }

  return (
    <section>
      <PageHeader title="Scorer" back="#/me" subtitle="Your scoring matches" />
      {me && !me.roles.includes('scorer') && <p className="error">Your account doesn't have the scorer role yet. Ask your sports admin.</p>}
      {error && <p className="error">{error}</p>}
      {matches.length === 0 && !error && <p className="muted">No matches assigned to you.</p>}
      <ul className="list">
        {matches.map((m) => (
          <li key={m.id}>
            <button className="match-card" onClick={() => setOpenMatch(m.id)}>
              <strong>{m.home_team} vs {m.away_team}</strong>
              <span className="muted">
                {m.tournament} · {new Date(m.scheduled_start).toLocaleString()} · {m.role} scorer
              </span>
              <span className={`badge ${m.status}`}>{m.submitted ? 'submitted' : m.status.replace('_', ' ')}</span>
            </button>
          </li>
        ))}
      </ul>
    </section>
  )
}
