import { Outlet, useMatch, useNavigate } from 'react-router-dom'
import { config } from '../config'
import { useAuth } from '../auth/AuthContext'
import { orgPath, useOrgPath, useTenant } from '../auth/TenantContext'
import { AppShell, type NavGroup, type NavItem } from '../shell/AppShell'
import { loadApps } from '../shell/AppSwitcher'
import { settingsTabs } from '../pages/Hubs'

/** "Manage organization": people, sites and products are managed in the PhotonID directory app, not here. */
export const DIRECTORY_URL = config.directoryAppUrl

/** Someone who works on more than one customer: an integrator (partner staff), or Photon staff acting as one. They get the Customers list first. */
export const isIntegrator = (tenants: { source: string }[]): boolean => tenants.length > 1 || tenants.some((t) => t.source === 'partner')

export function Layout() {
  const { me, signOut, source } = useAuth()
  const { tenants, current, can } = useTenant()
  const at = useOrgPath()
  const nav = useNavigate()
  const siteMatch = useMatch('/org/:orgSlug/site/:siteSlug/*')
  // Photon staff may belong to no organization at all: they still get the shell, with Platform.
  if (!current && !me?.is_staff) return <NoOrganization />

  // The integrator's tool first (ARCHITECTURE §3): the customer's phone system, page by page. Pages a person has no use for are left out (a user
  // sees only their own phone), which keeps the list short on a phone. The API refuses them anyway.
  const items: (NavItem & { cap?: string })[] = !current ? [] : [
    ...(isIntegrator(tenants) ? [{ to: '/customers', label: 'Customers', icon: 'clients' as const }] : []),
    // Icons as photon-ui DESIGN.md "Icons" says (id1, 2026-11-14): a desk phone for phones, a handset for one's own, a call for live calls.
    { to: at(''), label: 'Dashboard', icon: 'overview', cap: 'vox.phone_system.view', end: true },
    { to: at('/users'), label: 'Users', icon: 'people', cap: 'vox.phone_system.view' },
    { to: at('/phones'), label: 'Phones', icon: 'deskphone', cap: 'vox.phone_system.view' },
    { to: at('/numbers'), label: 'Numbers', icon: 'numbers', cap: 'vox.phone_system.view' },
    { to: at('/call-flows'), label: 'Call flows', icon: 'flows', cap: 'vox.phone_system.view' },
    { to: at('/sites'), label: 'Sites', icon: 'sites', cap: 'vox.phone_system.view' },
    { to: at('/phone-system'), label: 'Phone system', icon: 'history', cap: 'vox.phone_system.view' },
    { to: at('/my-phone'), label: 'My phone', icon: 'phone', cap: 'vox.self.manage' },
  ]
  const visible = items.filter((i) => !i.cap || can(i.cap))
  // An admin has both; the self-service page is for people who have nothing else.
  const trimmed = visible.some((i) => i.to === at('')) ? visible.filter((i) => i.to !== at('/my-phone')) : visible
  const groups: NavGroup[] = [{ items: trimmed.map(({ cap: _cap, ...i }) => i) }]
  const footer: NavItem[] = []
  if (current && settingsTabs(can).length > 0) footer.push({ to: at('/settings'), label: 'Settings', icon: 'settings' })
  if (me?.is_staff) footer.push({ to: '/platform', label: 'Platform', icon: 'platform' })
  const who = me?.name || me?.email || 'Account'
  const ends = current?.expires_at ? new Date(current.expires_at) : null

  return (
    <AppShell
      product="PhotonVox"
      home={trimmed[0]?.to ?? '/'}
      apps={current ? {
        current: 'vox', homeUrl: 'https://account.photonind.com/',
        load: async () => loadApps(config.directoryApiUrl, await source.getAccessToken(), current.slug || current.id, siteMatch?.params.siteSlug ?? null),
        // the list is asked for once per organization and site, not again at every re-render (load is a new function each time)
        loadKey: `${current.slug || current.id}/${siteMatch?.params.siteSlug ?? ''}`,
      } : undefined}
      groups={groups}
      footer={footer}
      switcher={!current ? <span className="ph-hint">Photon staff</span> : tenants.length > 1 ? (
        <select aria-label="Customer" className="ph-input" value={current.id}
          onChange={(e) => { const t = tenants.find((x) => x.id === e.target.value); if (t) nav(orgPath(t) + '/') }}>
          {tenants.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
        </select>
      ) : <span className="ph-hint">{current.name}</span>}
      banner={current?.status === 'suspended' ? (
        <div className="ph-banner ph-banner-warning" role="alert">
          This organization’s PhotonVox plan needs attention: new numbers and outside calling beyond the usual are paused. Phones, incoming calls and 911 keep working.
        </div>
      ) : ends ? (
        <div className="ph-banner ph-banner-info" role="status">Your access to {current?.name} ends {ends.toLocaleString()}.</div>
      ) : undefined}
      account={{
        name: who,
        detail: me?.email && me.email !== who ? me.email : undefined,
        actions: [
          { label: 'Manage organization', onClick: () => window.open(DIRECTORY_URL, '_blank', 'noopener') },
          { label: 'Sign out', onClick: () => void signOut() },
        ],
      }}
    >
      <Outlet />
    </AppShell>
  )
}

/** Signed in, but with no access to any organization in PhotonVox. */
function NoOrganization() {
  const { me, signOut } = useAuth()
  return (
    <div className="ph-auth">
      <div className="ph-card">
        <h1>No access to PhotonVox yet</h1>
        <p>{me?.email ? <>You are signed in as <strong>{me.email}</strong>, which</> : <>This account</>} isn’t a member of any organization that has PhotonVox.
          Ask an administrator of your organization, or your Photon partner, to add you, or switch to another account.</p>
        <p className="ph-hint">People and products are managed in <a href={DIRECTORY_URL}>Manage organization</a>.</p>
        <button className="ph-btn ph-btn-secondary" onClick={() => void signOut()}>Sign out</button>
      </div>
    </div>
  )
}
