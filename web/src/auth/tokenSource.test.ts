import { afterEach, describe, expect, it, vi } from 'vitest'
import type { PhotonSignIn } from '../ph-auth/signin'
import { DevTokenSource, HybridTokenSource, OidcTokenSource, type TokenSource } from './tokenSource'

afterEach(() => vi.unstubAllEnvs())

const fakeAuth = () => ({
  getAccessToken: vi.fn(async () => 'oidc-tok'), signIn: vi.fn(async () => {}), signOut: vi.fn(async () => {}),
  unauthorized: vi.fn(async () => 'problem' as const),
}) as unknown as PhotonSignIn & Record<string, ReturnType<typeof vi.fn>>

describe('OidcTokenSource', () => {
  it('is the shared PhotonID sign-in (ph-auth), with no paste box', async () => {
    const a = fakeAuth()
    const s = new OidcTokenSource(a)
    expect(s.auth).toBe(a)
    expect(s.supportsPaste).toBe(false)
    expect(await s.getAccessToken()).toBe('oidc-tok')
    await s.signIn('/o/1/team')
    expect(a.signIn).toHaveBeenCalledWith('/o/1/team')
    expect(await s.unauthorized()).toBe('problem')
    await s.signOut()
    expect(a.signOut).toHaveBeenCalled()
  })
})

describe('DevTokenSource', () => {
  it('stores a pasted token in sessionStorage only; sign out or a 401 clears it', async () => {
    const d = new DevTokenSource()
    expect(d.auth).toBeNull()
    expect(await d.getAccessToken()).toBeNull()
    d.paste('  abc  ')
    expect(await d.getAccessToken()).toBe('abc')
    expect(localStorage.getItem('pv-dev-token')).toBeNull()
    await d.signOut()
    expect(await d.getAccessToken()).toBeNull()
    d.paste('again')
    expect(await d.unauthorized()).toBe('redirect')
    expect(await d.getAccessToken()).toBeNull()
    await d.signIn()
  })
  it('falls back to VITE_DEV_TOKEN in dev builds', async () => {
    vi.stubEnv('VITE_DEV_TOKEN', 'from-env')
    expect(await new DevTokenSource().getAccessToken()).toBe('from-env')
  })
})

describe('HybridTokenSource', () => {
  const oidc = (token: string | null): TokenSource & Record<string, unknown> => ({
    supportsPaste: false, auth: null, getAccessToken: async () => token, signIn: vi.fn(async () => {}), signOut: vi.fn(async () => {}),
    unauthorized: vi.fn(async () => 'redirect' as const),
  })
  it('prefers a pasted token, else the OIDC session', async () => {
    const dev = new DevTokenSource()
    const h = new HybridTokenSource(oidc('oidc-tok'), dev)
    expect(await h.getAccessToken()).toBe('oidc-tok')
    h.paste('dev-tok')
    expect(await h.getAccessToken()).toBe('dev-tok')
  })
  it('a 401 with a pasted token drops the paste; without one it asks the real sign-in', async () => {
    const o = oidc('oidc-tok')
    const h = new HybridTokenSource(o, new DevTokenSource())
    h.paste('dev-tok')
    expect(await h.unauthorized()).toBe('redirect')
    expect(o.unauthorized).not.toHaveBeenCalled()
    expect(await h.unauthorized()).toBe('redirect')
    expect(o.unauthorized).toHaveBeenCalled()
  })
  it('signs in through OIDC; signing out drops a pasted token first, else signs out of OIDC', async () => {
    const o = oidc(null)
    const h = new HybridTokenSource(o, new DevTokenSource())
    await h.signIn('/x')
    expect(o.signIn).toHaveBeenCalledWith('/x')
    h.paste('dev-tok')
    await h.signOut()
    expect(o.signOut).not.toHaveBeenCalled()
    await h.signOut()
    expect(o.signOut).toHaveBeenCalled()
  })
})
