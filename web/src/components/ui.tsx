import { useEffect, useRef, type ReactNode } from 'react'

export function Modal({ title, onClose, children, wide }: { title: string; onClose: () => void; children: ReactNode; wide?: boolean }) {
  const dialog = useRef<HTMLDivElement>(null)
  // Keyboard and screen-reader users land in the dialog when it opens and go back to what they were on when it closes.
  useEffect(() => {
    const before = document.activeElement as HTMLElement | null
    dialog.current?.focus()
    return () => before?.focus?.()
  }, [])
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])
  return (
    <div className="ph-modal-backdrop" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div ref={dialog} tabIndex={-1} className={`ph-modal${wide ? ' ph-modal-wide' : ''}`} role="dialog" aria-modal="true" aria-label={title}>
        <div className="ph-modal-header">
          <h2>{title}</h2>
          <button className="ph-btn ph-btn-ghost ph-btn-sm" onClick={onClose} aria-label="Close">✕</button>
        </div>
        {children}
      </div>
    </div>
  )
}

export const ErrorText = ({ children }: { children: ReactNode }) => (children ? <p className="ph-error" role="alert">{children}</p> : null)

/** `as="h2"` for a page that sits under a tabbed hub (Settings, Platform), whose own title is the h1. */
export function PageHeader({ title, children, as: Heading = 'h1' }: { title: string; children?: ReactNode; as?: 'h1' | 'h2' }) {
  // Under a tab the tab already says it; keep the heading for screen readers, show it only when there are actions to put beside it.
  if (Heading === 'h2' && !children) return <h2 className="ph-sr-only">{title}</h2>
  return (
    <div className="ph-page-header">
      <Heading>{title}</Heading>
      <div className="ph-actions">{children}</div>
    </div>
  )
}

export function Loading({ what }: { what: string }) {
  return <p className="ph-hint">Loading {what}…</p>
}

/** The state of a person's access or an organization, as a word plus color (never color alone). */
export function StatusBadge({ tone, children }: { tone: 'ok' | 'info' | 'warning' | 'error'; children: ReactNode }) {
  return <span className={`ph-badge ph-badge-${tone}`}>{children}</span>
}

/** A page whose feature is not built yet says so plainly, and says when it arrives and what it will show. */
export function NotYet({ title, arrives, children, as }: { title: string; arrives: string; children: ReactNode; as?: 'h1' | 'h2' }) {
  return (
    <>
      <PageHeader title={title} as={as} />
      <div className="ph-empty pv-notyet">
        <p><StatusBadge tone="info">Not built yet</StatusBadge> <span className="ph-hint">Planned for {arrives}</span></p>
        {children}
      </div>
    </>
  )
}
