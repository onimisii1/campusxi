import { useCallback, useEffect, useRef, useState } from 'react'
import { api, ApiError, OfflineError } from './api'
import { useSession } from './session'

/**
 * GET a resource with the session token; `reload` refetches. `path` null skips the call.
 * `refreshMs` polls while the page is visible (live points, leaderboards); a failed refresh
 * keeps the last data on screen and only marks it as stale.
 */
export function useApi<T>(path: string | null, refreshMs?: number) {
  const { token } = useSession()
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [updatedAt, setUpdatedAt] = useState<Date | null>(null)
  const [stale, setStale] = useState(false)
  const hasData = useRef(false)

  const reload = useCallback(async () => {
    if (!path) return
    try {
      setData(await api<T>(path, token))
      hasData.current = true
      setError(null)
      setStale(false)
      setUpdatedAt(new Date())
    } catch (e) {
      if (hasData.current) {
        setStale(true)
        return
      }
      if (e instanceof OfflineError) setError('No connection. Try again when you have signal.')
      else setError(e instanceof ApiError ? e.message : 'Something went wrong')
    }
  }, [path, token])

  useEffect(() => {
    hasData.current = false
    reload()
  }, [reload])

  useEffect(() => {
    if (!refreshMs || !path) return
    const tick = () => {
      if (document.visibilityState === 'visible') reload()
    }
    const timer = setInterval(tick, refreshMs)
    document.addEventListener('visibilitychange', tick)
    return () => {
      clearInterval(timer)
      document.removeEventListener('visibilitychange', tick)
    }
  }, [refreshMs, path, reload])

  return { data, error, reload, updatedAt, stale }
}

export function errorText(e: unknown): string {
  if (e instanceof ApiError) {
    const details = Array.isArray(e.details) ? e.details.filter((d) => typeof d === 'string') : []
    return details.length ? `${e.message}: ${details.join('; ')}` : e.message
  }
  if (e instanceof OfflineError) return 'No connection. Try again when you have signal.'
  return 'Something went wrong'
}

export const LIVE_REFRESH_MS = 20_000
