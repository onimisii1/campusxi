import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api, ApiError, OfflineError } from '../api'
import { recall, remember } from '../cache'
import { buttonsFor, eventLabel, type EventButton } from './events'
import { EventQueue, queueKey, type EventResult, type QueuedEvent } from './queue'

type Athlete = { id: string; name: string; position: string; side: 'home' | 'away'; started: boolean }
type ServerEvent = {
  client_seq: number
  athlete_id: string
  event_type: string
  minute: number | null
  amount: number
  reverses_client_seq: number | null
}
type Detail = {
  id: string
  sport: string
  status: string
  role: string
  home_team: string
  away_team: string
  scheduled_minutes: number
  event_types: string[]
  timed_events: string[]
  lineup: Athlete[]
  events: ServerEvent[]
  last_client_seq: number
  submission: { home_score: number; away_score: number } | null
}

type Sync = { state: 'synced' | 'sending' | 'offline' | 'blocked'; message?: string }

const RETRY_MS = 5000

export default function MatchScreen(props: { matchId: string; scorerId: string; token: string; onBack: () => void }) {
  const { matchId, scorerId, token, onBack } = props
  const queue = useMemo(() => new EventQueue(localStorage, queueKey(matchId, scorerId)), [matchId, scorerId])
  const [detail, setDetail] = useState<Detail | null>(null)
  const [pending, setPending] = useState<QueuedEvent[]>(queue.pending)
  const [rejected, setRejected] = useState(queue.rejected)
  const [selected, setSelected] = useState<string | null>(null)
  const [sync, setSync] = useState<Sync>({ state: 'synced' })
  const [notice, setNotice] = useState<string | null>(null)
  const minute = useMatchMinute(matchId)
  const flushing = useRef(false)

  const refresh = useCallback(async () => {
    try {
      const d = remember(`scorer.match.${matchId}`, await api<Detail>(`/scorer/matches/${matchId}`, token))
      queue.syncSeq(d.last_client_seq)
      setDetail(d)
    } catch (e) {
      if (e instanceof OfflineError) {
        setSync({ state: 'offline' })
        // Reopen from the last saved copy; queued events keep their own sequence numbers.
        setDetail((current) => current ?? recall<Detail>(`scorer.match.${matchId}`))
      } else if (e instanceof ApiError) setSync({ state: 'blocked', message: e.message })
    }
  }, [matchId, token, queue])

  const flush = useCallback(async () => {
    if (flushing.current) return
    const batch = queue.batch()
    if (batch.length === 0) {
      setSync((s) => (s.state === 'blocked' ? s : { state: 'synced' }))
      return
    }
    flushing.current = true
    setSync({ state: 'sending' })
    try {
      const res = await api<{ results: EventResult[] }>(`/scorer/matches/${matchId}/events`, token, {
        method: 'POST',
        body: { events: batch },
      })
      queue.apply(res.results)
      setSync({ state: queue.pending.length ? 'sending' : 'synced' })
      await refresh()
    } catch (e) {
      if (e instanceof OfflineError) setSync({ state: 'offline' })
      else if (e instanceof ApiError) setSync({ state: 'blocked', message: e.message })
    } finally {
      flushing.current = false
      setPending(queue.pending)
      setRejected(queue.rejected)
    }
  }, [matchId, token, queue, refresh])

  useEffect(() => {
    refresh().then(flush)
    const timer = setInterval(flush, RETRY_MS)
    window.addEventListener('online', flush)
    return () => {
      clearInterval(timer)
      window.removeEventListener('online', flush)
    }
  }, [refresh, flush])

  function record(button: EventButton, athleteId = selected) {
    if (!athleteId || !detail) return
    if (detail.timed_events.includes(button.type) && minute.value === null) {
      setNotice('Start the clock or enter the minute first.')
      return
    }
    setNotice(null)
    queue.add({
      athlete_id: athleteId,
      event_type: button.type,
      minute: detail.sport === 'football' ? minute.value : null,
      amount: button.amount ?? 1,
      reverses_client_seq: null,
    })
    setPending(queue.pending)
    setSelected(null)
    flush()
  }

  function undo(e: ServerEvent | QueuedEvent) {
    queue.add({ athlete_id: e.athlete_id, event_type: e.event_type, minute: e.minute, amount: e.amount,
      reverses_client_seq: e.client_seq })
    setPending(queue.pending)
    flush()
  }

  if (!detail) {
    return (
      <section>
        <button className="link" onClick={onBack}>← Matches</button>
        <p className="muted">{sync.state === 'offline' ? 'Offline: waiting for a connection…' : sync.message ?? 'Loading…'}</p>
      </section>
    )
  }

  const names = new Map(detail.lineup.map((a) => [a.id, a]))
  const buttons = buttonsFor(detail.sport, detail.event_types)
  const log = [
    ...detail.events.map((e) => ({ ...e, sent: true })),
    ...pending.map((e) => ({ ...e, sent: false })),
  ].sort((a, b) => b.client_seq - a.client_seq)
  const undone = new Set(log.filter((e) => e.reverses_client_seq).map((e) => e.reverses_client_seq))
  const closed = detail.submission !== null || !['scheduled', 'lineup_out', 'live'].includes(detail.status)

  return (
    <section className="scorer">
      <div className="row between">
        <button className="link" onClick={onBack}>← Matches</button>
        <SyncBadge sync={sync} pending={pending.length} />
      </div>
      <h2>{detail.home_team} vs {detail.away_team}</h2>
      <p className="muted">{detail.role} scorer · {detail.status.replace('_', ' ')}</p>

      {detail.sport === 'football' && !closed && <MinuteControl minute={minute} />}

      {rejected.length > 0 && (
        <div className="card warn">
          <strong>Not recorded:</strong>
          <ul>{rejected.map((r) => (
            <li key={r.event.client_seq}>
              {names.get(r.event.athlete_id)?.name ?? 'Unknown'} · {eventLabel(r.event.event_type, r.event.amount)}: {r.error}
            </li>
          ))}</ul>
          <button className="link" onClick={() => { queue.clearRejected(); setRejected([]) }}>Dismiss</button>
        </div>
      )}

      {!closed && (
        <div className="sides">
          {(['home', 'away'] as const).map((side) => (
            <div key={side}>
              <h3>{side === 'home' ? detail.home_team : detail.away_team}</h3>
              {detail.lineup
                .filter((a) => a.side === side)
                .sort((a, b) => Number(b.started) - Number(a.started) || a.name.localeCompare(b.name))
                .map((a) => (
                  <button key={a.id} className={`athlete ${selected === a.id ? 'selected' : ''} ${a.started ? '' : 'bench'}`}
                    onClick={() => setSelected(selected === a.id ? null : a.id)}>
                    <span>{a.name}</span>
                    <small>{a.position}{a.started ? '' : ' · bench'}</small>
                  </button>
                ))}
            </div>
          ))}
        </div>
      )}

      {selected && !closed && (
        <div className="event-pad" role="group" aria-label={`Events for ${names.get(selected)?.name}`}>
          <p><strong>{names.get(selected)?.name}</strong></p>
          {notice && <p className="error">{notice}</p>}
          <div className="grid">
            {buttons.map((b) => (
              <button key={b.type + b.label} className={`event ${b.tone ?? ''}`} onClick={() => record(b)}>{b.label}</button>
            ))}
          </div>
        </div>
      )}

      <h3>Event log</h3>
      {log.length === 0 && <p className="muted">Nothing recorded yet.</p>}
      <ol className="log">
        {log.map((e) => {
          const a = names.get(e.athlete_id)
          const isUndo = e.reverses_client_seq !== null
          return (
            <li key={e.client_seq} className={undone.has(e.client_seq) ? 'undone' : ''}>
              <span>
                {e.minute !== null && <b>{e.minute}′ </b>}
                {isUndo ? 'Undo: ' : ''}{a?.name ?? 'Unknown'} · {eventLabel(e.event_type, e.amount)}
                {!e.sent && <em> · waiting to send</em>}
              </span>
              {!isUndo && !undone.has(e.client_seq) && !closed && (
                <button className="link" onClick={() => undo(e)}>Undo</button>
              )}
            </li>
          )
        })}
      </ol>

      {detail.submission ? (
        <p className="card">Submitted: {detail.home_team} {detail.submission.home_score} – {detail.submission.away_score} {detail.away_team}</p>
      ) : (
        !closed && <SubmitForm detail={detail} token={token} pending={pending.length} onDone={refresh} />
      )}
    </section>
  )
}

function SyncBadge({ sync, pending }: { sync: Sync; pending: number }) {
  if (sync.state === 'blocked') return <span className="badge bad">{sync.message}</span>
  if (sync.state === 'offline') return <span className="badge warn">Offline · {pending} waiting</span>
  if (pending > 0) return <span className="badge warn">Sending {pending}…</span>
  return <span className="badge good">All saved</span>
}

type Minute = { value: number | null; set: (m: number) => void; startClock: () => void; running: boolean }

function useMatchMinute(matchId: string): Minute {
  const key = `campusxi.clock.${matchId}`
  const [kickoff, setKickoff] = useState<number | null>(() => Number(localStorage.getItem(key)) || null)
  const [manual, setManual] = useState<number | null>(null)
  const [, tick] = useState(0)
  useEffect(() => {
    const t = setInterval(() => tick((n) => n + 1), 15000)
    return () => clearInterval(t)
  }, [])
  const fromClock = kickoff ? Math.floor((Date.now() - kickoff) / 60000) + 1 : null
  return {
    value: manual ?? fromClock,
    running: kickoff !== null,
    set: (m) => setManual(Math.max(0, m)),
    startClock: () => {
      const now = Date.now()
      localStorage.setItem(key, String(now))
      setKickoff(now)
      setManual(null)
    },
  }
}

function MinuteControl({ minute }: { minute: Minute }) {
  return (
    <div className="row minute">
      <span>Minute</span>
      <button onClick={() => minute.set((minute.value ?? 1) - 1)} aria-label="Minute down">−</button>
      <input type="number" min={0} max={200} value={minute.value ?? ''} placeholder="–"
        onChange={(e) => minute.set(Number(e.target.value))} aria-label="Match minute" />
      <button onClick={() => minute.set((minute.value ?? 0) + 1)} aria-label="Minute up">+</button>
      {!minute.running && <button className="link" onClick={minute.startClock}>Start clock at kick-off</button>}
    </div>
  )
}

function SubmitForm({ detail, token, pending, onDone }: { detail: Detail; token: string; pending: number; onDone: () => void }) {
  const [home, setHome] = useState(0)
  const [away, setAway] = useState(0)
  const [shootout, setShootout] = useState<'' | 'home' | 'away'>('')
  const [error, setError] = useState<string | null>(null)
  const [confirming, setConfirming] = useState(false)

  async function submit() {
    try {
      await api(`/scorer/matches/${detail.id}/submit`, token, {
        method: 'POST',
        body: { home_score: home, away_score: away, shootout_winner: shootout || null },
      })
      onDone()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'could not submit')
    }
  }

  return (
    <div className="card">
      <h3>Final score</h3>
      <div className="row">
        <label>{detail.home_team}<input type="number" min={0} value={home} onChange={(e) => setHome(Number(e.target.value))} /></label>
        <label>{detail.away_team}<input type="number" min={0} value={away} onChange={(e) => setAway(Number(e.target.value))} /></label>
      </div>
      {detail.sport === 'football' && home === away && (
        <label>Penalty shoot-out winner (knockout only)
          <select value={shootout} onChange={(e) => setShootout(e.target.value as '' | 'home' | 'away')}>
            <option value="">No shoot-out</option>
            <option value="home">{detail.home_team}</option>
            <option value="away">{detail.away_team}</option>
          </select>
        </label>
      )}
      {pending > 0 && <p className="error">Wait until every event is sent before submitting.</p>}
      {error && <p className="error">{error}</p>}
      {confirming ? (
        <div className="row">
          <button className="primary" disabled={pending > 0} onClick={submit}>Yes, submit {home}–{away}</button>
          <button className="link" onClick={() => setConfirming(false)}>Cancel</button>
        </div>
      ) : (
        <button className="primary" disabled={pending > 0} onClick={() => setConfirming(true)}>Submit final stats</button>
      )}
    </div>
  )
}
