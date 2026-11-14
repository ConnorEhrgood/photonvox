import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Route, Routes, useParams } from 'react-router-dom'
import { beforeEach, describe, expect, it } from 'vitest'
import { App, Home, OrgHome } from '../App'
import { OrgRoute } from '../auth/TenantContext'
import { Layout } from '../components/Layout'
import { meWith, OWNER, renderApp, TECH_A, TECH_B, USER } from '../test/helpers'
import { CustomersPage } from './Customers'
import { PlatformOrganizationsPage } from './Platform'
import { SitesPage } from './Sites'
import { TeamPage } from './Team'

const SITES = [{ id: 's1', slug: 'cw-main', name: 'Main office', address: '1 Mill Road', timezone: 'America/New_York' },
  { id: 's2', slug: 'cw-annex', name: 'Annex', address: '', timezone: 'America/New_York' }]

function withShell(route: string, me = meWith(OWNER), routes: Record<string, unknown> = {}) {
  return renderApp(
    <Routes>
      <Route element={<Layout />}>
        <Route path="*" element={<p>page</p>} />
      </Route>
    </Routes>, { route, me, routes })
}

const navNames = () => within(screen.getAllByRole('navigation')[0]).queryAllByRole('link').map((a) => a.textContent)

describe('the sidebar', () => {
  it('an owner sees the phone system’s pages, Settings, and no Customers list', async () => {
    withShell('/overview')
    await screen.findByText('page')
    expect(navNames()).toEqual(expect.arrayContaining(['Overview', 'Users', 'Phones', 'Numbers', 'Call flows', 'Sites', 'Monitor']))
    expect(navNames()).not.toContain('Customers')
    expect(navNames()).not.toContain('My phone')
    expect(screen.getByRole('link', { name: /Settings/ })).toBeInTheDocument()
  })
  it('an integrator gets Customers first and a customer picker', async () => {
    withShell('/customers', meWith(TECH_A, TECH_B))
    await screen.findByText('page')
    expect(navNames()[0]).toMatch(/Customers/)
    expect(screen.getByRole('combobox', { name: 'Customer' })).toBeInTheDocument()
  })
  it('a user sees only their own phone and no Settings', async () => {
    withShell('/my-phone', meWith(USER))
    await screen.findByText('page')
    expect(navNames()).toEqual(['My phone'])
    expect(screen.queryByRole('link', { name: /Settings/ })).toBeNull()
  })
  it('platform staff see Platform', async () => {
    withShell('/overview', { ...meWith(OWNER), is_staff: true })
    await screen.findByText('page')
    expect(screen.getByRole('link', { name: /Platform/ })).toBeInTheDocument()
  })
  it('a restricted organization is told that phones and 911 keep working', async () => {
    withShell('/overview', meWith({ ...OWNER, status: 'suspended' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('911 keep working')
  })
  it('access that ends says when', async () => {
    withShell('/overview', meWith({ ...OWNER, expires_at: '2099-01-01T00:00:00Z' }))
    expect(await screen.findByRole('status')).toHaveTextContent('Your access to Cedar Works ends')
  })
  it('someone with no organization is told so', async () => {
    withShell('/overview', meWith())
    expect(await screen.findByRole('heading', { name: 'No access to PhotonVox yet' })).toBeInTheDocument()
  })
  it('Photon staff with no organization of their own still get the shell, with Platform and nothing else', async () => {
    withShell('/overview', { ...meWith(), is_staff: true })
    await screen.findByText('page')
    expect(screen.getByRole('link', { name: /Platform/ })).toBeInTheDocument()
    expect(screen.getByText('Photon staff')).toBeInTheDocument()
    expect(navNames()).toEqual([])
    expect(screen.queryByRole('heading', { name: 'No access to PhotonVox yet' })).toBeNull()
  })
})

describe('home', () => {
  const home = (me = meWith(OWNER)) => renderApp(
    <Routes>
      <Route path="/" element={<Home />} />
      <Route path="/customers" element={<p>customers</p>} />
      <Route path="/org/:org/" element={<OrgSeen />} />
      <Route path="/platform" element={<p>platform</p>} />
    </Routes>, { route: '/', me, routes: {} })
  beforeEach(() => localStorage.clear())
  it('with one organization, straight into it', async () => { home(); expect(await screen.findByText('org t1')).toBeInTheDocument() })
  it('with several, the one this person last opened in PhotonVox', async () => {
    localStorage.setItem('pg:tenant', 't2'); home(meWith(TECH_A, TECH_B)); expect(await screen.findByText('org t2')).toBeInTheDocument()
  })
  it('with several and none opened yet, the list to choose from', async () => { home(meWith(TECH_A, TECH_B)); expect(await screen.findByText('customers')).toBeInTheDocument() })
  it('a remembered organization this person no longer reaches is not opened', async () => {
    localStorage.setItem('pg:tenant', 'gone'); home(meWith(TECH_A, TECH_B)); expect(await screen.findByText('customers')).toBeInTheDocument()
  })
  it('goes to Platform for Photon staff with no organization', async () => { home({ ...meWith(), is_staff: true }); expect(await screen.findByText('platform')).toBeInTheDocument() })
  it('the address uses the organization’s slug once the directory has sent it', async () => {
    home(meWith({ ...OWNER, slug: 'cedar-works' })); expect(await screen.findByText('org cedar-works')).toBeInTheDocument()
  })
})

function OrgSeen() {
  const { org, orgSlug } = useParams()
  return <p>org {org ?? orgSlug}</p>
}

describe('addresses', () => {
  const CEDAR = { ...OWNER, slug: 'cedar-works', former_slugs: ['cedar'] }
  const app = (route: string, me = meWith(CEDAR)) => renderApp(<App />, { route, me, routes: {
    'GET /tenants/t1/phone-system': null, 'GET /tenants/t1/sites': SITES, 'GET /tenants/t1/members': [] }, bare: true })
  it('an organization’s home in PhotonVox is its overview, or My phone for someone with only their own', async () => {
    const at = (me: ReturnType<typeof meWith>) => renderApp(
      <Routes><Route path="/org/:orgSlug" element={<OrgRoute />}>
        <Route index element={<OrgHome />} /><Route path="overview" element={<p>overview</p>} /><Route path="my-phone" element={<p>my phone</p>} />
      </Route></Routes>, { route: '/org/cedar-works/', me, routes: {} })
    at(meWith(CEDAR))
    expect(await screen.findByText('overview')).toBeInTheDocument()
  })
  it('… and My phone for a user', async () => {
    renderApp(<Routes><Route path="/org/:orgSlug" element={<OrgRoute />}><Route index element={<OrgHome />} />
      <Route path="my-phone" element={<p>my phone</p>} /></Route></Routes>, { route: '/org/cedar-works/', me: meWith({ ...USER, slug: 'cedar-works' }), routes: {} })
    expect(await screen.findByText('my phone')).toBeInTheDocument()
  })
  it('a former slug goes to the same page under the slug it has now', async () => {
    app('/org/cedar/sites')
    expect(await screen.findByRole('heading', { name: 'Sites' })).toBeInTheDocument()
  })
  it('an organization this person cannot reach is a page saying so, never another organization', async () => {
    app('/org/someone-else/overview')
    expect(await screen.findByRole('heading', { name: 'No such organization in PhotonVox' })).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'Cedar Works' })).toBeNull()
  })
  it('an old address without /org/ is the same page in the current organization', async () => {
    app('/sites')
    expect(await screen.findByRole('heading', { name: 'Sites' })).toBeInTheDocument()
  })
  it('a site’s home is that site alone', async () => {
    app(`/org/cedar-works/site/${SITES[1].slug}`)
    expect(await screen.findByRole('heading', { name: SITES[1].name })).toBeInTheDocument()
    expect(screen.queryByText(SITES[0].name)).toBeNull()
  })
  it('a site that is not there says so', async () => {
    app('/org/cedar-works/site/nowhere')
    expect(await screen.findByText('This organization has no site at this address.')).toBeInTheDocument()
  })
  it('an unknown page inside an organization says it is not for them', async () => {
    app('/org/cedar-works/nonsense')
    expect(await screen.findByText('Your role doesn’t include this page.')).toBeInTheDocument()
  })
})

describe('the app’s routes', () => {
  it('a user who follows a link to an admin page is told it is not for them', async () => {
    renderApp(<App />, { route: '/phones', me: meWith(USER), routes: {}, bare: true })
    expect(await screen.findByText('Your role doesn’t include this page.')).toBeInTheDocument()
  })
  it('the platform pages send non-staff home', async () => {
    renderApp(<App />, { route: '/platform/gdms', me: meWith(OWNER), routes: {}, bare: true })
    expect(await screen.findByRole('heading', { name: 'Cedar Works' })).toBeInTheDocument()       // the overview
  })
  it('Settings opens its first tab, and a user has none', async () => {
    renderApp(<App />, { route: '/settings', me: meWith(OWNER), routes: { 'GET /tenants/t1/members': [], 'GET /tenants/t1/sites': SITES }, bare: true })
    expect(await screen.findByRole('heading', { name: 'Team' })).toBeInTheDocument()
  })
  it('Settings for a user says there is nothing for them', async () => {
    renderApp(<App />, { route: '/settings', me: meWith(USER), routes: {}, bare: true })
    expect(await screen.findByText('Your role doesn’t include this page.')).toBeInTheDocument()
  })
})

describe('customers', () => {
  it('lists every customer and opens one', async () => {
    renderApp(
      <Routes>
        <Route path="/customers" element={<CustomersPage />} />
        <Route path="/org/:org/" element={<OrgSeen />} />
      </Routes>, { route: '/customers', me: meWith(TECH_A, TECH_B), routes: {} })
    const rows = await screen.findAllByRole('row')
    expect(rows).toHaveLength(3)
    expect(screen.getAllByText('Admin (partner)')).toHaveLength(2)
    await userEvent.click(screen.getByRole('button', { name: 'Open Birch Co' }))
    expect(await screen.findByText('org t2')).toBeInTheDocument()
  })
  it('a restricted customer says so', async () => {
    renderApp(<CustomersPage />, { me: meWith({ ...TECH_A, status: 'suspended' }), routes: {} })
    expect(await screen.findByText('Restricted')).toBeInTheDocument()
  })
})

describe('sites', () => {
  it('lists the sites with their emergency address not set up yet', async () => {
    renderApp(<SitesPage />, { routes: { 'GET /tenants/t1/sites': SITES } })
    expect(await screen.findByText('Main office')).toBeInTheDocument()
    expect(screen.getAllByText('Not set up')).toHaveLength(2)
  })
  it('says how to add the first site', async () => {
    renderApp(<SitesPage />, { routes: { 'GET /tenants/t1/sites': [] } })
    expect(await screen.findByText(/No sites yet/)).toBeInTheDocument()
  })
})

describe('team', () => {
  const MEMBERS = [
    { person_id: 'p1', name: 'Ada Owner', email: 'ada@example.com', role: 'owner', scope: { all: true }, source: 'direct', pending: false },
    { person_id: 'p2', name: 'Partner support', email: '', role: 'admin', scope: { all: true }, source: 'partner', pending: false },
    { person_id: 'p3', name: 'Ben', email: 'ben@example.com', role: 'user', scope: { sites: ['s2'] }, source: 'direct', pending: true },
  ]
  it('shows who can sign in, partner support included, with their sites', async () => {
    renderApp(<TeamPage />, { routes: { 'GET /tenants/t1/members': MEMBERS, 'GET /tenants/t1/sites': SITES } })
    expect(await screen.findByText('Admin (partner)')).toBeInTheDocument()
    expect(screen.getByText('Invited')).toBeInTheDocument()
    expect(await screen.findByText('Annex')).toBeInTheDocument()
  })
  it('is not for a user', async () => {
    renderApp(<TeamPage />, { me: meWith(USER), routes: { 'GET /tenants/t1/sites': SITES } })
    expect(await screen.findByText('Your role doesn’t include this page.')).toBeInTheDocument()
  })
})

describe('platform', () => {
  const ORGS = [{ id: 'o1', name: 'Cedar Works', status: 'active', plan_key: 'standard', home_region: 'us-east', partner_id: null, products: ['console', 'vox'] },
    { id: 'o2', name: 'Birch Co', status: 'suspended', plan_key: '', home_region: 'us-east', partner_id: null }]
  it('lists the organizations with the other products they have, and the directory copy’s freshness', async () => {
    renderApp(<PlatformOrganizationsPage />, { routes: { 'GET /platform/organizations': ORGS, 'GET /platform/directory': { cursor: 4, last_pull_at: null, last_ok_at: new Date().toISOString(), last_error: null } } })
    expect(await screen.findByText('console')).toBeInTheDocument()
    expect(screen.getByText('Restricted')).toBeInTheDocument()
    expect(await screen.findByText(/Directory copy: up to date/)).toBeInTheDocument()
  })
  it('says when the directory copy cannot be refreshed', async () => {
    renderApp(<PlatformOrganizationsPage />, { routes: { 'GET /platform/organizations': [], 'GET /platform/directory': { cursor: 0, last_pull_at: null, last_ok_at: null, last_error: 'down' } } })
    expect(await screen.findByRole('alert')).toHaveTextContent('It has never succeeded')
    expect(screen.getByText(/No organization has PhotonVox switched on yet/)).toBeInTheDocument()
  })
})

describe('the shell’s controls', () => {
  it('the app switcher asks the directory for this organization and site, with the person’s token', async () => {
    const apps = { home: 'https://account.photonind.com/', organization: { id: 't1', slug: 'cedar-works', name: 'Cedar Works' },
      site: { id: 's2', slug: 'cw-annex', name: 'Annex' },
      apps: [{ key: 'vox', name: 'PhotonVox', state: 'open', url: 'https://vox.photonind.com/org/cedar-works/site/cw-annex/' },
             { key: 'console', name: 'PhotonConsole', state: 'open', url: 'https://console.photonind.com/org/cedar-works/site/cw-annex/' }] }
    const { calls } = renderApp(<Routes><Route path="/org/:orgSlug" element={<OrgRoute />}><Route element={<Layout />}>
      <Route path="*" element={<OrgSeen />} /></Route></Route></Routes>,
      { route: '/org/cedar-works/site/cw-annex/', me: meWith({ ...OWNER, slug: 'cedar-works' }), routes: { 'GET /v1/me/apps': apps } })
    await userEvent.click(await screen.findByRole('button', { name: 'Switch app' }))
    expect(await screen.findByRole('link', { name: /PhotonConsole/ })).toHaveAttribute('href', apps.apps[1].url)
    expect(calls.find((c) => c.path.startsWith('/v1/me/apps'))?.path).toBe('/v1/me/apps?organization=cedar-works&site=cw-annex')
  })
  it('the customer picker goes to the other customer’s address, and the shell follows it', async () => {
    renderApp(<Routes><Route path="/org/:orgSlug" element={<OrgRoute />}><Route element={<Layout />}><Route index element={<OrgSeen />} />
      <Route path="*" element={<OrgSeen />} /></Route></Route></Routes>,
      { route: '/org/t1/overview', me: meWith(TECH_A, TECH_B), routes: {} })
    await userEvent.selectOptions(await screen.findByRole('combobox', { name: 'Customer' }), 't2')
    expect(await screen.findByText('org t2')).toBeInTheDocument()
    expect((screen.getByRole('combobox', { name: 'Customer' }) as HTMLSelectElement).value).toBe('t2')
    expect(screen.getByRole('link', { name: /Phones/ })).toHaveAttribute('href', '/org/t2/phones')
  })
  it('the account menu opens Manage organization and signs out', async () => {
    const opened: string[] = []
    const realOpen = window.open
    window.open = ((u: string) => { opened.push(u); return null }) as typeof window.open
    const { source } = withShell('/overview')
    await screen.findByText('page')
    await userEvent.click(screen.getByRole('button', { name: /Ada Owner/ }))
    await userEvent.click(screen.getByRole('menuitem', { name: 'Manage organization' }))
    expect(opened).toEqual(['https://account.photonind.com'])
    await userEvent.click(screen.getByRole('button', { name: /Ada Owner/ }))
    await userEvent.click(screen.getByRole('menuitem', { name: 'Sign out' }))
    expect(source.signOut).toHaveBeenCalled()
    window.open = realOpen
  })
  it('someone with no organization can sign out', async () => {
    const { source } = withShell('/overview', meWith())
    await userEvent.click(await screen.findByRole('button', { name: 'Sign out' }))
    expect(source.signOut).toHaveBeenCalled()
  })
  it('the Platform hub has its tabs', async () => {
    renderApp(<App />, { route: '/platform/instances', me: { ...meWith(OWNER), is_staff: true }, routes: {}, bare: true })
    expect(await screen.findByRole('heading', { name: 'Instances' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Number stock' })).toBeInTheDocument()
  })
})

describe('words', () => {
  it('a site-limited scope names its sites, and an unknown site is “a site”', async () => {
    const { scopeText } = await import('../api/types')
    expect(scopeText({ sites: ['s1', 'zz'] }, { s1: 'Main office' })).toBe('Main office, a site')
    expect(scopeText({ all: true })).toBe('Whole organization')
  })
  it('a directly granted customer in the list has no “(partner)”', async () => {
    renderApp(<CustomersPage />, { me: meWith(OWNER, { ...OWNER, id: 't2', name: 'Birch Co' }), routes: {} })
    expect(await screen.findAllByText('Owner')).toHaveLength(2)
  })
  it('a directory copy that failed after working says when it last worked', async () => {
    renderApp(<PlatformOrganizationsPage />, { routes: { 'GET /platform/organizations': [], 'GET /platform/directory': { cursor: 3, last_pull_at: null, last_ok_at: new Date().toISOString(), last_error: 'down' } } })
    expect(await screen.findByRole('alert')).toHaveTextContent('Last good pull just now')
  })
  it('a directory copy never pulled says so', async () => {
    renderApp(<PlatformOrganizationsPage />, { routes: { 'GET /platform/organizations': [], 'GET /platform/directory': { cursor: 0, last_pull_at: null, last_ok_at: null, last_error: null } } })
    expect(await screen.findByText('Directory copy: not pulled yet.')).toBeInTheDocument()
  })
})

describe('an invited person with no name yet', () => {
  it('is shown by their email', async () => {
    renderApp(<TeamPage />, { routes: { 'GET /tenants/t1/members': [{ person_id: 'p9', name: '', email: 'new.hire@example.com', role: 'user', scope: { all: true }, source: 'direct', pending: true }], 'GET /tenants/t1/sites': SITES } })
    expect(await screen.findByText('new.hire@example.com', { selector: 'strong' })).toBeInTheDocument()
  })
})
