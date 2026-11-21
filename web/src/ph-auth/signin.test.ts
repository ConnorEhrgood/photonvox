// GENERATED from @photon/ui by scripts/sync-vendored.mjs. Do not edit here: change photon-ui, then re-run it. photon-ui 031c370e5fa1
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { LOOP_WINDOW_MS, PhotonSignIn, RenewalError, SignInError, currentPath, safeReturnPath, type UserManagerLike } from './signin'

/** What oidc-client-ts throws when the token endpoint answers with an OIDC error. */
function refusal(error: string) {
  return Object.assign(new Error(error), { name: 'ErrorResponse', error })
}

function user(over: Record<string, unknown> = {}) {
  return { access_token: 'at', refresh_token: 'rt', id_token: 'idt', expired: false, expires_in: 300, state: '/', ...over }
}

function fakeManager(initial: ReturnType<typeof user> | null = user()) {
  let current: ReturnType<typeof user> | null = initial
  const m = {
    getUser: vi.fn(async () => current),
    removeUser: vi.fn(async () => { current = null }),
    revokeTokens: vi.fn(async (_types?: string[]) => {}),
    signinRedirect: vi.fn(async (_args?: unknown) => {}),
    signinRedirectCallback: vi.fn(async (_url?: string) => user({ state: '/o/1/team?tab=a#x' })),
    signinSilent: vi.fn(async () => (current = user({ access_token: 'renewed' }))),
    signoutRedirect: vi.fn(async (_args?: unknown) => {}),
    set(u: ReturnType<typeof user> | null) { current = u },
  }
  return m
}

const cfg = { issuer: 'https://id.example', clientId: 'c', audienceProject: 'p', origin: 'https://app.example' }
let clock = 1_000_000
const now = () => clock

function make(m = fakeManager()) {
  return { m, auth: new PhotonSignIn(cfg, m as unknown as UserManagerLike, window.sessionStorage, now) }
}

beforeEach(() => { sessionStorage.clear(); clock = 1_000_000 })

describe('safeReturnPath', () => {
  it.each([
    ['/o/1/team?x=1#h', '/o/1/team?x=1#h'], ['/', '/'], ['//evil.example', '/'], ['/\\evil.example', '/'], ['https://evil.example/', '/'],
    ['', '/'], [undefined, '/'], [42, '/'], ['/auth/callback?code=1', '/'], ['/auth/signed-out', '/'], ['/auth/callbacks', '/auth/callbacks'],
    // browsers drop tab, CR and LF from an address, so these are `//evil.example` (another site)
    ['/\t/evil.example/x', '/'], ['/\n/evil.example', '/'], ['/\r\\evil.example', '/'], ['/a\u0000b', '/'], ['/a\u007fb', '/'],
    ['/a\\b?x=1', '/a\\b?x=1'],
  ])('%s -> %s', (input, want) => expect(safeReturnPath(input)).toBe(want))

  it('reads the whole current address', () => {
    expect(currentPath({ pathname: '/a', search: '?b=1', hash: '#c' })).toBe('/a?b=1#c')
  })
})

describe('the access token', () => {
  it('is the stored one while it is fresh', async () => {
    const { auth, m } = make()
    expect(await auth.getAccessToken()).toBe('at')
    expect(m.signinSilent).not.toHaveBeenCalled()
  })

  it('is null with no session', async () => {
    const { auth } = make(fakeManager(null))
    expect(await auth.getAccessToken()).toBeNull()
  })

  it.each([[{ expired: true }], [{ expires_in: 10 }]])('is renewed by refresh token when out of date or nearly (%o)', async (over) => {
    const { auth, m } = make(fakeManager(user(over)))
    expect(await auth.getAccessToken()).toBe('renewed')
    expect(m.signinSilent).toHaveBeenCalledTimes(1)
  })

  it('is never renewed through an iframe: no refresh token means no session', async () => {
    const { auth, m } = make(fakeManager(user({ expired: true, refresh_token: undefined })))
    expect(await auth.getAccessToken()).toBeNull()
    expect(m.signinSilent).not.toHaveBeenCalled()
    expect(m.removeUser).toHaveBeenCalled()
  })

  it('a renewal PhotonID refuses (invalid_grant) forgets the session', async () => {
    const m = fakeManager(user({ expired: true }))
    m.signinSilent.mockRejectedValueOnce(refusal('invalid_grant'))
    const { auth } = make(m)
    expect(await auth.getAccessToken()).toBeNull()
    expect(await m.getUser()).toBeNull()
  })

  it.each([
    ['a network error', new TypeError('Failed to fetch')],
    ['a timeout', Object.assign(new Error('timed out'), { name: 'ErrorTimeout' })],
    ['a 5xx without an OIDC error', new Error('Internal Server Error')],
    ['a temporary OIDC error', refusal('temporarily_unavailable')],
  ])('%s keeps the session: the token while it still works, else a retryable error', async (_what, err) => {
    const early = fakeManager(user({ expires_in: 10 }))
    early.signinSilent.mockRejectedValueOnce(err)
    expect(await make(early).auth.getAccessToken()).toBe('at')
    expect(early.removeUser).not.toHaveBeenCalled()

    const late = fakeManager(user({ expired: true }))
    late.signinSilent.mockRejectedValueOnce(err)
    const { auth } = make(late)
    const e = await auth.getAccessToken().catch((x) => x)
    expect(e).toBeInstanceOf(RenewalError)
    expect(e.retryable).toBe(true)
    expect(late.removeUser).not.toHaveBeenCalled()
    expect(await auth.getAccessToken()).toBe('renewed')          // the next try works once PhotonID answers
  })

  it('callers that find the token due at the same time share one renewal (refresh tokens may be single use)', async () => {
    const m = fakeManager(user({ expired: true }))
    let finish: (v: unknown) => void = () => {}
    m.signinSilent.mockImplementationOnce(() => new Promise((r) => { finish = r }).then(() => { m.set(user({ access_token: 'renewed' })); return user({ access_token: 'renewed' }) }) as never)
    const { auth } = make(m)
    const all = Promise.all([auth.getAccessToken(), auth.getAccessToken(), auth.getAccessToken()])
    await new Promise((r) => setTimeout(r, 0))
    finish(null)
    expect(await all).toEqual(['renewed', 'renewed', 'renewed'])
    expect(m.signinSilent).toHaveBeenCalledTimes(1)
  })

  it('a refusal does not delete a session stored meanwhile by another renewal', async () => {
    const m = fakeManager(user({ expired: true, refresh_token: 'old' }))
    m.signinSilent.mockImplementationOnce(async () => { m.set(user({ refresh_token: 'new', access_token: 'other' })); throw refusal('invalid_grant') })
    expect(await make(m).auth.getAccessToken()).toBeNull()
    expect(m.removeUser).not.toHaveBeenCalled()
    expect((await m.getUser())?.access_token).toBe('other')
  })

  it('a renewal that answers nothing is no token', async () => {
    const m = fakeManager(user({ expired: true }))
    m.signinSilent.mockResolvedValueOnce(null as never)
    expect(await make(m).auth.getAccessToken()).toBeNull()
  })
})

describe('a session begun before the app asked for more', () => {
  const full = 'openid profile email offline_access urn:zitadel:iam:org:project:id:p:aud urn:zitadel:iam:org:project:id:dir:aud'
  const withDirectory = () => new PhotonSignIn({ ...cfg, extraScope: 'urn:zitadel:iam:org:project:id:dir:aud' }, m as unknown as UserManagerLike, window.sessionStorage, now)
  let m: ReturnType<typeof fakeManager>

  it('is dropped, so the app signs in again with every scope it asks for now', async () => {
    m = fakeManager(user({ scope: 'openid profile email offline_access urn:zitadel:iam:org:project:id:p:aud' }))
    expect(await withDirectory().getAccessToken()).toBeNull()
    expect(m.removeUser).toHaveBeenCalledTimes(1)
  })

  it('once per scope: should PhotonID not grant it, the session is kept rather than looping', async () => {
    m = fakeManager(user({ scope: 'openid profile email offline_access urn:zitadel:iam:org:project:id:p:aud' }))
    await withDirectory().getAccessToken()
    m.set(user({ scope: 'openid profile email offline_access urn:zitadel:iam:org:project:id:p:aud' }))
    expect(await withDirectory().getAccessToken()).toBe('at')
    expect(m.removeUser).toHaveBeenCalledTimes(1)
  })

  it('a session with every scope, more than asked (a sign-up\'s organization), or none recorded is kept', async () => {
    for (const scope of [full, `${full} urn:zitadel:iam:org:id:9`, undefined]) {
      m = fakeManager(user({ scope }))
      expect(await withDirectory().getAccessToken()).toBe('at')
      expect(m.removeUser).not.toHaveBeenCalled()
    }
  })
})

describe('signing in', () => {
  it('goes to PhotonID once with the deep link as state, however often it is asked', async () => {
    const { auth, m } = make()
    await auth.signIn('/o/1/team?x=1#h')
    await auth.signIn('/elsewhere')
    expect(m.signinRedirect).toHaveBeenCalledTimes(1)
    expect(m.signinRedirect).toHaveBeenCalledWith({ state: '/o/1/team?x=1#h', prompt: undefined, extraQueryParams: undefined })
  })

  it('never carries another site as the place to come back to', async () => {
    const { auth, m } = make()
    await auth.signIn('//evil.example/x')
    expect(m.signinRedirect.mock.calls[0][0]).toMatchObject({ state: '/' })
  })

  it('defaults to the current address and passes a prompt', async () => {
    window.history.replaceState(null, '', '/sites?a=1')
    const { auth, m } = make()
    await auth.signIn(undefined, { prompt: 'create', extraQueryParams: { login_hint: 'a@b' } })
    expect(m.signinRedirect).toHaveBeenCalledWith({ state: '/sites?a=1', prompt: 'create', extraQueryParams: { login_hint: 'a@b' } })
  })

  it('a sign-up asks for one organization on that request only', async () => {
    const { auth, m } = make()
    await auth.signIn('/', { prompt: 'create', extraScope: 'urn:zitadel:iam:org:id:77' })
    expect(m.signinRedirect).toHaveBeenCalledWith({ state: '/', prompt: 'create', extraQueryParams: undefined,
      scope: 'openid profile email offline_access urn:zitadel:iam:org:project:id:p:aud urn:zitadel:iam:org:id:77' })
  })

  it('can be tried again when leaving failed', async () => {
    const m = fakeManager()
    m.signinRedirect.mockRejectedValueOnce(new Error('offline'))
    const { auth } = make(m)
    await expect(auth.signIn('/')).rejects.toThrow('offline')
    await auth.signIn('/')
    expect(m.signinRedirect).toHaveBeenCalledTimes(2)
  })
})

describe('coming back from PhotonID', () => {
  it('returns the deep link, uses the code once, and remembers when', async () => {
    const { auth, m } = make()
    const [a, b] = await Promise.all([auth.handleCallback(), auth.handleCallback()])
    expect(a).toBe('/o/1/team?tab=a#x')
    expect(b).toBe(a)
    expect(m.signinRedirectCallback).toHaveBeenCalledTimes(1)
    expect(sessionStorage.getItem('ph-auth:callback-at')).toBe(String(clock))
  })

  it('an unsafe state sends the person home', async () => {
    const m = fakeManager()
    m.signinRedirectCallback.mockResolvedValueOnce(user({ state: 'https://evil.example' }))
    expect(await make(m).auth.handleCallback()).toBe('/')
  })

  it('PhotonID refusing is a SignInError with its code', async () => {
    const m = fakeManager(null)
    m.signinRedirectCallback.mockRejectedValueOnce(Object.assign(new Error('denied by user'), { error: 'access_denied' }))
    const err = await make(m).auth.handleCallback().catch((e) => e)
    expect(err).toBeInstanceOf(SignInError)
    expect(err.code).toBe('access_denied')
    expect(err.message).toBe('denied by user')
  })

  it('any other failure is callback_failed', async () => {
    const m = fakeManager(null)
    m.signinRedirectCallback.mockRejectedValueOnce(new Error('No matching state found in storage'))
    expect((await make(m).auth.handleCallback().catch((e) => e)).code).toBe('callback_failed')
    const m2 = fakeManager(null)
    m2.signinRedirectCallback.mockRejectedValueOnce('odd')
    m2.getUser.mockRejectedValueOnce(new Error('storage'))
    const e2 = await make(m2).auth.handleCallback().catch((e) => e)
    expect(e2.code).toBe('callback_failed')
    expect(e2.message).toBe('callback_failed')
  })

  it('the callback opened again while signed in just goes home', async () => {
    const m = fakeManager(user())
    m.signinRedirectCallback.mockRejectedValueOnce(new Error('No matching state found in storage'))
    expect(await make(m).auth.handleCallback()).toBe('/')
  })

  it('an expired session does not count as signed in there', async () => {
    const m = fakeManager(user({ expired: true }))
    m.signinRedirectCallback.mockRejectedValueOnce(new Error('No matching state'))
    expect((await make(m).auth.handleCallback().catch((e) => e)).code).toBe('callback_failed')
  })
})

describe('a 401 from the product', () => {
  it('long after signing in: forget the token and go to PhotonID', async () => {
    const { auth, m } = make()
    expect(await auth.unauthorized()).toBe('redirect')
    expect(await m.getUser()).toBeNull()
  })

  it('just after coming back: a problem to show, not a loop; the next sign-in may fail once more', async () => {
    const { auth } = make()
    await auth.handleCallback()
    clock += LOOP_WINDOW_MS - 1
    expect(await auth.unauthorized()).toBe('problem')
    expect(await auth.unauthorized()).toBe('redirect')
  })

  it('after the window it is an ordinary end of session', async () => {
    const { auth } = make()
    await auth.handleCallback()
    clock += LOOP_WINDOW_MS
    expect(await auth.unauthorized()).toBe('redirect')
  })
})

describe('signing out', () => {
  it('revokes the refresh token first, then forgets everything here and ends the PhotonID session with the id token', async () => {
    const { auth, m } = make()
    sessionStorage.setItem('ph-auth:callback-at', '1')
    await auth.signOut()
    expect(m.revokeTokens).toHaveBeenCalledWith(['refresh_token'])
    expect(m.revokeTokens.mock.invocationCallOrder[0]).toBeLessThan(m.removeUser.mock.invocationCallOrder[0])
    expect(m.removeUser.mock.invocationCallOrder[0]).toBeLessThan(m.signoutRedirect.mock.invocationCallOrder[0])
    expect(m.signoutRedirect).toHaveBeenCalledWith({ id_token_hint: 'idt' })
    expect(sessionStorage.getItem('ph-auth:callback-at')).toBeNull()
  })

  it('a revocation that fails does not stop the sign-out', async () => {
    const m = fakeManager()
    m.revokeTokens.mockRejectedValueOnce(new Error('offline'))
    await make(m).auth.signOut()
    expect(m.removeUser).toHaveBeenCalled()
    expect(m.signoutRedirect).toHaveBeenCalledWith({ id_token_hint: 'idt' })
  })

  it('when PhotonID cannot be reached it rejects and lets the person try again (no stuck latch)', async () => {
    const m = fakeManager()
    m.signoutRedirect.mockRejectedValueOnce(new Error('Failed to fetch'))
    const { auth } = make(m)
    await expect(auth.signOut()).rejects.toThrow('Failed to fetch')
    await auth.signIn('/')
    expect(m.signinRedirect).toHaveBeenCalledTimes(1)               // the latch was released
  })

  it('a page restored from the back/forward cache after leaving may sign in again', async () => {
    const { auth, m } = make()
    await auth.signIn('/')
    window.dispatchEvent(Object.assign(new Event('pageshow'), { persisted: true }))
    await auth.signIn('/')
    expect(m.signinRedirect).toHaveBeenCalledTimes(2)
  })

  it('a sign-in asked for while the page leaves for PhotonID does not race the sign-out', async () => {
    const { auth, m } = make()
    await auth.signOut()
    await auth.signIn('/')
    expect(m.signinRedirect).not.toHaveBeenCalled()
  })

  it('works without a stored session (a new tab): nothing to revoke', async () => {
    const { auth, m } = make(fakeManager(null))
    await auth.signOut()
    expect(m.revokeTokens).not.toHaveBeenCalled()
    expect(m.signoutRedirect).toHaveBeenCalledWith(undefined)
  })

  it('then goes straight to the sign-in form, never a silent sign-in, and home afterwards', async () => {
    const { auth, m } = make()
    await auth.afterSignOut()
    expect(m.signinRedirect).toHaveBeenCalledWith({ state: '/', prompt: 'login', extraQueryParams: undefined })
  })
})

describe('the real UserManager', () => {
  it('is set up for the two registered addresses, sessionStorage and no automatic iframe renewal', () => {
    const auth = new PhotonSignIn({ ...cfg, extraScope: 'urn:zitadel:iam:org:id:9' })
    const s = (auth as unknown as { mgr: { settings: Record<string, unknown> } }).mgr.settings
    expect(s.redirect_uri).toBe('https://app.example/auth/callback')
    expect(s.post_logout_redirect_uri).toBe('https://app.example/auth/signed-out')
    expect(s.automaticSilentRenew).toBe(false)
    expect(s.scope).toBe('openid profile email offline_access urn:zitadel:iam:org:project:id:p:aud urn:zitadel:iam:org:id:9')
  })

  it('defaults the origin to the page', () => {
    const auth = new PhotonSignIn({ issuer: 'https://id.example', clientId: 'c', audienceProject: 'p' })
    const s = (auth as unknown as { mgr: { settings: Record<string, unknown> } }).mgr.settings
    expect(s.redirect_uri).toBe(`${window.location.origin}/auth/callback`)
  })
})
