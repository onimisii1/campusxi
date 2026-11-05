// Offline-safe event queue for the scorer app (PRD E2).
//
// Every tap is written to storage *before* any network call, with a client_seq that is
// never reused for this match and scorer. Sending is just "post everything pending";
// the server treats a resend as a harmless duplicate, so retries are always safe.

export type QueuedEvent = {
  client_seq: number
  athlete_id: string
  event_type: string
  minute: number | null
  amount: number
  reverses_client_seq: number | null
}

export type NewEvent = Omit<QueuedEvent, 'client_seq'>

export type EventResult = {
  client_seq: number
  status: 'accepted' | 'duplicate' | 'rejected'
  error?: string
}

export type Rejected = { event: QueuedEvent; error: string }

export interface KeyValueStore {
  getItem(key: string): string | null
  setItem(key: string, value: string): void
}

type Saved = { nextSeq: number; pending: QueuedEvent[]; rejected: Rejected[] }

export const MAX_BATCH = 200

export function queueKey(matchId: string, scorerId: string): string {
  return `campusxi.queue.${matchId}.${scorerId}`
}

export class EventQueue {
  private store: KeyValueStore
  private key: string

  constructor(store: KeyValueStore, key: string) {
    this.store = store
    this.key = key
  }

  private read(): Saved {
    const raw = this.store.getItem(this.key)
    if (!raw) return { nextSeq: 1, pending: [], rejected: [] }
    try {
      return JSON.parse(raw) as Saved
    } catch {
      return { nextSeq: 1, pending: [], rejected: [] }
    }
  }

  private write(saved: Saved): void {
    this.store.setItem(this.key, JSON.stringify(saved))
  }

  get pending(): QueuedEvent[] {
    return this.read().pending
  }

  get rejected(): Rejected[] {
    return this.read().rejected
  }

  /** Never hand out a seq the server already has (e.g. after storage was cleared). */
  syncSeq(serverLastSeq: number): void {
    const saved = this.read()
    const highestPending = saved.pending.reduce((m, e) => Math.max(m, e.client_seq), 0)
    saved.nextSeq = Math.max(saved.nextSeq, serverLastSeq + 1, highestPending + 1)
    this.write(saved)
  }

  add(event: NewEvent): QueuedEvent {
    const saved = this.read()
    const queued = { ...event, client_seq: saved.nextSeq }
    saved.nextSeq += 1
    saved.pending.push(queued)
    this.write(saved)
    return queued
  }

  batch(max = MAX_BATCH): QueuedEvent[] {
    return this.read().pending.slice(0, max)
  }

  /** Drop everything the server has settled; keep rejected events visible for the scorer. */
  apply(results: EventResult[]): void {
    const saved = this.read()
    const byseq = new Map(results.map((r) => [r.client_seq, r]))
    const still: QueuedEvent[] = []
    for (const e of saved.pending) {
      const r = byseq.get(e.client_seq)
      if (!r) still.push(e)
      else if (r.status === 'rejected') saved.rejected.push({ event: e, error: r.error ?? 'rejected' })
    }
    saved.pending = still
    this.write(saved)
  }

  clearRejected(): void {
    const saved = this.read()
    saved.rejected = []
    this.write(saved)
  }
}
