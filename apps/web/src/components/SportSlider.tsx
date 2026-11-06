import { useApi } from '../useApi'

type Sport = { code: string; name: string; live: boolean }

const KEY = 'campusxi.sport'
const BALL: Record<string, string> = { football: '⚽', basketball: '🏀', volleyball: '🏐' }

// eslint-disable-next-line react-refresh/only-export-components
export function savedSport(): string {
  try {
    return localStorage.getItem(KEY) || 'football'
  } catch {
    return 'football'
  }
}

export default function SportSlider({ value, onChange }: { value: string; onChange: (code: string) => void }) {
  const { data: sports } = useApi<Sport[]>('/sports')
  return (
    <div className="slider" role="tablist" aria-label="Sport">
      {(sports ?? []).map((s) => (
        <button key={s.code} role="tab" aria-selected={value === s.code} disabled={!s.live}
          className={value === s.code ? 'seg on' : 'seg'}
          onClick={() => {
            try {
              localStorage.setItem(KEY, s.code)
            } catch {
              // remembering the sport is a convenience only
            }
            onChange(s.code)
          }}>
          <span className="ball" aria-hidden>{BALL[s.code] ?? '🏆'}</span>{s.name}{!s.live && <small> soon</small>}
        </button>
      ))}
    </div>
  )
}
