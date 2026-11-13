// Production check after a deploy (read-only, signs nobody in): signed out at desktop and phone width, a deep link goes straight to PhotonID's
// sign-in form with PhotonVox's callback, without a page of PhotonVox's own and without an iframe.   node scripts/signin-prod-check.mjs <screenshot dir>
import { chromium } from 'playwright-core'
import { homedir } from 'node:os'
import { join } from 'node:path'
const out = process.argv[2]
const browser = await chromium.launch({ executablePath: join(homedir(), '.cache/ms-playwright/chromium-1248/chrome-linux64/chrome'), args: ['--no-sandbox'] })
let bad = 0
for (const [w, h] of [[1440, 900], [390, 844]]) {
  const ctx = await browser.newContext({ viewport: { width: w, height: h } })
  const p = await ctx.newPage()
  const seen = []
  p.on('request', (r) => { if (r.isNavigationRequest() && r.frame() === p.mainFrame()) seen.push(r.url()) })
  await p.goto('https://vox.photonind.com/numbers?site=x#n1')
  await p.waitForURL((u) => u.href.startsWith('https://id.photonind.com/ui/v2/login/'), { timeout: 20000 }).catch(() => {})
  await p.waitForLoadState('networkidle')
  const authz = seen.find((u) => u.startsWith('https://id.photonind.com/oauth/v2/authorize'))
  const own = seen.filter((u) => u.startsWith('https://vox.photonind.com/') && !u.startsWith('https://vox.photonind.com/numbers'))
  const state = authz ? new URL(authz).searchParams : null
  const okk = p.url().startsWith('https://id.photonind.com/ui/v2/login/') && authz && own.length === 0 && state.get('redirect_uri') === 'https://vox.photonind.com/auth/callback'
  console.log(`${okk ? 'ok  ' : 'FAIL'} ${w}x${h}: ${p.url().split('?')[0]}; authorize trips ${seen.filter((u) => u.includes('/oauth/v2/authorize')).length}; app pages besides the deep link: ${own.length}; frames ${p.frames().length}`)
  if (!okk) bad++
  await p.screenshot({ path: join(out, `prod-signed-out-${w}.png`) })
  await ctx.close()
}
await browser.close()
process.exit(bad ? 1 : 0)
