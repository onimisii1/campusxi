import { useCallback, useState, type ReactNode } from 'react'
import { ToastContext } from '../toast'

type Item = { id: number; text: string; tone: 'good' | 'bad' }

/** Short confirmations at the bottom of the screen ("Joined Free contest", "Goal recorded"). */
export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<Item[]>([])

  const show = useCallback((text: string, tone: 'good' | 'bad' = 'good') => {
    const id = Date.now() + Math.random()
    setItems((list) => [...list.slice(-2), { id, text, tone }])
    setTimeout(() => setItems((list) => list.filter((i) => i.id !== id)), 2600)
  }, [])

  return (
    <ToastContext.Provider value={show}>
      {children}
      <div className="toasts" role="status" aria-live="polite">
        {items.map((i) => <div key={i.id} className={`toast ${i.tone}`}>{i.text}</div>)}
      </div>
    </ToastContext.Provider>
  )
}
