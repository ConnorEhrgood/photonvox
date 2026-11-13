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
const tenant = (over = {}) => ({ id: 't1', name: 'Cedar Works', status: 'active', partner_id: null, role: 'owner', scope: { all: true }, source: 'direct', expires_at: null, capabilities: ALL, ...over })
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
const answers = (who) => ({
  '/me': who === 'pending' ? [503, { detail: { code: 'access_pending', detail: 'x' } }] : who === 'noaccess' ? [403, { detail: { code: 'no_access', detail: 'x' } }]
    : [200, who === 'user' ? me([tenant({ role: 'user', capabilities: ['vox.self.manage'] })], { name: 'Bo User' })
      : who === 'staff' ? me([tenant()], { name: 'Sam Staff', is_platform_admin: true })
      : who === 'tech' ? me([tech(), tech({ id: 't2', name: 'Birch Co', status: 'suspended' }), tech({ id: 't3', name: 'Elm Street Dental' })], { name: 'Tom Tech' })
      : me([tenant()])],
  '/tenants/t1/sites': [200, SITES], '/tenants/t1/members': [200, MEMBERS],
  '/platform/organizations': [200, ORGS],
  '/platform/directory': [200, { cursor: 12, last_pull_at: null, last_ok_at: new Date().toISOString(), last_error: null }],
})

// [file name, route, who]
const PAGES = [
  ['login', '/login', 'signedout'], ['pending', '/', 'pending'], ['noaccess', '/', 'noaccess'],
  ['customers-tech', '/', 'tech'], ['overview-owner', '/overview', 'owner'], ['phones-owner', '/phones', 'owner'], ['sites', '/sites', 'owner'],
  ['team', '/settings/team', 'owner'], ['myphone-user', '/', 'user'], ['platform-orgs', '/platform', 'staff'], ['platform-gdms', '/platform/gdms', 'staff'],
].filter(([name]) => !only || name.includes(only))

mkdirSync('screenshots', { recursive: true })
const env = { ...process.env, VITE_API_URL: API, VITE_OIDC_ISSUER: 'http://idp.test', VITE_OIDC_CLIENT_ID: 'x', VITE_OIDC_AUDIENCE_PROJECT: '1', VITE_DEV_TOKEN_LOGIN: '1' }
const vite = spawn('npx', ['vite', '--port', String(PORT), '--strictPort'], { env, stdio: 'ignore', detached: true })
const stop = () => { try { process.kill(-vite.pid) } catch { /* already gone */ } }
process.on('exit', stop)

for (let i = 0; i < 100; i++) { try { if ((await fetch(`http://localhost:${PORT}/`)).ok) break } catch { /* not up yet */ } await new Promise((r) => setTimeout(r, 200)) }
const browser = await chromium.launch({ executablePath })
try {
  for (const [name, route, who] of PAGES) {
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
      const page = await ctx.newPage()
      await page.goto(`http://localhost:${PORT}${route}`)
      await page.waitForTimeout(700)
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
