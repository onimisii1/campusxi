import { useEffect, useState } from 'react'
import { api } from '../api'
import { changeEmail, confirmEmailChange, currentEmail, signOutEverywhere, supabase } from '../auth'
import PageHeader from '../components/PageHeader'
import { go } from '../router'
import { useSession } from '../session'
import { useToast } from '../toast'
import { errorText } from '../useApi'

/** Account and security: sign-in email, change it, sign out everywhere, delete the account. */
export default function AccountPage() {
  const { status, token, reload, signOut } = useSession()
  const toast = useToast()
  const [email, setEmail] = useState<{ email: string | null; pending: string | null } | null>(null)
  const refresh = () => currentEmail().then(setEmail)
  useEffect(() => { refresh() }, [])

  if (status !== 'ready') return <section><PageHeader title="Account" back="#/me" /><p className="muted">Sign in first.</p></section>

  return (
    <section>
      <PageHeader title="Account" back="#/me" />
      <div className="glass-card">
        <small className="muted">Signed in as</small>
        <p className="account-email">{email?.email ?? (supabase ? '…' : 'Development sign-in (no email)')}</p>
        {email?.pending && <p className="small notice">Waiting to confirm the move to <b>{email.pending}</b>.</p>}
      </div>
      {supabase && <ChangeEmail pending={email?.pending ?? null} onDone={() => { refresh(); toast('Email updated') }} />}
      <div className="glass-card">
        <strong>Sign out everywhere</strong>
        <p className="small muted">Lost your phone? This ends your session on every device. You'll sign in again with a code.</p>
        <button className="sheet-btn" onClick={async () => {
          if (!window.confirm('Sign out on all your devices?')) return
          await signOutEverywhere()
          await reload()
          go('/')
        }}>Sign out everywhere</button>
      </div>
      <DeleteAccount token={token} onDeleted={async () => { await signOut(); toast('Your account was deleted'); go('/') }} />
    </section>
  )
}

function ChangeEmail({ pending, onDone }: { pending: string | null; onDone: () => void }) {
  const toast = useToast()
  const [next, setNext] = useState('')
  const [sentTo, setSentTo] = useState<string | null>(pending)
  const [code, setCode] = useState('')
  const [busy, setBusy] = useState(false)
  useEffect(() => { setSentTo(pending) }, [pending])

  async function run(fn: () => Promise<void>) {
    setBusy(true)
    try {
      await fn()
    } catch (e) {
      toast(e instanceof Error ? e.message : 'something went wrong', 'bad')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="glass-card">
      <strong>Change email</strong>
      {!sentTo ? (
        <>
          <p className="small muted">We'll send a code to the new address to confirm it's yours.</p>
          <label>New email<input type="email" value={next} onChange={(e) => setNext(e.target.value)} /></label>
          <button className="primary" disabled={busy || !/^\S+@\S+\.\S+$/.test(next)}
            onClick={() => run(async () => { await changeEmail(next.trim()); setSentTo(next.trim()) })}>Send code</button>
        </>
      ) : (
        <>
          <p className="small muted">Enter the code we emailed to <b>{sentTo}</b>. If your old address also got a code, enter
            that one next.</p>
          <label>Code<input inputMode="numeric" value={code} onChange={(e) => setCode(e.target.value)} /></label>
          <button className="primary" disabled={busy || code.length < 6}
            onClick={() => run(async () => {
              await confirmEmailChange(sentTo, code.trim())
              setCode('')
              const now = await currentEmail()
              if (now.pending) {
                toast('Confirmed. Now enter the code sent to your old address.')
                setSentTo(now.email)
              } else {
                setSentTo(null)
                setNext('')
                onDone()
              }
            })}>Confirm</button>
          <button className="link" onClick={() => { setSentTo(null); setCode('') }}>Use a different email</button>
        </>
      )}
    </div>
  )
}

function DeleteAccount({ token, onDeleted }: { token: string | null; onDeleted: () => void }) {
  const toast = useToast()
  const [open, setOpen] = useState(false)
  const [typed, setTyped] = useState('')
  const [busy, setBusy] = useState(false)
  return (
    <div className="glass-card danger-zone">
      <strong>Delete account</strong>
      {!open ? (
        <>
          <p className="small muted">Erases your name, photo and sign-in. Withdraw any cash first; coins are lost.</p>
          <button className="sheet-btn danger" onClick={() => setOpen(true)}>Delete my account…</button>
        </>
      ) : (
        <>
          <ul className="small">
            <li>Your team name, photo and sign-in email are erased; you can't undo this.</li>
            <li>Your cash must be withdrawn first, and nothing can still be in play.</li>
            <li>Referral coins are lost.</li>
            <li>Payment and match records are kept without your name, because the law requires it.</li>
          </ul>
          <label>Type DELETE to confirm<input value={typed} onChange={(e) => setTyped(e.target.value)} /></label>
          <button className="primary danger-btn" disabled={typed !== 'DELETE' || busy} onClick={async () => {
            setBusy(true)
            try {
              await api('/me', token, { method: 'DELETE' })
              onDeleted()
            } catch (e) {
              toast(errorText(e), 'bad')
            } finally {
              setBusy(false)
            }
          }}>{busy ? 'Deleting…' : 'Delete my account'}</button>
          <button className="link" onClick={() => { setOpen(false); setTyped('') }}>Cancel</button>
        </>
      )}
    </div>
  )
}
