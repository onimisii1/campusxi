import { useEffect, useState } from 'react'
import { api } from '../api'
import ComingSoon from '../components/ComingSoon'
import PageHeader from '../components/PageHeader'
import Skeleton from '../components/Skeleton'
import { naira, rememberReferral, useWallet } from '../money'
import { useSession } from '../session'
import { useToast } from '../toast'
import { errorText, useApi } from '../useApi'

/** ID check (NIN or BVN). Needed before money moves; we keep only the last 4 digits. */
export function VerifyPage() {
  const { token } = useSession()
  const toast = useToast()
  const { data: w, reload } = useWallet()
  const [idType, setIdType] = useState<'nin' | 'bvn'>('nin')
  const [number, setNumber] = useState('')
  const [name, setName] = useState('')
  const [busy, setBusy] = useState(false)
  const [reason, setReason] = useState<string | null>(null)
  if (!w) return <Skeleton rows={3} />
  if (!w.kyc_required && w.kyc_status !== 'verified') {
    return (
      <section>
        <PageHeader title="Verify your ID" back="#/me" />
        <ComingSoon icon="🪪" title="ID verification (NIN / BVN)">
          Not needed to play right now: tick 18+ in your wallet, and your bank name comes from your first deposit.
        </ComingSoon>
      </section>
    )
  }

  async function go() {
    setBusy(true)
    setReason(null)
    try {
      const r = await api<{ status: string; reason: string | null }>('/me/kyc', token,
        { method: 'POST', body: { id_type: idType, number, full_name: name } })
      if (r.status === 'verified') toast('Verified: you can add money and play for cash')
      else setReason(r.reason ?? 'We could not verify that ID')
      reload()
    } catch (e) {
      toast(errorText(e), 'bad')
    } finally {
      setBusy(false)
    }
  }

  return (
    <section>
      <PageHeader title="Verify your ID" back="#/wallet" />
      {w.kyc_status === 'verified' ? (
        <div className="glass-card center"><p className="big-emoji">✅</p><h2>You're verified</h2>
          <a className="primary as-button" href="#/wallet">Go to wallet</a></div>
      ) : (
        <div className="glass-card">
          <p className="small">CampusXI is 18+. Paid play needs your NIN or BVN so we know it's really you, and so winnings go
            to an account in your name. We keep only the last 4 digits.</p>
          <div className="toggle" role="tablist">
            {(['nin', 'bvn'] as const).map((t) => (
              <button key={t} role="tab" aria-selected={idType === t} className={idType === t ? 'on' : ''} onClick={() => setIdType(t)}>
                {t.toUpperCase()}</button>
            ))}
          </div>
          <label>{idType.toUpperCase()} (11 digits)
            <input inputMode="numeric" maxLength={11} value={number} onChange={(e) => setNumber(e.target.value.replace(/\D/g, ''))} />
          </label>
          <label>Full name as on your ID<input value={name} onChange={(e) => setName(e.target.value)} /></label>
          {reason && <p className="error">{reason}</p>}
          <button className="primary" disabled={number.length !== 11 || name.trim().length < 3 || busy} onClick={go}>
            {busy ? 'Checking…' : 'Verify'}</button>
        </div>
      )}
    </section>
  )
}

/** Responsible gaming: daily limits (lower now, higher after 24h) and breaks. */
export function LimitsPage() {
  const { token } = useSession()
  const toast = useToast()
  const { data: w, reload } = useWallet()
  const [deposit, setDeposit] = useState('')
  const [stake, setStake] = useState('')
  if (!w) return <Skeleton rows={3} />
  const l = w.limits

  async function save() {
    try {
      await api('/me/limits', token, { method: 'PUT', body: {
        daily_deposit_kobo: deposit ? Math.round(Number(deposit) * 100) : null,
        daily_stake_kobo: stake ? Math.round(Number(stake) * 100) : null } })
      toast('Saved. Lower limits apply now; higher ones after 24 hours.')
      setDeposit('')
      setStake('')
      reload()
    } catch (e) {
      toast(errorText(e), 'bad')
    }
  }

  async function pause(days: number) {
    if (!window.confirm(`No paid play or deposits for ${days} days. This can't be undone early. Continue?`)) return
    try {
      await api('/me/self-exclusion', token, { method: 'POST', body: { days } })
      toast(`Break started: back in ${days} days`)
      reload()
    } catch (e) {
      toast(errorText(e), 'bad')
    }
  }

  return (
    <section>
      <PageHeader title="Limits and breaks" back="#/wallet" />
      <div className="stat-tiles money">
        <div><b>{l.daily_deposit_kobo != null ? naira(l.daily_deposit_kobo) : '—'}</b><span>Deposit limit / day</span></div>
        <div><b>{l.daily_stake_kobo != null ? naira(l.daily_stake_kobo) : 'None'}</b><span>Stake limit / day</span></div>
        <div><b>{naira(l.staked_today_kobo)}</b><span>Staked today</span></div>
      </div>
      <div className="glass-card form-grid">
        <label>New deposit limit (₦)<input inputMode="numeric" value={deposit} onChange={(e) => setDeposit(e.target.value)} /></label>
        <label>New stake limit (₦)<input inputMode="numeric" value={stake} onChange={(e) => setStake(e.target.value)} /></label>
        <button className="primary" disabled={!deposit && !stake} onClick={save}>Save limits</button>
      </div>
      <h3>Take a break</h3>
      {l.self_excluded_until
        ? <p className="notice">On a break until {new Date(l.self_excluded_until).toLocaleDateString()}.</p>
        : <div className="row gap">{[1, 7, 30, 180].map((d) => <button key={d} className="sheet-btn" onClick={() => pause(d)}>{d === 1 ? '24 hours' : `${d} days`}</button>)}</div>}
      <p className="muted small">Playing should stay fun. If it isn't, take a break or talk to someone you trust.</p>
    </section>
  )
}

type Referral = { code: string; link: string; friends_rewarded: number; friends_waiting: number; coins_earned_kobo: number
  reward_kobo: number; friend_reward_kobo: number; min_deposit_kobo: number }

/** Invite friends: both get coins once the friend verifies and makes a first deposit. */
export function ReferPage() {
  const { data: r } = useApi<Referral>('/me/referral')
  const toast = useToast()
  if (!r) return <Skeleton rows={3} />
  async function share() {
    const text = `Join me on CampusXI, fantasy for our campus games. Use my code ${r!.code}: ${r!.link}`
    try {
      if (navigator.share) await navigator.share({ title: 'CampusXI', text })
      else {
        await navigator.clipboard.writeText(text)
        toast('Invite copied: paste it in WhatsApp')
      }
    } catch {
      // cancelled
    }
  }
  return (
    <section>
      <PageHeader title="Invite friends" back="#/wallet" />
      <div className="glass-hero balance-card center">
        <span className="small">Your code</span>
        <b className="balance code">{r.code}</b>
        <button className="primary" onClick={share}>Share invite</button>
      </div>
      <p className="small">You get <b>{naira(r.reward_kobo)}</b> in coins and your friend gets <b>{naira(r.friend_reward_kobo)}</b> once
        they verify their ID and add at least {naira(r.min_deposit_kobo)}.</p>
      <div className="stat-tiles money">
        <div><b>{r.friends_rewarded}</b><span>Friends joined</span></div>
        <div><b>{r.friends_waiting}</b><span>Waiting to deposit</span></div>
        <div><b>{naira(r.coins_earned_kobo)}</b><span>Coins earned</span></div>
      </div>
      <p className="muted small">Coins can't be withdrawn. Use them for up to half of any entry or stake; winnings are cash.</p>
    </section>
  )
}

/** #/join/CODE: remember a friend's code for sign-up. */
export function JoinWithCode({ code }: { code: string }) {
  useEffect(() => { rememberReferral(code) }, [code])
  return (
    <section>
      <PageHeader title="Welcome to CampusXI" back="#/" />
      <div className="glass-card center">
        <p className="big-emoji">⚽🏀</p>
        <h2>Your friend invited you</h2>
        <p className="muted">Code <b>{code.toUpperCase()}</b> is saved: sign up and verify your ID to get your welcome coins.</p>
        <a className="primary as-button" href="#/signin">Sign up</a>
      </div>
    </section>
  )
}
