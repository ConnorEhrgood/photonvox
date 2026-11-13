import { Navigate, NavLink, Outlet } from 'react-router-dom'
import { useTenant } from '../auth/TenantContext'
import { PageHeader } from '../components/ui'

/** A page title over a row of tabs, one route per tab. Settings and Platform are both this shape. */
function Hub({ title, tabs }: { title: string; tabs: { to: string; label: string; end?: boolean }[] }) {
  return (
    <>
      <PageHeader title={title} />
      <nav className="ph-tabs" aria-label={title}>
        {tabs.map((t) => <NavLink key={t.to} to={t.to} end={t.end}>{t.label}</NavLink>)}
      </nav>
      <Outlet />
    </>
  )
}

/** The Settings tabs this person may use; they follow what the role can do (a user has none). */
export function settingsTabs(can: (capability: string) => boolean): { to: string; label: string }[] {
  const tabs = []
  if (can('vox.members.view')) tabs.push({ to: '/settings/team', label: 'Team' })
  if (can('vox.phone_system.build')) tabs.push({ to: '/settings/templates', label: 'Templates' })
  if (can('vox.phone_system.view')) tabs.push({ to: '/settings/alerts', label: 'Alerts' })
  if (can('vox.console.manage')) tabs.push({ to: '/settings/console', label: 'PhotonConsole connection' })
  if (can('vox.audit.view')) tabs.push({ to: '/settings/audit', label: 'Audit log' })
  return tabs
}

export function SettingsHub() {
  const { can } = useTenant()
  return <Hub title="Settings" tabs={settingsTabs(can)} />
}

export function SettingsIndex() {
  const { can } = useTenant()
  const tabs = settingsTabs(can)
  return tabs.length ? <Navigate to={tabs[0].to} replace /> : <NotForYou />
}

export const PlatformHub = () => (
  <Hub title="Platform" tabs={[
    { to: '/platform', label: 'Organizations', end: true },
    { to: '/platform/instances', label: 'Instances' },
    { to: '/platform/upstreams', label: 'Upstreams' },
    { to: '/platform/gdms', label: 'GDMS' },
    { to: '/platform/numbers', label: 'Number stock' },
  ]} />
)

/** The API says no (404/403) for anything outside a person's role; this is what they see if they follow a link there anyway. */
export function NotForYou() {
  return <div className="ph-empty"><p>Your role doesn’t include this page.</p></div>
}
