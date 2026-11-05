import { api } from '../api'
import MyBetRow, { type MyBet } from '../components/MyBetRow'
import { signInThenReturn } from '../router'
import { useSession } from '../session'
import { useApi } from '../useApi'

export default function MyChallenges() {
  const { status, token } = useSession()
  const { data, reload } = useApi<MyBet[]>(status === 'ready' ? '/me/bets' : null)
  if (status === 'signed_out') {
    return <p className="card">Sign in to see your challenges. <button className="link" onClick={signInThenReturn}>Sign in</button></p>
  }
  const won = data?.filter((b) => b.result === 'won').length ?? 0
  const lost = data?.filter((b) => b.result === 'lost').length ?? 0
  const tied = data?.filter((b) => b.result === 'tie').length ?? 0

  async function cancel(id: string) {
    try {
      await api(`/bets/${id}/cancel`, token, { method: 'POST' })
    } finally {
      reload()
    }
  }

  return (
    <section>
      <h2>Your challenges</h2>
      <p className="muted">Record: {won}W {lost}L {tied}T</p>
      {data?.length === 0 && <p className="muted">No challenges yet. Open a match and challenge someone.</p>}
      <ul className="plain">{data?.map((b) => <MyBetRow key={b.id} b={b} onCancel={cancel} showMatch />)}</ul>
    </section>
  )
}
