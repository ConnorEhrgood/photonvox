import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import type { EmergencyState, PhoneSystemSummary, Version } from '../api/types'
import { meWith, OWNER, renderApp, USER } from '../test/helpers'
import { Emergency911Page } from './Emergency911'
import { OverviewPage } from './Overview'
import { UsersPage } from './Users'

const B = '/tenants/t1'
const SITES = [{ id: 's1', slug: 'cw-main', name: 'Main office', address: '', timezone: 'America/New_York' }, { id: 's2', slug: 'cw-annex', name: 'Annex', address: '', timezone: 'America/New_York' }]
const NONE = new Response(JSON.stringify({ detail: { code: 'no_phone_system', detail: 'This organization has no phone system yet.' } }), { status: 404 })
const PS = (over: Partial<PhoneSystemSummary> = {}): PhoneSystemSummary => ({
  id: 'ps1', status: 'new', domain: 'k3x9q2.sip.photoninfra.xyz', instance: 'colo-a', published_version: null, draft_updated_at: '2026-11-13T12:00:00Z',
  draft: { version: 1, users: { 'u-ada': { name: 'Ada Front', site: 's1', extension: '100', email: 'ada@example.com' },
    'u-pat': { name: 'Pat Pastor', site: 's2', extension: '102', direct_number: '+17245550123', show: 'direct' } },
  numbers: { '+17245550100': { site: 's1', open: { group: 'everyone' } } }, groups: { everyone: { members: ['u-ada'] } } },
  problems: [], drift: { checked_at: null, changed: 0, missing: 0, extra: [] }, ...over,
})
const V = (n: number, state: Version['state'], over: Partial<Version> = {}): Version => ({
  number: n, state, note: '', error: '', created_by: 'Tech', created_at: '2026-11-13T12:00:00Z', published_at: null,
  checks: { passed: 4, total: 4, failed: [] }, ...over,
})
const E911: EmergencyState = { locations: [], numbers: [{ number: '+17245550100', status: 'unconfirmed', location_id: 'l1', confirmed_at: null },
  { number: '+17245550111', status: 'confirmed', location_id: 'l1', confirmed_at: '2026-11-13T12:00:00Z' }], requests: [] }

describe('the overview', () => {
  it('offers to set up a phone system, and the wizard builds it from a template and pasted people', async () => {
    let created = false
    let filled = false
    const { calls } = renderApp(<OverviewPage />, { routes: {
      [`GET ${B}/phone-system`]: () => (filled ? PS() : created ? PS({ draft: { version: 1 } }) : NONE.clone()),
      [`POST ${B}/phone-system`]: () => { created = true; return PS({ draft: { version: 1 } }) },
      [`GET ${B}/phone-system/versions`]: [], [`GET ${B}/emergency`]: { locations: [], numbers: [], requests: [] },
      [`GET ${B}/sites`]: SITES, [`GET ${B}/numbers`]: [{ number: '+17245550100', carrier: 'htc' }],
      [`GET ${B}/phone-system/templates`]: [{ key: 'ring-everyone', name: 'Small office', description: 'Rings everyone.' }, { key: 'front-desk-menu', name: 'Front desk menu', description: 'A menu.' }],
      [`POST ${B}/sites/s1/emergency-locations`]: { id: 'l1', key: 'main', status: 'pending' },
      [`POST ${B}/phone-system/import`]: { rows: [{ line: 1, id: 'u-ada', user: { name: 'Ada', site: 's1', extension: '100' }, problems: [] },
        { line: 2, id: 'u-bo', user: { name: 'Bo', site: 's1', extension: '100' }, problems: ['extension 100 is taken'] }], ready: 1 },
      [`POST ${B}/phone-system/draft/template`]: () => { filled = true; return PS() },
    } })
    await userEvent.click(await screen.findByRole('button', { name: 'Set up the phone system' }))
    const dialog = await screen.findByRole('dialog', { name: 'Set up the phone system' })
    await userEvent.type(within(dialog).getByLabelText('Street'), '100 Main St')
    await userEvent.type(within(dialog).getByLabelText('City'), 'Pittsburgh')
    await userEvent.type(within(dialog).getByLabelText('State'), 'pa')
    await userEvent.type(within(dialog).getByLabelText('ZIP code'), '15222')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Next' }))
    await userEvent.selectOptions(await within(dialog).findByLabelText('Main number'), '+17245550100')
    await userEvent.click(within(dialog).getByRole('radio', { name: /Front desk menu/ }))
    await userEvent.click(within(dialog).getByRole('button', { name: 'Next' }))
    await userEvent.type(within(dialog).getByLabelText(/People, one per line/), 'Ada, 100{enter}Bo, 100')
    expect(within(dialog).getByRole('button', { name: /Create the phone system/ })).toBeDisabled()
    await userEvent.click(within(dialog).getByRole('button', { name: 'Check' }))
    expect(await within(dialog).findByRole('status')).toHaveTextContent('1 ready, 1 with problems (left out)')
    expect(within(dialog).getByText('extension 100 is taken')).toBeInTheDocument()
    await userEvent.click(within(dialog).getByRole('button', { name: 'Create the phone system with 1 person' }))
    expect(await screen.findByRole('button', { name: 'Publish' })).toBeEnabled()
    const address = calls.find((c) => c.path.endsWith('/emergency-locations'))!.body
    expect(address).toMatchObject({ key: 'main', street: '100 Main St', state: 'PA', zip: '15222' })
    expect(calls.find((c) => c.path.endsWith('/draft/template'))!.body).toMatchObject({ template: 'front-desk-menu', site_id: 's1', location: 'main', main_number: '+17245550100' })
  })

  it('a site that already has an address keeps it, and the wizard can go back', async () => {
    const { calls } = renderApp(<OverviewPage />, { routes: {
      [`GET ${B}/phone-system`]: PS({ draft: { version: 1 } }), [`GET ${B}/phone-system/versions`]: [],
      [`GET ${B}/emergency`]: { locations: [{ id: 'l1', site_id: 's2', key: 'annex', address: {}, status: 'validated', note: '' }], numbers: [], requests: [] },
      [`GET ${B}/sites`]: SITES, [`GET ${B}/phone-system/templates`]: [], [`GET ${B}/numbers`]: [],
    } })
    await userEvent.click(await screen.findByRole('button', { name: 'Set up from a template' }))
    const dialog = await screen.findByRole('dialog')
    await userEvent.selectOptions(within(dialog).getByLabelText('Site'), 's2')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Next' }))
    expect(await within(dialog).findByText(/has not assigned this customer any numbers yet/)).toBeInTheDocument()
    await userEvent.click(within(dialog).getByRole('button', { name: 'Back' }))
    expect(within(dialog).getByLabelText('Street')).toBeInTheDocument()
    expect(calls.some((c) => c.method === 'POST')).toBe(false)
  })

  it('shows problems that stop publishing, and the wizard reports errors', async () => {
    renderApp(<OverviewPage />, { routes: {
      [`GET ${B}/phone-system`]: PS({ problems: [{ path: 'sites.s1.emergency_location', code: 'emergency_location_unvalidated', message: 'The emergency address is not validated yet.' }] }),
      [`GET ${B}/phone-system/versions`]: [], [`GET ${B}/emergency`]: { locations: [], numbers: [], requests: [] },
      [`GET ${B}/sites`]: SITES, [`GET ${B}/phone-system/templates`]: [],
      [`POST ${B}/sites/s1/emergency-locations`]: new Response(JSON.stringify({ detail: { detail: 'The address is not complete.' } }), { status: 422 }),
    } })
    expect(await screen.findByText('The emergency address is not validated yet.')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Publish' })).toBeDisabled()
    await userEvent.click(screen.getByRole('button', { name: 'Start again from a template' }))
    const dialog = await screen.findByRole('dialog')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Next' }))
    expect(await within(dialog).findByRole('alert')).toHaveTextContent('The address is not complete.')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Close' }))
    expect(screen.queryByRole('dialog')).toBeNull()
  })

  it('publishes, shows versions with their check, and goes back to an earlier one', async () => {
    let versions = [V(2, 'failed', { error: '1 of 4 checks failed; version 1 restored', note: '',
      checks: { passed: 2, total: 4, failed: [{ kind: 'route', number: '911', expected: ['emergency g1 911'], got: null },
        { kind: 'inbound', number: '+17245550100', expected: ['reached group-everyone'], got: 'reached 100' },
        { kind: 'route', number: '19005550100', expected: ['blocked premium'], got: 'national g1' }] } }), V(1, 'ready', { published_at: '2026-11-13T12:00:00Z' })]
    const { calls } = renderApp(<OverviewPage />, { routes: {
      [`GET ${B}/phone-system`]: PS({ status: 'failed', published_version: 1 }), [`GET ${B}/phone-system/versions`]: () => versions,
      [`GET ${B}/emergency`]: E911,
      [`POST ${B}/phone-system/publish`]: () => { versions = [V(3, 'queued'), ...versions]; return V(3, 'queued') },
      [`POST ${B}/phone-system/versions/1/restore`]: () => V(4, 'queued'),
    } })
    expect(await screen.findByText('Last publish failed')).toBeInTheDocument()
    expect(await screen.findByText('911: should go out the emergency route, dialing 911; went nowhere')).toBeInTheDocument()
    expect(screen.getByText('2 of 4 test calls passed')).toBeInTheDocument()
    expect(screen.getByText('+17245550100: should reach group-everyone; reached 100')).toBeInTheDocument()
    expect(screen.getByText('19005550100: should go blocked (premium); went out the national route, dialing —')).toBeInTheDocument()
    expect(screen.getByText('911 address unconfirmed')).toBeInTheDocument()
    expect(screen.getByText('911 address confirmed')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Publish' }))
    expect(await screen.findByText('Waiting')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Publish' })).toBeDisabled()          // one at a time
    versions = [V(3, 'ready'), V(1, 'superseded')]
    expect(calls.filter((c) => c.method === 'POST').map((c) => c.path)).toEqual([`${B}/phone-system/publish`])
  })

  it('offers to go back to a superseded version', async () => {
    const { calls } = renderApp(<OverviewPage />, { routes: {
      [`GET ${B}/phone-system`]: PS({ status: 'ready', published_version: 2 }), [`GET ${B}/emergency`]: E911,
      [`GET ${B}/phone-system/versions`]: [V(2, 'ready', { note: 'restored from version 1' }), V(1, 'superseded', { checks: { passed: 0, total: 0, failed: [] } })],
      [`POST ${B}/phone-system/versions/1/restore`]: V(3, 'queued'),
    } })
    expect(await screen.findByText('Running')).toBeInTheDocument()
    expect(screen.getByText('restored from version 1')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Go back to version 1' }))
    expect(calls.some((c) => c.path === `${B}/phone-system/versions/1/restore`)).toBe(true)
  })

  it('says when someone changed the engine by hand', async () => {
    renderApp(<OverviewPage />, { routes: {
      [`GET ${B}/phone-system`]: PS({ status: 'changed', published_version: 1, drift: { checked_at: 'x', changed: 1, missing: 2, extra: [{ table: 'v_extensions', uuid: 'u', label: '555' }] } }),
      [`GET ${B}/phone-system/versions`]: [V(1, 'ready')], [`GET ${B}/emergency`]: E911,
    } })
    expect(await screen.findByRole('status')).toHaveTextContent('(1 change, 2 removed)')
    expect(screen.getByText(/left alone: 555/)).toBeInTheDocument()
  })

  it('a person who cannot build sees it without the buttons, and errors are shown', async () => {
    renderApp(<OverviewPage />, { me: meWith({ ...OWNER, capabilities: ['vox.phone_system.view'] }), routes: { [`GET ${B}/phone-system`]: NONE.clone() } })
    expect(await screen.findByText('Your partner or an administrator sets it up.')).toBeInTheDocument()
    renderApp(<OverviewPage />, { routes: { [`GET ${B}/phone-system`]: new Response(JSON.stringify({ detail: 'boom' }), { status: 500 }) } })
    expect(await screen.findByRole('alert')).toHaveTextContent('boom')
  })

  it('a failed start says why', async () => {
    renderApp(<OverviewPage />, { routes: { [`GET ${B}/phone-system`]: NONE.clone(),
      [`POST ${B}/phone-system`]: new Response(JSON.stringify({ detail: { code: 'no_instance', detail: 'No engine is available yet.' } }), { status: 409 }) } })
    await userEvent.click(await screen.findByRole('button', { name: 'Set up the phone system' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('No engine is available yet.')
  })
})

describe('users', () => {
  it('lists the draft’s people and imports more into a group', async () => {
    let added = false
    const { calls } = renderApp(<UsersPage />, { routes: {
      [`GET ${B}/phone-system`]: () => PS(added ? { draft: { ...PS().draft, users: { ...PS().draft.users, 'u-cy': { name: 'Cy', site: 's1', extension: '103' } } } } : {}),
      [`GET ${B}/sites`]: SITES,
      [`POST ${B}/phone-system/import`]: (body) => {
        if ((body as { apply: boolean }).apply) added = true
        return { rows: [{ line: 1, id: 'u-cy', user: { name: 'Cy', site: 's1', extension: '103' }, problems: [] }], ready: 1 }
      },
    } })
    expect(await screen.findByText('Ada Front')).toBeInTheDocument()
    expect(screen.getByText('+17245550123')).toBeInTheDocument()
    expect(screen.getByText('Annex')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Import users' }))
    const dialog = await screen.findByRole('dialog', { name: 'Import users' })
    await userEvent.type(within(dialog).getByLabelText(/One per line/), 'Cy')
    await userEvent.selectOptions(within(dialog).getByLabelText('Site, when a row names none'), 's2')
    expect(within(dialog).getByLabelText('Also add them to')).toHaveValue('everyone')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Check' }))
    await userEvent.click(await within(dialog).findByRole('button', { name: 'Add 1 user' }))
    expect(await screen.findByText('Cy')).toBeInTheDocument()
    expect(calls.filter((c) => c.method === 'POST').map((c) => c.body)).toEqual([
      { text: 'Cy', site_id: 's2', group: 'everyone', apply: false }, { text: 'Cy', site_id: 's2', group: 'everyone', apply: true }])
  })

  it('without a phone system, or without people, says what to do; import errors are shown', async () => {
    renderApp(<UsersPage />, { routes: { [`GET ${B}/phone-system`]: NONE.clone(), [`GET ${B}/sites`]: SITES } })
    expect(await screen.findByText(/has no phone system yet/)).toBeInTheDocument()
    renderApp(<UsersPage />, { routes: { [`GET ${B}/phone-system`]: PS({ draft: { version: 1 } }), [`GET ${B}/sites`]: SITES,
      [`POST ${B}/phone-system/import`]: new Response(JSON.stringify({ detail: 'bad paste' }), { status: 422 }) } })
    expect(await screen.findByText(/No users yet/)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Import users' }))
    const dialog = await screen.findByRole('dialog')
    expect(within(dialog).queryByLabelText('Also add them to')).toBeNull()
    await userEvent.type(within(dialog).getByLabelText(/One per line/), 'x')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Check' }))
    expect(await within(dialog).findByRole('alert')).toHaveTextContent('bad paste')
  })

  it('a user role sees no import button, and a failed load is shown', async () => {
    renderApp(<UsersPage />, { me: meWith({ ...USER, capabilities: ['vox.phone_system.view'] }), routes: { [`GET ${B}/phone-system`]: PS(), [`GET ${B}/sites`]: SITES } })
    expect(await screen.findByText('Ada Front')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Import users' })).toBeNull()
    renderApp(<UsersPage />, { routes: { [`GET ${B}/phone-system`]: new Response(JSON.stringify({ detail: 'down' }), { status: 500 }), [`GET ${B}/sites`]: SITES } })
    expect(await screen.findByRole('alert')).toHaveTextContent('down')
  })
})

describe('the 911 queue (Photon staff)', () => {
  const ADDR = { street: '100 Main St', unit: 'Floor 2', city: 'Pittsburgh', state: 'PA', zip: '15222' }
  it('validates addresses and records the carrier’s answers', async () => {
    let open = true
    const { calls } = renderApp(<Emergency911Page />, { routes: {
      'GET /platform/emergency-locations': () => (open ? [{ id: 'l1', organization: 'Cedar Works', site_id: 's1', key: 'main', address: ADDR }] : []),
      'POST /platform/emergency-locations/l1/validate': () => { open = false; return { id: 'l1', status: 'validated' } },
      'GET /platform/carrier-requests': [
        { id: 'r1', organization: 'Cedar Works', carrier: 'htc', method: 'email', status: 'open', reference: '', created_at: 'x', sent_at: null,
          items: [{ number: '+17245550100', action: 'add', address: ADDR }, { number: '+17245550111', action: 'remove', address: null }],
          email: { subject: '911 address update r1', body: 'Please update' } },
        { id: 'r2', organization: 'Birch Co', carrier: 'htc', method: 'ticket', status: 'sent', reference: 'HTC-1', created_at: 'x', sent_at: '2026-11-13T12:00:00Z',
          items: [], email: { subject: 's', body: 'b' } }],
      'POST /platform/carrier-requests/r1/sent': { id: 'r1', status: 'sent' }, 'POST /platform/carrier-requests/r2/close': { id: 'r2', status: 'confirmed' },
      'POST /platform/carrier-requests/r1/close': new Response(JSON.stringify({ detail: 'There is no such request waiting.' }), { status: 404 }),
    } })
    expect(await screen.findByText(/100 Main St, Floor 2, Pittsburgh, PA 15222/, { selector: 'p' })).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Valid' }))
    expect(await screen.findByText('None waiting.')).toBeInTheDocument()
    expect(screen.getByText('Not sent yet')).toBeInTheDocument()
    expect(screen.getByText('remove +17245550111')).toBeInTheDocument()
    await userEvent.type(screen.getByLabelText('Ticket or note for Cedar Works'), 'HTC-9')
    await userEvent.click(screen.getByRole('button', { name: 'Sent by hand' }))
    const [first, second] = screen.getAllByRole('button', { name: 'Carrier confirmed' })
    await userEvent.click(second)
    await userEvent.click(first)
    expect(await screen.findByRole('alert')).toHaveTextContent('There is no such request waiting.')
    expect(calls.filter((c) => c.method === 'POST').map((c) => [c.path, c.body])).toEqual([
      ['/platform/emergency-locations/l1/validate', { ok: true }],
      ['/platform/carrier-requests/r1/sent', { ok: true, reference: 'HTC-9' }],
      ['/platform/carrier-requests/r2/close', { ok: true, note: '' }],
      ['/platform/carrier-requests/r1/close', { ok: true, note: 'HTC-9' }],
    ])
  })

  it('rejects an address with a note, and a request with the carrier’s reason', async () => {
    const { calls } = renderApp(<Emergency911Page />, { routes: {
      'GET /platform/emergency-locations': [{ id: 'l1', organization: 'Cedar Works', site_id: 's1', key: 'main', address: { ...ADDR, unit: '' } }],
      'POST /platform/emergency-locations/l1/validate': { id: 'l1', status: 'rejected' },
      'GET /platform/carrier-requests': [{ id: 'r1', organization: 'Cedar Works', carrier: 'htc', method: 'email', status: 'sent', reference: '', created_at: 'x', sent_at: null,
        items: [], email: { subject: 's', body: 'b' } }],
      'POST /platform/carrier-requests/r1/close': { id: 'r1', status: 'rejected' },
    } })
    await userEvent.type(await screen.findByLabelText('Note on 100 Main St, Pittsburgh, PA 15222'), 'No such street')
    await userEvent.click(screen.getByRole('button', { name: 'Not valid' }))
    await userEvent.click(screen.getByRole('button', { name: 'Carrier rejected' }))
    expect(screen.getByText(/Sent/)).toBeInTheDocument()
    expect(calls.filter((c) => c.method === 'POST').map((c) => c.body)).toEqual([{ ok: false, note: 'No such street' }, { ok: false, note: '' }])
    renderApp(<Emergency911Page />, { routes: { 'GET /platform/emergency-locations': [], 'GET /platform/carrier-requests': [] } })
    expect(await screen.findByText('Nothing waiting for a carrier.')).toBeInTheDocument()
  })
})
