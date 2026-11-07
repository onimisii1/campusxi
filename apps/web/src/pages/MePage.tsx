import type { MyBet } from '../components/MyBetRow'
import { useState } from 'react'
import Avatar from '../components/Avatar'
import { SoonBadge } from '../components/ComingSoon'
import { useWallet } from '../money'
import PageHeader from '../components/PageHeader'
import { AVATAR, pickPhoto, resize, uploadImage } from '../media'
import { useToast } from '../toast'
import { errorText } from '../useApi'
import { signInThenReturn } from '../router'
import { useSession } from '../session'
import { useApi } from '../useApi'

type School = { id: string; name: string }

export default function MePage() {
  const { status, me, signOut, token, reload } = useSession()
  const toast = useToast()
  const [busy, setBusy] = useState(false)
  const { data: schools } = useApi<School[]>(status === 'ready' ? '/schools' : null)
  const { data: bets } = useApi<MyBet[]>(status === 'ready' ? '/me/bets' : null)
  const { data: w } = useWallet()

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
  async function changePhoto() {
    const file = await pickPhoto()
    if (!file) return
    setBusy(true)
    try {
      await uploadImage('/me/avatar', token, await resize(file, AVATAR))
      await reload()
      toast('Photo updated')
    } catch (e) {
      toast(e instanceof Error && !('code' in e) ? e.message : errorText(e), 'bad')
    } finally {
      setBusy(false)
    }
  }

  return (
    <section>
      <PageHeader title="Profile" back="#/" action={<span className="round-btn ghost" aria-hidden />} />
      <div className="profile-card">
        <button className="avatar-btn" onClick={changePhoto} disabled={busy} aria-label="Change your photo">
          <Avatar name={me.team_name} url={me.avatar_url} size={64} />
          <span className="avatar-edit" aria-hidden>{busy ? '…' : '📷'}</span>
        </button>
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
        <li><a href="#/notifications">Notifications <span aria-hidden>→</span></a></li>
        <li><a href="#/verify">Verify ID{!w?.kyc_required && <SoonBadge />} <span aria-hidden>→</span></a></li>
        <li><a href="#/limits">Limits and breaks <span aria-hidden>→</span></a></li>
        <li><a href="#/account">Account and security <span aria-hidden>→</span></a></li>
        {me.roles.includes('scorer') && <li><a href="#/scorer">Scorer app <span aria-hidden>→</span></a></li>}
        {me.roles.some((r) => r === 'admin' || r === 'superadmin') && (
          <li><a href="#/admin">Admin: match day <span aria-hidden>→</span></a></li>)}
        <li><button onClick={signOut}>Sign out</button></li>
      </ul>
      <p className="muted small">CampusXI is for players aged 18 and over. Play responsibly.</p>
    </section>
  )
}
