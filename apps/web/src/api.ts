// Thin client for the CampusXI API. Errors use the API's { error: { code, message } } shape;
// a failed fetch (no signal) surfaces as OfflineError so callers can queue and retry.

const BASE = import.meta.env.VITE_API_URL ?? 'http://localhost:8000'

export class ApiError extends Error {
  status: number
  code: string
  details?: unknown

  constructor(status: number, code: string, message: string, details?: unknown) {
    super(message)
    this.status = status
    this.code = code
    this.details = details
  }
}

export class OfflineError extends Error {}

export async function api<T>(path: string, token: string | null,
  init: { method?: string; body?: unknown; csv?: string; idempotencyKey?: string } = {}) {
  let res: Response
  try {
    res = await fetch(`${BASE}${path}`, {
      method: init.method ?? 'GET',
      headers: {
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        ...(init.body !== undefined ? { 'Content-Type': 'application/json' } : {}),
        ...(init.csv !== undefined ? { 'Content-Type': 'text/csv' } : {}),
        ...(init.idempotencyKey ? { 'Idempotency-Key': init.idempotencyKey } : {}),
      },
      body: init.csv ?? (init.body !== undefined ? JSON.stringify(init.body) : undefined),
    })
  } catch {
    throw new OfflineError('no connection')
  }
  const data = await res.json().catch(() => null)
  if (!res.ok) {
    const err = data?.error ?? {}
    throw new ApiError(res.status, err.code ?? 'error', err.message ?? res.statusText, err.details)
  }
  return data as T
}
