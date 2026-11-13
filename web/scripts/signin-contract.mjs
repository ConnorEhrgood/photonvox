// The suite's sign-in contract (photonid docs/SIGNIN-PLAN.md, SIGNIN-BRIEFS.md) end to end for PhotonVox, against the DEV PhotonID on LXC 800,
// modelled on photonid/directory/web/scripts/signin-contract.mjs (which also covers PhotonID's own pages: password reset, authenticator app,
// invitations; they are the same for every product and not repeated here). Screenshots of PhotonVox's sign-in moments at 1440, 820 and 390.
//   npm run build with the dev values below in the environment, then:  node scripts/signin-contract.mjs <output dir>
//     VITE_OIDC_ISSUER=http://10.10.0.80:8085 VITE_OIDC_CLIENT_ID=399486252400836611 VITE_OIDC_AUDIENCE_PROJECT=399486252065226755 VITE_API_URL=https://api.test
// The app is served by `vite preview` on http://localhost:5183 (the dev app's registered origin; localhost is a secure context, so PKCE works) and
// signs in for real; its API is faked inside the browser (https://api.test), so a 401 or a 403 can be forced. One test person is made through
// PhotonID's API (~/keys/zitadel-dev-provisioner.pat) and deleted at the end. Exits 1 on the first thing that is not as expected.
import { spawn } from 'node:child_process'
import { randomBytes } from 'node:crypto'
import { mkdirSync, readFileSync } from 'node:fs'
import { homedir } from 'node:os'
import { join } from 'node:path'
import { chromium } from 'playwright-core'

const out = process.argv[2]
if (!out) { console.error('usage: signin-contract.mjs <output dir>'); process.exit(2) }
mkdirSync(out, { recursive: true })
const ISSUER = process.env.E2E_ISSUER || 'http://10.10.0.80:8085'
const APP = 'http://localhost:5183'
const PAT = readFileSync(join(homedir(), 'keys/zitadel-dev-provisioner.pat'), 'utf8').trim()
const SIZES = [[1440, 900], [820, 1180], [390, 844]]
const run = Date.now().toString(36)
const ok = (what) => console.log(`ok   ${what}`)
const fail = (what) => { console.error(`FAIL ${what}`); process.exitCode = 1; throw new Error(what) }
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

async function zitadel(method, path, body) {
  const r = await fetch(ISSUER + path, { method, headers: { Authorization: `Bearer ${PAT}`, 'Content-Type': 'application/json' }, body: body ? JSON.stringify(body) : undefined })
  const text = await r.text()
  if (!r.ok) throw new Error(`${method} ${path} -> ${r.status} ${text.slice(0, 300)}`)
  return text ? JSON.parse(text) : {}
}
const made = []
async function person(tag, password) {
  const email = `vox-signin-${tag}-${run}@example.test`
  const { userId } = await zitadel('POST', '/v2/users/human', {
    username: email, profile: { givenName: 'Sam', familyName: 'Signin' }, email: { email, isVerified: true }, password: { password, changeRequired: false },
  })
  made.push(userId)
  return { id: userId, email }
}

const preview = spawn('npx', ['vite', 'preview', '--port', '5183', '--strictPort'], { cwd: new URL('..', import.meta.url).pathname, stdio: 'ignore', detached: true })
for (let i = 0; i < 60; i++) { try { if ((await fetch(APP)).ok) break } catch { /* not up yet */ } await sleep(250) }

// What the faked PhotonVox API answers: ok | unauth | forbidden.
let api = 'ok'
let currentEmail = ''
const tenant = { id: 't1', name: 'Cedar Works', status: 'active', partner_id: null, role: 'user', scope: { all: true }, source: 'direct', expires_at: null, capabilities: ['vox.self.manage'] }
const me = () => ({ id: 'p1', name: 'Sam Signin', email: currentEmail, is_platform_admin: false, tenants: [tenant] })

const browser = await chromium.launch({
  executablePath: join(homedir(), '.cache/ms-playwright/chromium-1248/chrome-linux64/chrome'),
  args: ['--no-sandbox', `--unsafely-treat-insecure-origin-as-secure=${new URL(ISSUER).origin}`],
})
async function context(viewport = { width: 1440, height: 900 }) {
  const ctx = await browser.newContext({ viewport })
  await ctx.route('https://api.test/**', (route) => {
    const path = new URL(route.request().url()).pathname
    if (route.request().method() === 'OPTIONS') return route.fulfill({ status: 204, headers: { 'access-control-allow-origin': APP, 'access-control-allow-headers': '*', 'access-control-allow-methods': '*' } })
    const cors = { 'access-control-allow-origin': APP }
    if (api === 'unauth') return route.fulfill({ status: 401, headers: { ...cors, 'www-authenticate': 'Bearer' }, contentType: 'application/json', body: '{"detail":"Invalid token"}' })
    if (api === 'forbidden' && path === '/me') return route.fulfill({ status: 403, headers: cors, contentType: 'application/json', body: '{"detail":{"code":"no_access","detail":"This account has no access to PhotonVox."}}' })
    if (path === '/me') return route.fulfill({ status: 200, headers: cors, contentType: 'application/json', body: JSON.stringify(me()) })
    return route.fulfill({ status: 200, headers: cors, contentType: 'application/json', body: '[]' })
  })
  return ctx
}
/** Every address the tab's main frame asked for, redirects included. */
function watch(page) {
  const seen = []
  page.on('request', (r) => { if (r.isNavigationRequest() && r.frame() === page.mainFrame()) seen.push(r.url()) })
  return seen
}
const authorizeCount = (seen) => seen.filter((u) => u.startsWith(`${ISSUER}/oauth/v2/authorize`)).length
let n = 0
async function shot(page, name) {
  n++
  for (const [w, h] of SIZES) {
    await page.setViewportSize({ width: w, height: h })
    await sleep(250)
    await page.screenshot({ path: join(out, `${String(n).padStart(2, '0')}-${name}-${w}.png`), fullPage: true })
  }
  await page.setViewportSize({ width: 1440, height: 900 })
}
const onLogin = (page, part) => page.waitForURL((u) => u.href.startsWith(`${ISSUER}/ui/v2/login/${part}`), { timeout: 20000 })
async function typeLoginName(page, email) {
  await page.locator('input[name="loginName"], input[autocomplete="username"], input').first().fill(email)
  await page.getByRole('button', { name: 'Continue' }).click()
}
async function skipMfaPrompt(page) {
  await page.waitForLoadState('networkidle')
  if (page.url().includes('/ui/v2/login/mfa/set')) await page.getByRole('button', { name: 'Not now' }).click()
}
const DEEP = '/my-phone?tab=x#h'

try {
  const password = `Pw-${randomBytes(6).toString('hex')}-A1!`
  const sam = await person('sam', password)
  currentEmail = sam.email
  ok(`test person made in PhotonID (${sam.email})`)

  // 1. No sign-in page: a deep link with no session lands straight on PhotonID's form, at desktop and at phone width.
  for (const [w, h] of [[1440, 900], [390, 844]]) {
    const c = await context({ width: w, height: h })
    const p = await c.newPage()
    const seen = watch(p)
    await p.goto(`${APP}${DEEP}`)
    await onLogin(p, 'loginname')
    if (seen.some((u) => u.startsWith(APP) && /\/login(\?|$)/.test(new URL(u).pathname))) fail('the app showed a sign-in page of its own')
    if (authorizeCount(seen) !== 1) fail(`signed out at ${w}: ${authorizeCount(seen)} trips to PhotonID`)
    ok(`signed out at ${w}×${h}: straight from the deep link to PhotonID (no sign-in page)`)
    await c.close()
  }
  const ctx = await context()
  const page = await ctx.newPage()
  await page.goto(`${APP}${DEEP}`)
  await onLogin(page, 'loginname')
  await page.waitForLoadState('networkidle')
  await shot(page, 'sign-in')

  // 2. Password, then back to exactly the deep link.
  await typeLoginName(page, sam.email)
  await onLogin(page, 'password')
  await page.locator('input[type="password"]').first().fill(password)
  await page.getByRole('button', { name: 'Continue' }).click()
  await page.waitForURL((u) => u.href.startsWith(APP) && !u.pathname.startsWith('/auth/'), { timeout: 20000 }).catch(async () => { await skipMfaPrompt(page) })
  if (page.url().includes('/ui/v2/login/mfa/set')) await skipMfaPrompt(page)
  await page.waitForURL(`${APP}${DEEP}`, { timeout: 20000 })
  await page.getByRole('heading', { name: 'My phone' }).waitFor()
  ok(`deep link survived sign-in (${DEEP})`)
  await shot(page, 'signed-in')
  const stored = await page.evaluate(() => ({ local: Object.keys(localStorage), session: Object.keys(sessionStorage) }))
  if (stored.local.some((k) => /oidc|token|auth/i.test(k))) fail(`session data in localStorage: ${stored.local.join(' ')}`)
  if (!stored.session.some((k) => k.startsWith('oidc.user:'))) fail('the session is not in sessionStorage')
  ok('tokens in sessionStorage only')

  // 3. Silent SSO: a new tab (no tokens of its own) is signed in without seeing a PhotonID page.
  const p2 = await ctx.newPage()
  const seen2 = watch(p2)
  await p2.goto(`${APP}/my-phone`)
  await p2.getByRole('heading', { name: 'My phone' }).waitFor({ timeout: 20000 })
  const pages2 = seen2.filter((u) => u.includes('/ui/v2/login/') && !u.includes('/ui/v2/login/login?'))
  if (pages2.length) fail(`silent SSO showed a PhotonID page: ${pages2.join(' ')}`)
  if (authorizeCount(seen2) !== 1) fail(`silent SSO took ${authorizeCount(seen2)} trips to PhotonID`)
  const frames = p2.frames().length
  if (frames !== 1) fail(`the app opened ${frames - 1} iframe(s)`)
  ok('silent SSO: a new tab signed in with one trip to PhotonID, no page shown, no iframe')
  await p2.close()

  // 4. No loop: the API refusing the new token right after sign-in is a page, after exactly one trip to PhotonID.
  api = 'unauth'
  const p3 = await ctx.newPage()
  const seen3 = watch(p3)
  await p3.goto(`${APP}/`)
  await p3.getByRole('heading', { name: "We couldn't sign you in" }).waitFor({ timeout: 20000 })
  await sleep(3000)
  if (authorizeCount(seen3) !== 1) fail(`a 401 after sign-in went to PhotonID ${authorizeCount(seen3)} times (a loop)`)
  ok('401 right after sign-in: the problem page, one trip to PhotonID, no loop')
  await shot(p3, 'sign-in-problem')
  await p3.close()

  // 5. A 403 is a page, never a redirect.
  api = 'forbidden'
  const p4 = await ctx.newPage()
  const seen4 = watch(p4)
  await p4.goto(`${APP}/`)
  await p4.getByRole('heading', { name: 'No access to PhotonVox' }).waitFor({ timeout: 20000 })
  await sleep(2000)
  if (authorizeCount(seen4) !== 1) fail(`a 403 went to PhotonID ${authorizeCount(seen4)} times`)
  ok('403: a "No access to PhotonVox" page with Sign out, no redirect')
  await shot(p4, 'no-access')
  await p4.close()
  api = 'ok'

  // 6. The moment of leaving for PhotonID (held back so it can be seen).
  const ctxWait = await context()
  await ctxWait.route(`${ISSUER}/.well-known/openid-configuration`, async (route) => { await sleep(4000); await route.continue() })
  const p5 = await ctxWait.newPage()
  await p5.goto(`${APP}/`)
  await p5.getByRole('status').filter({ hasText: 'Signing you in' }).waitFor()
  await shot(p5, 'signing-in')
  await ctxWait.close()

  // 7. Sign out: the PhotonID session ends, back through /auth/signed-out to the sign-in form (prompt=login), and a new tab is not signed in silently.
  const seenOut = watch(page)
  await page.reload()
  await page.getByRole('heading', { name: 'My phone' }).waitFor({ timeout: 20000 })
  await page.getByRole('button', { name: /Sam Signin/ }).click()
  await page.getByRole('menuitem', { name: 'Sign out' }).click()
  await onLogin(page, 'loginname')
  if (!seenOut.some((u) => u.startsWith(`${APP}/auth/signed-out`))) fail('sign-out did not come back through /auth/signed-out')
  if (!seenOut.some((u) => u.startsWith(`${ISSUER}/oauth/v2/authorize`) && u.includes('prompt=login'))) fail('after sign-out the sign-in did not ask for prompt=login')
  ok('sign-out: PhotonID session ended, back through /auth/signed-out to the sign-in form (prompt=login)')
  await page.waitForLoadState('networkidle')
  await shot(page, 'after-sign-out')
  const p6 = await ctx.newPage()
  await p6.goto(`${APP}/my-phone`)
  await p6.waitForURL((u) => u.href.startsWith(`${ISSUER}/ui/v2/login/`) && !u.href.includes('/ui/v2/login/login?'), { timeout: 20000 })
  await p6.waitForLoadState('networkidle')
  if (p6.url().startsWith(APP)) fail('after sign-out a new tab was signed in silently')
  ok(`after sign-out a new tab is not signed in silently (PhotonID shows ${new URL(p6.url()).pathname.split('/').pop()})`)
  await p6.close()

  // 8. The old /login address is home: signed out, that is PhotonID.
  const ctxOld = await context()
  const p7 = await ctxOld.newPage()
  await p7.goto(`${APP}/login`)
  await onLogin(p7, 'loginname')
  ok('the old /login address goes straight to PhotonID')
  await ctxOld.close()
  await ctx.close()
} catch (e) {
  if (!process.exitCode) { console.error(`FAIL ${e.message}`); process.exitCode = 1 }
  let i = 0
  for (const c of browser.contexts()) for (const p of c.pages()) {
    await p.screenshot({ path: join(out, `FAILED-${++i}.png`), fullPage: true }).catch(() => {})
    console.error(`  tab ${i}: ${p.url()}`)
  }
} finally {
  for (const id of made) await zitadel('DELETE', `/v2/users/${id}`).catch((e) => console.error(`could not delete ${id}: ${e.message}`))
  console.log(`cleanup: ${made.length} test person(s) deleted`)
  await browser.close()
  try { process.kill(-preview.pid) } catch { preview.kill() }
}
