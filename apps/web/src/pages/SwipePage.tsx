import { useCallback, useEffect, useRef, useState, type CSSProperties, type PointerEvent } from 'react'
import { api } from '../api'
import Avatar from '../components/Avatar'
import PageHeader from '../components/PageHeader'
import Skeleton from '../components/Skeleton'
import TeamBadge from '../components/TeamBadge'
import { kickoff } from '../format'
import { naira, newIdempotencyKey, payLine, split, useWallet, type Wallet } from '../money'
import { signInThenReturn } from '../router'
import { useSession } from '../session'
import { buzz, useToast } from '../toast'
import { errorText, useApi } from '../useApi'

type Side = 'home' | 'away'
type TeamRef = { name: string; colour: string | null; logo: string | null }
export type SwipeCardData = {
  id: string
  kind: 'fantasy_h2h' | 'match_result'
  stake_kobo: number
  unmatched_kobo: number
  side: Side | null
  your_side: Side | null
  win_up_to_kobo: number
  quote_kobo: number
  creator: { team_name: string; record: { won: number; lost: number; tied: number } }
  creator_avatar: string | null
  match: { id: string; sport: string; tournament: string; stage: string | null; venue: string | null
    scheduled_start: string; home_team: TeamRef; away_team: TeamRef }
  my_teams: { id: string; label: string }[]
}
type Feed = { cards: SwipeCardData[]; skipped: number }
type Dir = 'left' | 'right'

const SPORTS = [['', 'All'], ['football', '⚽ Football'], ['basketball', '🏀 Basketball']] as const
const FLY_MS = 280
const sideTeam = (c: SwipeCardData, s: Side | null) => (s === 'away' ? c.match.away_team : c.match.home_team)

/** Swipe to match: open challenges one card at a time. Right takes it on, left skips it. */
export default function SwipePage({ matchId }: { matchId?: string }) {
  const { status, token, me } = useSession()
  const toast = useToast()
  const [sport, setSport] = useState('')
  const query = matchId ? `match_id=${matchId}` : sport ? `sport=${sport}` : ''
  const { data, reload } = useApi<Feed>(status === 'ready' ? `/bets/feed${query ? `?${query}` : ''}` : null)
  const { data: w, reload: reloadWallet } = useWallet()
  const [deck, setDeck] = useState<SwipeCardData[] | null>(null)
  const [skipped, setSkipped] = useState(0)
  const [history, setHistory] = useState<SwipeCardData[]>([])     // skipped this visit, for rewind
  const [fling, setFling] = useState<Dir | null>(null)
  const [taking, setTaking] = useState<SwipeCardData | null>(null)
  const [needTeam, setNeedTeam] = useState<SwipeCardData | null>(null)
  const [matched, setMatched] = useState<{ card: SwipeCardData; team: string | null; amount: number } | null>(null)

  useEffect(() => {
    if (data) {
      setDeck(data.cards)
      setSkipped(data.skipped)
    }
  }, [data])

  const top = deck?.[0]
  const back = matchId ? `#/match/${matchId}/challenges` : '#/challenges'

  const accept = useCallback(async (card: SwipeCardData, team: string | null, amount: number) => {
    const body = card.kind === 'match_result' ? { amount_kobo: amount } : { fantasy_team_id: team }
    await api(`/bets/${card.id}/fills`, token, { method: 'POST', body, idempotencyKey: newIdempotencyKey() })
    buzz(60)
    setMatched({ card, team: card.my_teams.find((t) => t.id === team)?.label ?? null, amount })
    reloadWallet()
  }, [token, reloadWallet])

  // Right swipe: free head-to-head with one team goes straight through; anything else asks first.
  const decide = useCallback((card: SwipeCardData, dir: Dir): boolean => {
    if (dir === 'left') return true
    if (card.kind === 'fantasy_h2h' && card.my_teams.length === 0) {
      setNeedTeam(card)
      return false
    }
    if (card.kind === 'fantasy_h2h' && card.stake_kobo === 0 && card.my_teams.length === 1) return true
    setTaking(card)
    return false
  }, [])

  const gone = useCallback(async (card: SwipeCardData, dir: Dir) => {
    setFling(null)
    setDeck((d) => d?.filter((c) => c.id !== card.id) ?? d)
    if (dir === 'left') {
      setHistory((h) => [card, ...h].slice(0, 20))
      setSkipped((n) => n + 1)
      api(`/bets/${card.id}/skip`, token, { method: 'POST' }).catch(() => {})
      return
    }
    try {
      await accept(card, card.my_teams[0].id, card.stake_kobo)
    } catch (e) {
      toast(errorText(e), 'bad')
      setDeck((d) => (d ? [card, ...d] : d))
    }
  }, [accept, toast, token])

  const press = useCallback((dir: Dir) => {
    if (!top || fling) return
    if (decide(top, dir)) setFling(dir)
  }, [top, fling, decide])

  async function rewind() {
    const [card, ...rest] = history
    if (!card) return
    setHistory(rest)
    setSkipped((n) => Math.max(0, n - 1))
    setDeck((d) => (d ? [card, ...d.filter((c) => c.id !== card.id)] : [card]))
    api(`/bets/${card.id}/skip`, token, { method: 'DELETE' }).catch(() => {})
  }

  async function showSkipped() {
    await api(`/me/bet-skips${matchId ? `?match_id=${matchId}` : ''}`, token, { method: 'DELETE' })
    setHistory([])
    reload()
  }

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (taking || needTeam || matched) return
      if (e.key === 'ArrowLeft') press('left')
      if (e.key === 'ArrowRight') press('right')
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [press, taking, needTeam, matched])

  if (status === 'signed_out' || status === 'needs_profile') {
    return (
      <section>
        <PageHeader title="Swipe & Match" back="#/" />
        <div className="swipe-empty">
          <p className="headline">Find your<br /><b>next rival</b></p>
          <p className="muted">Sign in to swipe through open challenges from other fans.</p>
          <button className="primary" onClick={signInThenReturn}>Sign in</button>
        </div>
      </section>
    )
  }

  return (
    <section className="swipe-page">
      <PageHeader title="Swipe & Match" back={back} subtitle="Right to take it on · left to skip" />
      {!matchId && (
        <div className="chip-row swipe-sports" role="group" aria-label="Sport">
          {SPORTS.map(([code, label]) => (
            <button key={code} className={`chip ${sport === code ? 'on' : ''}`} onClick={() => setSport(code)}>{label}</button>
          ))}
        </div>
      )}

      {!deck && <Skeleton hero rows={1} />}
      {deck && (
        <div className="swipe-deck" aria-live="polite">
          {deck.length === 0 && (
            <div className="swipe-empty">
              <span className="swipe-empty-icon" aria-hidden>⚡</span>
              <p className="headline">You're all<br /><b>caught up</b></p>
              <p className="muted">No open challenges left{matchId ? ' on this match' : ''}. Post your own and let
                someone swipe right on you.</p>
              {skipped > 0 && <button className="sheet-btn" onClick={showSkipped}>Show the {skipped} you skipped</button>}
              <a className="primary as-button" href={matchId ? `#/match/${matchId}/challenges` : '#/live'}>Post a challenge</a>
            </div>
          )}
          {deck.slice(0, 3).reverse().map((c) => {
            const depth = deck.indexOf(c)
            return depth === 0
              ? <SwipeCard key={c.id} card={c} fling={fling} onDecide={(dir) => decide(c, dir)} onGone={(dir) => gone(c, dir)} />
              : <div key={c.id} className="swipe-card behind" style={{ '--depth': depth } as CSSProperties}>
                  <CardFace card={c} />
                </div>
          })}
        </div>
      )}

      {deck && deck.length > 0 && (
        <div className="swipe-controls">
          <button className="swipe-btn small" onClick={rewind} disabled={!history.length} aria-label="Bring back the last one you skipped">
            <svg width="20" height="20" viewBox="0 0 24 24" aria-hidden><path d="M4 9h11a5 5 0 0 1 0 10H9M4 9l4-4M4 9l4 4"
              fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" /></svg>
          </button>
          <button className="swipe-btn skip" onClick={() => press('left')} aria-label="Skip">
            <svg width="26" height="26" viewBox="0 0 24 24" aria-hidden><path d="M6 6l12 12M18 6L6 18" stroke="currentColor"
              strokeWidth="2.6" strokeLinecap="round" /></svg>
          </button>
          <button className="swipe-btn take" onClick={() => press('right')} aria-label="Take on this challenge">
            <svg width="28" height="28" viewBox="0 0 24 24" aria-hidden><path d="M13 2L4 14h7l-1 8 9-12h-7z" fill="currentColor" /></svg>
          </button>
          <span className="swipe-count small muted">{deck.length} open{skipped ? ` · ${skipped} skipped` : ''}</span>
        </div>
      )}

      {needTeam && (
        <div className="sheet-backdrop" onClick={() => setNeedTeam(null)}>
          <div className="sheet" role="dialog" aria-label="Build a team first" onClick={(e) => e.stopPropagation()}>
            <strong>Build a team to take this on</strong>
            <p className="muted small">It's your team against {needTeam.creator.team_name}'s for {needTeam.match.home_team.name} v{' '}
              {needTeam.match.away_team.name}. Pick your players, then come back and swipe right.</p>
            <a className="primary as-button" href={`#/build/${needTeam.match.id}`}>Build my team</a>
            <button className="link" onClick={() => setNeedTeam(null)}>Not now</button>
          </div>
        </div>
      )}

      {taking && (
        <TakeSheet card={taking} wallet={w ?? null} onClose={() => setTaking(null)}
          onTake={async (team, amount) => {
            const card = taking
            await accept(card, team, amount)
            setTaking(null)
            setDeck((d) => d?.filter((c) => c.id !== card.id) ?? d)
          }} />
      )}

      {matched && <MatchedOverlay mine={me?.team_name ?? 'You'} myAvatar={me?.avatar_url ?? null} {...matched}
        onClose={() => setMatched(null)} />}
    </section>
  )
}

/** The top card: follows your finger, tilts, shows MATCH / SKIP, and flies off past the threshold. */
function SwipeCard({ card, fling, onDecide, onGone }: {
  card: SwipeCardData; fling: Dir | null; onDecide: (dir: Dir) => boolean; onGone: (dir: Dir) => void
}) {
  const [dx, setDx] = useState(0)
  const [dy, setDy] = useState(0)
  const [leaving, setLeaving] = useState<Dir | null>(null)
  const start = useRef<{ x: number; y: number; t: number } | null>(null)

  const leave = useCallback((dir: Dir) => {
    setLeaving(dir)
    window.setTimeout(() => onGone(dir), FLY_MS)
  }, [onGone])

  useEffect(() => {
    if (fling && !leaving) leave(fling)
  }, [fling, leaving, leave])

  function up(e: PointerEvent) {
    if (!start.current) return
    const vx = dx / Math.max(1, e.timeStamp - start.current.t)
    start.current = null
    const dir: Dir | null = Math.abs(dx) > 110 || Math.abs(vx) > 0.6 ? (dx > 0 ? 'right' : 'left') : null
    if (dir && onDecide(dir)) {
      leave(dir)
      return
    }
    setDx(0)
    setDy(0)
  }

  const x = leaving ? (leaving === 'right' ? 1 : -1) * (window.innerWidth + 200) : dx
  const style = {
    transform: `translate(${x}px, ${dy}px) rotate(${x / 18}deg)`,
    transition: start.current ? 'none' : `transform ${FLY_MS}ms ease-out`,
  }
  const lean = Math.max(-1, Math.min(1, dx / 110))
  return (
    <div className="swipe-card top" style={style} role="group" aria-label={`Challenge from ${card.creator.team_name}`}
      onPointerDown={(e) => {
        if (leaving) return
        start.current = { x: e.clientX - dx, y: e.clientY - dy, t: e.timeStamp }
        e.currentTarget.setPointerCapture(e.pointerId)
      }}
      onPointerMove={(e) => {
        if (!start.current) return
        setDx(e.clientX - start.current.x)
        setDy((e.clientY - start.current.y) / 4)
      }}
      onPointerUp={up} onPointerCancel={up}>
      <span className="stamp take" style={{ opacity: leaving === 'right' ? 1 : Math.max(0, lean) }}>MATCH</span>
      <span className="stamp skip" style={{ opacity: leaving === 'left' ? 1 : Math.max(0, -lean) }}>SKIP</span>
      <CardFace card={card} />
    </div>
  )
}

function CardFace({ card }: { card: SwipeCardData }) {
  const { match: m, creator } = card
  const h2h = card.kind === 'fantasy_h2h'
  const r = creator.record
  const played = r.won + r.lost + r.tied
  return (
    <>
      <div className="sc-who">
        <Avatar name={creator.team_name} url={card.creator_avatar} size={46} />
        <span className="sc-name"><strong>{creator.team_name}</strong>
          <small>{played ? `${r.won}W · ${r.lost}L · ${r.tied}T` : 'New challenger'}</small></span>
        <span className="sc-kind">{h2h ? 'Head to head' : 'Who wins?'}</span>
      </div>
      <p className="sc-line">{h2h
        ? <>Thinks their team beats yours.<br /><b>Prove them wrong.</b></>
        : <>Backs <b>{sideTeam(card, card.side).name}</b> to win.<br />You take <b>{sideTeam(card, card.your_side).name}</b>.</>}</p>
      <div className="sc-match">
        <span className="sc-team"><TeamBadge {...m.home_team} /><b>{m.home_team.name}</b></span>
        <span className="sc-vs">VS</span>
        <span className="sc-team"><TeamBadge {...m.away_team} /><b>{m.away_team.name}</b></span>
      </div>
      <p className="sc-when">{kickoff(m.scheduled_start)}
        {m.stage && m.stage !== 'league' ? ` · ${m.stage[0].toUpperCase()}${m.stage.slice(1).replace('_', '-')}` : ''}</p>
      <div className="sc-prize">
        {card.stake_kobo
          ? <><span><small>{h2h ? 'Stake' : 'Open'}</small><b>{naira(h2h ? card.stake_kobo : card.unmatched_kobo)}</b></span>
              <span><small>You could win</small><b>{naira(h2h ? card.win_up_to_kobo : card.quote_kobo)}</b></span></>
          : <><span><small>Stake</small><b>Free</b></span><span><small>Prize</small><b>Bragging rights</b></span></>}
      </div>
      {h2h && <p className="sc-yours small">{card.my_teams.length
        ? `Plays your ${card.my_teams.length === 1 ? card.my_teams[0].label : `pick of ${card.my_teams.length} teams`}`
        : 'You need a team for this match'}</p>}
    </>
  )
}

const SLICES = [0.25, 0.5, 1]

function TakeSheet({ card, wallet, onClose, onTake }: {
  card: SwipeCardData; wallet: Wallet | null; onClose: () => void
  onTake: (team: string | null, amount: number) => Promise<void>
}) {
  const toast = useToast()
  const h2h = card.kind === 'fantasy_h2h'
  const [team, setTeam] = useState(card.my_teams[0]?.id ?? '')
  const [amount, setAmount] = useState(h2h ? card.stake_kobo : card.unmatched_kobo)
  const [busy, setBusy] = useState(false)
  const short = amount && wallet ? split(wallet, amount).short : 0
  const win = h2h ? card.win_up_to_kobo : Math.round(2 * amount - amount / 10)
  const cantPay = amount > 0 && wallet && !wallet.can_play_paid

  return (
    <div className="sheet-backdrop" onClick={onClose}>
      <div className="sheet" role="dialog" aria-label="Take on this challenge" onClick={(e) => e.stopPropagation()}>
        <strong>Take on {card.creator.team_name}</strong>
        <p className="muted small">{card.match.home_team.name} v {card.match.away_team.name} · {kickoff(card.match.scheduled_start)}</p>
        {h2h && card.my_teams.length > 1 && (
          <div className="chip-row" role="group" aria-label="Your team">
            {card.my_teams.map((t) => (
              <button key={t.id} className={`chip ${team === t.id ? 'on' : ''}`} onClick={() => setTeam(t.id)}>{t.label}</button>
            ))}
          </div>
        )}
        {!h2h && (
          <div className="chip-row" role="group" aria-label="How much to take">
            {SLICES.map((s) => {
              const v = Math.max(100_000, Math.round((card.unmatched_kobo * s) / 100) * 100)
              return v <= card.unmatched_kobo && (
                <button key={s} className={`chip ${amount === v ? 'on' : ''}`} onClick={() => setAmount(v)}>
                  {s === 1 ? `All ${naira(v)}` : naira(v)}</button>
              )
            })}
          </div>
        )}
        {amount > 0 && wallet && (
          <p className="small">Stake {naira(amount)} · win {naira(win)}{!cantPay && !short && <> · pays {payLine(wallet, amount)}</>}</p>
        )}
        {cantPay && <a className="small block" href="#/wallet">Confirm you're 18+ in your wallet to play for cash →</a>}
        {!cantPay && short > 0 && <a className="small block" href="#/wallet">Need {naira(short)} more · Add money →</a>}
        <button className="primary" disabled={busy || (h2h && !team) || !!cantPay || short > 0} onClick={async () => {
          setBusy(true)
          try {
            await onTake(h2h ? team : null, amount)
          } catch (e) {
            toast(errorText(e), 'bad')
          } finally {
            setBusy(false)
          }
        }}>{busy ? 'Matching…' : amount ? `Match for ${naira(amount)}` : 'Match'}</button>
        <button className="link" onClick={onClose}>Not now</button>
      </div>
    </div>
  )
}

function MatchedOverlay({ card, team, amount, mine, myAvatar, onClose }: {
  card: SwipeCardData; team: string | null; amount: number; mine: string; myAvatar: string | null; onClose: () => void
}) {
  const h2h = card.kind === 'fantasy_h2h'
  return (
    <div className="matched" role="dialog" aria-label="It's a match">
      <div className="matched-burst" aria-hidden>{Array.from({ length: 14 }, (_, i) => <i key={i} style={{ '--i': i } as CSSProperties} />)}</div>
      <p className="headline">It's a<br /><b>Match!</b></p>
      <div className="matched-faces">
        <Avatar name={mine} url={myAvatar} size={88} />
        <span className="matched-bolt" aria-hidden>⚡</span>
        <Avatar name={card.creator.team_name} url={card.creator_avatar} size={88} />
      </div>
      <p className="matched-line">
        {h2h ? <>Your <b>{team ?? 'team'}</b> vs <b>{card.creator.team_name}</b></>
          : <>You took <b>{sideTeam(card, card.your_side).name}</b> against <b>{card.creator.team_name}</b></>}
        <span className="muted small block">{card.match.home_team.name} v {card.match.away_team.name} · {kickoff(card.match.scheduled_start)}
          {amount ? ` · ${naira(amount)} staked` : ' · for bragging rights'}</span>
      </p>
      <button className="primary" onClick={onClose}>Keep swiping</button>
      <a className="link" href="#/challenges">See my challenges</a>
    </div>
  )
}
