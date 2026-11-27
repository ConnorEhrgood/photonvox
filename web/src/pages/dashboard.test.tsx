import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import type { Dashboard, HourMix } from '../api/types'
import { meWith, OWNER, renderApp } from '../test/helpers'
import { DashboardPage, versus } from './Dashboard'

const B = '/tenants/t1/dashboard'
const hours = (at: Record<number, Partial<HourMix>> = {}): HourMix[] =>
  Array.from({ length: 24 }, (_, h) => ({ inbound: 0, outbound: 0, internal: 0, ...at[h] }))
const SITES = [{ id: 's1', slug: 'demo-hq', name: 'Headquarters' }, { id: 's2', slug: 'demo-warehouse', name: 'Distribution Center' }]

export const BUSY: Dashboard = {
  published: true, as_of: '2026-11-12T20:30:00Z', timezone: 'America/New_York', site: null, sites: SITES, unavailable: [],
  phone_system: { status: 'ready', version: 4 },
  now: { count: 3, lines: 2, calls: [
    { kind: 'inbound', who: [{ extension: '100', name: 'Reception' }], other: '…0188', number: '+14125550100', state: 'talking', seconds: 95, site: 's1' },
    { kind: 'outbound', who: [{ extension: '103', name: 'Jordan Lee' }], other: '…0190', number: null, state: 'talking', seconds: 20, site: 's1' },
    { kind: 'internal', who: [{ extension: '200', name: 'Shipping desk' }, { extension: '101', name: 'Sam Ortiz' }], other: 'Sam Ortiz', number: null, state: 'ringing', seconds: 3, site: 's2' }] },
  phones: { online: 21, total: 22, devices: 21, offline: [{ extension: '110', name: 'Conference room', site: 's1' }] },
  trunk: { state: 'ok', words: 'Calls in and out are working.', gateways: 1, last_in: '2026-11-12T20:28:00Z', last_out: '2026-11-12T20:29:00Z' },
  today: { calls: 142, minutes: 388, answered: 128, missed: 9, to_voicemail: 5, inbound: 80, outbound: 41, internal: 21, peak_lines: 7,
           by_hour: hours({ 9: { inbound: 12, outbound: 5, internal: 2 }, 10: { inbound: 18, outbound: 7, internal: 3 }, 14: { inbound: 15, outbound: 6 } }) },
  typical: { days: 4, weekday: 'Thursday', by_hour: Array.from({ length: 24 }, (_, h) => (h >= 8 && h < 17 ? 14 : 0)), calls_so_far: 120, minutes_so_far: 380, missed_so_far: 8 },
  busiest: { grid: Array.from({ length: 7 }, (_, d) => Array.from({ length: 24 }, (_, h) => (d < 5 && h >= 8 && h < 17 ? (h === 10 ? 21 : 9) : 0))),
             top: { weekday: 1, hour: 10, calls: 21 } },
  week: { inbound: 520, outbound: 260, internal: 140 },
  emergency: [],
  voicemail: { new: 4, boxes: [{ box: '100', extension: '100', name: 'Reception', new: 3, oldest_new: '2026-11-12T14:00:00Z' }, { box: '9901', extension: null, name: 'Company mailbox', new: 1, oldest_new: null }] },
  numbers: [{ number: '+14125550100', site: 'Headquarters', rings: 'the main menu', closed: 'voicemail (Company mailbox)', calls_today: 61, last_call: '2026-11-12T20:28:00Z' }],
}

const page = (data: Dashboard, more: Record<string, Dashboard> = {}) =>
  renderApp(<DashboardPage />, { me: meWith(OWNER), routes: { [`GET ${B}`]: data, ...Object.fromEntries(Object.entries(more).map(([q, d]) => [`GET ${B}${q}`, d])) } })

describe('the customer dashboard', () => {
  it('shows calls in progress, phones, lines, the outside lines and today at a glance', async () => {
    page(BUSY)
    const now = await screen.findByRole('region', { name: 'Right now' })
    expect(within(now).getByText('3')).toBeInTheDocument()
    expect(within(now).getByText('Reception')).toBeInTheDocument()
    expect(within(now).getByText(/from …0188 on \(412\) 555-0100/)).toBeInTheDocument()
    expect(within(now).getByText('1:35')).toBeInTheDocument()
    expect(within(now).getByText('ringing')).toBeInTheDocument()
    expect(within(now).getByText('21 of 22')).toBeInTheDocument()
    expect(within(now).getByRole('meter', { name: '21 of 22 phones online' })).toBeInTheDocument()
    expect(within(now).getByText(/Offline: Conference room \(110\)/)).toBeInTheDocument()
    expect(within(now).getByText('Calls in and out are working.')).toBeInTheDocument()
    expect(within(now).getByText('Most at once today: 7')).toBeInTheDocument()
    const today = screen.getByRole('region', { name: 'Today' })
    expect(within(today).getByText('142')).toBeInTheDocument()
    expect(within(today).getByText('22 more than a usual Thursday by now')).toBeInTheDocument()
    expect(within(today).getByText(/5 callers left voicemail · 90% answered/)).toBeInTheDocument()
    expect(within(today).getByRole('img', { name: /Calls by hour today: 68 in all, the most at 10 am \(28\)/ })).toBeInTheDocument()
    expect(within(today).getByRole('img', { name: 'Today: 80 incoming, 41 outgoing, 21 inside' })).toBeInTheDocument()
    expect(within(today).getByText('3 new')).toBeInTheDocument()
    expect(screen.getByText('Tuesdays around 10 am')).toBeInTheDocument()
    expect(screen.getByRole('cell', { name: /\(412\) 555-0100/ })).toBeInTheDocument()
    expect(screen.getByText(/after hours: voicemail \(Company mailbox\)/)).toBeInTheDocument()
    expect(screen.getByText(/Phone system up to date/)).toBeInTheDocument()
    expect(screen.queryByRole('alert')).toBeNull()
  })

  it('says a caller no phone has yet (in a menu, leaving a message) is a caller, not ringing', async () => {
    const call = { kind: 'inbound' as const, who: [], other: '…0188', number: null, site: null }
    page({ ...BUSY, now: { ...BUSY.now!, calls: [{ ...call, state: 'talking', seconds: 9 }, { ...call, other: '…0190', state: 'ringing', seconds: 2 }] } })
    const now = await screen.findByRole('region', { name: 'Right now' })
    expect(within(now).getByText('A caller')).toBeInTheDocument()
    expect(within(now).getByText('Ringing in')).toBeInTheDocument()
  })

  it('puts an emergency call today at the top: who, where, and the address given to 911', async () => {
    page({ ...BUSY, emergency: [{ at: '2026-11-12T15:42:00Z', dialed: '911', extension: '101', who: 'Sam Ortiz', site: 'Headquarters',
      address: '1 Example Way, Pittsburgh, PA 15222', answered: true, seconds: 185 }] })
    const alert = await screen.findByRole('alert', { name: 'Emergency calls today' })
    expect(within(alert).getByText('An emergency call today')).toBeInTheDocument()
    expect(alert).toHaveTextContent('10:42 AM: Sam Ortiz (101) dialed 911 at Headquarters. Connected for 3:05.')
    expect(alert).toHaveTextContent('The location given to 911: 1 Example Way, Pittsburgh, PA 15222')
  })

  it('says plainly when the outside lines are in trouble', async () => {
    page({ ...BUSY, trunk: { state: 'trouble', words: 'Outside calls are not getting through since 2026-11-12T20:10:00Z. Photon has been told.', gateways: 1, last_in: null, last_out: null } })
    expect(await screen.findByText('Outside calls are not getting through since 3:10 PM. Photon has been told.')).toBeInTheDocument()
    expect(screen.getByText('Trouble')).toBeInTheDocument()
  })

  it('reads well on a quiet day and when parts are not available yet', async () => {
    page({ ...BUSY, unavailable: ['live', 'voicemail'], now: null, phones: null, voicemail: null,
      trunk: { state: 'unknown', words: 'Calls in and out worked at the last call; the live view of the lines isn’t available yet.', gateways: 0, last_in: null, last_out: null },
      today: { ...BUSY.today!, calls: 0, minutes: 0, answered: 0, missed: 0, to_voicemail: 0, inbound: 0, outbound: 0, internal: 0, peak_lines: 0, by_hour: hours() },
      typical: { days: 0, weekday: 'Tuesday', by_hour: Array(24).fill(0), calls_so_far: null, minutes_so_far: null, missed_so_far: null },
      busiest: { grid: Array.from({ length: 7 }, () => Array(24).fill(0)), top: null }, week: { inbound: 0, outbound: 0, internal: 0 } })
    expect(await screen.findByText('A quiet day so far.')).toBeInTheDocument()
    expect(screen.getByText(/live view of this phone system isn’t switched on yet/)).toBeInTheDocument()
    expect(screen.getAllByText(/Not available yet/).length).toBeGreaterThanOrEqual(2)
    expect(screen.getByText('Not enough calls yet to show a pattern.')).toBeInTheDocument()
    expect(screen.getAllByText('no calls').length).toBe(2)
    expect(screen.queryByText(/than a usual/)).toBeNull()
  })

  it('switches between the whole organization and one site', async () => {
    const { calls } = page(BUSY, { '?site=demo-warehouse': { ...BUSY, site: 's2' } })
    await screen.findByRole('region', { name: 'Right now' })
    expect(screen.getByRole('button', { name: 'All sites' })).toHaveAttribute('aria-current', 'page')
    await userEvent.click(screen.getByRole('button', { name: 'Distribution Center' }))
    expect(await screen.findByRole('heading', { level: 1, name: 'Distribution Center' })).toBeInTheDocument()
    expect(calls.at(-1)?.path).toBe(`${B}?site=demo-warehouse`)
  })

  it('before the phone system runs, says what will be here', async () => {
    page({ published: false, site: null, sites: [] })
    expect(await screen.findByText(/fills in once the phone system is running/)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Set up the phone system' })).toBeInTheDocument()
  })

  it('compares with a usual day in words', () => {
    expect(versus(10, null, 'Monday')).toBeNull()
    expect(versus(10, 11, 'Monday')).toBe('About the same as a usual Monday by now')
    expect(versus(40, 20, 'Monday', ' min')).toBe('20 min more than a usual Monday by now')
    expect(versus(3, 20, 'Monday')).toBe('17 fewer than a usual Monday by now')
  })
})

describe('times on the dashboard', () => {
  it('say which day when not today, in the site’s zone', async () => {
    const { whenIn } = await import('./Dashboard')
    const now = new Date('2026-11-14T16:00:00Z')
    expect(whenIn('2026-11-14T15:10:00Z', 'America/New_York', now)).toBe('10:10 AM')
    expect(whenIn('2026-11-13T23:28:00Z', 'America/New_York', now)).toBe('yesterday 6:28 PM')
    expect(whenIn('2026-11-10T23:28:00Z', 'America/New_York', now)).toBe('Nov 10, 6:28 PM')
    expect(whenIn(null, 'America/New_York', now)).toBeNull()
  })
})
