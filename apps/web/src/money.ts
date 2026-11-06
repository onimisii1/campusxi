// Shared wallet types and helpers. Money is integer kobo everywhere.
import { useSession } from './session'
import { useApi } from './useApi'

export type Wallet = {
  cash_kobo: number
  bonus_kobo: number
  held_kobo: number
  bonus_expires_at: string | null
  kyc_status: 'none' | 'pending' | 'verified' | 'rejected'
  paid_play_enabled: boolean
  result_bets_enabled: boolean
  bonus_max_share_bps: number
  min_deposit_kobo: number
  min_withdrawal_kobo: number
  limits: {
    daily_deposit_kobo: number | null
    daily_stake_kobo: number | null
    deposited_today_kobo: number
    staked_today_kobo: number
    self_excluded_until: string | null
  }
}

export function naira(kobo: number): string {
  return `₦${(kobo / 100).toLocaleString(undefined, { maximumFractionDigits: 2 })}`
}

/** How a stake would be paid: coins first, up to the allowed share, then cash. */
export function split(w: Wallet, amount: number): { coins: number; cash: number; short: number } {
  const coins = Math.min(w.bonus_kobo, Math.floor((amount * w.bonus_max_share_bps) / 10000))
  const cash = amount - coins
  return { coins, cash, short: Math.max(0, cash - w.cash_kobo) }
}

export function payLine(w: Wallet, amount: number): string {
  const s = split(w, amount)
  return s.coins ? `${naira(s.coins)} coins + ${naira(s.cash)} cash` : `${naira(s.cash)} from your cash`
}

/** The signed-in player's wallet (null when signed out). */
export function useWallet() {
  const { status } = useSession()
  return useApi<Wallet>(status === 'ready' ? '/me/wallet' : null)
}

const REF_KEY = 'campusxi.referral'

export function rememberReferral(code: string): void {
  try {
    localStorage.setItem(REF_KEY, code.toUpperCase())
  } catch {
    // private mode: the code just isn't kept
  }
}

export function savedReferral(): string | null {
  try {
    return localStorage.getItem(REF_KEY)
  } catch {
    return null
  }
}

export function newIdempotencyKey(): string {
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`
}
