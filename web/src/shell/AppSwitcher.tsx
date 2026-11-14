// GENERATED from @photon/ui by scripts/sync-vendored.mjs. Do not edit here: change photon-ui, then re-run it.
/**
 * The suite's app switcher (photonid docs/HOME-PLAN.md): a grid button in the shell's header that lists, for the organization (and site) on screen,
 * every Photon product: the ones you can open link to the SAME organization and site there; the others say why not (no access, not switched on for
 * this customer, coming). Home (the dashboard at account.photonind.com) is first. It never leads to another customer.
 * Keyboard: Ctrl+. or ⌘. opens it anywhere (AppShell); type to filter, arrows move, Enter opens, Esc closes.
 * GENERATED COPY in products: edit it in photon-ui (shell/), then run scripts/sync-vendored.mjs.
 */
import { useEffect, useMemo, useRef, useState, type KeyboardEvent as ReactKeyboardEvent } from 'react'
import { Icon } from './icons'

export type AppState = 'open' | 'no_access' | 'not_enabled' | 'coming'

export interface SwitcherApp {
  key: string
  name: string
  state: AppState
  /** Only for `open`: the product on the same organization (and site), `/org/<org-slug>/[site/<site-slug>/]`. */
  url?: string
}

/** What the directory answers at GET /v1/me/apps?organization=<slug>&site=<slug>. */
export interface SwitcherData {
  home: string
  organization: { id: string; slug: string; name: string }
  site?: { id: string; slug: string; name: string } | null
  apps: SwitcherApp[]
}

/** How long the switcher waits for the directory. */
export const SWITCHER_TIMEOUT_MS = 4000

/** Reads the switcher's list from the directory with the product's own token (it carries the directory's audience too). */
export async function loadApps(directoryApi: string, token: string | null, organization: string, site?: string | null,
                               fetchImpl: typeof fetch = fetch, timeoutMs = SWITCHER_TIMEOUT_MS): Promise<SwitcherData> {
  const q = new URLSearchParams({ organization, ...(site ? { site } : {}) })
  const ctrl = new AbortController()
  const timer = setTimeout(() => ctrl.abort(), timeoutMs)
  try {
    const r = await fetchImpl(`${directoryApi.replace(/\/$/, '')}/v1/me/apps?${q}`, {
      headers: token ? { Authorization: `Bearer ${token}` } : {}, signal: ctrl.signal,
    })
    if (!r.ok) throw new Error(`The directory answered ${r.status}`)
    return (await r.json()) as SwitcherData
  } finally {
    clearTimeout(timer)
  }
}

const WHY: Record<Exclude<AppState, 'open'>, string> = {
  no_access: 'No access',
  not_enabled: 'Not on for this customer',
  coming: 'Coming',
}

export interface AppSwitcherProps {
  /** The product this is (its key: "guard", "vox"): marked "here". */
  current: string
  /** Loads the list (usually `() => loadApps(DIRECTORY_URL, token, orgSlug, siteSlug)`); called on the first open and again when it changes. */
  load: () => Promise<SwitcherData>
  /** Where Home goes if the list cannot be loaded (the dashboard). */
  homeUrl?: string
  open: boolean
  onOpenChange: (open: boolean) => void
}

export function AppSwitcher({ current, load, homeUrl = 'https://account.photonind.com/', open, onOpenChange }: AppSwitcherProps) {
  const [data, setData] = useState<SwitcherData | null>(null)
  const [failed, setFailed] = useState(false)
  const [filter, setFilter] = useState('')
  const loadedFor = useRef<(() => Promise<SwitcherData>) | null>(null)   // the list is asked for once per place (load), not at every open
  const root = useRef<HTMLDivElement>(null)
  const button = useRef<HTMLButtonElement>(null)
  const input = useRef<HTMLInputElement>(null)

  useEffect(() => {
    if (!open || loadedFor.current === load) return
    let live = true, done = false
    loadedFor.current = load
    setData(null)
    setFailed(false)
    load().then((d) => live && setData(d)).catch(() => live && setFailed(true)).finally(() => { done = true })
    return () => {
      live = false
      if (!done) loadedFor.current = null   // closed before the answer came: ask again at the next open
    }
  }, [open, load])

  useEffect(() => {
    if (!open) return
    setFilter('')
    input.current?.focus()
    const onDown = (e: MouseEvent) => { if (!root.current?.contains(e.target as Node)) onOpenChange(false) }
    document.addEventListener('mousedown', onDown)
    return () => document.removeEventListener('mousedown', onDown)
  }, [open, onOpenChange])

  const apps = useMemo(() => {
    const f = filter.trim().toLowerCase()
    return (data?.apps ?? []).filter((a) => !f || a.name.toLowerCase().includes(f) || a.key.includes(f))
  }, [data, filter])

  const move = (from: HTMLElement | null, step: number) => {
    const all = Array.from(root.current!.querySelectorAll<HTMLElement>('[data-switch-item]'))      // Home is always there, so never empty
    const i = from ? all.indexOf(from) : step > 0 ? -1 : 0      // from the filter box: down to the first, up to the last
    all[(i + step + all.length) % all.length].focus()
  }
  const onKey = (e: ReactKeyboardEvent) => {
    if (e.key === 'Escape') { e.preventDefault(); onOpenChange(false); button.current?.focus() }
    else if (e.key === 'ArrowDown') { e.preventDefault(); move(e.target === input.current ? null : (e.target as HTMLElement), 1) }
    else if (e.key === 'ArrowUp') { e.preventDefault(); move(e.target === input.current ? null : (e.target as HTMLElement), -1) }
  }
  const home = data?.home || homeUrl
  const where = data ? (data.site ? `${data.organization.name} · ${data.site.name}` : data.organization.name) : ''

  return (
    <div className="ph-appswitch" ref={root} onKeyDown={onKey}>
      <button ref={button} type="button" className="ph-btn ph-btn-ghost ph-btn-sm ph-appswitch-btn" aria-label="Switch app" title="Switch app (Ctrl+.)"
              aria-haspopup="dialog" aria-expanded={open} onClick={() => onOpenChange(!open)}>
        <Icon name="apps" size={20} />
      </button>
      {open && (
        <div className="ph-appswitch-panel" role="dialog" aria-label="Photon apps">
          <input ref={input} className="ph-input ph-appswitch-filter" placeholder="Find an app" aria-label="Find an app" value={filter}
                 onChange={(e) => setFilter(e.target.value)} />
          <a data-switch-item className="ph-appswitch-item ph-appswitch-home" href={home}>
            <Icon name="overview" size={18} /><span><b>Home</b><small>All your organizations and sites</small></span>
          </a>
          {where && <div className="ph-appswitch-where">In {where}</div>}
          {failed && <p className="ph-error ph-appswitch-note" role="alert">Couldn’t load your apps. Home still works.</p>}
          {!data && !failed && <p className="ph-hint ph-appswitch-note" role="status"><span className="ph-spinner" aria-hidden="true" /> Loading your apps</p>}
          {data && (
            <ul className="ph-appswitch-list" aria-label="Apps">
              {apps.map((a) => (
                <li key={a.key}>
                  {a.state === 'open' && a.url && a.key !== current
                    ? <a data-switch-item className="ph-appswitch-item" href={a.url}><span><b>{a.name}</b></span></a>
                    : (
                      <span className="ph-appswitch-item" aria-disabled="true" data-current={a.key === current || undefined}>
                        <span><b>{a.name}</b><small>{a.key === current ? 'You are here' : WHY[a.state as Exclude<AppState, 'open'>]}</small></span>
                      </span>
                    )}
                </li>
              ))}
              {apps.length === 0 && <li className="ph-hint ph-appswitch-note">No app matches “{filter}”.</li>}
            </ul>
          )}
        </div>
      )}
    </div>
  )
}
