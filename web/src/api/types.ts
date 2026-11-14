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

export interface DraftUser { name: string; site: string; extension: string; email?: string; direct_number?: string; show?: 'site' | 'direct'; voicemail?: boolean; caller_id?: string | null }

/** The document being built (api/app/document/model.py). A target is one of {user}, {group}, {menu}, {voicemail}. */
export type DraftTarget = Record<string, string>
export interface DraftNumber { site: string; open: DraftTarget; closed?: DraftTarget | null; hours?: string | null }
export interface DraftGroup { members: string[]; strategy?: 'simultaneous' | 'sequence'; ring_seconds?: number; then?: DraftTarget | null }
export interface DraftMenu { greeting: string; options: Record<string, DraftTarget>; timeout?: DraftTarget }   // none: the call ends (an adopted menu, decision 32)
export interface DraftHours { week: Partial<Record<'mon' | 'tue' | 'wed' | 'thu' | 'fri' | 'sat' | 'sun', string[]>>; holidays?: 'none' | 'us-federal' }
/** A door station (PhotonEntry's intercom): whatever it dials rings `open` (or `closed` after hours); never a menu or voicemail. */
export interface DraftDoor { name: string; site: string; extension: string; open: DraftTarget; closed?: DraftTarget | null; hours?: string | null }
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
  doors?: Record<string, DraftDoor>
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

/** A PhotonEntry connection token (api/app/routes/integrations.py); `token` only in the answer that made it. */
export interface EntryToken { id: string; label: string; scope: string; hint: string; created_at: string; revoked_at: string | null; last_used_at: string | null; token?: string }

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

/** The customer dashboard (GET /tenants/{id}/dashboard; api/app/dashboard.py). A part the engine could not give is null and named in `unavailable`. */
export type CallKind = 'inbound' | 'outbound' | 'internal'
export interface HourMix { inbound: number; outbound: number; internal: number }
export interface Dashboard {
  published: boolean
  as_of?: string
  timezone?: string
  site: string | null
  sites: { id: string; slug: string; name: string }[]
  unavailable?: ('history' | 'live' | 'voicemail')[]
  phone_system?: { status: PhoneSystemStatus; version: number }
  now?: { count: number; lines: number; calls: { kind: CallKind; who: { extension: string; name: string }[]; other: string | null; number: string | null; state: 'talking' | 'ringing'; seconds: number; site: string | null }[] } | null
  phones?: { online: number; total: number; devices: number; offline: { extension: string; name: string; site: string }[] } | null
  trunk?: { state: 'ok' | 'trouble' | 'unknown'; words: string; gateways: number; last_in: string | null; last_out: string | null }
  today?: (HourMix & { calls: number; minutes: number; answered: number; missed: number; to_voicemail: number; by_hour: HourMix[]; peak_lines: number; in_progress?: number }) | null
  typical?: { days: number; weekday: string; by_hour: number[]; calls_so_far: number | null; minutes_so_far: number | null; missed_so_far: number | null } | null
  busiest?: { grid: number[][]; top: { weekday: number; hour: number; calls: number } | null } | null
  week?: HourMix | null
  emergency?: { at: string; dialed: string; extension: string | null; who: string | null; site: string | null; address: string | null; answered: boolean; seconds: number }[] | null
  voicemail?: { new: number; boxes: { box: string; extension: string | null; name: string; new: number; oldest_new: string | null }[] } | null
  numbers?: { number: string; site: string | null; rings: string; closed: string | null; calls_today: number; last_call: string | null }[]
}
