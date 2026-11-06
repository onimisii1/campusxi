import { useState } from 'react'
import { api } from '../api'
import PageHeader from '../components/PageHeader'
import { savedReferral } from '../money'
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
  const [referral, setReferral] = useState(savedReferral() ?? '')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  if (status !== 'needs_profile') return <p className="muted">Your profile is already set up.</p>

  async function save(e: React.FormEvent) {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await api('/me', token, { method: 'POST', body: {
        school_id: schoolId, team_name: teamName, dob, referral_code: referral.trim() || null } })
      await reload()
      returnAfterSignIn()
    } catch (err) {
      setError(errorText(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <section>
    <PageHeader title="Your profile" back="#/" />
    <form className="card" onSubmit={save}>
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
      <label>
        Friend's referral code <small className="muted">(optional)</small>
        <input value={referral} onChange={(e) => setReferral(e.target.value.toUpperCase())} maxLength={12} />
      </label>
      {error && <p className="error">{error}</p>}
      <button className="primary" disabled={busy}>Create profile</button>
    </form>
    </section>
  )
}
