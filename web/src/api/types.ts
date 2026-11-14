// The shapes the PhotonVox API returns (api/app/routes). Kept by hand next to the routes they describe.

export type Role = 'user' | 'admin' | 'owner'
export type Scope = { all: true } | { sites: string[] }

/** An organization the signed-in person has access to, as /me says it. Partner staff (integrators) see every customer of their partner, `source: 'partner'`. */
export interface TenantAccess {
  id: string
  name: string
  /** The organization's address in every Photon product, /org/<slug>/ (from the directory); its former ones redirect. */
  slug?: string | null
  former_slugs?: string[]
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
  /** Photon staff (the directory's platform administrators and partner Photon's members): the Platform pages. */
  is_staff: boolean
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

// ---- the phone system (api/app/routes/phone_system.py) ----

export interface Problem { path: string; code: string; message: string }

export type PhoneSystemStatus = 'new' | 'publishing' | 'ready' | 'failed' | 'changed'

export interface DraftUser { name: string; site: string; extension: string; email?: string; direct_number?: string; show?: 'site' | 'direct'; voicemail?: boolean }

/** The document being built (api/app/document/model.py). A target is one of {user}, {group}, {menu}, {voicemail}. */
export type DraftTarget = Record<string, string>
export interface DraftNumber { site: string; open: DraftTarget; closed?: DraftTarget | null; hours?: string | null }
export interface DraftGroup { members: string[]; strategy?: 'simultaneous' | 'sequence'; ring_seconds?: number; then?: DraftTarget | null }
export interface DraftMenu { greeting: string; options: Record<string, DraftTarget>; timeout?: DraftTarget }   // none: the call ends (an adopted menu, decision 32)
export interface DraftHours { week: Partial<Record<'mon' | 'tue' | 'wed' | 'thu' | 'fri' | 'sat' | 'sun', string[]>>; holidays?: 'none' | 'us-federal' }
export interface DraftSite { emergency_location: string; emergency_number: string; caller_id: string; hours?: string | null; unreachable?: 'voicemail' | 'none'; outside_prefix?: '8' | '9' | null }
export interface Draft {
  version: 1
  voice?: string
  sites?: Record<string, DraftSite>
  hours?: Record<string, DraftHours>
  numbers?: Record<string, DraftNumber>
  menus?: Record<string, DraftMenu>
  groups?: Record<string, DraftGroup>
  users?: Record<string, DraftUser>
  boxes?: Record<string, { name: string; email?: string | null }>
  calling?: Record<string, unknown>
  features?: Record<string, boolean>
}

export interface PhoneSystemSummary {
  id: string
  status: PhoneSystemStatus
  domain: string
  instance: string
  published_version: number | null
  draft: Draft
  draft_updated_at: string
  problems: Problem[]
  drift: { checked_at: string | null; changed: number; missing: number; extra: { table: string; uuid: string; label: string }[] }
}

export interface Version {
  number: number
  state: 'queued' | 'publishing' | 'ready' | 'failed' | 'superseded'
  note: string
  error: string
  created_by: string
  created_at: string
  published_at: string | null
  checks: { passed: number; total: number; failed: { kind: string; number: string; expected: string[]; got: string | null }[] }
}

export interface Template { key: string; name: string; description: string }

export interface ImportRow { line: number; id: string; user: DraftUser; problems: string[] }

export interface EmergencyAddress { street: string; unit: string; city: string; state: string; zip: string }

export interface EmergencyState {
  locations: { id: string; site_id: string; key: string; address: EmergencyAddress; status: 'pending' | 'validated' | 'rejected'; note: string }[]
  numbers: { number: string; status: 'unconfirmed' | 'requested' | 'confirmed'; location_id: string | null; confirmed_at: string | null }[]
  requests: { id: string; status: string; items: { number: string; action: string }[]; reference: string; sent_at: string | null }[]
}

export interface CarrierRequestRow {
  id: string
  organization: string
  carrier: string
  method: string
  status: 'open' | 'sent'
  items: { number: string; action: 'add' | 'change' | 'remove'; address: EmergencyAddress | null }[]
  reference: string
  created_at: string
  sent_at: string | null
  email: { subject: string; body: string }
}

export interface PendingLocation { id: string; organization: string; site_id: string; key: string; address: EmergencyAddress }

/** The voices greetings are spoken in (api/app/speech VOICES; decision 30: Google Chirp 3 HD), as integrators choose them. */
export const VOICES: [string, string][] = [
  ['en-US-Chirp3-HD-Kore', 'Kore (US English, female)'], ['en-US-Chirp3-HD-Charon', 'Charon (US English, male)'],
  ['en-US-Chirp3-HD-Aoede', 'Aoede (US English, female, lighter)'], ['es-US-Chirp3-HD-Kore', 'Kore (US Spanish, female)'],
]
