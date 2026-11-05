import { useState } from 'react'
import { api } from '../api'
import { returnAfterSignIn } from '../router'
import { useSession } from '../session'
import { errorText, useApi } from '../useApi'

type School = { id: string; name: string }

export default function ProfilePage() {
  const { token, status, reload } = useSession()
  const { data: schools } = useApi<School[]>('/schools')
  const [schoolId, setSchoolId] = useState('')
  const [teamName, setTeamName] = useState('')
  const [dob, setDob] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  if (status !== 'needs_profile') return <p className="muted">Your profile is already set up.</p>

  async function save(e: React.FormEvent) {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await api('/me', token, { method: 'POST', body: { school_id: schoolId, team_name: teamName, dob } })
      await reload()
      returnAfterSignIn()
    } catch (err) {
      setError(errorText(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <form className="card" onSubmit={save}>
      <h2>Set up your profile</h2>
      <label>
        School
        <select value={schoolId} onChange={(e) => setSchoolId(e.target.value)} required>
          <option value="">Choose your school</option>
          {schools?.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
        </select>
      </label>
      <label>
        Team name <small className="muted">(permanent: choose carefully)</small>
        <input value={teamName} onChange={(e) => setTeamName(e.target.value)} minLength={3} maxLength={30}
          pattern="[A-Za-z0-9_ .\-]+" required />
      </label>
      <label>
        Date of birth <small className="muted">(CampusXI is 18+)</small>
        <input type="date" value={dob} onChange={(e) => setDob(e.target.value)} required />
      </label>
      {error && <p className="error">{error}</p>}
      <button className="primary" disabled={busy}>Create profile</button>
    </form>
  )
}
