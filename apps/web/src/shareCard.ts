// Shareable result images (results, tables, golden boot, MVP) drawn with the Canvas 2D API: no
// library, works offline. Shared through the Web Share API (straight to WhatsApp on phones),
// with a download as the fallback. CampusXI branding only: no school or association logos.

export type CardRow = {
  rank?: string
  chip?: { code: string; colour: string }
  text: string
  sub?: string
  cells: string[]          // right-aligned columns, the last one drawn bold
  highlight?: boolean
}

export type CardSpec = {
  title: string            // "LEAGUE TABLE"
  kicker: string           // tournament name
  badge?: string           // "AFTER THU 5 NOV"
  headers: string[]        // for `cells`
  rows: CardRow[]
  note?: string
}

const W = 1080
const H = 1350
const NAVY = '#0b2545'
const NAVY_2 = '#13315c'
const GREEN = '#19a68f'

function luminance(hex: string): number {
  const [r, g, b] = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16))
  return 0.299 * r + 0.587 * g + 0.114 * b
}

function roundRect(ctx: CanvasRenderingContext2D, x: number, y: number, w: number, h: number, r: number) {
  ctx.beginPath()
  ctx.moveTo(x + r, y)
  ctx.arcTo(x + w, y, x + w, y + h, r)
  ctx.arcTo(x + w, y + h, x, y + h, r)
  ctx.arcTo(x, y + h, x, y, r)
  ctx.arcTo(x, y, x + w, y, r)
  ctx.closePath()
}

function fit(ctx: CanvasRenderingContext2D, text: string, max: number): string {
  if (ctx.measureText(text).width <= max) return text
  let t = text
  while (t.length > 1 && ctx.measureText(`${t}…`).width > max) t = t.slice(0, -1)
  return `${t}…`
}

export function drawCard(canvas: HTMLCanvasElement, spec: CardSpec): void {
  canvas.width = W
  canvas.height = H
  const ctx = canvas.getContext('2d')!
  const font = (weight: number, size: number) => `${weight} ${size}px Inter, system-ui, Arial, sans-serif`

  // background
  const bg = ctx.createLinearGradient(0, 0, W, H)
  bg.addColorStop(0, NAVY)
  bg.addColorStop(1, '#0f4c5c')
  ctx.fillStyle = bg
  ctx.fillRect(0, 0, W, H)

  // header
  ctx.textAlign = 'center'
  ctx.fillStyle = GREEN
  ctx.font = font(700, 30)
  ctx.fillText(fit(ctx, spec.kicker.toUpperCase(), W - 120), W / 2, 100)
  ctx.fillStyle = '#fff'
  ctx.font = font(900, 92)
  ctx.fillText(fit(ctx, spec.title.toUpperCase(), W - 100), W / 2, 205)
  ctx.fillStyle = GREEN
  roundRect(ctx, W / 2 - 70, 232, 140, 10, 5)
  ctx.fill()
  if (spec.badge) {
    ctx.font = font(800, 30)
    const bw = ctx.measureText(spec.badge).width + 60
    roundRect(ctx, W / 2 - bw / 2, 270, bw, 56, 28)
    ctx.fillStyle = GREEN
    ctx.fill()
    ctx.fillStyle = '#fff'
    ctx.fillText(spec.badge, W / 2, 309)
  }

  // panel
  const top = 360
  const rowH = Math.min(100, Math.floor((H - top - 230) / Math.max(spec.rows.length, 1)))
  const panelH = 80 + rowH * spec.rows.length
  roundRect(ctx, 50, top, W - 100, panelH, 28)
  ctx.fillStyle = '#ffffff'
  ctx.fill()
  ctx.save()
  roundRect(ctx, 50, top, W - 100, 80, 28)
  ctx.clip()
  ctx.fillStyle = NAVY_2
  ctx.fillRect(50, top, W - 100, 80)
  ctx.restore()

  const colW = 92
  const cellX = (i: number) => W - 90 - (spec.headers.length - 1 - i) * colW
  ctx.font = font(800, 26)
  ctx.fillStyle = '#cfd8e3'
  ctx.textAlign = 'left'
  ctx.fillText('#', 80, top + 52)
  ctx.textAlign = 'right'
  spec.headers.forEach((h, i) => ctx.fillText(h, cellX(i), top + 52))

  ctx.save()
  roundRect(ctx, 50, top, W - 100, panelH, 28)   // keep row shading inside the rounded panel
  ctx.clip()
  spec.rows.forEach((r, i) => {
    const y = top + 80 + i * rowH
    if (r.highlight) {
      ctx.fillStyle = '#e6f6f2'
      ctx.fillRect(50, y, W - 100, rowH)
    }
    if (i > 0) {
      ctx.fillStyle = '#e3e8ef'
      ctx.fillRect(70, y, W - 140, 2)
    }
    const mid = y + rowH / 2 + 12
    ctx.textAlign = 'left'
    ctx.fillStyle = GREEN
    ctx.font = font(900, 36)
    ctx.fillText(r.rank ?? '', 76, mid)
    let x = 150
    if (r.chip) {
      ctx.font = font(900, 28)
      const cw = 110
      roundRect(ctx, x, mid - 38, cw, 50, 12)
      ctx.fillStyle = r.chip.colour
      ctx.fill()
      ctx.strokeStyle = '#c3ccd8'
      ctx.lineWidth = 2
      ctx.stroke()
      ctx.fillStyle = luminance(r.chip.colour) > 170 ? '#0b2545' : '#fff'
      ctx.textAlign = 'center'
      ctx.fillText(r.chip.code, x + cw / 2, mid - 3)
      x += cw + 22
    }
    ctx.textAlign = 'left'
    ctx.fillStyle = NAVY
    ctx.font = font(800, 34)
    const textMax = cellX(0) - colW + 30 - x
    ctx.fillText(fit(ctx, r.text, textMax), x, r.sub ? mid - 10 : mid)
    if (r.sub) {
      ctx.font = font(500, 24)
      ctx.fillStyle = '#5f6b7a'
      ctx.fillText(fit(ctx, r.sub, textMax), x, mid + 22)
    }
    ctx.textAlign = 'right'
    r.cells.forEach((c, j) => {
      const last = j === r.cells.length - 1
      ctx.font = font(last ? 900 : 600, last ? 40 : 32)
      ctx.fillStyle = NAVY
      ctx.fillText(c, cellX(j), mid)
    })
  })
  ctx.restore()

  // footer
  ctx.textAlign = 'center'
  if (spec.note) {
    ctx.fillStyle = '#cfd8e3'
    ctx.font = font(500, 26)
    ctx.fillText(fit(ctx, spec.note, W - 120), W / 2, top + panelH + 60)
  }
  ctx.fillStyle = GREEN
  ctx.fillRect(0, H - 90, W, 90)
  ctx.fillStyle = '#fff'
  ctx.font = font(900, 36)
  ctx.fillText('CampusXI · play the games you watch', W / 2, H - 32)
}

/** Share the card as a PNG (WhatsApp etc.), or download it where sharing files isn't supported. */
export async function shareCard(spec: CardSpec, filename: string): Promise<'shared' | 'downloaded' | 'cancelled'> {
  const canvas = document.createElement('canvas')
  drawCard(canvas, spec)
  const blob = await new Promise<Blob>((resolve, reject) =>
    canvas.toBlob((b) => (b ? resolve(b) : reject(new Error('could not draw the image'))), 'image/png'))
  const file = new File([blob], filename, { type: 'image/png' })
  if (navigator.canShare?.({ files: [file] })) {
    try {
      await navigator.share({ files: [file], title: spec.title })
      return 'shared'
    } catch (e) {
      if (e instanceof DOMException && e.name === 'AbortError') return 'cancelled'
    }
  }
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  setTimeout(() => URL.revokeObjectURL(url), 5000)
  return 'downloaded'
}
