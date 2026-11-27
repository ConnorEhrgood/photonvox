import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import type { Draft, PhoneSystemSummary } from '../api/types'
import { rename, slug, targetText, targetValue, toTarget } from '../components/draft'
import { meWith, OWNER, renderApp, TECH_A, TECH_B } from '../test/helpers'
import { CallFlowsPage } from './CallFlows'
import { NumberStockPage } from './NumberStock'
import { NumbersPage, toE164 } from './Numbers'
import { SitesPage } from './Sites'

const B = '/tenants/t1'
const SITES = [{ id: 's1', slug: 'cw-main', name: 'Main office', address: '', timezone: 'America/New_York' }]
const NONE = () => new Response(JSON.stringify({ detail: { code: 'no_phone_system', detail: 'x' } }), { status: 404 })
const DRAFT: Draft = {
  version: 1,
  sites: { s1: { emergency_location: 'main', emergency_number: '+17245550100', caller_id: '+17245550100', hours: 'office' } },
  hours: { office: { week: { mon: ['08:00-17:00'], fri: ['08:00-12:00', '13:00-17:00'] }, holidays: 'us-federal' } },
  numbers: { '+17245550100': { site: 's1', open: { menu: 'main' }, closed: { voicemail: 'general' } }, '+17245550123': { site: 's1', open: { user: 'u-ada' } } },
  menus: { main: { greeting: 'Thanks for calling.', options: { '1': { group: 'everyone' } }, timeout: { group: 'everyone' } } },
  groups: { everyone: { members: ['u-ada'], strategy: 'simultaneous', ring_seconds: 25, then: { voicemail: 'general' } } },
  users: { 'u-ada': { name: 'Ada Front', site: 's1', extension: '100' }, 'u-ben': { name: 'Ben Office', site: 's1', extension: '101' } },
  boxes: { general: { name: 'General mailbox', email: 'office@example.com' } },
}
const PS = (draft: Draft = DRAFT): PhoneSystemSummary => ({ id: 'ps1', status: 'new', domain: 'd', instance: 'colo-a', published_version: null,
  draft_updated_at: 'x', draft, problems: [], drift: { checked_at: null, changed: 0, missing: 0, extra: [] } })

/** The page as it would be, with the server keeping the last draft saved. */
function withServer(page: React.ReactElement, start: Draft = DRAFT, me = meWith(OWNER)) {
  let current = start
  const saved: Draft[] = []
  const r = renderApp(page, { me, routes: {
    [`GET ${B}/phone-system`]: () => PS(current), [`GET ${B}/sites`]: SITES,
    [`GET ${B}/numbers`]: [{ number: '+17245550100' }, { number: '+17245550111' }, { number: '+17245550123' }],
    [`PUT ${B}/phone-system/draft`]: (body) => { current = (body as { document: Draft }).document; saved.push(current); return PS(current) },
  } })
  return { ...r, saved }
}

describe('the draft helpers', () => {
  it('turn targets to and from one value, words, and slugs', () => {
    expect(targetValue({ group: 'everyone' })).toBe('group:everyone')
    expect(targetValue(null)).toBe('')
    expect(toTarget('menu:main')).toEqual({ menu: 'main' })
    expect(toTarget('')).toBeNull()
    expect(slug('  Front Desk!! ')).toBe('front-desk')
    expect(targetText(DRAFT, { voicemail: 'u-ben' })).toBe('Ben Office’s voicemail')
    expect(targetText(DRAFT, { voicemail: 'general' })).toBe('General mailbox')
    expect(targetText(DRAFT, { user: 'u-x' })).toBe('u-x')
    expect(targetText(DRAFT, null)).toBe('—')
    expect(toE164('(724) 555-0100')).toBe('+17245550100')
    expect(toE164('')).toBe('')
  })
  it('renaming follows every reference, and does nothing for the same name', () => {
    const d = rename(DRAFT, 'group', 'everyone', 'desk')
    expect(d.menus!.main).toEqual({ greeting: 'Thanks for calling.', options: { '1': { group: 'desk' } }, timeout: { group: 'desk' } })
    expect(rename(DRAFT, 'voicemail', 'general', 'office').numbers!['+17245550100'].closed).toEqual({ voicemail: 'office' })
    expect(rename(DRAFT, 'group', 'everyone', 'everyone')).toBe(DRAFT)
    expect(rename({ version: 1 }, 'menu', 'a', 'b')).toEqual({ version: 1, numbers: {}, groups: {}, menus: {} })
  })
})

describe('numbers', () => {
  it('lists numbers by what they ring, adds one and changes another', async () => {
    const { saved } = withServer(<NumbersPage />)
    expect(await screen.findByText('Menu main')).toBeInTheDocument()
    expect(screen.getByText('General mailbox')).toBeInTheDocument()
    expect(screen.getByText('the same, at all hours')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Add a number' }))
    let dialog = await screen.findByRole('dialog', { name: 'Add a number' })
    expect(within(dialog).getAllByRole('option').map((o) => o.textContent)).toContain('+17245550111')
    expect(within(dialog).queryByRole('option', { name: '+17245550100' })).toBeNull()       // already in use
    await userEvent.selectOptions(within(dialog).getByLabelText('Number'), '+17245550111')
    expect(within(dialog).getByRole('button', { name: 'Save' })).toBeDisabled()
    await userEvent.selectOptions(within(dialog).getByLabelText('It rings'), 'group:everyone')
    await userEvent.click(within(dialog).getByLabelText('Something else after hours'))
    await userEvent.selectOptions(within(dialog).getByLabelText('After hours it rings'), 'voicemail:general')
    await userEvent.selectOptions(within(dialog).getByLabelText('Office hours'), 'office')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Save' }))
    expect(await screen.findByText('+17245550111')).toBeInTheDocument()
    expect(saved[0].numbers!['+17245550111']).toEqual({ site: 's1', open: { group: 'everyone' }, closed: { voicemail: 'general' }, hours: 'office' })
    await userEvent.click(screen.getByRole('button', { name: 'Change +17245550123' }))
    dialog = await screen.findByRole('dialog', { name: 'Change +17245550123' })
    expect(within(dialog).getByLabelText('Site (its 911 address and caller ID)')).toHaveDisplayValue('Main office')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Remove +17245550123' }))
    expect(screen.queryByRole('dialog')).toBeNull()
    expect(saved[1].numbers).not.toHaveProperty('+17245550123')
  })

  it('shows what the server refused, and says when there is no phone system', async () => {
    renderApp(<NumbersPage />, { routes: { [`GET ${B}/phone-system`]: PS(), [`GET ${B}/sites`]: SITES, [`GET ${B}/numbers`]: [{ number: '+17245550123' }],
      [`PUT ${B}/phone-system/draft`]: new Response(JSON.stringify({ detail: { code: 'invalid_document', detail: 'x',
        errors: [{ path: 'numbers.+1', message: 'not a North American number' }] } }), { status: 422 }) } })
    await userEvent.click(await screen.findByRole('button', { name: 'Change +17245550123' }))
    const dialog = await screen.findByRole('dialog')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Save' }))
    expect(await within(dialog).findByRole('alert')).toHaveTextContent('numbers.+1: not a North American number')
    renderApp(<NumbersPage />, { routes: { [`GET ${B}/phone-system`]: NONE, [`GET ${B}/sites`]: SITES } })
    expect(await screen.findByText(/has no phone system yet/)).toBeInTheDocument()
  })

  it('without numbers or the right to build, it says so and offers nothing', async () => {
    withServer(<NumbersPage />, { ...DRAFT, numbers: {} }, meWith({ ...OWNER, capabilities: ['vox.phone_system.view'] }))
    expect(await screen.findByText('No numbers yet.')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Add a number' })).toBeNull()
  })
})

describe('call flows', () => {
  it('shows groups, menus, mailboxes and hours in words', async () => {
    withServer(<CallFlowsPage />)
    expect(await screen.findByText(/all at once, 25 s, then General mailbox/)).toBeInTheDocument()
    expect(screen.getByText(/1 → Ring group everyone; no key → Ring group everyone/)).toBeInTheDocument()
    expect(screen.getByText('emails office@example.com')).toBeInTheDocument()
    expect(screen.getByText(/Mon 08:00-17:00; Fri 08:00-12:00, 13:00-17:00; closed on US federal holidays/)).toBeInTheDocument()
  })

  it('renames a ring group, changes who it rings, and the menu follows', async () => {
    const { saved } = withServer(<CallFlowsPage />)
    await userEvent.click(await screen.findByRole('button', { name: 'Change everyone' }))
    const dialog = await screen.findByRole('dialog', { name: 'Ring group everyone' })
    await userEvent.clear(within(dialog).getByLabelText('Name'))
    await userEvent.type(within(dialog).getByLabelText('Name'), 'Front Desk')
    await userEvent.click(within(dialog).getByLabelText('Ben Office (101)'))
    await userEvent.selectOptions(within(dialog).getByLabelText('How'), 'sequence')
    expect(within(dialog).getByLabelText('Ring each phone for (seconds)')).toHaveValue(25)
    await userEvent.selectOptions(within(dialog).getByLabelText('If nobody answers'), '')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Save' }))
    expect(await screen.findByText(/one after another, 25 s each, then hang up/)).toBeInTheDocument()
    expect(saved[0].groups).toEqual({ 'front-desk': { members: ['u-ada', 'u-ben'], strategy: 'sequence', ring_seconds: 25, then: null } })
    expect(saved[0].menus!.main.timeout).toEqual({ group: 'front-desk' })
  })

  it('a menu that ends the call when no key is pressed (an adopted one) says so, and a rename leaves it so', async () => {
    const menus = { main: { greeting: 'recording:MainMenu.wav', options: { 1: { group: 'everyone' } } } }
    const { saved } = withServer(<CallFlowsPage />, { ...DRAFT, menus } as typeof DRAFT)
    expect(await screen.findByText(/1 → Ring group everyone; no key → the call ends/)).toBeInTheDocument()
    await userEvent.click(await screen.findByRole('button', { name: 'Change everyone' }))
    const dialog = await screen.findByRole('dialog', { name: 'Ring group everyone' })
    await userEvent.clear(within(dialog).getByLabelText('Name'))
    await userEvent.type(within(dialog).getByLabelText('Name'), 'Front Desk')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Save' }))
    await screen.findByText(/no key → the call ends/)
    expect(saved[0].menus!.main).toEqual({ greeting: 'recording:MainMenu.wav', options: { 1: { group: 'front-desk' } } })
  })

  it('adds a menu with keys, a mailbox and office hours, and sets a site’s hours', async () => {
    const { saved } = withServer(<CallFlowsPage />, { ...DRAFT, menus: {} })
    const add = async (section: string) => userEvent.click(within(await screen.findByRole('region', { name: section })).getByRole('button', { name: 'Add' }))
    await add('Menus')
    let dialog = await screen.findByRole('dialog', { name: 'New menu' })
    await userEvent.type(within(dialog).getByLabelText('What callers hear'), 'Press 1 for the desk.')
    await userEvent.selectOptions(within(dialog).getByLabelText('Key 1'), 'group:everyone')
    await userEvent.selectOptions(within(dialog).getByLabelText('If no key is pressed'), 'user:u-ada')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Save' }))
    expect(await screen.findByText(/“Press 1 for the desk.”/)).toBeInTheDocument()
    expect(saved[0].menus!.main).toEqual({ greeting: 'Press 1 for the desk.', options: { '1': { group: 'everyone' } }, timeout: { user: 'u-ada' } })
    await add('Shared mailboxes')
    dialog = await screen.findByRole('dialog', { name: 'New shared mailbox' })
    await userEvent.type(within(dialog).getByLabelText('Name'), 'Billing')
    await userEvent.type(within(dialog).getByLabelText('Email new messages to'), 'not-an-email')
    expect(within(dialog).getByRole('button', { name: 'Save' })).toBeDisabled()
    await userEvent.clear(within(dialog).getByLabelText('Email new messages to'))
    await userEvent.click(within(dialog).getByRole('button', { name: 'Save' }))
    expect(saved[1].boxes!.billing).toEqual({ name: 'Billing', email: null })
    await add('Office hours')
    dialog = await screen.findByRole('dialog', { name: 'New office hours' })
    await userEvent.clear(within(dialog).getByLabelText('Name'))
    await userEvent.type(within(dialog).getByLabelText('Name'), 'Weekend')
    await userEvent.type(within(dialog).getByLabelText('Saturday'), '9-5')
    expect(within(dialog).getByText('Not a time span: Saturday.')).toBeInTheDocument()
    await userEvent.clear(within(dialog).getByLabelText('Saturday'))
    await userEvent.type(within(dialog).getByLabelText('Saturday'), '09:00-13:00')
    await userEvent.click(within(dialog).getByLabelText('Closed on US federal holidays'))
    await userEvent.click(within(dialog).getByRole('button', { name: 'Save' }))
    expect(saved[2].hours!.weekend).toEqual({ holidays: 'none', week: { sat: ['09:00-13:00'] } })
    await userEvent.selectOptions(await screen.findByLabelText('Main office: office hours'), 'weekend')
    expect(saved[3].sites!.s1.hours).toBe('weekend')
  })

  it('renames hours with the sites and numbers that use them, removes things, and refuses a taken name', async () => {
    const { saved } = withServer(<CallFlowsPage />, { ...DRAFT, numbers: { ...DRAFT.numbers, '+17245550100': { ...DRAFT.numbers!['+17245550100'], hours: 'office' } } })
    await userEvent.click(await screen.findByRole('button', { name: 'Change office' }))
    let dialog = await screen.findByRole('dialog')
    await userEvent.clear(within(dialog).getByLabelText('Name'))
    await userEvent.type(within(dialog).getByLabelText('Name'), 'week')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Save' }))
    expect(saved[0].sites!.s1.hours).toBe('week')
    expect(saved[0].numbers!['+17245550100'].hours).toBe('week')
    await userEvent.click(await screen.findByRole('button', { name: 'Change main' }))
    dialog = await screen.findByRole('dialog')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Remove main' }))
    expect(saved[1].menus).toEqual({})
    await userEvent.click(await screen.findByRole('button', { name: 'Change general' }))
    dialog = await screen.findByRole('dialog')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Remove general' }))
    expect(saved[2].boxes).toEqual({})
    await userEvent.click(within(await screen.findByRole('region', { name: 'Ring groups' })).getByRole('button', { name: 'Add' }))
    dialog = await screen.findByRole('dialog', { name: 'New ring group' })
    await userEvent.type(within(dialog).getByLabelText('Name'), 'everyone')
    expect(within(dialog).getByText('That name is taken.')).toBeInTheDocument()
    await userEvent.click(within(dialog).getByRole('button', { name: 'Close' }))
    await userEvent.click(await screen.findByRole('button', { name: 'Change everyone' }))
    dialog = await screen.findByRole('dialog')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Remove everyone' }))
    expect(saved[3].groups).toEqual({})
    await userEvent.click(await screen.findByRole('button', { name: 'Change week' }))
    dialog = await screen.findByRole('dialog')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Remove week' }))
    expect(saved[4].hours).toEqual({})
  })

  it('an empty phone system says so, a view-only role cannot change it, and no phone system is explained', async () => {
    withServer(<CallFlowsPage />, { version: 1 }, meWith({ ...OWNER, capabilities: ['vox.phone_system.view'] }))
    expect(await screen.findAllByText('None yet.')).toHaveLength(3)
    expect(screen.getByText('None yet. Everyone also has their own.')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Add' })).toBeNull()
    renderApp(<CallFlowsPage />, { routes: { [`GET ${B}/phone-system`]: NONE, [`GET ${B}/sites`]: SITES } })
    expect(await screen.findByText(/has no phone system yet/)).toBeInTheDocument()
  })
})

describe('the forms’ small paths', () => {
  it('closing each form leaves the draft alone, and the ring time can be changed', async () => {
    const { saved } = withServer(<CallFlowsPage />)
    for (const name of ['Change main', 'Change general', 'Change office']) {
      await userEvent.click(await screen.findByRole('button', { name }))
      await userEvent.click(within(await screen.findByRole('dialog')).getByRole('button', { name: 'Close' }))
    }
    await userEvent.click(await screen.findByRole('button', { name: 'Change everyone' }))
    const dialog = await screen.findByRole('dialog')
    await userEvent.clear(within(dialog).getByLabelText('Ring for (seconds)'))
    await userEvent.type(within(dialog).getByLabelText('Ring for (seconds)'), '40')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Save' }))
    expect(saved).toHaveLength(1)
    expect(saved[0].groups!.everyone.ring_seconds).toBe(40)
  })

  it('a number can move to another site, and its form can be closed', async () => {
    const two = { ...DRAFT, sites: { ...DRAFT.sites, s2: { emergency_location: 'annex', emergency_number: '+17245550123', caller_id: '+17245550123' } } }
    const { saved } = withServer(<NumbersPage />, two)
    await userEvent.click(await screen.findByRole('button', { name: 'Change +17245550123' }))
    expect(await screen.findByRole('option', { name: '+17245550123' })).toBeInTheDocument()
    let dialog = await screen.findByRole('dialog')
    await userEvent.selectOptions(within(dialog).getByLabelText('Site (its 911 address and caller ID)'), 's2')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Save' }))
    expect(saved[0].numbers!['+17245550123'].site).toBe('s2')
    await userEvent.click(await screen.findByRole('button', { name: 'Add a number' }))
    dialog = await screen.findByRole('dialog')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Close' }))
    expect(screen.queryByRole('dialog')).toBeNull()
  })

  it('a failed load is shown', async () => {
    renderApp(<CallFlowsPage />, { routes: { [`GET ${B}/phone-system`]: new Response(JSON.stringify({ detail: 'down' }), { status: 500 }), [`GET ${B}/sites`]: SITES } })
    expect(await screen.findByRole('alert')).toHaveTextContent('down')
  })
})

describe('clone', () => {
  it('an integrator copies another customer’s call flows; errors are shown', async () => {
    let fail = true
    const { calls } = renderApp(<CallFlowsPage />, { me: meWith(TECH_A, TECH_B), routes: {
      [`GET ${B}/phone-system`]: PS(), [`GET ${B}/sites`]: SITES,
      [`POST ${B}/phone-system/draft/clone`]: () => (fail ? (fail = false, new Response(JSON.stringify({ detail: { detail: 'There is no such phone system to copy from.' } }), { status: 404 })) : PS()),
    } })
    await userEvent.click(await screen.findByRole('button', { name: 'Copy from another customer' }))
    const dialog = await screen.findByRole('dialog', { name: 'Copy call flows from another customer' })
    expect(within(dialog).getByLabelText('Customer')).toHaveDisplayValue('Birch Co')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Copy' }))
    expect(await within(dialog).findByRole('alert')).toHaveTextContent('There is no such phone system to copy from.')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Copy' }))
    expect(screen.queryByRole('dialog')).toBeNull()
    expect(calls.filter((c) => c.method === 'POST').map((c) => c.body)).toEqual([{ from_tenant_id: 't2' }, { from_tenant_id: 't2' }])
  })

  it('someone with one customer is not offered it', async () => {
    withServer(<CallFlowsPage />)
    expect(await screen.findByText('Ring groups')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Copy from another customer' })).toBeNull()
  })

  it('the dialog can be closed', async () => {
    renderApp(<CallFlowsPage />, { me: meWith(TECH_A, TECH_B), routes: { [`GET ${B}/phone-system`]: PS(), [`GET ${B}/sites`]: SITES } })
    await userEvent.click(await screen.findByRole('button', { name: 'Copy from another customer' }))
    await userEvent.click(within(await screen.findByRole('dialog')).getByRole('button', { name: 'Close' }))
    expect(screen.queryByRole('dialog')).toBeNull()
  })
})

describe('sites set up for phones', () => {
  const TWO = [...SITES, { id: 's2', slug: 'cw-annex', name: 'Annex', address: '', timezone: 'America/New_York' }]
  const E = { locations: [{ id: 'l1', site_id: 's1', key: 'main', address: {}, status: 'validated', note: '' },
    { id: 'l9', site_id: 's9', key: 'x', address: {}, status: 'rejected', note: 'No such street' }], numbers: [], requests: [] }

  it('a second site gets its 911 address, the numbers it shows and its hours', async () => {
    let current = DRAFT
    const saved: Draft[] = []
    const { calls } = renderApp(<SitesPage />, { routes: {
      [`GET ${B}/sites`]: TWO, [`GET ${B}/phone-system`]: () => PS(current), [`GET ${B}/emergency`]: E,
      [`POST ${B}/sites/s2/emergency-locations`]: { id: 'l2', key: 'main', status: 'pending' },
      [`PUT ${B}/phone-system/draft`]: (body) => { current = (body as { document: Draft }).document; saved.push(current); return PS(current) },
    } })
    expect(await screen.findByText('Validated')).toBeInTheDocument()
    expect(screen.getByText('911 shows +17245550100')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Set up Annex for phones' }))
    const dialog = await screen.findByRole('dialog', { name: 'Annex: phones' })
    expect(within(dialog).getByRole('button', { name: 'Save' })).toBeDisabled()
    await userEvent.type(within(dialog).getByLabelText('Street'), '2 Mill Road')
    await userEvent.type(within(dialog).getByLabelText('City'), 'Asheville')
    await userEvent.type(within(dialog).getByLabelText('State'), 'nc')
    await userEvent.type(within(dialog).getByLabelText('ZIP code'), '28801')
    await userEvent.selectOptions(within(dialog).getByLabelText('A 911 call from here shows'), '+17245550123')
    await userEvent.selectOptions(within(dialog).getByLabelText('Other calls show'), '+17245550123')
    await userEvent.selectOptions(within(dialog).getByLabelText('Office hours'), 'office')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Save' }))
    expect(await screen.findByText('911 shows +17245550123')).toBeInTheDocument()
    expect(calls.find((c) => c.path.endsWith('/s2/emergency-locations'))!.body).toEqual({ key: 'main', street: '2 Mill Road', unit: '', city: 'Asheville', state: 'NC', zip: '28801' })
    expect(saved[0].sites!.s2).toEqual({ emergency_location: 'main', emergency_number: '+17245550123', caller_id: '+17245550123', hours: 'office' })
  })

  it('a site with an address already keeps it; a site with no numbers yet is told; a failure is shown', async () => {
    renderApp(<SitesPage />, { routes: {
      [`GET ${B}/sites`]: TWO, [`GET ${B}/phone-system`]: PS({ ...DRAFT, numbers: {} }), [`GET ${B}/emergency`]: E,
      [`PUT ${B}/phone-system/draft`]: new Response(JSON.stringify({ detail: 'refused' }), { status: 500 }),
    } })
    await userEvent.click(await screen.findByRole('button', { name: 'Set up Main office for phones' }))
    let dialog = await screen.findByRole('dialog')
    expect(within(dialog).getByText(/Its emergency address is set/)).toBeInTheDocument()
    expect(within(dialog).getByText(/Add the site’s numbers first/)).toBeInTheDocument()
    await userEvent.click(within(dialog).getByRole('button', { name: 'Close' }))
    await userEvent.click(screen.getByRole('button', { name: 'Set up Annex for phones' }))
    dialog = await screen.findByRole('dialog')
    expect(within(dialog).getByRole('button', { name: 'Save' })).toBeDisabled()
  })

  it('an address that cannot be added says why', async () => {
    renderApp(<SitesPage />, { routes: {
      [`GET ${B}/sites`]: TWO, [`GET ${B}/phone-system`]: PS(), [`GET ${B}/emergency`]: { ...E, locations: [] },
      [`POST ${B}/sites/s1/emergency-locations`]: new Response(JSON.stringify({ detail: 'zip: invalid' }), { status: 422 }),
    } })
    await userEvent.click(await screen.findByRole('button', { name: 'Set up Main office for phones' }))
    const dialog = await screen.findByRole('dialog')
    for (const [label, v] of [['Street', '1 A St'], ['City', 'X'], ['State', 'PA'], ['ZIP code', '15222']]) await userEvent.type(within(dialog).getByLabelText(label), v)
    await userEvent.click(within(dialog).getByRole('button', { name: 'Save' }))
    expect(await within(dialog).findByRole('alert')).toHaveTextContent('zip: invalid')
  })
})

describe('the greetings’ voice', () => {
  it('is chosen for the whole phone system and saved with the draft', async () => {
    const { saved } = withServer(<CallFlowsPage />)
    expect(await screen.findByLabelText('Greetings are spoken in')).toHaveDisplayValue('Kore (US English, female)')
    await userEvent.selectOptions(screen.getByLabelText('Greetings are spoken in'), 'es-US-Chirp3-HD-Kore')
    expect(saved[0].voice).toBe('es-US-Chirp3-HD-Kore')
  })
})

describe('number stock (Photon staff)', () => {
  it('adds a number to an organization, puts one back in stock, gives one back to the carrier', async () => {
    let list = [{ number: '+17245550100', tenant_id: 't1', organization: 'Cedar Works', carrier: 'htc', note: '' },
      { number: '+17245550199', tenant_id: null, organization: null, carrier: 'htc', note: '' }]
    const { calls } = renderApp(<NumberStockPage />, { routes: {
      'GET /platform/numbers': () => list, 'GET /platform/organizations': [{ id: 't1', name: 'Cedar Works', status: 'active', plan_key: '', home_region: 'us-east', partner_id: null }],
      'PUT /platform/numbers/%2B17245550111': () => { list = [...list, { number: '+17245550111', tenant_id: 't1', organization: 'Cedar Works', carrier: 'htc', note: '' }]; return {} },
      'PUT /platform/numbers/%2B17245550100': {}, 'DELETE /platform/numbers/%2B17245550199': null,
    } })
    expect(await screen.findByText('Photon’s stock')).toBeInTheDocument()
    await userEvent.type(screen.getByLabelText('Number'), '(724) 555-0111')
    await userEvent.selectOptions(screen.getByLabelText('Assign to'), 't1')
    await userEvent.click(screen.getByRole('button', { name: 'Save' }))
    expect(await screen.findByText('+17245550111')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Back to stock: +17245550100' }))
    await userEvent.click(screen.getByRole('button', { name: 'Give +17245550199 back to the carrier' }))
    expect(calls.filter((c) => c.method !== 'GET').map((c) => [c.method, c.path, c.body])).toEqual([
      ['PUT', '/platform/numbers/%2B17245550111', { tenant_id: 't1' }], ['PUT', '/platform/numbers/%2B17245550100', { tenant_id: null }],
      ['DELETE', '/platform/numbers/%2B17245550199', undefined]])
  })

  it('an empty stock and a refusal are shown', async () => {
    renderApp(<NumberStockPage />, { routes: { 'GET /platform/numbers': [], 'GET /platform/organizations': [],
      'PUT /platform/numbers/%2B17245550100': new Response(JSON.stringify({ detail: { detail: 'A North American number in +1 form.' } }), { status: 422 }) } })
    expect(await screen.findByText('No numbers yet.')).toBeInTheDocument()
    await userEvent.type(screen.getByLabelText('Number'), '724-555-0100')
    await userEvent.click(screen.getByRole('button', { name: 'Save' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('A North American number in +1 form.')
  })
})

describe('doors', () => {
  it('adds a door that rings a group (never a menu or voicemail), changes it, and keeps it when the group is renamed', async () => {
    const { saved } = withServer(<CallFlowsPage />)
    expect(await screen.findByText(/A door station is a PhotonEntry intercom/)).toBeInTheDocument()
    await userEvent.click(within(screen.getByRole('region', { name: 'Doors' })).getByRole('button', { name: 'Add' }))
    const dialog = await screen.findByRole('dialog', { name: 'New door' })
    const rings = within(dialog).getByLabelText('Rings')
    expect(within(rings).queryByRole('option', { name: 'main' })).toBeNull()                       // a menu would take the "#"
    expect(within(rings).queryByRole('option', { name: 'General mailbox' })).toBeNull()
    await userEvent.type(within(dialog).getByLabelText('Name'), 'Front door')
    await userEvent.type(within(dialog).getByLabelText('Extension'), '100')
    expect(within(dialog).getByText('That extension is taken.')).toBeInTheDocument()               // Ada's
    await userEvent.clear(within(dialog).getByLabelText('Extension'))
    await userEvent.type(within(dialog).getByLabelText('Extension'), '701')
    expect(within(dialog).getByRole('button', { name: 'Save' })).toBeDisabled()                    // rings nobody yet
    await userEvent.selectOptions(rings, 'group:everyone')
    await userEvent.selectOptions(within(dialog).getByLabelText("After hours (the site's office hours)"), 'user:u-ben')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Save' }))
    expect(saved[0].doors).toEqual({ 'front-door': { name: 'Front door', site: 's1', extension: '701', open: { group: 'everyone' }, closed: { user: 'u-ben' } } })
    expect(await screen.findByText(/rings .*everyone.*, after hours Ben Office/)).toBeInTheDocument()
    expect(rename(saved[0], 'group', 'everyone', 'desk').doors!['front-door'].open).toEqual({ group: 'desk' })
    await userEvent.click(screen.getByRole('button', { name: 'Change front-door' }))
    const again = await screen.findByRole('dialog', { name: 'Door Front door' })
    await userEvent.click(within(again).getByRole('button', { name: 'Remove front-door' }))
    expect(saved[1].doors).toEqual({})
  })
})

describe('paging', () => {
  it('adds a paging group of one site’s phones, refuses a taken extension, changes and removes it', async () => {
    const { saved } = withServer(<CallFlowsPage />)
    expect(await screen.findByText(/A paging group speaks through several phones/)).toBeInTheDocument()
    await userEvent.click(within(screen.getByRole('region', { name: 'Paging' })).getByRole('button', { name: 'Add' }))
    const dialog = await screen.findByRole('dialog', { name: 'New paging group' })
    await userEvent.type(within(dialog).getByLabelText('Name'), 'Office paging')
    await userEvent.type(within(dialog).getByLabelText('Extension to dial'), '101')
    expect(within(dialog).getByText('That extension is taken.')).toBeInTheDocument()               // Ben's
    await userEvent.clear(within(dialog).getByLabelText('Extension to dial'))
    await userEvent.type(within(dialog).getByLabelText('Extension to dial'), '290')
    expect(within(dialog).getByRole('button', { name: 'Save' })).toBeDisabled()                    // speaks through nobody yet
    expect(within(dialog).queryByLabelText(/Cy Annex/)).toBeNull()                                 // only this site's phones
    await userEvent.click(within(dialog).getByLabelText(/Ada Front/))
    await userEvent.click(within(dialog).getByLabelText(/Ben Office/))
    await userEvent.click(within(dialog).getByRole('button', { name: 'Save' }))
    expect(saved[0].pages).toEqual({ 'office-paging': { name: 'Office paging', site: 's1', extension: '290', members: ['u-ada', 'u-ben'] } })
    expect(await screen.findByText(/Ada Front, Ben Office/)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Change office-paging' }))
    const again = await screen.findByRole('dialog', { name: 'Paging Office paging' })
    await userEvent.click(within(again).getByRole('button', { name: 'Remove office-paging' }))
    expect(saved[1].pages).toEqual({})
  })
})
