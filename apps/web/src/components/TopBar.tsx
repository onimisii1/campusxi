import { useEffect } from 'react'
import { naira, useWallet } from '../money'

export default function TopBar() {
  const { data: w, reload } = useWallet()
  useEffect(() => {           // keep the balance fresh as the player moves around
    window.addEventListener('hashchange', reload)
    return () => window.removeEventListener('hashchange', reload)
  }, [reload])
  return (
    <header className="topbar">
      <a className="round-btn menu" href="#/me" aria-label="Menu and profile">
        <span /><span /><span />
      </a>
      <a className="wordmark" href="#/">CampusXI</a>
      {w ? (
        <a className="balance-chip" href="#/wallet" aria-label={`Wallet: ${naira(w.cash_kobo)} cash, ${naira(w.bonus_kobo)} coins`}>
          {naira(w.cash_kobo)}{w.bonus_kobo > 0 && <small className="coin">{naira(w.bonus_kobo)}</small>}
        </a>
      ) : <span className="round-btn ghost" aria-hidden="true" />}
    </header>
  )
}
