import { createContext, useContext } from 'react'

export const ToastContext = createContext<(text: string, tone?: 'good' | 'bad') => void>(() => {})

export function useToast() {
  return useContext(ToastContext)
}

/** A short vibration where supported, so a scorer feels each tap register. */
export function buzz(ms = 25): void {
  try {
    navigator.vibrate?.(ms)
  } catch {
    // vibration is a nicety only
  }
}
