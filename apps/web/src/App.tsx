import { ToastProvider } from './components/Toast'
import TopBar from './components/TopBar'
import AdminHome from './pages/admin/AdminHome'
import AdminMatchPage from './pages/admin/AdminMatchPage'
import AdminTournament from './pages/admin/AdminTournament'
import ChallengeInvite from './pages/ChallengeInvite'
import ContestBoard from './pages/ContestBoard'
import Home from './pages/Home'
import MatchHub from './pages/MatchHub'
import MatchSection, { SECTIONS, type Section } from './pages/MatchSection'
import MePage from './pages/MePage'
import MyChallenges from './pages/MyChallenges'
import PickTeam from './pages/PickTeam'
import PlayerPage from './pages/PlayerPage'
import ProfilePage from './pages/ProfilePage'
import SeasonTable from './pages/SeasonTable'
import SignInPage from './pages/SignInPage'
import TournamentPage from './pages/TournamentPage'
import { useRoute } from './router'
import ScorerApp from './scorer/ScorerApp'
import { SessionProvider } from './session'

function Page({ route }: { route: string[] }) {
  const [page, a, b, c] = route
  switch (page) {
    case 'match':
      if (b && b in SECTIONS) return <MatchSection key={`${a}/${b}`} matchId={a} section={b as Section} focus={c} />
      return <MatchHub key={a} matchId={a} />
    case 'build': return <PickTeam key={`${a}/${b ?? 'new'}`} matchId={a} teamId={b} />
    case 'contest': return <ContestBoard key={a} contestId={a} />
    case 'table': return <SeasonTable key={a} tournamentId={a} />
    case 'player': return <PlayerPage key={a} athleteId={a} />
    case 'tournament': return <TournamentPage key={a} tournamentId={a} />
    case 'challenge': return <ChallengeInvite key={a} token={a} />
    case 'challenges': return <MyChallenges />
    case 'me': return <MePage />
    case 'signin': return <SignInPage />
    case 'profile': return <ProfilePage />
    case 'scorer': return <ScorerApp />
    case 'admin':
      if (a === 't' && b) return <AdminTournament key={b} tournamentId={b} />
      if (a === 'm' && b && c) return <AdminMatchPage key={c} tournamentId={b} matchId={c} />
      return <AdminHome />
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
