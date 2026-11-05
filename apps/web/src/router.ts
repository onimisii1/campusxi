import { useEffect, useState } from 'react'

// Hash routes keep the PWA working from any static host: "#/match/abc" -> ["match", "abc"].
export function useRoute(): string[] {
  const [hash, setHash] = useState(window.location.hash)
  useEffect(() => {
    const onChange = () => {
      setHash(window.location.hash)
      window.scrollTo(0, 0)
    }
    window.addEventListener('hashchange', onChange)
    return () => window.removeEventListener('hashchange', onChange)
  }, [])
  return hash.replace(/^#\/?/, '').split('/').filter(Boolean)
}

export function go(path: string): void {
  window.location.hash = path
}

const RETURN_KEY = 'campusxi.returnTo'

/** Send the user to sign in, then back to where they were. */
export function signInThenReturn(): void {
  sessionStorage.setItem(RETURN_KEY, window.location.hash || '#/')
  go('/signin')
}

export function returnAfterSignIn(): void {
  const to = sessionStorage.getItem(RETURN_KEY) || '#/'
  sessionStorage.removeItem(RETURN_KEY)
  window.location.hash = to
}
