import PageHeader from '../../components/PageHeader'
import Skeleton from '../../components/Skeleton'
import { useSession } from '../../session'
import { useApi } from '../../useApi'

type Tournament = { id: string; name: string; sport: string; status: string; match_minutes: number }

/** Admin home: the school's tournaments. Everything else hangs off a tournament. */
export default function AdminHome() {
  const { status, me } = useSession()
  const isAdmin = !!me?.roles.some((r) => r === 'admin' || r === 'superadmin')
  const { data, error } = useApi<Tournament[]>(status === 'ready' && isAdmin ? '/admin/tournaments' : null)

  if (status === 'loading') return null
  if (!isAdmin) return <section><PageHeader title="Admin" back="#/me" /><p className="card">Admins only.</p></section>
  return (
    <section>
      <PageHeader title="Admin" back="#/me" subtitle="Run match day: kick-offs, line-ups, scorers, results" />
      <a className="row-card" href="#/admin/finance"><strong>💰 Finance and withdrawals</strong><span aria-hidden>→</span></a>
      {error && <p className="error">{error}</p>}
      {!data && !error && <Skeleton rows={3} />}
      {data?.length === 0 && <p className="muted">No tournaments yet.</p>}
      <ul className="plain">
        {data?.map((t) => (
          <li key={t.id}>
            <a className="card row between admin-link" href={`#/admin/t/${t.id}`}>
              <span><strong>{t.name}</strong><span className="muted small block">{t.sport} · {t.match_minutes} min matches</span></span>
              <span className={`badge ${t.status === 'published' ? 'good' : 'warn'}`}>{t.status}</span>
            </a>
          </li>
        ))}
      </ul>
    </section>
  )
}
