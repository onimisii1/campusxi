import { api } from '../../api'
import PageHeader from '../../components/PageHeader'
import Skeleton from '../../components/Skeleton'
import { naira } from '../../money'
import { useSession } from '../../session'
import { useToast } from '../../toast'
import { errorText, useApi } from '../../useApi'

type Finance = {
  player_cash_kobo: number; player_coins_kobo: number; held_kobo: number; in_pots_kobo: number
  platform_fee_kobo: number; coins_issued_kobo: number; deposits_24h_kobo: number; deposits_pending: number
  withdrawals_paid_24h_kobo: number; withdrawals_awaiting: number; paid_play_enabled: boolean
  ledger: { balanced: boolean; total_kobo: number; negative_accounts: { account: string; b: number }[] }
}
type Queued = { id: string; amount_kobo: number; created_at: string; team_name: string; bank_name: string | null
  account_name: string | null; last4: string | null; paid_before: number }

/** Money at a glance, the ledger check, and the withdrawal approval queue. */
export default function AdminFinance() {
  const { token } = useSession()
  const toast = useToast()
  const { data: f, reload } = useApi<Finance>('/admin/finance', 30_000)
  const { data: queue, reload: reloadQueue } = useApi<Queued[]>('/admin/withdrawals', 30_000)
  if (!f) return <Skeleton rows={5} />

  async function decide(id: string, action: 'approve' | 'reject') {
    if (action === 'reject' && !window.confirm('Reject this withdrawal? The money goes back to the player\'s wallet.')) return
    try {
      await api(`/admin/withdrawals/${id}/${action}`, token, { method: 'POST' })
      toast(action === 'approve' ? 'Approved: transfer sent' : 'Rejected: money returned')
      reload()
      reloadQueue()
    } catch (e) {
      toast(errorText(e), 'bad')
    }
  }

  const tiles: [string, number][] = [
    ['Players\' cash', f.player_cash_kobo], ['In play (held)', f.held_kobo], ['Awaiting payout', f.in_pots_kobo],
    ['Platform fees', f.platform_fee_kobo], ['Coins outstanding', f.player_coins_kobo], ['Deposits (24h)', f.deposits_24h_kobo],
  ]
  return (
    <section>
      <PageHeader title="Finance" back="#/admin" subtitle={f.paid_play_enabled ? 'Paid play is ON' : 'Paid play is off'} />
      <p className={`notice ${f.ledger.balanced && f.ledger.negative_accounts.length === 0 ? '' : 'warn'}`}>
        {f.ledger.balanced && f.ledger.negative_accounts.length === 0
          ? '✓ Ledger balanced: every naira is accounted for.'
          : `⚠ Ledger problem: total ${naira(f.ledger.total_kobo)}, ${f.ledger.negative_accounts.length} negative accounts.`}
      </p>
      <div className="stat-tiles money">
        {tiles.map(([label, v]) => <div key={label}><b>{naira(v)}</b><span>{label}</span></div>)}
      </div>
      <h3>Withdrawals to approve ({queue?.length ?? 0})</h3>
      {queue?.length === 0 && <p className="muted">Nothing waiting. First withdrawals and large ones land here.</p>}
      <ul className="plain">
        {queue?.map((q) => (
          <li key={q.id} className="glass-card">
            <div className="row between"><strong>{q.team_name}</strong><strong>{naira(q.amount_kobo)}</strong></div>
            <p className="small muted">{q.bank_name} ····{q.last4} · {q.account_name} · {q.paid_before ? `${q.paid_before} paid before` : 'first withdrawal'}
              {' · '}{new Date(q.created_at).toLocaleString()}</p>
            <div className="row gap">
              <button className="primary" onClick={() => decide(q.id, 'approve')}>Approve</button>
              <button className="sheet-btn" onClick={() => decide(q.id, 'reject')}>Reject</button>
            </div>
          </li>
        ))}
      </ul>
    </section>
  )
}
