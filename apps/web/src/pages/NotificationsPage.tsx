import { useEffect } from 'react'
import { api } from '../api'
import PageHeader from '../components/PageHeader'
import Skeleton from '../components/Skeleton'
import { signInThenReturn } from '../router'
import { useSession } from '../session'
import { useApi } from '../useApi'

export type Inbox = {
  items: { id: number; kind: string; title: string; body: string | null; link: string | null; created_at: string
    read_at: string | null }[]
  unread: number
}

const ICON: Record<string, string> = {
  lineup: '📋', deadline: '⏰', challenge_accepted: '⚡', result: '🏁', prize: '₦',
}

function ago(iso: string): string {
  const s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000)
  if (s < 60) return 'just now'
  if (s < 3600) return `${Math.floor(s / 60)}m ago`
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`
  return new Date(iso).toLocaleDateString(undefined, { day: 'numeric', month: 'short' })
}

/** The bell: line-ups out, deadlines, challenges taken, results and winnings. Opening it reads them. */
export default function NotificationsPage() {
  const { status, token } = useSession()
  const { data } = useApi<Inbox>(status === 'ready' ? '/me/notifications' : null)
  useEffect(() => {
    if (data?.unread) api('/me/notifications/read', token, { method: 'POST', body: {} }).catch(() => {})
  }, [data?.unread, token])

  if (status === 'signed_out') {
    return (
      <section><PageHeader title="Notifications" back="#/" />
        <p className="muted">Sign in to get line-up alerts, deadline reminders and results.</p>
        <button className="primary" onClick={signInThenReturn}>Sign in</button></section>
    )
  }
  return (
    <section>
      <PageHeader title="Notifications" back="#/" />
      {!data && <Skeleton rows={4} />}
      {data?.items.length === 0 && (
        <div className="swipe-empty">
          <span className="swipe-empty-icon" aria-hidden>🔔</span>
          <p className="muted">Nothing yet. You'll hear here when line-ups are out, a match is about to lock, someone
            takes your challenge, results are in and winnings land.</p>
        </div>
      )}
      <ul className="plain notif-list">
        {data?.items.map((n) => (
          <li key={n.id}>
            <a className={`notif glass-card ${n.read_at ? '' : 'unread'}`} href={n.link ?? '#/'}>
              <span className="notif-icon" aria-hidden>{ICON[n.kind] ?? '•'}</span>
              <span className="grow">
                <strong>{n.title}</strong>
                {n.body && <span className="muted small block">{n.body}</span>}
              </span>
              <small className="muted">{ago(n.created_at)}</small>
            </a>
          </li>
        ))}
      </ul>
    </section>
  )
}
