import { useCallback, useEffect, useState } from 'react'
import { api, ApiError, OfflineError } from '../api'
import { getToken, signOut } from '../auth'
import { recall, remember } from '../cache'
import MatchScreen from './MatchScreen'
import SignIn from './SignIn'

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

type Me = { id: string; team_name: string; roles: string[] }

export default function ScorerApp() {
  const [token, setToken] = useState<string | null>(null)
  const [me, setMe] = useState<Me | null>(null)
  const [matches, setMatches] = useState<AssignedMatch[]>([])
  const [openMatch, setOpenMatch] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [checked, setChecked] = useState(false)

  const load = useCallback(async () => {
    const t = await getToken()
    setToken(t)
    setChecked(true)
    if (!t) return
    try {
      setMe(remember('me', await api<Me>('/me', t)))
      setMatches(remember('scorer.matches', await api<AssignedMatch[]>('/scorer/matches', t)))
      setError(null)
    } catch (e) {
      if (e instanceof OfflineError && recall<Me>('me')) {
        setMe(recall<Me>('me'))
        setMatches(recall<AssignedMatch[]>('scorer.matches') ?? [])
        setError('Offline: showing your last saved matches. Events you record are kept until you reconnect.')
      } else {
        setError(e instanceof ApiError ? e.message : 'could not reach CampusXI; check your connection')
      }
    }
  }, [])

  useEffect(() => {
    load()
  }, [load])

  if (!checked) return null
  if (!token) return <SignIn onSignedIn={load} />
  if (openMatch && me) {
    return <MatchScreen matchId={openMatch} scorerId={me.id} token={token} onBack={() => { setOpenMatch(null); load() }} />
  }

  return (
    <section>
      <div className="row between">
        <h2>Your matches</h2>
        <button className="link" onClick={async () => { await signOut(); setToken(null); setMe(null) }}>Sign out</button>
      </div>
      {me && !me.roles.includes('scorer') && <p className="error">Your account doesn't have the scorer role yet.</p>}
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
