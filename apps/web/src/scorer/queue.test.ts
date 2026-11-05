import { describe, expect, it } from 'vitest'
import { EventQueue, type KeyValueStore, MAX_BATCH, queueKey } from './queue'

class MemoryStore implements KeyValueStore {
  data = new Map<string, string>()
  getItem(key: string) {
    return this.data.get(key) ?? null
  }
  setItem(key: string, value: string) {
    this.data.set(key, value)
  }
}

const goal = { athlete_id: 'a1', event_type: 'goal', minute: 10, amount: 1, reverses_client_seq: null }

describe('EventQueue', () => {
  it('assigns increasing sequence numbers and persists before sending', () => {
    const store = new MemoryStore()
    const q = new EventQueue(store, queueKey('m', 's'))
    expect(q.add(goal).client_seq).toBe(1)
    expect(q.add({ ...goal, event_type: 'assist' }).client_seq).toBe(2)
    // a fresh instance (page reload) sees the same pending events and continues the sequence
    const reloaded = new EventQueue(store, queueKey('m', 's'))
    expect(reloaded.pending.map((e) => e.client_seq)).toEqual([1, 2])
    expect(reloaded.add(goal).client_seq).toBe(3)
  })

  it('never reuses a sequence number the server already has', () => {
    const q = new EventQueue(new MemoryStore(), 'k')
    q.syncSeq(41)
    expect(q.add(goal).client_seq).toBe(42)
    q.syncSeq(10) // an older server view never moves the sequence backwards
    expect(q.add(goal).client_seq).toBe(43)
  })

  it('removes accepted and duplicate events, keeps rejected ones visible, leaves unknown pending', () => {
    const q = new EventQueue(new MemoryStore(), 'k')
    for (let i = 0; i < 4; i++) q.add(goal)
    q.apply([
      { client_seq: 1, status: 'accepted' },
      { client_seq: 2, status: 'duplicate' },
      { client_seq: 3, status: 'rejected', error: 'needs a minute' },
    ])
    expect(q.pending.map((e) => e.client_seq)).toEqual([4])
    expect(q.rejected).toEqual([{ event: { ...goal, client_seq: 3 }, error: 'needs a minute' }])
    q.apply([{ client_seq: 1, status: 'accepted' }]) // replaying a response is harmless
    expect(q.pending.map((e) => e.client_seq)).toEqual([4])
    q.clearRejected()
    expect(q.rejected).toEqual([])
  })

  it('sends at most one batch at a time', () => {
    const q = new EventQueue(new MemoryStore(), 'k')
    for (let i = 0; i < MAX_BATCH + 5; i++) q.add(goal)
    expect(q.batch()).toHaveLength(MAX_BATCH)
    expect(q.batch()[0].client_seq).toBe(1)
  })

  it('keeps separate queues per match and scorer', () => {
    const store = new MemoryStore()
    new EventQueue(store, queueKey('m1', 's')).add(goal)
    expect(new EventQueue(store, queueKey('m2', 's')).pending).toEqual([])
  })

  it('survives corrupted storage', () => {
    const store = new MemoryStore()
    store.setItem('k', '{not json')
    const q = new EventQueue(store, 'k')
    expect(q.add(goal).client_seq).toBe(1)
  })
})
