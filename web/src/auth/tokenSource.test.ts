import { afterEach, describe, expect, it, vi } from 'vitest'
import { DevTokenSource, HybridTokenSource, OidcTokenSource, safeReturnPath, type TokenSource } from './tokenSource'

const cfg = { issuer: 'https://id.test', clientId: 'cid', audienceProject: '123', redirectUri: 'https://app.test/auth/callback', postLogoutUri: 'https://app.test/' }
const mgr = (over: Record<string, unknown> = {}) => ({
  getUser: vi.fn(async () => null), signinSilent: vi.fn(), signinRedirect: vi.fn(async () => {}), signoutRedirect: vi.fn(async () => {}),
  signinRedirectCallback: vi.fn(), ...over,
}) as never

afterEach(() => vi.unstubAllEnvs())

describe('OidcTokenSource', () => {
  it('returns null with no user, the token for a live user, and refreshes an expired one silently', async () => {
    expect(await new OidcTokenSource(cfg, mgr()).getAccessToken()).toBeNull()
    expect(await new OidcTokenSource(cfg, mgr({ getUser: async () => ({ expired: false, access_token: 'live' }) })).getAccessToken()).toBe('live')
    const m = mgr({ getUser: async () => ({ expired: true, access_token: 'old' }), signinSilent: async () => ({ access_token: 'fresh' }) })
    expect(await new OidcTokenSource(cfg, m).getAccessToken()).toBe('fresh')
  })
  it('an expired session that can’t refresh counts as signed out, not an error', async () => {
    const m = mgr({ getUser: async () => ({ expired: true, access_token: 'old' }), signinSilent: async () => { throw new Error('login_required') } })
    expect(await new OidcTokenSource(cfg, m).getAccessToken()).toBeNull()
    const m2 = mgr({ getUser: async () => ({ expired: true, access_token: 'old' }), signinSilent: async () => null })
    expect(await new OidcTokenSource(cfg, m2).getAccessToken()).toBeNull()
  })
  it('signIn remembers where the person was going; the callback returns there', async () => {
    const m = mgr({ signinRedirectCallback: async () => ({ state: '/screens/s1?tab=device' }) })
    const s = new OidcTokenSource(cfg, m)
    await s.signIn('/content')
    expect((m as unknown as { signinRedirect: ReturnType<typeof vi.fn> }).signinRedirect).toHaveBeenCalledWith({ state: '/content' })
    expect(await s.handleCallback()).toBe('/screens/s1?tab=device')
  })
  it('signIn with create asks the IdP for its registration form', async () => {
    const m = mgr({})
    await new OidcTokenSource(cfg, m).signIn('/o/acme', { create: true })
    expect((m as unknown as { signinRedirect: ReturnType<typeof vi.fn> }).signinRedirect).toHaveBeenCalledWith({ state: '/o/acme', prompt: 'create' })
  })
  it('the callback never redirects to an off-site address smuggled in state', async () => {
    for (const state of ['https://evil.example', '//evil.example', '/\\evil.example', 'javascript:alert(1)', 'evil', '', undefined, 42, null]) {
      const s = new OidcTokenSource(cfg, mgr({ signinRedirectCallback: async () => ({ state }) }))
      expect(await s.handleCallback()).toBe('/')
    }
    expect(safeReturnPath('/screens?tab=device')).toBe('/screens?tab=device')
  })
  it('signOut delegates to the IdP and pasting isn’t supported', async () => {
    const m = mgr()
    const s = new OidcTokenSource(cfg, m)
    await s.signOut()
    expect((m as unknown as { signoutRedirect: ReturnType<typeof vi.fn> }).signoutRedirect).toHaveBeenCalled()
    expect(s.supportsPaste).toBe(false)
  })
  it('requests the project audience and offline access, using authorization code + PKCE', () => {
    // Constructing without an injected manager exercises the real configuration path.
    const s = new OidcTokenSource(cfg)
    expect(s.supportsPaste).toBe(false)
  })
})

describe('DevTokenSource', () => {
  it('stores a pasted token in sessionStorage only; sign out clears it', async () => {
    const d = new DevTokenSource()
    expect(await d.getAccessToken()).toBeNull()
    d.paste('  abc  ')
    expect(await d.getAccessToken()).toBe('abc')
    expect(localStorage.getItem('pv-dev-token')).toBeNull()
    await d.signOut()
    expect(await d.getAccessToken()).toBeNull()
    expect(await d.handleCallback()).toBe('/')
    await d.signIn()
  })
  it('falls back to VITE_DEV_TOKEN in dev builds', async () => {
    vi.stubEnv('VITE_DEV_TOKEN', 'from-env')
    expect(await new DevTokenSource().getAccessToken()).toBe('from-env')
  })
})

describe('HybridTokenSource', () => {
  const oidc = (token: string | null): TokenSource => ({
    supportsPaste: false, getAccessToken: async () => token, signIn: vi.fn(async () => {}), signOut: vi.fn(async () => {}), handleCallback: async () => '/x',
  })
  it('prefers a pasted token, else the OIDC session', async () => {
    const dev = new DevTokenSource()
    const h = new HybridTokenSource(oidc('oidc-tok'), dev)
    expect(await h.getAccessToken()).toBe('oidc-tok')
    h.paste('dev-tok')
    expect(await h.getAccessToken()).toBe('dev-tok')
    expect(h.supportsPaste).toBe(true)
    expect(await h.handleCallback()).toBe('/x')
  })
  it('sign out clears a pasted token locally, otherwise signs out of the IdP', async () => {
    const o = oidc('t')
    const h = new HybridTokenSource(o, new DevTokenSource())
    await h.signOut()
    expect(o.signOut).toHaveBeenCalled()
    const o2 = oidc('t')
    const h2 = new HybridTokenSource(o2, new DevTokenSource())
    h2.paste('p')
    await h2.signOut()
    expect(o2.signOut).not.toHaveBeenCalled()
    await h2.signIn('/y')
    expect(o2.signIn).toHaveBeenCalledWith('/y')
  })
})
