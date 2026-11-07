import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from 'react'
import { api, ApiError, OfflineError } from './api'
import { getToken, signOut as authSignOut, supabase } from './auth'
import { recall, remember } from './cache'

export type Me = { id: string; team_name: string; roles: string[]; school_id: string; avatar_url?: string | null }

type Status = 'loading' | 'signed_out' | 'needs_profile' | 'ready'
type Session = { status: Status; token: string | null; me: Me | null; reload: () => Promise<void>; signOut: () => Promise<void> }

const SessionContext = createContext<Session | null>(null)

export function SessionProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<Status>('loading')
  const [token, setToken] = useState<string | null>(null)
  const [me, setMe] = useState<Me | null>(null)

  const reload = useCallback(async () => {
    const t = await getToken()
    setToken(t)
    if (!t) {
      setMe(null)
      setStatus('signed_out')
      return
    }
    try {
      setMe(remember('me', await api<Me>('/me', t)))
      setStatus('ready')
    } catch (e) {
      if (e instanceof ApiError && e.code === 'profile_required') setStatus('needs_profile')
      else if (e instanceof OfflineError && recall<Me>('me')) {
        setMe(recall<Me>('me'))
        setStatus('ready')
      } else {
        setMe(null)
        setStatus('signed_out')
      }
    }
  }, [])

  useEffect(() => {
    // Back from an email sign-in link: supabase-js has read the tokens from the URL; tidy it up.
    if (/access_token=|error_description=/.test(window.location.hash)) {
      const failed = /error_description=([^&]+)/.exec(window.location.hash)
      if (failed) sessionStorage.setItem('campusxi.signinError', decodeURIComponent(failed[1].replace(/\+/g, ' ')))
      window.history.replaceState(null, '', `${window.location.pathname}#/`)
    }
    reload()
    const sub = supabase?.auth.onAuthStateChange(() => { reload() })
    return () => sub?.data.subscription.unsubscribe()
  }, [reload])

  const signOut = useCallback(async () => {
    await authSignOut()
    localStorage.removeItem('campusxi.cache.me')
    await reload()
  }, [reload])

  return <SessionContext.Provider value={{ status, token, me, reload, signOut }}>{children}</SessionContext.Provider>
}

// eslint-disable-next-line react-refresh/only-export-components
export function useSession(): Session {
  const s = useContext(SessionContext)
  if (!s) throw new Error('useSession outside SessionProvider')
  return s
}
