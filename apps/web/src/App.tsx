import { useEffect, useState } from 'react'
import ScorerApp from './scorer/ScorerApp'

// Hash routes keep the PWA working from any static host: #/scorer opens the scorer app.
// The lobby, team builder and contests arrive in Phase 4 (PRD section 10).
const SPORTS = [
  { name: 'Football', live: true },
  { name: 'Basketball', live: true },
  { name: 'Volleyball', live: true },
  { name: 'Table tennis', live: false },
  { name: 'Athletics', live: false },
  { name: 'Handball', live: false },
]

function useHashRoute() {
  const [hash, setHash] = useState(window.location.hash)
  useEffect(() => {
    const onChange = () => setHash(window.location.hash)
    window.addEventListener('hashchange', onChange)
    return () => window.removeEventListener('hashchange', onChange)
  }, [])
  return hash
}

function App() {
  const route = useHashRoute()

  return (
    <main className="shell">
      <header>
        <h1><a href="#/">CampusXI</a></h1>
        {route !== '#/scorer' && <p className="tagline">Your campus, your league.</p>}
      </header>
      {route === '#/scorer' ? (
        <ScorerApp />
      ) : (
        <>
          <section aria-label="Sports" className="sports">
            {SPORTS.map((s) => (
              <div key={s.name} className={s.live ? 'tile' : 'tile soon'}>
                <span>{s.name}</span>
                {!s.live && <small>Coming soon</small>}
              </div>
            ))}
          </section>
          <p><a href="#/scorer">Scorer sign-in →</a></p>
        </>
      )}
      <footer>18+ only. Play responsibly.</footer>
    </main>
  )
}

export default App
