import ChallengeInvite from './pages/ChallengeInvite'
import ContestBoard from './pages/ContestBoard'
import Lobby from './pages/Lobby'
import MatchPage from './pages/MatchPage'
import MyChallenges from './pages/MyChallenges'
import ProfilePage from './pages/ProfilePage'
import SeasonTable from './pages/SeasonTable'
import SignInPage from './pages/SignInPage'
import TeamBuilder from './pages/TeamBuilder'
import { signInThenReturn, useRoute } from './router'
import ScorerApp from './scorer/ScorerApp'
import { SessionProvider, useSession } from './session'

function Page({ route }: { route: string[] }) {
  const [page, a, b] = route
  switch (page) {
    case 'match': return <MatchPage key={a} matchId={a} />
    case 'build': return <TeamBuilder key={`${a}/${b ?? 'new'}`} matchId={a} teamId={b} />
    case 'contest': return <ContestBoard key={a} contestId={a} />
    case 'table': return <SeasonTable key={a} tournamentId={a} />
    case 'challenge': return <ChallengeInvite key={a} token={a} />
    case 'challenges': return <MyChallenges />
    case 'signin': return <SignInPage />
    case 'profile': return <ProfilePage />
    case 'scorer': return <ScorerApp />
    default: return <Lobby />
  }
}

function Header() {
  const { status, me, signOut } = useSession()
  return (
    <header className="top">
      <h1><a href="#/">CampusXI</a></h1>
      <nav className="row">
        <a href="#/">Matches</a>
        <a href="#/challenges">Challenges</a>
        {status === 'ready' && <>
          <span className="muted small">{me?.team_name}</span>
          <button className="link" onClick={signOut}>Sign out</button>
        </>}
        {status === 'signed_out' && <button className="link" onClick={signInThenReturn}>Sign in</button>}
        {status === 'needs_profile' && <a href="#/profile">Finish profile</a>}
      </nav>
    </header>
  )
}

function Shell() {
  const route = useRoute()
  return (
    <main className="shell">
      <Header />
      <Page route={route} />
      <footer>
        18+ only. Play responsibly. · <a href="#/scorer">Scorer sign-in</a>
      </footer>
    </main>
  )
}

export default function App() {
  return (
    <SessionProvider>
      <Shell />
    </SessionProvider>
  )
}
