import { useState } from 'react'
import { EventCard, ScoreCard, type MatchCardData } from '../components/MatchCard'
import Skeleton from '../components/Skeleton'
import SportSlider, { savedSport } from '../components/SportSlider'
import Avatar from '../components/Avatar'
import type { Inbox } from './NotificationsPage'
import { naira, useWallet } from '../money'
import { useSession } from '../session'
import { useApi } from '../useApi'

/** Featured match: a live one first, then the next to lock, then the latest result. */
function featured(matches: MatchCardData[]): MatchCardData | undefined {
  return matches.find((m) => m.status === 'live')
    ?? matches.find((m) => !m.locked)
    ?? matches.find((m) => m.status === 'final_pending')
    ?? [...matches].reverse().find((m) => m.status === 'confirmed')
}

/** Home (design screen 1): greeting, "Choose your Favourite game", sport pills, stacked event cards. */
export default function Home() {
  const [sport, setSport] = useState(savedSport)
  const { data, error } = useApi<MatchCardData[]>('/matches', 60_000)

  const matches = (data ?? []).filter((m) => m.sport === sport && m.status !== 'abandoned')
  const top = featured(matches)
  const rest = matches.filter((m) => m !== top)
  const upcoming = rest.filter((m) => m.status !== 'confirmed')
  const results = rest.filter((m) => m.status === 'confirmed').reverse()
  const tournaments = [...new Map(matches.map((m) => [m.tournament_id, m.tournament])).entries()]

  return (
    <section>
      <Greeting />
      <SportSlider value={sport} onChange={setSport} />
      {error && <p className="error">{error}</p>}
      {!data && !error && <Skeleton hero rows={2} />}
      {data && !top && <p className="card muted">No {sport} events yet. Check back soon.</p>}

      {top && (
        <>
          <div className="section-head"><h3>Top Events</h3>
            <a href="#/live">View All</a></div>
          <div className={`event-stack ${upcoming[0] ? 'joined' : ''}`}>
            <EventCard m={top} lime />
            {upcoming[0] && <EventCard m={upcoming[0]} stacked />}
          </div>
        </>
      )}
      <SwipePromo />


      {upcoming.length > 1 && <div className="section-head"><h3>Up next</h3></div>}
      <ul className="list">{upcoming.slice(1).map((m) => <li key={m.id}><ScoreCard m={m} /></li>)}</ul>

      {results.length > 0 && <div className="section-head"><h3>Results</h3></div>}
      <ul className="list">{results.map((m) => <li key={m.id}><ScoreCard m={m} /></li>)}</ul>

      {tournaments.length > 0 && <div className="section-head"><h3>Tournaments</h3></div>}
      <ul className="list">
        {tournaments.map(([id, name]) => (
          <li key={id}><a className="row-card" href={`#/tournament/${id}`}>
            <span><strong>{name}</strong><span className="muted small block">Table, results, top scorers, bracket</span></span>
            <span className="round-btn small" aria-hidden>›</span></a></li>
        ))}
      </ul>
    </section>
  )
}

/** "Swipe to match" teaser: how many open challenges are waiting (signed-in players only). */
function SwipePromo() {
  const { status } = useSession()
  const { data } = useApi<{ cards: unknown[] }>(status === 'ready' ? '/bets/feed' : null, 60_000)
  if (!data || data.cards.length === 0) return null
  const n = data.cards.length
  return (
    <a className="swipe-promo" href="#/swipe">
      <span><b>{n} open challenge{n === 1 ? '' : 's'}</b><small>Swipe right to take one on</small></span>
      <span className="swipe-promo-icon" aria-hidden>⚡</span>
    </a>
  )
}

function Greeting() {
  const { status, me } = useSession()
  const { data: w } = useWallet()
  const { data: inbox } = useApi<Inbox>(status === 'ready' ? '/me/notifications?limit=1' : null, 60_000)
  const h = new Date().getHours()
  const hello = h < 12 ? 'Good Morning!' : h < 17 ? 'Good Afternoon!' : 'Good Evening!'
  if (status === 'loading') return <div className="greet" />
  if (status !== 'ready' || !me) {
    return (
      <div className="greet">
        <span className="who"><span className="avatar">XI</span><span><small>Welcome to</small><strong>CampusXI</strong></span></span>
        <a className="pill-btn" href={status === 'needs_profile' ? '#/profile' : '#/signin'}>
          {status === 'needs_profile' ? 'Finish profile' : 'Sign in'}</a>
      </div>
    )
  }
  return (
    <div className="greet">
      <a className="who plain-link" href="#/me" aria-label="Your profile and menu"><Avatar name={me.team_name} url={me.avatar_url} />
        <span><small>{hello}</small><strong>{me.team_name}</strong></span></a>
      <span className="greet-right">
        {w && (
          <a className="balance-chip" href="#/wallet" aria-label={`Wallet: ${naira(w.cash_kobo)}`}>
            {naira(w.cash_kobo)}{w.bonus_kobo > 0 && <small className="coin">{naira(w.bonus_kobo)}</small>}
          </a>
        )}
        <a className="round-btn bell" href="#/notifications"
          aria-label={inbox?.unread ? `Notifications: ${inbox.unread} new` : 'Notifications'}>
          <svg width="20" height="20" viewBox="0 0 24 24" aria-hidden><path d="M6 16V11a6 6 0 1 1 12 0v5l1.5 2h-15zM10 20a2 2 0 0 0 4 0"
            fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round" /></svg>
          {!!inbox?.unread && <span className="bell-count">{inbox.unread > 9 ? '9+' : inbox.unread}</span>}
        </a>
      </span>
    </div>
  )
}
