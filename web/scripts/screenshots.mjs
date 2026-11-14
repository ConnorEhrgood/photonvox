#!/usr/bin/env node
// The screenshot recipe (photon-suite/ARCHITECTURE.md §6): run the dev server, intercept the API with fixtures, screenshot every page at the three
// sizes every page is reviewed at (1440x900, 820x1180, 390x844), then LOOK at them. Output goes to web/screenshots/ (git-ignored).
//   node scripts/screenshots.mjs                 all pages, all sizes
//   node scripts/screenshots.mjs team            only pages whose name contains "team"
// Chromium comes from Playwright's cache (~/.cache/ms-playwright); no Playwright test runner is needed.
import { spawn } from 'node:child_process'
import { existsSync, mkdirSync, readdirSync } from 'node:fs'
import { homedir } from 'node:os'
import { join } from 'node:path'
import { chromium } from 'playwright-core'

const PORT = 5183
const API = 'http://api.test'
const SIZES = { desktop: { width: 1440, height: 900 }, tablet: { width: 820, height: 1180 }, phone: { width: 390, height: 844 } }
const only = process.argv[2]

const cache = join(homedir(), '.cache/ms-playwright')
const shellDir = readdirSync(cache).find((d) => d.startsWith('chromium_headless_shell'))
const executablePath = join(cache, shellDir, 'chrome-headless-shell-linux64/chrome-headless-shell')
if (!existsSync(executablePath)) throw new Error(`no Chromium at ${executablePath}`)

const ALL = ['vox.phone_system.view', 'vox.phone_system.build', 'vox.phone.enroll', 'vox.phone.control', 'vox.site.emergency', 'vox.number.manage',
  'vox.number.port', 'vox.number.release', 'vox.calling.policy', 'vox.forwarding.external', 'vox.console.manage', 'vox.members.view', 'vox.audit.view', 'vox.self.manage']
const ADMIN = ALL.filter((c) => !['vox.number.port', 'vox.number.release', 'vox.calling.policy', 'vox.audit.view'].includes(c))
const tenant = (over = {}) => ({ id: 't1', name: 'Cedar Works', slug: 'cedar-works', former_slugs: [], status: 'active', partner_id: null, role: 'owner', scope: { all: true }, source: 'direct', expires_at: null, capabilities: ALL, ...over })
const tech = (over = {}) => tenant({ role: 'admin', source: 'partner', partner_id: 'pa', capabilities: ADMIN, ...over })
const me = (tenants, extra = {}) => ({ id: 'p1', name: 'Ada Owner', email: 'ada@example.com', is_platform_admin: false, tenants, ...extra })
const SITES = [
  { id: 's1', slug: 'cw-main', name: 'Main office', address: '1 Mill Road, Asheville NC', timezone: 'America/New_York' },
  { id: 's2', slug: 'cw-annex', name: 'Annex', address: '', timezone: 'America/New_York' },
]
const member = (o) => ({ person_id: 'm', name: 'Bo User', email: 'bo@example.com', role: 'user', scope: { all: true }, source: 'direct', pending: false, ...o })
const MEMBERS = [
  member({ person_id: 'm1', name: 'Ada Owner', email: 'ada@example.com', role: 'owner' }),
  member({ person_id: 'm2', name: 'Cy Admin', email: 'cy@example.com', role: 'admin', scope: { sites: ['s1'] } }),
  member({ person_id: 'm5', name: 'Partner support', email: '', role: 'admin', source: 'partner' }),
  member({ person_id: 'm4', name: 'Bo User', scope: { sites: ['s2'] } }),
  member({ person_id: 'm6', name: '', email: 'new.hire@example.com', pending: true }),
]
const ORGS = [
  { id: 'o1', name: 'Cedar Works', status: 'active', plan_key: 'standard', home_region: 'us-east', partner_id: null, products: ['console', 'vox'] },
  { id: 'o2', name: 'Birch Co', status: 'suspended', plan_key: 'standard', home_region: 'us-east', partner_id: null, products: ['vox'] },
]
const ADDR = { street: '1 Mill Road', unit: 'Suite 200', city: 'Asheville', state: 'NC', zip: '28801' }
const user = (name, ext, site = 's1', o = {}) => ({ name, site, extension: ext, ...o })
const PHONE_SYSTEM = {
  id: 'ps1', status: 'ready', domain: 'k3x9q2.sip.photoninfra.xyz', instance: 'colo-a', published_version: 3, draft_updated_at: '2026-11-13T12:00:00Z',
  draft: { version: 1, users: { 'u-ada': user('Ada Front', '100', 's1', { email: 'ada@example.com' }), 'u-ben': user('Ben Office', '101'),
    'u-pat': user('Pat Pastor', '102', 's1', { direct_number: '+17245550123', show: 'direct' }), 'u-cy': user('Cy Annex', '200', 's2') },
  sites: { s1: { emergency_location: 'main', emergency_number: '+17245550100', caller_id: '+17245550100', hours: 'office' },
    s2: { emergency_location: 'annex', emergency_number: '+17245550110', caller_id: '+17245550110', hours: 'office' } },
  hours: { office: { week: { mon: ['08:00-17:00'], tue: ['08:00-17:00'], wed: ['08:00-17:00'], thu: ['08:00-17:00'], fri: ['08:00-12:00', '13:00-17:00'] }, holidays: 'us-federal' } },
  numbers: { '+17245550100': { site: 's1', open: { menu: 'main' }, closed: { voicemail: 'general' } }, '+17245550110': { site: 's2', open: { group: 'annex' } },
    '+17245550123': { site: 's1', open: { user: 'u-pat' } } },
  menus: { main: { greeting: 'Thank you for calling Cedar Works. For the office, press 1. For the pastor, press 2.', options: { 1: { group: 'everyone' }, 2: { user: 'u-pat' } },
    timeout: { group: 'everyone' } } },
  groups: { everyone: { members: ['u-ada', 'u-ben'], strategy: 'simultaneous', ring_seconds: 25, then: { voicemail: 'general' } },
    annex: { members: ['u-cy'], strategy: 'sequence', ring_seconds: 20, then: { voicemail: 'u-cy' } } },
  boxes: { general: { name: 'General mailbox', email: 'office@example.com' } } },
  problems: [], drift: { checked_at: new Date().toISOString(), changed: 0, missing: 0, extra: [] },
}
const ver = (number, state, o = {}) => ({ number, state, note: '', error: '', created_by: 'Tom Tech', created_at: '2026-11-13T12:00:00Z',
  published_at: '2026-11-13T12:01:00Z', checks: { passed: 6, total: 6, failed: [] }, ...o })
const VERSIONS = [ver(3, 'ready', { note: 'restored from version 1' }),
  ver(2, 'failed', { error: '1 of 6 checks failed; the first: inbound +17245550110; version 1 restored',
    checks: { passed: 5, total: 6, failed: [{ kind: 'inbound', number: '+17245550110', expected: ['reached group-annex'], got: null }] } }), ver(1, 'superseded')]
const E911 = { locations: [], requests: [], numbers: [{ number: '+17245550100', status: 'confirmed', location_id: 'l1', confirmed_at: null },
  { number: '+17245550110', status: 'requested', location_id: 'l2', confirmed_at: null }, { number: '+17245550123', status: 'unconfirmed', location_id: 'l1', confirmed_at: null }] }
const TEMPLATES = [{ key: 'ring-everyone', name: 'Small office', description: 'The main number rings everyone in office hours, then the mailbox.' },
  { key: 'front-desk-menu', name: 'Front desk menu', description: 'A short menu in office hours: front desk or a message.' }]
const answers = (who) => ({
  '/me': who === 'pending' ? [503, { detail: { code: 'access_pending', detail: 'x' } }] : who === 'noaccess' ? [403, { detail: { code: 'no_access', detail: 'x' } }]
    : [200, who === 'user' ? me([tenant({ role: 'user', capabilities: ['vox.self.manage'] })], { name: 'Bo User' })
      : who === 'staff' ? me([tenant()], { name: 'Sam Staff', is_platform_admin: true })
      : who === 'tech' ? me([tech(), tech({ id: 't2', name: 'Birch Co', status: 'suspended' }), tech({ id: 't3', name: 'Elm Street Dental' })], { name: 'Tom Tech' })
      : me([tenant()])],
  '/tenants/t1/sites': [200, SITES], '/tenants/t1/members': [200, MEMBERS],
  '/platform/organizations': [200, ORGS],
  '/tenants/t1/phone-system': [200, PHONE_SYSTEM], '/tenants/t1/phone-system/versions': [200, VERSIONS],
  '/tenants/t1/emergency': [200, E911], '/tenants/t1/phone-system/templates': [200, TEMPLATES],
  '/platform/emergency-locations': [200, [{ id: 'l1', organization: 'Elm Street Dental', site_id: 's9', key: 'main', address: ADDR }]],
  '/platform/carrier-requests': [200, [{ id: 'r1', organization: 'Cedar Works', carrier: 'htc', method: 'email', status: 'sent', reference: 'pm-3f2a', created_at: '2026-11-13T12:00:00Z',
    sent_at: new Date(Date.now() - 3 * 3600e3).toISOString(), items: [{ number: '+17245550100', action: 'add', address: ADDR }, { number: '+17245550111', action: 'remove', address: null }],
    email: { subject: '911 address update 1a2b3c4d: Cedar Works (2 numbers)', body: 'Hello,\n\nPlease update the 911 address records for these numbers (Cedar Works):\n\n  Add     +17245550100  at  100 Main St, Asheville, NC 28801\n  Remove  +17245550111  (no longer in service with us)\n' } }]],
  '/platform/directory': [200, { cursor: 12, last_pull_at: null, last_ok_at: new Date().toISOString(), last_error: null }],
})

// [file name, route, who]
const PAGES = [
  ['login', '/login', 'signedout'], ['pending', '/', 'pending'], ['noaccess', '/', 'noaccess'],
  ['customers-tech', '/', 'tech'], ['overview-owner', '/overview', 'owner'], ['phones-owner', '/phones', 'owner'], ['sites', '/sites', 'owner'],
  ['team', '/settings/team', 'owner'], ['myphone-user', '/', 'user'], ['platform-orgs', '/platform', 'staff'], ['platform-gdms', '/platform/gdms', 'staff'],
  ['org-home', '/org/cedar-works/', 'owner'], ['site-home', '/org/cedar-works/site/cw-annex/', 'owner'],
  ['switcher-open', '/org/cedar-works/site/cw-annex/', 'owner', 'Switch app'],
  ['users', '/users', 'owner'], ['numbers', '/numbers', 'owner'], ['call-flows', '/call-flows', 'owner'], ['menu-form', '/call-flows', 'owner', 'Change main'], ['setup-wizard', '/overview', 'owner', 'Start again from a template'], ['platform-911', '/platform/911', 'staff'],
].filter(([name]) => !only || name.includes(only))

mkdirSync('screenshots', { recursive: true })
const DIRECTORY = 'http://dir.test'
const APPS = { home: 'https://account.photonind.com/', organization: { id: 't1', slug: 'cedar-works', name: 'Cedar Works' },
  site: { id: 's2', slug: 'cw-annex', name: 'Annex' },
  apps: [{ key: 'home', name: 'Home', state: 'open', url: 'https://account.photonind.com/' },
         { key: 'vox', name: 'PhotonVox', state: 'open', url: 'https://vox.photonind.com/org/cedar-works/site/cw-annex/' },
         { key: 'console', name: 'PhotonConsole', state: 'open', url: 'https://console.photonind.com/org/cedar-works/site/cw-annex/' },
         { key: 'guard', name: 'PhotonGuard', state: 'not_enabled' }, { key: 'board', name: 'PhotonBoard', state: 'no_access' },
         { key: 'entry', name: 'PhotonEntry', state: 'coming' }] }
const env = { ...process.env, VITE_DIRECTORY_API_URL: DIRECTORY, VITE_API_URL: API, VITE_OIDC_ISSUER: 'http://idp.test', VITE_OIDC_CLIENT_ID: 'x', VITE_OIDC_AUDIENCE_PROJECT: '1', VITE_DEV_TOKEN_LOGIN: '1' }
const vite = spawn('npx', ['vite', '--port', String(PORT), '--strictPort'], { env, stdio: 'ignore', detached: true })
const stop = () => { try { process.kill(-vite.pid) } catch { /* already gone */ } }
process.on('exit', stop)

for (let i = 0; i < 100; i++) { try { if ((await fetch(`http://localhost:${PORT}/`)).ok) break } catch { /* not up yet */ } await new Promise((r) => setTimeout(r, 200)) }
const browser = await chromium.launch({ executablePath })
try {
  for (const [name, route, who, click] of PAGES) {
    for (const [size, viewport] of Object.entries(SIZES)) {
      const ctx = await browser.newContext({ viewport, deviceScaleFactor: 1 })
      if (who !== 'signedout') await ctx.addInitScript(() => sessionStorage.setItem('pv-dev-token', 'screenshot'))
      const table = answers(who)
      await ctx.route(`${API}/**`, async (r) => {
        const path = new URL(r.request().url()).pathname
        const hit = table[path]
        if (r.request().method() === 'OPTIONS') return r.fulfill({ status: 204, headers: { 'access-control-allow-origin': '*', 'access-control-allow-headers': '*', 'access-control-allow-methods': '*' } })
        const [status, body] = hit ?? [404, { detail: 'no fixture' }]
        return r.fulfill({ status, contentType: 'application/json', headers: { 'access-control-allow-origin': '*' }, body: JSON.stringify(body) })
      })
      await ctx.route(`${DIRECTORY}/**`, async (r) => r.request().method() === 'OPTIONS'
        ? r.fulfill({ status: 204, headers: { 'access-control-allow-origin': '*', 'access-control-allow-headers': '*' } })
        : r.fulfill({ status: 200, contentType: 'application/json', headers: { 'access-control-allow-origin': '*' }, body: JSON.stringify(APPS) }))
      const page = await ctx.newPage()
      await page.goto(`http://localhost:${PORT}${route}`)
      await page.waitForTimeout(700)
      if (click) { await page.getByRole('button', { name: click }).click(); await page.waitForTimeout(400) }   // a dialog opened from the page
      await page.screenshot({ path: `screenshots/${name}-${size}.png`, fullPage: true })
      // A page must not scroll sideways at any size (the layout rule); report it rather than hide it.
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)
      if (overflow > 0) console.log(`HORIZONTAL SCROLL ${name} ${size}: ${overflow}px`)
      await ctx.close()
    }
    console.log('shot', name)
  }
} finally {
  await browser.close()
  stop()
}
