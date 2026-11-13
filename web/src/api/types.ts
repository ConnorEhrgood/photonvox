// The shapes the PhotonVox API returns (api/app/routes). Kept by hand next to the routes they describe.

export type Role = 'user' | 'admin' | 'owner'
export type Scope = { all: true } | { sites: string[] }

/** An organization the signed-in person has access to, as /me says it. Partner staff (integrators) see every customer of their partner, `source: 'partner'`. */
export interface TenantAccess {
  id: string
  name: string
  status: string
  partner_id: string | null
  role: Role
  scope: Scope
  source: 'direct' | 'partner'
  expires_at: string | null
  capabilities: string[]
}

export interface Me {
  id: string
  name: string
  email: string
  is_platform_admin: boolean
  tenants: TenantAccess[]
}

export interface Site {
  id: string
  slug: string
  name: string
  address: string
  timezone: string
}

export interface Member {
  person_id: string
  name: string
  email: string
  role: Role
  scope: Scope
  source: 'direct' | 'partner'
  pending: boolean
}

export interface PlatformOrganization {
  id: string
  name: string
  status: string
  plan_key: string
  home_region: string
  partner_id: string | null
  products?: string[]
}

export interface DirectoryStatus {
  cursor: number
  last_pull_at: string | null
  last_ok_at: string | null
  last_error: string | null
}

export const ROLE_LABEL: Record<Role, string> = { user: 'User', admin: 'Admin', owner: 'Owner' }

export const scopeText = (s: Scope, siteNames: Record<string, string> = {}): string =>
  'all' in s ? 'Whole organization' : s.sites.map((id) => siteNames[id] ?? 'a site').join(', ')
