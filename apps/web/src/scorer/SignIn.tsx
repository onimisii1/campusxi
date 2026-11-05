import { useState } from 'react'
import { devTokenMode, sendCode, setDevToken, supabase, verifyCode } from '../auth'

export default function SignIn({ onSignedIn }: { onSignedIn: () => void }) {
  const [email, setEmail] = useState('')
  const [code, setCode] = useState('')
  const [sent, setSent] = useState(false)
  const [token, setToken] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function run(fn: () => Promise<void>) {
    setBusy(true)
    setError(null)
    try {
      await fn()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'something went wrong')
    } finally {
      setBusy(false)
    }
  }

  if (devTokenMode) {
    return (
      <form className="card" onSubmit={(e) => { e.preventDefault(); setDevToken(token); onSignedIn() }}>
        <h2>Scorer sign-in (development)</h2>
        <p className="muted">Supabase isn't configured, so paste an API token for a scorer account.</p>
        <textarea value={token} onChange={(e) => setToken(e.target.value)} rows={4} required aria-label="API token" />
        <button className="primary" type="submit">Continue</button>
      </form>
    )
  }

  if (!supabase) {
    return <p className="card">Sign-in isn't configured for this build.</p>
  }

  return (
    <form
      className="card"
      onSubmit={(e) => {
        e.preventDefault()
        run(async () => {
          if (!sent) {
            await sendCode(email)
            setSent(true)
          } else {
            await verifyCode(email, code)
            onSignedIn()
          }
        })
      }}
    >
      <h2>Scorer sign-in</h2>
      <label>
        Email
        <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required disabled={sent} />
      </label>
      {sent && (
        <label>
          Code from your email
          <input inputMode="numeric" value={code} onChange={(e) => setCode(e.target.value)} required autoFocus />
        </label>
      )}
      {error && <p className="error">{error}</p>}
      <button className="primary" type="submit" disabled={busy}>{sent ? 'Sign in' : 'Send code'}</button>
    </form>
  )
}
