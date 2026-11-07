import { useEffect, useRef, useState } from 'react'
import { devTokenMode, sendCode, setDevToken, supabase, verifyCode } from '../auth'

const LENGTH = 6
const RESEND_AFTER = 30

/** Email one-time code sign-in: email, then six code boxes (paste and phone autofill fill them all;
 *  the sixth digit signs you in). */
export default function SignIn({ onSignedIn, title = 'Sign in' }: { onSignedIn: () => void; title?: string }) {
  const [email, setEmail] = useState('')
  const [sent, setSent] = useState(false)
  const [token, setToken] = useState('')
  const [error, setError] = useState<string | null>(() => {
    const e = sessionStorage.getItem('campusxi.signinError')   // e.g. an expired email link
    sessionStorage.removeItem('campusxi.signinError')
    return e ? `${e}. Send a new code below.` : null
  })
  const [busy, setBusy] = useState(false)
  const [wait, setWait] = useState(0)

  useEffect(() => {
    if (wait <= 0) return
    const t = window.setTimeout(() => setWait((w) => w - 1), 1000)
    return () => window.clearTimeout(t)
  }, [wait])

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

  const send = () => run(async () => {
    await sendCode(email.trim())
    setSent(true)
    setWait(RESEND_AFTER)
  })

  if (devTokenMode) {
    return (
      <form className="auth" onSubmit={(e) => { e.preventDefault(); setDevToken(token); onSignedIn() }}>
        <p className="headline">{title}<br /><b>(development)</b></p>
        <p className="muted small">Supabase isn't configured: paste an API token from scripts/dev_seed.py.</p>
        <textarea value={token} onChange={(e) => setToken(e.target.value)} rows={4} required aria-label="API token" />
        <button className="primary" type="submit">Continue</button>
      </form>
    )
  }

  if (!supabase) return <p className="muted">Sign-in isn't configured for this build.</p>

  if (!sent) {
    return (
      <form className="auth" onSubmit={(e) => { e.preventDefault(); send() }}>
        <p className="headline">Welcome to<br /><b>CampusXI</b></p>
        <p className="muted">Sign in with your email. We'll send a 6-digit code, no password needed.</p>
        <input className="field-lg" type="email" inputMode="email" autoComplete="email" placeholder="you@school.edu.ng"
          value={email} onChange={(e) => setEmail(e.target.value)} required aria-label="Email" autoFocus />
        {error && <p className="error">{error}</p>}
        <button className="primary" type="submit" disabled={busy || !/^\S+@\S+\.\S+$/.test(email)}>
          {busy ? 'Sending…' : 'Send code'}</button>
      </form>
    )
  }

  return (
    <div className="auth">
      <p className="headline">Check your<br /><b>email</b></p>
      <p className="muted">Enter the code we sent to <b className="ink">{email}</b>.</p>
      <CodeBoxes disabled={busy} onComplete={(code) => run(async () => {
        await verifyCode(email.trim(), code)
        onSignedIn()
      })} />
      {error && <p className="error">{error}</p>}
      {busy && <p className="muted small">Signing you in…</p>}
      <div className="text-actions">
        <button className="link" type="button" disabled={wait > 0 || busy} onClick={send}>
          {wait > 0 ? `Resend in ${wait}s` : 'Resend code'}</button>
        <span aria-hidden>·</span>
        <button className="link" type="button" onClick={() => { setSent(false); setError(null) }}>Change email</button>
      </div>
      <p className="muted small">Or tap the link in the email on this phone.</p>
    </div>
  )
}

function CodeBoxes({ onComplete, disabled }: { onComplete: (code: string) => void; disabled: boolean }) {
  const [digits, setDigits] = useState<string[]>(Array(LENGTH).fill(''))
  const refs = useRef<(HTMLInputElement | null)[]>([])

  function fill(from: number, text: string) {
    const clean = text.replace(/\D/g, '')
    if (!clean) return
    const next = [...digits]
    for (let i = 0; i < clean.length && from + i < LENGTH; i++) next[from + i] = clean[i]
    setDigits(next)
    const empty = next.findIndex((d) => !d)
    refs.current[empty === -1 ? LENGTH - 1 : empty]?.focus()
    if (next.every(Boolean)) onComplete(next.join(''))
  }

  return (
    <div className="code-boxes" role="group" aria-label="6-digit code">
      {digits.map((d, i) => (
        <input key={i} ref={(el) => { refs.current[i] = el }} value={d} disabled={disabled}
          inputMode="numeric" autoComplete={i === 0 ? 'one-time-code' : 'off'} aria-label={`Digit ${i + 1}`}
          autoFocus={i === 0}
          onChange={(e) => {
            const v = e.target.value
            if (v === '') {
              setDigits(digits.map((x, j) => (j === i ? '' : x)))
              return
            }
            // One new digit types into this box; several (autofill, or a paste the browser let through) spread out.
            fill(i, v.length > 1 && v.replace(/\D/g, '').length > 1 ? v : v.slice(-1))
          }}
          onPaste={(e) => { e.preventDefault(); fill(0, e.clipboardData.getData('text')) }}
          onKeyDown={(e) => {
            if (e.key === 'Backspace' && !digits[i] && i > 0) refs.current[i - 1]?.focus()
          }} />
      ))}
    </div>
  )
}
