#!/usr/bin/env node
// The dashboard's screenshots from saved answers (real ones read from production, or the demo's): the page as it is built here, its API answered
// from a file, at 1440x900 and 390x844. The file: {"org": {"name", "slug"}, "pages": {"": <the whole organization>, "<site slug>": <one site>}}.
//   node scripts/dashboard-shots.mjs <answers.json> <output dir>
// Output stays out of git (real customers' names and numbers). Chromium comes from Playwright's cache, as in screenshots.mjs.
import { spawn } from 'node:child_process'
import { mkdirSync, readFileSync, readdirSync } from 'node:fs'
import { homedir } from 'node:os'
import { join } from 'node:path'
import { chromium } from 'playwright-core'

const [file, out] = process.argv.slice(2)
if (!file || !out) { console.error('usage: dashboard-shots.mjs <answers.json> <output dir>'); process.exit(2) }
const { org, pages } = JSON.parse(readFileSync(file, 'utf8'))
const PORT = 5184
const API = 'http://api.test'
const SIZES = { desktop: { width: 1440, height: 900 }, phone: { width: 390, height: 844 } }
const cache = join(homedir(), '.cache/ms-playwright')
const executablePath = join(cache, readdirSync(cache).find((d) => d.startsWith('chromium_headless_shell')), 'chrome-headless-shell-linux64/chrome-headless-shell')
const ALL = ['vox.phone_system.view', 'vox.phone_system.build', 'vox.site.emergency', 'vox.number.manage', 'vox.members.view', 'vox.self.manage']
const me = { id: 'p1', name: 'Owner', email: 'owner@example.com', is_platform_admin: false,
  tenants: [{ id: 't1', name: org.name, slug: org.slug, former_slugs: [], status: 'active', partner_id: null, role: 'owner', scope: { all: true }, source: 'direct', expires_at: null, capabilities: ALL }] }
const cors = { 'access-control-allow-origin': '*', 'access-control-allow-headers': '*', 'access-control-allow-methods': '*' }

mkdirSync(out, { recursive: true })
const env = { ...process.env, VITE_DIRECTORY_API_URL: 'http://dir.test', VITE_API_URL: API, VITE_OIDC_ISSUER: 'http://idp.test', VITE_OIDC_CLIENT_ID: 'x', VITE_OIDC_AUDIENCE_PROJECT: '1', VITE_DEV_TOKEN_LOGIN: '1' }
const vite = spawn('npx', ['vite', '--port', String(PORT), '--strictPort'], { env, stdio: 'ignore', detached: true })
process.on('exit', () => { try { process.kill(-vite.pid) } catch { /* gone */ } })
for (let i = 0; i < 100; i++) { try { if ((await fetch(`http://localhost:${PORT}/`)).ok) break } catch { /* not up yet */ } await new Promise((r) => setTimeout(r, 200)) }

const browser = await chromium.launch({ executablePath })
try {
  for (const slug of Object.keys(pages)) {
    for (const [size, viewport] of Object.entries(SIZES)) {
      const ctx = await browser.newContext({ viewport, deviceScaleFactor: 1, timezoneId: pages[slug].timezone || 'America/New_York' })
      await ctx.addInitScript(() => sessionStorage.setItem('pv-dev-token', 'screenshot'))
      await ctx.route(`${API}/**`, (r) => {
        if (r.request().method() === 'OPTIONS') return r.fulfill({ status: 204, headers: cors })
        const u = new URL(r.request().url())
        const body = u.pathname === '/me' ? me : u.pathname === '/tenants/t1/dashboard' ? pages[u.searchParams.get('site') ?? ''] ?? pages[''] : null
        return r.fulfill({ status: body ? 200 : 404, contentType: 'application/json', headers: cors, body: JSON.stringify(body ?? { detail: 'no fixture' }) })
      })
      await ctx.route('http://dir.test/**', (r) => r.fulfill({ status: 404, headers: cors, body: '{}' }))
      const page = await ctx.newPage()
      await page.goto(`http://localhost:${PORT}/org/${org.slug}/${slug ? `?site=${slug}` : ''}`)
      await page.waitForTimeout(1200)
      const name = `dashboard-${slug || 'all'}-${size}.png`
      await page.screenshot({ path: join(out, name), fullPage: true })
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)
      console.log(`${name}${overflow > 0 ? `  HORIZONTAL SCROLL ${overflow}px` : ''}`)
      await ctx.close()
    }
  }
} finally {
  await browser.close()
}
process.exit(0)
