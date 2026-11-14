import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { Navigate, Outlet, useLocation, useParams } from 'react-router-dom'
import type { TenantAccess } from '../api/types'
import { useAuth } from './AuthContext'

interface TenantState {
  tenants: TenantAccess[]
  current: TenantAccess | null
  select: (id: string) => void
  /** True if the signed-in person may use `capability` in the current organization. This is the server's own answer (role, scope and fine limits
   *  already applied) and only decides what the app shows; the API checks again on every request. */
  can: (capability: string) => boolean
}

const Ctx = createContext<TenantState | null>(null)
const KEY = 'pg:tenant'

/** The organization this person last opened in PhotonVox (per browser), or null. */
export function rememberedTenant(): string | null {
  try { return localStorage.getItem(KEY) } catch { return null }
}

/** An organization's address in every Photon product (photon-suite ARCHITECTURE §6): /org/<slug>. Its id stands in until the directory has sent
 *  the slug (an organization document from before slugs existed). */
export const orgPath = (t: Pick<TenantAccess, 'id' | 'slug'>) => `/org/${t.slug || t.id}`

/** A path inside the current organization ("/numbers" → "/org/<slug>/numbers"); outside any organization, the path as it is. */
export function useOrgPath(): (path: string) => string {
  const { current } = useTenant()
  return (path) => (current ? orgPath(current) + path : path)
}

export function useTenant(): TenantState {
  const v = useContext(Ctx)
  if (!v) throw new Error('useTenant outside TenantProvider')
  return v
}

export function TenantProvider({ children }: { children: ReactNode }) {
  const { me } = useAuth()
  const tenants = me?.tenants ?? []
  const [picked, setPicked] = useState<string | null>(rememberedTenant)
  const current = tenants.find((t) => t.id === picked) ?? tenants[0] ?? null

  const value = useMemo<TenantState>(() => ({
    tenants, current,
    select: (id) => {
      setPicked(id)
      try { localStorage.setItem(KEY, id) } catch { /* private mode: the choice just won't persist */ }
    },
    can: (capability) => !!current && current.capabilities.includes(capability),
  }), [tenants, current])

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>
}

/** The organization named in the address (`/org/<slug>/…`) is the current one for every page below. A slug it had before redirects to the one it has
 *  now, on the same page; one this person cannot reach (or no such organization) is a page saying so, never another organization's. */
export function OrgRoute() {
  const parent = useTenant()
  const { orgSlug = '' } = useParams()
  const { pathname, search, hash } = useLocation()
  const t = parent.tenants.find((x) => x.slug === orgSlug || x.id === orgSlug)
  const moved = t ? (t.slug && t.slug !== orgSlug ? t : null) : parent.tenants.find((x) => (x.former_slugs ?? []).includes(orgSlug)) ?? null
  const value = useMemo<TenantState | null>(() => t ? { ...parent, current: t, can: (c) => t.capabilities.includes(c) } : null, [parent, t])
  const remember = parent.select
  useEffect(() => { if (t && !moved) remember(t.id) }, [t, moved, remember])
  if (moved) return <Navigate to={pathname.replace(`/org/${orgSlug}`, orgPath(moved)) + search + hash} replace />
  if (!value) return <OrgNotFound />
  return <Ctx.Provider value={value}><Outlet /></Ctx.Provider>
}

function OrgNotFound() {
  const { signOut } = useAuth()
  return (
    <div className="ph-auth"><div className="ph-card">
      <h1>No such organization in PhotonVox</h1>
      <p>This address names an organization that does not exist, or one you have no access to in PhotonVox.</p>
      <div className="ph-actions"><a className="ph-btn" href="/">Go to my organizations</a>
        <button className="ph-btn ph-btn-secondary" onClick={() => void signOut()}>Sign out</button></div>
    </div></div>
  )
}

/** An old address without /org/ ("/numbers", "/settings/team"): the same page in the current organization. */
export function ToCurrentOrg() {
  const { current } = useTenant()
  const { pathname, search, hash } = useLocation()
  return <Navigate to={current ? orgPath(current) + pathname + search + hash : '/'} replace />
}
