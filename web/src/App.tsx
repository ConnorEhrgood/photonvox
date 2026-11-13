import { Navigate, Outlet, Route, Routes, useLocation } from 'react-router-dom'
import { useAuth } from './auth/AuthContext'
import { TenantProvider, useTenant } from './auth/TenantContext'
import { isIntegrator, Layout } from './components/Layout'
import { Loading } from './components/ui'
import { CustomersPage } from './pages/Customers'
import { NotForYou, PlatformHub, SettingsHub, SettingsIndex } from './pages/Hubs'
import { CallbackPage, LoginPage } from './pages/Login'
import { Emergency911Page } from './pages/Emergency911'
import { OverviewPage } from './pages/Overview'
import { PlatformOrganizationsPage } from './pages/Platform'
import { SitesPage } from './pages/Sites'
import {
  AlertsPage, AuditPage, CallFlowsPage, ConsolePage, GdmsPage, InstancesPage, MonitorPage, MyPhonePage, NumberStockPage, NumbersPage, PhonesPage,
  TemplatesPage, UpstreamsPage,
} from './pages/Soon'
import { TeamPage } from './pages/Team'
import { UsersPage } from './pages/Users'

function Protected() {
  const { status, error, me, signOut } = useAuth()
  const loc = useLocation()
  if (status === 'loading') return <div className="ph-auth"><Loading what="your session" /></div>
  if (status === 'signedOut') return <Navigate to="/login" replace state={{ from: loc.pathname + loc.search }} />
  if (status === 'pending') return (
    <div className="ph-auth"><div className="ph-card">
      <h1>Setting up your access</h1>
      <p>You have been added, and PhotonVox is still being told. This takes a moment; the page will continue by itself.</p>
      <p className="ph-hint" role="status">Checking…</p>
    </div></div>
  )
  if (status === 'noAccess') return (
    <div className="ph-auth"><div className="ph-card">
      <h1>No access to PhotonVox</h1>
      <p>{me?.email ?? 'This account'} isn’t a member of an organization that has PhotonVox. Ask an administrator of your organization, or your Photon partner, to add you, or sign in with another account.</p>
      <button className="ph-btn ph-btn-secondary" onClick={() => void signOut()}>Sign out</button>
    </div></div>
  )
  if (status === 'error') return <div className="ph-auth"><div className="ph-card"><h1>Something went wrong</h1><p className="ph-error">{error}</p><button className="ph-btn" onClick={() => location.reload()}>Try again</button></div></div>
  return (
    <TenantProvider>
      <Outlet />
    </TenantProvider>
  )
}

/** Where "/" goes: the customer list for an integrator, the customer's overview for its admin, "My phone" for a user. */
export function Home() {
  const { tenants, can } = useTenant()
  if (isIntegrator(tenants)) return <Navigate to="/customers" replace />
  return <Navigate to={can('vox.phone_system.view') ? '/overview' : '/my-phone'} replace />
}

/** A page for people whose role includes `cap`; anyone else following a link there is told so (the API refuses them anyway). */
function Needs({ cap }: { cap: string }) {
  const { can } = useTenant()
  return can(cap) ? <Outlet /> : <NotForYou />
}

function PlatformOnly() {
  const { me } = useAuth()
  return me?.is_platform_admin ? <Outlet /> : <Navigate to="/" replace />
}

export function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/auth/callback" element={<CallbackPage />} />
      <Route element={<Protected />}>
        <Route element={<Layout />}>
          <Route index element={<Home />} />
          <Route path="customers" element={<CustomersPage />} />
          <Route path="my-phone" element={<MyPhonePage />} />
          <Route element={<Needs cap="vox.phone_system.view" />}>
            <Route path="overview" element={<OverviewPage />} />
            <Route path="users" element={<UsersPage />} />
            <Route path="phones" element={<PhonesPage />} />
            <Route path="numbers" element={<NumbersPage />} />
            <Route path="call-flows" element={<CallFlowsPage />} />
            <Route path="sites" element={<SitesPage />} />
            <Route path="monitor" element={<MonitorPage />} />
          </Route>
          <Route path="settings" element={<SettingsHub />}>
            <Route index element={<SettingsIndex />} />
            <Route path="team" element={<TeamPage />} />
            <Route path="templates" element={<TemplatesPage />} />
            <Route path="alerts" element={<AlertsPage />} />
            <Route path="console" element={<ConsolePage />} />
            <Route path="audit" element={<AuditPage />} />
          </Route>
          <Route element={<PlatformOnly />}>
            <Route path="platform" element={<PlatformHub />}>
              <Route index element={<PlatformOrganizationsPage />} />
              <Route path="instances" element={<InstancesPage />} />
              <Route path="911" element={<Emergency911Page />} />
              <Route path="upstreams" element={<UpstreamsPage />} />
              <Route path="gdms" element={<GdmsPage />} />
              <Route path="numbers" element={<NumberStockPage />} />
            </Route>
          </Route>
        </Route>
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}
