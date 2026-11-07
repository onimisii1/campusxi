import { useEffect, useRef, useState } from 'react'
import { api } from '../api'
import PageHeader from '../components/PageHeader'
import Skeleton from '../components/Skeleton'
import { naira, newIdempotencyKey, useWallet, type Wallet } from '../money'
import { signInThenReturn } from '../router'
import { useSession } from '../session'
import { useToast } from '../toast'
import { errorText, useApi } from '../useApi'

type HistoryRow = { at: string; label: string; type: string; cash_kobo: number; bonus_kobo: number }
type Bank = { code: string; name: string }
type BankAccount = { id: string; bank_name: string; account_name: string; last4: string }
type Withdrawal = { id: string; amount_kobo: number; status: string; created_at: string; failure_reason: string | null }

const TABS = ['Add money', 'Withdraw', 'History'] as const
type Tab = (typeof TABS)[number]
const CHIPS = [100_000, 200_000, 500_000, 1_000_000]

/** Wallet: balances, deposits (Paystack / Flutterwave checkout), withdrawals to a bank, history. */
export default function WalletPage() {
  const { status } = useSession()
  const { data: w, reload } = useWallet()
  const [tab, setTab] = useState<Tab>('Add money')
  if (status === 'signed_out') {
    return <section><PageHeader title="Wallet" back="#/me" /><button className="primary" onClick={signInThenReturn}>Sign in</button></section>
  }
  if (!w) return <Skeleton hero rows={3} />
  return (
    <section>
      <PageHeader title="Wallet" back="#/me" />
      <div className="balance-card glass-hero">
        <span className="small">Cash (withdrawable)</span>
        <b className="balance">{naira(w.cash_kobo)}</b>
        <div className="row between small">
          <span><i className="coin-dot" aria-hidden />{naira(w.bonus_kobo)} coins{w.bonus_expires_at ? ` · expire ${new Date(w.bonus_expires_at).toLocaleDateString()}` : ''}</span>
          {w.held_kobo > 0 && <span>In play {naira(w.held_kobo)}</span>}
        </div>
      </div>
      {w.kyc_required ? w.kyc_status !== 'verified' && (
        <a className="notice block-link" href="#/verify">🪪 Verify your ID (NIN or BVN) to add money and play for cash →</a>
      ) : <StartChecks w={w} onDone={reload} />}
      {w.limits.self_excluded_until && (
        <p className="notice">You're on a break from paid play until {new Date(w.limits.self_excluded_until).toLocaleDateString()}.
          You can still withdraw.</p>
      )}
      <div className="tabs" role="tablist">
        {TABS.map((t) => (
          <button key={t} role="tab" aria-selected={tab === t} className={tab === t ? 'tab on' : 'tab'} onClick={() => setTab(t)}>{t}</button>
        ))}
      </div>
      {tab === 'Add money' && <Deposit minimum={w.min_deposit_kobo} disabled={!w.can_play_paid} transferOnly={!w.kyc_required} />}
      {tab === 'Withdraw' && <Withdraw cash={w.cash_kobo} minimum={w.min_withdrawal_kobo}
        verified={w.kyc_required ? w.kyc_status === 'verified' : !!w.legal_name}
        legalName={w.kyc_required ? null : w.legal_name} onDone={reload} />}
      {tab === 'History' && <History />}
      <div className="link-pair">
        <a className="action-pill" href="#/refer">Invite friends</a>
        <a className="action-pill" href="#/limits">Limits</a>
      </div>
    </section>
  )
}

/** KYC optional for now (SportyBet-style): tick 18+, and give the full name your bank account is in. */
function StartChecks({ w, onDone }: { w: Wallet; onDone: () => void }) {
  const { token } = useSession()
  const toast = useToast()
  const [ticked, setTicked] = useState(false)
  const [name, setName] = useState(w.legal_name ?? '')
  const [editing, setEditing] = useState(!w.legal_name)
  const run = async (fn: () => Promise<unknown>, done: string) => {
    try {
      await fn()
      toast(done)
      onDone()
    } catch (e) {
      toast(errorText(e), 'bad')
    }
  }
  if (w.adult_confirmed && w.legal_name && !editing) {
    return (
      <div className="glass-card row between start-checks done">
        <span className="small"><span className="muted">Bank name</span> <b>{w.legal_name}</b></span>
        {!w.legal_name_locked && <button className="link" onClick={() => setEditing(true)}>Change</button>}
      </div>
    )
  }
  // One form, one button: the 18+ tick and the bank-account name are saved together.
  const needAdult = !w.adult_confirmed
  const needName = editing || !w.legal_name
  const nameOk = name.trim().split(/\s+/).length >= 2
  return (
    <div className="glass-card start-checks">
      <strong>Play for cash</strong>
      {needName && (
        <input value={name} onChange={(e) => setName(e.target.value)} autoComplete="name"
          placeholder="Full name, as on your bank account" aria-label="Full name, as on your bank account" />
      )}
      {needAdult && (
        <label className="inline small"><input type="checkbox" checked={ticked} onChange={(e) => setTicked(e.target.checked)} />
          I'm 18+ and play with my own money</label>
      )}
      <button className="primary" disabled={(needAdult && !ticked) || (needName && !nameOk)}
        onClick={() => run(async () => {
          if (needAdult) await api('/me/confirm-18', token, { method: 'POST', body: { confirm: true } })
          if (needName) await api('/me/legal-name', token, { method: 'PUT', body: { legal_name: name } })
          setEditing(false)
        }, 'Saved: paid play is open')}>Save</button>
    </div>
  )
}

function Deposit({ minimum, disabled, transferOnly }: { minimum: number; disabled: boolean; transferOnly: boolean }) {
  const { token } = useSession()
  const toast = useToast()
  const [amount, setAmount] = useState(200_000)
  const [busy, setBusy] = useState(false)
  const key = useRef(newIdempotencyKey())

  async function go() {
    setBusy(true)
    try {
      const d = await api<{ checkout_url: string }>('/wallet/deposits', token,
        { method: 'POST', body: { amount_kobo: amount }, idempotencyKey: key.current })
      window.location.href = d.checkout_url        // provider's secure checkout; it sends you back here
    } catch (e) {
      toast(errorText(e), 'bad')
      key.current = newIdempotencyKey()
      setBusy(false)
    }
  }

  return (
    <div className="glass-card">
      <div className="chip-row">
        {CHIPS.map((c) => (
          <button key={c} className={`chip ${amount === c ? 'on' : ''}`} onClick={() => { setAmount(c); key.current = newIdempotencyKey() }}>
            {naira(c)}</button>
        ))}
      </div>
      <div className="inline-form">
        <input inputMode="numeric" value={amount / 100} aria-label="Amount in naira" placeholder="Other amount (₦)"
          onChange={(e) => { setAmount(Math.round(Number(e.target.value || 0) * 100)); key.current = newIdempotencyKey() }} />
        <button className="primary" disabled={disabled || busy || amount < minimum} onClick={go}>
          {busy ? 'Opening…' : `Add ${naira(amount)}`}</button>
      </div>
      <p className="muted small">{transferOnly ? 'Bank transfer from your own account: winnings go back there.'
        : 'Card, transfer or USSD.'} Min {naira(minimum)}.</p>
    </div>
  )
}

function Withdraw({ cash, minimum, verified, legalName, onDone }: {
  cash: number; minimum: number; verified: boolean; legalName: string | null; onDone: () => void
}) {
  const { token } = useSession()
  const toast = useToast()
  const { data: accounts, reload } = useApi<BankAccount[]>('/me/bank-accounts')
  const { data: history, reload: reloadHistory } = useApi<Withdrawal[]>('/me/withdrawals')
  const [account, setAccount] = useState('')
  const [amount, setAmount] = useState('')
  const [adding, setAdding] = useState(false)
  const key = useRef(newIdempotencyKey())
  useEffect(() => { if (!account && accounts?.length) setAccount(accounts[0].id) }, [accounts, account])

  async function go() {
    try {
      const w = await api<Withdrawal & { needs_approval: boolean }>('/wallet/withdrawals', token, {
        method: 'POST', body: { amount_kobo: Math.round(Number(amount) * 100), bank_account_id: account },
        idempotencyKey: key.current })
      toast(w.needs_approval ? 'Requested: an admin checks first withdrawals and large ones' : 'On its way to your bank')
      key.current = newIdempotencyKey()
      setAmount('')
      onDone()
      reloadHistory()
    } catch (e) {
      toast(errorText(e), 'bad')
    }
  }

  if (!verified) {
    return <p className="muted">{legalName === null ? 'Verify your ID first.' : 'Save your bank name above first.'}</p>
  }
  return (
    <div>
      <div className="glass-card">
        {accounts?.length ? (
          <label>To
            <select value={account} onChange={(e) => setAccount(e.target.value)}>
              {accounts.map((a) => <option key={a.id} value={a.id}>{a.bank_name} ····{a.last4} · {a.account_name}</option>)}
            </select>
          </label>
        ) : <p className="muted small">Add the bank account to pay into.</p>}
        {adding || !accounts?.length
          ? <AddBank onAdded={() => { setAdding(false); reload() }} />
          : <button className="link" onClick={() => setAdding(true)}>+ Another bank account</button>}
        {accounts && accounts.length > 0 && (
          <>
            <label>Amount (₦) <small className="muted">available {naira(cash)}</small>
              <input inputMode="numeric" value={amount} onChange={(e) => setAmount(e.target.value)} placeholder={String(minimum / 100)} />
            </label>
            <button className="primary" disabled={!account || Number(amount) * 100 < minimum || Number(amount) * 100 > cash}
              onClick={go}>Withdraw</button>
          </>
        )}
      </div>
      {history && history.length > 0 && (
        <ul className="plain txn-list">
          {history.map((x) => (
            <li key={x.id} className="row between">
              <span>{naira(x.amount_kobo)}<span className="muted small block">{new Date(x.created_at).toLocaleString()}</span></span>
              <span className={`badge ${x.status === 'paid' ? 'good' : ['reversed', 'failed', 'rejected'].includes(x.status) ? 'bad' : 'warn'}`}>
                {x.status.replace('_', ' ')}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

function AddBank({ onAdded }: { onAdded: () => void }) {
  const { token } = useSession()
  const toast = useToast()
  const { data: banks } = useApi<Bank[]>('/payments/banks')
  const [bank, setBank] = useState('')
  const [number, setNumber] = useState('')
  const [busy, setBusy] = useState(false)
  async function add() {
    setBusy(true)
    try {
      const a = await api<BankAccount>('/me/bank-accounts', token, { method: 'POST', body: { bank_code: bank, account_number: number } })
      toast(`Added ${a.bank_name} · ${a.account_name}`)
      onAdded()
    } catch (e) {
      toast(errorText(e), 'bad')
    } finally {
      setBusy(false)
    }
  }
  return (
    <div className="form-grid">
      <label>Bank
        <select value={bank} onChange={(e) => setBank(e.target.value)}>
          <option value="">Choose</option>
          {banks?.map((b) => <option key={b.code} value={b.code}>{b.name}</option>)}
        </select>
      </label>
      <label>Account number<input inputMode="numeric" maxLength={10} value={number} onChange={(e) => setNumber(e.target.value.replace(/\D/g, ''))} /></label>
      <button className="primary" disabled={!bank || number.length !== 10 || busy} onClick={add}>
        {busy ? 'Checking the name…' : 'Add account'}</button>
    </div>
  )
}

function History() {
  const { data } = useApi<HistoryRow[]>('/me/wallet/history')
  if (!data) return <Skeleton rows={4} />
  if (data.length === 0) return <p className="muted">No transactions yet.</p>
  return (
    <ul className="plain txn-list">
      {data.map((h, i) => {
        const total = h.cash_kobo + h.bonus_kobo
        return (
          <li key={i} className="row between">
            <span>{h.label}<span className="muted small block">{new Date(h.at).toLocaleString()}</span></span>
            <span className={total >= 0 ? 'amount-in' : 'amount-out'}>
              {total >= 0 ? '+' : '−'}{naira(Math.abs(h.cash_kobo))}{h.bonus_kobo ? ` ${h.bonus_kobo > 0 ? "+" : "−"}${naira(Math.abs(h.bonus_kobo))} coins` : ''}
            </span>
          </li>
        )
      })}
    </ul>
  )
}

/** Where checkout sends the player back: wait for our server to verify the payment. */
export function DepositReturn({ reference }: { reference: string }) {
  const { token } = useSession()
  const [state, setState] = useState<{ status: string; amount_kobo?: number }>({ status: 'pending' })
  useEffect(() => {
    let tries = 0
    let stop = false
    async function poll() {
      try {
        const r = await api<{ status: string; amount_kobo: number }>(`/wallet/deposits/${reference}`, token)
        setState(r)
        if (r.status !== 'pending' || stop) return
      } catch {
        // keep trying
      }
      if (++tries < 20 && !stop) setTimeout(poll, 3000)
    }
    if (token) poll()
    return () => { stop = true }
  }, [reference, token])
  return (
    <section>
      <PageHeader title="Payment" back="#/wallet" />
      <div className="glass-card center">
        {state.status === 'success' && <><p className="big-emoji">✅</p><h2>{naira(state.amount_kobo ?? 0)} added</h2></>}
        {state.status === 'failed' && <><p className="big-emoji">⚠️</p><h2>Payment didn't go through</h2><p className="muted">No money was taken from your wallet.</p></>}
        {state.status === 'pending' && <><p className="big-emoji">⏳</p><h2>Confirming your payment…</h2>
          <p className="muted">This usually takes a few seconds. Bank transfers can take a few minutes.</p></>}
        <a className="primary as-button" href="#/wallet">Back to wallet</a>
      </div>
    </section>
  )
}
