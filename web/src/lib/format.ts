/** "5 minutes ago", for a status line. */
export function ago(iso: string, now: number = Date.now()): string {
  const s = Math.max(0, Math.round((now - new Date(iso).getTime()) / 1000))
  if (s < 90) return 'just now'
  const m = Math.round(s / 60)
  if (m < 90) return `${m} minutes ago`
  const h = Math.round(m / 60)
  if (h < 36) return `${h} hours ago`
  return `${Math.round(h / 24)} days ago`
}
