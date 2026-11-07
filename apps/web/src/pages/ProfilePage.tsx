import { useEffect, useState } from 'react'
import { api } from '../api'
import PageHeader from '../components/PageHeader'
import { savedReferral } from '../money'
import { returnAfterSignIn } from '../router'
import { useSession } from '../session'
import { errorText, useApi } from '../useApi'

type School = { id: string; name: string }

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
const NAME_OK = /^[A-Za-z0-9_ .-]+$/

function initials(name: string): string {
  return name.split(/\s+/).filter((w) => /^[A-Z]/.test(w) && !['Of', 'The'].includes(w)).map((w) => w[0]).join('').slice(0, 3)
}

function age(y: number, m: number, d: number): number {
  const now = new Date()
  return now.getFullYear() - y - (now.getMonth() + 1 < m || (now.getMonth() + 1 === m && now.getDate() < d) ? 1 : 0)
}

/** After the first sign-in: choose your school, a permanent team name and your date of birth (18+). */
export default function ProfilePage() {
  const { token, status, reload } = useSession()
  const { data: schools } = useApi<School[]>('/schools')
  const [schoolId, setSchoolId] = useState('')
  const [teamName, setTeamName] = useState('')
  const [day, setDay] = useState('')
  const [month, setMonth] = useState('')
  const [year, setYear] = useState('')
  const [referral, setReferral] = useState(savedReferral() ?? '')
  const [showReferral, setShowReferral] = useState(!!savedReferral())
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => { if (schools?.length === 1 && !schoolId) setSchoolId(schools[0].id) }, [schools, schoolId])

  if (status !== 'needs_profile') {
    return <section><PageHeader title="Profile" back="#/" /><p className="muted">Your profile is already set up.</p></section>
  }

  const name = teamName.trim()
  const nameError = name.length > 0 && name.length < 3 ? 'At least 3 characters'
    : name && !NAME_OK.test(name) ? 'Letters, numbers, spaces, _ . - only' : null
  const dobSet = day && month && year
  const under18 = dobSet ? age(+year, +month, +day) < 18 : false
  const ready = schoolId && name.length >= 3 && !nameError && dobSet && !under18
  const thisYear = new Date().getFullYear()
  const daysIn = month && year ? new Date(+year, +month, 0).getDate() : 31

  async function save(e: React.FormEvent) {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      const dob = `${year}-${month.padStart(2, '0')}-${day.padStart(2, '0')}`
      await api('/me', token, { method: 'POST', body: {
        school_id: schoolId, team_name: name, dob, referral_code: referral.trim() || null } })
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
      <PageHeader title="" back="#/" action={<span />} />
      <form className="auth onboarding" onSubmit={save}>
        <p className="headline">Set up your<br /><b>profile</b></p>

        <div className="field-group">
          <span className="field-label">Your school</span>
          <SchoolPicker schools={schools ?? null} value={schoolId} onChange={setSchoolId} />
        </div>

        <div className="field-group">
          <label className="field-label" htmlFor="team-name">Team name
            <small className="muted"> {name.length}/30</small></label>
          <input id="team-name" className="field-lg" value={teamName} maxLength={30} autoComplete="off"
            placeholder="e.g. Ballers FC" onChange={(e) => setTeamName(e.target.value)} />
          <small className={nameError ? 'error' : 'muted'}>{nameError ?? 'Shown on leaderboards. It can\'t be changed later.'}</small>
        </div>

        <div className="field-group">
          <span className="field-label">Date of birth</span>
          <div className="dob-row">
            <Select label="Day" value={day} onChange={setDay}
              options={Array.from({ length: daysIn }, (_, i) => [String(i + 1), String(i + 1)])} />
            <Select label="Month" value={month} onChange={setMonth}
              options={MONTHS.map((m, i) => [String(i + 1), m])} />
            <Select label="Year" value={year} onChange={setYear}
              options={Array.from({ length: 50 }, (_, i) => String(thisYear - 17 - i)).map((y) => [y, y])} />
          </div>
          <small className={under18 ? 'error' : 'muted'}>{under18 ? 'CampusXI is for players aged 18 and over.' : 'CampusXI is 18+.'}</small>
        </div>

        {showReferral ? (
          <div className="field-group">
            <label className="field-label" htmlFor="referral">Friend's code</label>
            <input id="referral" className="field-lg" value={referral} maxLength={12} autoComplete="off"
              onChange={(e) => setReferral(e.target.value.toUpperCase())} placeholder="ABC123" />
          </div>
        ) : (
          <button type="button" className="link" onClick={() => setShowReferral(true)}>Got a friend's code?</button>
        )}

        {error && <p className="error">{error}</p>}
        <button className="primary" disabled={busy || !ready}>{busy ? 'Saving…' : 'Create profile'}</button>
      </form>
    </section>
  )
}

/** Schools as tappable rows (a search box appears once there are more than five). */
function SchoolPicker({ schools, value, onChange }: { schools: School[] | null; value: string; onChange: (id: string) => void }) {
  const [q, setQ] = useState('')
  if (!schools) return <div className="pick-list"><div className="pick-row skeleton-row" /></div>
  if (schools.length === 0) return <p className="muted small">No schools yet: ask your sports council to get set up.</p>
  const term = q.trim().toLowerCase()
  const shown = schools.filter((s) => !term || s.name.toLowerCase().includes(term))
  return (
    <>
      {schools.length > 5 && (
        <input className="field-lg" placeholder="Search schools" value={q} onChange={(e) => setQ(e.target.value)}
          aria-label="Search schools" />
      )}
      <div className="pick-list" role="radiogroup" aria-label="School">
        {shown.map((s) => (
          <button key={s.id} type="button" role="radio" aria-checked={value === s.id}
            className={`pick-row ${value === s.id ? 'on' : ''}`} onClick={() => onChange(s.id)}>
            <span className="pick-mark" aria-hidden>{initials(s.name) || s.name[0]}</span>
            <span className="grow">{s.name}</span>
            <span className="pick-check" aria-hidden>{value === s.id ? '✓' : ''}</span>
          </button>
        ))}
        {shown.length === 0 && <p className="muted small">No school matches "{q}".</p>}
      </div>
    </>
  )
}

function Select({ label, value, onChange, options }: {
  label: string; value: string; onChange: (v: string) => void; options: [string, string][]
}) {
  return (
    <label className={`select-pill ${value ? 'set' : ''}`}>
      <span className="sr-only">{label}</span>
      <select value={value} onChange={(e) => onChange(e.target.value)} aria-label={label}>
        <option value="">{label}</option>
        {options.map(([v, text]) => <option key={v} value={v}>{text}</option>)}
      </select>
    </label>
  )
}
