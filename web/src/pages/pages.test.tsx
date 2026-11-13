import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Route, Routes } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import { App, Home } from '../App'
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
      <Route path="/overview" element={<p>overview</p>} />
      <Route path="/my-phone" element={<p>my phone</p>} />
      <Route path="/platform" element={<p>platform</p>} />
    </Routes>, { route: '/', me, routes: {} })
  it('goes to the customer list for an integrator', async () => { home(meWith(TECH_A)); expect(await screen.findByText('customers')).toBeInTheDocument() })
  it('goes to the overview for a customer’s admin', async () => { home(); expect(await screen.findByText('overview')).toBeInTheDocument() })
  it('goes to My phone for a user', async () => { home(meWith(USER)); expect(await screen.findByText('my phone')).toBeInTheDocument() })
  it('goes to Platform for Photon staff with no organization', async () => { home({ ...meWith(), is_staff: true }); expect(await screen.findByText('platform')).toBeInTheDocument() })
  it('a platform administrator flag alone is not staff in the app (the API says is_staff)', async () => {
    home({ ...meWith(), is_platform_admin: true }); expect(await screen.findByText('my phone')).toBeInTheDocument()
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
        <Route path="/overview" element={<p>overview</p>} />
      </Routes>, { route: '/customers', me: meWith(TECH_A, TECH_B), routes: {} })
    const rows = await screen.findAllByRole('row')
    expect(rows).toHaveLength(3)
    expect(screen.getAllByText('Admin (partner)')).toHaveLength(2)
    await userEvent.click(screen.getByRole('button', { name: 'Open Birch Co' }))
    expect(await screen.findByText('overview')).toBeInTheDocument()
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
  it('the customer picker switches customers', async () => {
    withShell('/overview', meWith(TECH_A, TECH_B))
    await userEvent.selectOptions(await screen.findByRole('combobox', { name: 'Customer' }), 't2')
    expect((screen.getByRole('combobox', { name: 'Customer' }) as HTMLSelectElement).value).toBe('t2')
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
