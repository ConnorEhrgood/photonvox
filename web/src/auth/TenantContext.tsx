import { createContext, useContext, useMemo, useState, type ReactNode } from 'react'
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

export function useTenant(): TenantState {
  const v = useContext(Ctx)
  if (!v) throw new Error('useTenant outside TenantProvider')
  return v
}

export function TenantProvider({ children }: { children: ReactNode }) {
  const { me } = useAuth()
  const tenants = me?.tenants ?? []
  const [picked, setPicked] = useState<string | null>(() => {
    try { return localStorage.getItem(KEY) } catch { return null }
  })
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
