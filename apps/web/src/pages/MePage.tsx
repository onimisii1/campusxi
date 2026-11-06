import type { MyBet } from '../components/MyBetRow'
import PageHeader from '../components/PageHeader'
import { signInThenReturn } from '../router'
import { useSession } from '../session'
import { useApi } from '../useApi'

type School = { id: string; name: string }

export default function MePage() {
  const { status, me, signOut } = useSession()
  const { data: schools } = useApi<School[]>(status === 'ready' ? '/schools' : null)
  const { data: bets } = useApi<MyBet[]>(status === 'ready' ? '/me/bets' : null)

  if (status === 'loading') return null
  if (status !== 'ready' || !me) {
    return (
      <section>
        <PageHeader title="Menu" back="#/" />
        {status === 'needs_profile'
          ? <a className="primary as-button" href="#/profile">Finish your profile</a>
          : <button className="primary" onClick={signInThenReturn}>Sign in</button>}
        <ul className="menu-list">
          <li><a href="#/scorer">Scorer sign-in <span aria-hidden>→</span></a></li>
        </ul>
      </section>
    )
  }

  const school = schools?.find((s) => s.id === me.school_id)?.name
  const record = (r: string) => bets?.filter((b) => b.result === r).length ?? 0
  const initials = me.team_name.split(/[\s_]+/).map((w) => w[0]).join('').slice(0, 2).toUpperCase()

  return (
    <section>
      <PageHeader title="Profile" back="#/" action={<span className="round-btn ghost" aria-hidden />} />
      <div className="profile-card">
        <span className="avatar" aria-hidden>{initials}</span>
        <div>
          <strong>{me.team_name}</strong>
          {school && <span className="muted small block">{school}</span>}
          <span className="muted small block">Challenges: {record('won')}W {record('lost')}L {record('tie')}T</span>
        </div>
      </div>
      <ul className="menu-list">
        <li><a href="#/wallet">Wallet <span aria-hidden>→</span></a></li>
        <li><a href="#/challenges">My challenges <span aria-hidden>→</span></a></li>
        <li><a href="#/refer">Invite friends, earn coins <span aria-hidden>→</span></a></li>
        <li><a href="#/verify">Verify ID <span aria-hidden>→</span></a></li>
        <li><a href="#/limits">Limits and breaks <span aria-hidden>→</span></a></li>
        {me.roles.includes('scorer') && <li><a href="#/scorer">Scorer app <span aria-hidden>→</span></a></li>}
        {me.roles.some((r) => r === 'admin' || r === 'superadmin') && (
          <li><a href="#/admin">Admin: match day <span aria-hidden>→</span></a></li>)}
        <li><button onClick={signOut}>Sign out</button></li>
      </ul>
      <p className="muted small">CampusXI is for players aged 18 and over. Play responsibly.</p>
    </section>
  )
}
