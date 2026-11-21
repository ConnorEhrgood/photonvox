// GENERATED from @photon/ui by scripts/sync-vendored.mjs. Do not edit here: change photon-ui, then re-run it. photon-ui 031c370e5fa1
import { useEffect, useRef, useState, type ReactNode } from 'react'
import { Link, NavLink, useLocation } from 'react-router-dom'
import { AppSwitcher, type SwitcherData } from './AppSwitcher'
import { Icon, PhotonMark, type IconName } from './icons'

/** The width at which the sidebar becomes a drawer and the top bar appears (components.css). */
const PHONE = '(max-width: 900px)'

function useIsPhone(): boolean {
  const query = () => typeof window !== 'undefined' && typeof window.matchMedia === 'function' && window.matchMedia(PHONE).matches
  const [phone, setPhone] = useState(query)
  useEffect(() => {
    if (typeof window.matchMedia !== 'function') return
    const m = window.matchMedia(PHONE)
    const on = () => setPhone(m.matches)
    m.addEventListener('change', on)
    return () => m.removeEventListener('change', on)
  }, [])
  return phone
}

export interface NavItem {
  to: string
  label: string
  icon: IconName
  /** Match only this exact path (for an index page such as "/"). */
  end?: boolean
  /** A count or dot shown at the right of the item. */
  badge?: ReactNode
}
export interface NavGroup {
  /** A small heading above the group. Leave it out for the first group. */
  label?: string
  items: NavItem[]
}
export interface AccountAction {
  label: string
  /** Where it goes. Give this or onClick. */
  to?: string
  onClick?: () => void
}
export interface AppShellProps {
  /** The product's name, shown beside the Photon ring: "PhotonBoard", "PhotonConsole". */
  product: string
  /** Where the brand links to. */
  home: string
  groups: NavGroup[]
  /** Pinned to the bottom of the sidebar: Settings, Platform. */
  footer?: NavItem[]
  /** The organization picker, under the brand. */
  switcher?: ReactNode
  /** Always-visible status, above the account (PhotonConsole's alert counts). */
  status?: ReactNode
  /** A message for the whole page, above the content (billing, an unconfirmed address). */
  banner?: ReactNode
  account: { name: string; detail?: string; actions: AccountAction[] }
  /** The suite's app switcher (AppSwitcher.tsx): this product's key and how to load the list for the organization and site on screen. */
  apps?: { current: string; load: () => Promise<SwitcherData>; loadKey?: string; homeUrl?: string }
  children: ReactNode
}

/**
 * The one application frame for every Photon product: sidebar on the left (a drawer on phones), settings pinned at the bottom,
 * the signed-in person's menu under it. GENERATED COPY: edit it in photon-ui (shell/), then run scripts/sync-vendored.mjs.
 */
export function AppShell({ product, home, groups, footer = [], switcher, status, banner, account, apps, children }: AppShellProps) {
  // The drawer remembers the page it was opened on, so going anywhere else closes it without an effect to do so.
  const { pathname } = useLocation()
  const [openAt, setOpenAt] = useState<string | null>(null)
  const open = openAt === pathname
  const setOpen = (v: boolean) => setOpenAt(v ? pathname : null)
  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && setOpenAt(null)
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open])

  // The app switcher: ONE copy, in the sidebar's head on a desktop and in the top bar on a phone; Ctrl+. or ⌘. opens it from anywhere.
  const phone = useIsPhone()
  const [appsOpen, setAppsOpen] = useState(false)
  useEffect(() => {
    if (!apps) return
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key === '.') { e.preventDefault(); setAppsOpen((v) => !v) }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [apps])
  const appSwitcher = apps && <AppSwitcher {...apps} open={appsOpen} onOpenChange={setAppsOpen} />

  const item = (n: NavItem) => (
    <NavLink key={n.to} to={n.to} end={n.end} className="ph-nav-item">
      <Icon name={n.icon} />
      <span className="ph-nav-label">{n.label}</span>
      {n.badge}
    </NavLink>
  )

  return (
    <div className="ph-app">
      <aside id="ph-sidebar" className="ph-sidebar" data-open={open || undefined}>
        <div className="ph-sidebar-head">
          <Link to={home} className="ph-brand"><PhotonMark />{product}</Link>
          {appSwitcher && !phone && appSwitcher}
        </div>
        {switcher && <div className="ph-sidebar-switcher">{switcher}</div>}
        <nav className="ph-sidebar-nav" aria-label="Main">
          {groups.filter((g) => g.items.length > 0).map((g, i) => (
            <div className="ph-nav-group" key={g.label ?? i}>
              {g.label && <div className="ph-nav-group-label">{g.label}</div>}
              {g.items.map(item)}
            </div>
          ))}
        </nav>
        <div className="ph-sidebar-foot">
          {footer.length > 0 && <nav aria-label="Settings and administration">{footer.map(item)}</nav>}
          {status && <div className="ph-sidebar-status">{status}</div>}
          <AccountMenu {...account} />
        </div>
      </aside>
      {open && <div className="ph-scrim" onClick={() => setOpen(false)} />}
      <div className="ph-app-body">
        <header className="ph-topbar">
          <button type="button" className="ph-btn ph-btn-ghost ph-btn-sm" aria-label={open ? 'Close menu' : 'Open menu'} aria-expanded={open} aria-controls="ph-sidebar" onClick={() => setOpen(!open)}>
            <Icon name="menu" size={20} />
          </button>
          <Link to={home} className="ph-brand"><PhotonMark />{product}</Link>
          {appSwitcher && phone && appSwitcher}
        </header>
        {banner && <div className="ph-app-banner">{banner}</div>}
        <main className="ph-main">{children}</main>
      </div>
    </div>
  )
}

function AccountMenu({ name, detail, actions }: { name: string; detail?: string; actions: AccountAction[] }) {
  const [open, setOpen] = useState(false)
  const root = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!open) return
    const onDown = (e: MouseEvent) => { if (!root.current?.contains(e.target as Node)) setOpen(false) }
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && setOpen(false)
    document.addEventListener('mousedown', onDown)
    window.addEventListener('keydown', onKey)
    return () => { document.removeEventListener('mousedown', onDown); window.removeEventListener('keydown', onKey) }
  }, [open])
  return (
    <div className="ph-account" ref={root}>
      {open && (
        <div className="ph-menu" role="menu" aria-label="Account">
          {actions.map((a) => a.to
            ? <Link key={a.label} role="menuitem" className="ph-menu-item" to={a.to} onClick={() => setOpen(false)}>{a.label}</Link>
            : <button key={a.label} type="button" role="menuitem" className="ph-menu-item" onClick={() => { setOpen(false); a.onClick?.() }}>{a.label}</button>)}
        </div>
      )}
      <button type="button" className="ph-account-btn" aria-haspopup="menu" aria-expanded={open} onClick={() => setOpen(!open)}>
        <span className="ph-avatar" aria-hidden="true">{name.trim().charAt(0).toUpperCase() || '?'}</span>
        <span className="ph-account-text"><b>{name}</b>{detail && <small>{detail}</small>}</span>
        <Icon name="chevrons" size={16} />
      </button>
    </div>
  )
}
