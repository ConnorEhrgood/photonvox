import { Navigate, Outlet, Route, Routes, useNavigate, useParams } from 'react-router-dom'
import logo from './assets/photon-logo.png'
import { useAuth } from './auth/AuthContext'
import { DevTokenPage } from './auth/DevTokenPage'
import { OrgRoute, orgPath, rememberedTenant, TenantProvider, ToCurrentOrg, useTenant } from './auth/TenantContext'
import { isIntegrator, Layout } from './components/Layout'
import { CustomersPage } from './pages/Customers'
import { DashboardPage } from './pages/Dashboard'
import { NotForYou, PlatformHub, SettingsHub, SettingsIndex } from './pages/Hubs'
import { CallFlowsPage } from './pages/CallFlows'
import { Emergency911Page } from './pages/Emergency911'
import { NumberStockPage } from './pages/NumberStock'
import { NumbersPage } from './pages/Numbers'
import { OverviewPage } from './pages/Overview'
import { PlatformOrganizationsPage } from './pages/Platform'
import { SitesPage } from './pages/Sites'
import {
  AlertsPage, AuditPage, ConsolePage, GdmsPage, InstancesPage, MyPhonePage, PhonesPage,
  TemplatesPage, UpstreamsPage,
} from './pages/Soon'
import { TeamPage } from './pages/Team'
import { UsersPage } from './pages/Users'
import { AccessPending, CallbackRoute, NoAccess, RequireSignIn, SignedOutRoute, SignInProblem, SigningIn } from './ph-auth/pages'
import { EntryPage } from './pages/Entry'

/** Everything but the auth routes needs a session. Signed out: straight to PhotonID with the deep link kept (the suite's sign-in contract, ph-auth).
 *  A 401 just after signing in, and any 403, are pages here: never another redirect. */
function Protected() {
  const { status, error, source, signIn, signOut } = useAuth()
  const out = () => void signOut()
  if (status === 'loading') return <SigningIn logo={logo} title="Loading" hint="Opening PhotonVox." />
  if (status === 'signedOut') {
    if (source.supportsPaste) return <Navigate to="/login" replace /> // development builds: the paste-a-token page
    return <RequireSignIn auth={source.auth!} signedIn={false} logo={logo}>{null}</RequireSignIn>
  }
  if (status === 'problem') return <SignInProblem logo={logo} onRetry={() => void signIn()} onSignOut={out} detail="PhotonID signed you in, but PhotonVox did not accept the sign-in." />
  if (status === 'pending') return <AccessPending logo={logo} product="PhotonVox" onSignOut={out} />
  if (status === 'noAccess') return <NoAccess logo={logo} product="PhotonVox" detail={error} onSignOut={out} />
  if (status === 'error') return <div className="ph-auth"><div className="ph-card"><h1>Something went wrong</h1><p className="ph-error">{error}</p><button className="ph-btn" onClick={() => location.reload()}>Try again</button></div></div>
  return (
    <TenantProvider>
      <Outlet />
    </TenantProvider>
  )
}

/** PhotonID sends the browser here with ?code=…: load the person, then go where they were headed. */
function Callback() {
  const { source, refreshMe } = useAuth()
  const nav = useNavigate()
  if (!source.auth) return <Navigate to="/login" replace />
  return <CallbackRoute auth={source.auth} logo={logo} onSignedIn={async (to) => { await refreshMe(); nav(to, { replace: true }) }} />
}

/** PhotonID's post-logout address: straight on to its sign-in form. */
function SignedOut() {
  const { source } = useAuth()
  if (!source.auth) return <Navigate to="/login" replace />
  return <SignedOutRoute auth={source.auth} logo={logo} />
}

/** Where "/" goes (the dashboard's app tile links here): the organization this person last opened in PhotonVox, else the only one, else the list to
 *  choose from; Platform for Photon staff with no organization of their own. Never a blank page. */
export function Home() {
  const { me } = useAuth()
  const { tenants } = useTenant()
  if (tenants.length === 0 && me?.is_staff) return <Navigate to="/platform" replace />     // Photon staff with no organization of their own
  const last = tenants.find((t) => t.id === rememberedTenant())
  if (last) return <Navigate to={orgPath(last) + '/'} replace />
  if (tenants.length === 1) return <Navigate to={orgPath(tenants[0]) + '/'} replace />
  if (isIntegrator(tenants)) return <Navigate to="/customers" replace />
  return <NotForYou />            // no organization (the shell says so): unreachable through Layout, kept as a guard
}

/** An organization's home in PhotonVox, /org/<slug>/: its phone system's overview, or "My phone" for someone who only has their own. */
export function OrgHome() {
  const { can } = useTenant()
  return can('vox.phone_system.view') ? <DashboardPage /> : <Navigate to="my-phone" replace />
}

/** A site's home, /org/<slug>/site/<site-slug>/: the site set up for phones (its 911 address, numbers and hours). */
function SiteHome() {
  const { siteSlug = '' } = useParams()
  return <SitesPage only={siteSlug} />
}

/** A page for people whose role includes `cap`; anyone else following a link there is told so (the API refuses them anyway). */
function Needs({ cap }: { cap: string }) {
  const { can } = useTenant()
  return can(cap) ? <Outlet /> : <NotForYou />
}

function PlatformOnly() {
  const { me } = useAuth()
  return me?.is_staff ? <Outlet /> : <Navigate to="/" replace />
}

const LEGACY = ['overview', 'phone-system', 'users', 'phones', 'numbers', 'call-flows', 'sites', 'monitor', 'my-phone', 'settings']

export function App() {
  return (
    <Routes>
      {/* `/login` is the development paste-a-token page; in production an old address for home. There is no sign-in page. */}
      <Route path="/login" element={<DevTokenPage />} />
      <Route path="/auth/callback" element={<Callback />} />
      <Route path="/auth/signed-out" element={<SignedOut />} />
      <Route element={<Protected />}>
        {/* An organization's pages live at /org/<slug>/… (the suite's addresses: switching product keeps the organization and site). */}
        <Route path="org/:orgSlug" element={<OrgRoute />}>
          <Route element={<Layout />}>
            <Route index element={<OrgHome />} />
            <Route path="my-phone" element={<MyPhonePage />} />
            <Route element={<Needs cap="vox.phone_system.view" />}>
              <Route path="phone-system" element={<OverviewPage />} />
              <Route path="overview" element={<Navigate to="../phone-system" replace />} />
              <Route path="users" element={<UsersPage />} />
              <Route path="phones" element={<PhonesPage />} />
              <Route path="numbers" element={<NumbersPage />} />
              <Route path="call-flows" element={<CallFlowsPage />} />
              <Route path="sites" element={<SitesPage />} />
              <Route path="site/:siteSlug" element={<SiteHome />} />
              <Route path="monitor" element={<Navigate to=".." replace />} />
            </Route>
            <Route path="settings" element={<SettingsHub />}>
              <Route index element={<SettingsIndex />} />
              <Route path="team" element={<TeamPage />} />
              <Route path="templates" element={<TemplatesPage />} />
              <Route path="alerts" element={<AlertsPage />} />
              <Route path="console" element={<ConsolePage />} />
              <Route path="entry" element={<EntryPage />} />
              <Route path="audit" element={<AuditPage />} />
            </Route>
            <Route path="*" element={<NotForYou />} />
          </Route>
        </Route>
        <Route element={<Layout />}>
          <Route index element={<Home />} />
          <Route path="customers" element={<CustomersPage />} />
          {/* Old addresses (before /org/): the same page in the current organization. */}
          {LEGACY.map((p) => <Route key={p} path={`${p}/*`} element={<ToCurrentOrg />} />)}
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
