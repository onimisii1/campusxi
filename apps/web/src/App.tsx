// Phase 0 shell. Lobby, team builder and contests arrive in Phase 4 (PRD section 10).
const SPORTS = [
  { name: 'Football', live: true },
  { name: 'Basketball', live: true },
  { name: 'Volleyball', live: true },
  { name: 'Table tennis', live: false },
  { name: 'Athletics', live: false },
  { name: 'Handball', live: false },
]

function App() {
  return (
    <main className="shell">
      <header>
        <h1>CampusXI</h1>
        <p className="tagline">Your campus, your league.</p>
      </header>
      <section aria-label="Sports" className="sports">
        {SPORTS.map((s) => (
          <div key={s.name} className={s.live ? 'tile' : 'tile soon'}>
            <span>{s.name}</span>
            {!s.live && <small>Coming soon</small>}
          </div>
        ))}
      </section>
      <footer>18+ only. Play responsibly.</footer>
    </main>
  )
}

export default App
