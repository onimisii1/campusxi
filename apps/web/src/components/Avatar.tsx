import { mediaUrl } from '../media'

/** A player's round picture: their photo, or their initials on lime. */
export default function Avatar({ name, url, size = 42 }: { name: string; url?: string | null; size?: number }) {
  const src = mediaUrl(url)
  const initials = name.split(/[\s_]+/).map((w) => w[0]).join('').slice(0, 2).toUpperCase()
  return src
    ? <img className="avatar photo" src={src} alt="" width={size} height={size} style={{ width: size, height: size }} />
    : <span className="avatar" style={{ width: size, height: size }} aria-hidden>{initials}</span>
}
