import { useCallback, useEffect, useState } from 'react'
import { api, ApiError, OfflineError } from './api'
import { useSession } from './session'

/** GET a resource with the session token; `reload` refetches. `path` null skips the call. */
export function useApi<T>(path: string | null) {
  const { token } = useSession()
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<string | null>(null)

  const reload = useCallback(async () => {
    if (!path) return
    try {
      setData(await api<T>(path, token))
      setError(null)
    } catch (e) {
      if (e instanceof OfflineError) setError('No connection. Pull down or try again shortly.')
      else setError(e instanceof ApiError ? e.message : 'Something went wrong')
    }
  }, [path, token])

  useEffect(() => {
    reload()
  }, [reload])

  return { data, error, reload }
}

export function errorText(e: unknown): string {
  if (e instanceof ApiError) {
    const details = Array.isArray(e.details) ? e.details.filter((d) => typeof d === 'string') : []
    return details.length ? `${e.message}: ${details.join('; ')}` : e.message
  }
  if (e instanceof OfflineError) return 'No connection. Try again when you have signal.'
  return 'Something went wrong'
}
