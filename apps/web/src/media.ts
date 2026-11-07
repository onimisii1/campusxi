// Photos: resized on the phone before upload (fast on campus data, small to store), then sent raw
// to the API, which checks they really are images.
import { API_BASE, ApiError, OfflineError } from './api'

/** "/media/<id>" paths come from our API; full https links are used as they are. */
export function mediaUrl(path: string | null | undefined): string | null {
  if (!path) return null
  return path.startsWith('/media/') ? `${API_BASE}${path}` : path
}

type Fit = { max: number; square?: boolean; type: 'image/jpeg' | 'image/png'; quality?: number }

export const AVATAR: Fit = { max: 256, square: true, type: 'image/jpeg', quality: 0.85 }
export const CREST: Fit = { max: 256, type: 'image/png' }              // keeps a transparent background
export const MATCH_PHOTO: Fit = { max: 1280, type: 'image/jpeg', quality: 0.8 }

/** Downscale (and centre-crop to a square for avatars) with a canvas. */
export async function resize(file: File, fit: Fit): Promise<Blob> {
  if (!file.type.startsWith('image/')) throw new Error('Choose a photo (JPEG, PNG or WebP).')
  const bitmap = await createImageBitmap(file).catch(() => { throw new Error("That photo couldn't be opened.") })
  let sx = 0
  let sy = 0
  let sw = bitmap.width
  let sh = bitmap.height
  if (fit.square) {
    const side = Math.min(sw, sh)
    sx = (sw - side) / 2
    sy = (sh - side) / 2
    sw = sh = side
  }
  const scale = Math.min(1, fit.max / Math.max(sw, sh))
  const canvas = document.createElement('canvas')
  canvas.width = Math.round(sw * scale)
  canvas.height = Math.round(sh * scale)
  canvas.getContext('2d')!.drawImage(bitmap, sx, sy, sw, sh, 0, 0, canvas.width, canvas.height)
  return new Promise((resolve, reject) => canvas.toBlob(
    (b) => (b ? resolve(b) : reject(new Error("That photo couldn't be prepared."))), fit.type, fit.quality))
}

export async function uploadImage<T>(path: string, token: string | null, blob: Blob): Promise<T> {
  let res: Response
  try {
    res = await fetch(`${API_BASE}${path}`, {
      method: 'PUT', body: blob,
      headers: { 'Content-Type': blob.type, ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    })
  } catch {
    throw new OfflineError('no connection')
  }
  const data = await res.json().catch(() => null)
  if (!res.ok) {
    const err = data?.error ?? {}
    throw new ApiError(res.status, err.code ?? 'error', err.message ?? res.statusText)
  }
  return data as T
}

/** Open the phone's photo picker; resolves with the chosen file (or null if cancelled). */
export function pickPhoto(): Promise<File | null> {
  return new Promise((resolve) => {
    const input = document.createElement('input')
    input.type = 'file'
    input.accept = 'image/png,image/jpeg,image/webp'
    input.onchange = () => resolve(input.files?.[0] ?? null)
    input.click()
  })
}
