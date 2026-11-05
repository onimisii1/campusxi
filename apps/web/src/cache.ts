// Last-known-good copies of server data, so the scorer app reopens with no signal.

export function remember<T>(key: string, value: T): T {
  try {
    localStorage.setItem(`campusxi.cache.${key}`, JSON.stringify(value))
  } catch {
    // storage full or unavailable: the app still works online
  }
  return value
}

export function recall<T>(key: string): T | null {
  try {
    const raw = localStorage.getItem(`campusxi.cache.${key}`)
    return raw ? (JSON.parse(raw) as T) : null
  } catch {
    return null
  }
}
