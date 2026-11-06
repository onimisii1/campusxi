import { ToastProvider } from './components/Toast'
import TopBar from './components/TopBar'
import ChallengeInvite from './pages/ChallengeInvite'
import ContestBoard from './pages/ContestBoard'
import Home from './pages/Home'
import MatchHub from './pages/MatchHub'
import MatchSection, { SECTIONS, type Section } from './pages/MatchSection'
import MePage from './pages/MePage'
import MyChallenges from './pages/MyChallenges'
import PickTeam from './pages/PickTeam'
import ProfilePage from './pages/ProfilePage'
import SeasonTable from './pages/SeasonTable'
import SignInPage from './pages/SignInPage'
import { useRoute } from './router'
import ScorerApp from './scorer/ScorerApp'
import { SessionProvider } from './session'

function Page({ route }: { route: string[] }) {
  const [page, a, b] = route
  switch (page) {
    case 'match':
      if (b && b in SECTIONS) return <MatchSection key={`${a}/${b}`} matchId={a} section={b as Section} />
      return <MatchHub key={a} matchId={a} />
    case 'build': return <PickTeam key={`${a}/${b ?? 'new'}`} matchId={a} teamId={b} />
    case 'contest': return <ContestBoard key={a} contestId={a} />
    case 'table': return <SeasonTable key={a} tournamentId={a} />
    case 'challenge': return <ChallengeInvite key={a} token={a} />
    case 'challenges': return <MyChallenges />
    case 'me': return <MePage />
    case 'signin': return <SignInPage />
    case 'profile': return <ProfilePage />
    case 'scorer': return <ScorerApp />
    default: return <Home />
  }
}

function Shell() {
  const route = useRoute()
  return (
    <>
      <TopBar />
      <main className="shell">
        <Page route={route} />
      </main>
    </>
  )
}

export default function App() {
  return (
    <SessionProvider>
      <ToastProvider>
        <Shell />
      </ToastProvider>
    </SessionProvider>
  )
}
