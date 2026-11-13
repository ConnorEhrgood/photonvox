// GENERATED from @photon/ui by scripts/sync-vendored.mjs. Do not edit here: change photon-ui, then re-run it.
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { LOOP_WINDOW_MS, PhotonSignIn, SignInError, currentPath, safeReturnPath, type UserManagerLike } from './signin'

function user(over: Record<string, unknown> = {}) {
  return { access_token: 'at', refresh_token: 'rt', id_token: 'idt', expired: false, expires_in: 300, state: '/', ...over }
}

function fakeManager(initial: ReturnType<typeof user> | null = user()) {
  let current: ReturnType<typeof user> | null = initial
  const m = {
    getUser: vi.fn(async () => current),
    removeUser: vi.fn(async () => { current = null }),
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

  it('a refused renewal forgets the session', async () => {
    const m = fakeManager(user({ expired: true }))
    m.signinSilent.mockRejectedValueOnce(new Error('invalid_grant'))
    const { auth } = make(m)
    expect(await auth.getAccessToken()).toBeNull()
    expect(await m.getUser()).toBeNull()
  })

  it('a renewal that answers nothing is no token', async () => {
    const m = fakeManager(user({ expired: true }))
    m.signinSilent.mockResolvedValueOnce(null as never)
    expect(await make(m).auth.getAccessToken()).toBeNull()
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
  it('ends the PhotonID session with the id token and forgets everything here', async () => {
    const { auth, m } = make()
    sessionStorage.setItem('ph-auth:callback-at', '1')
    await auth.signOut()
    expect(m.removeUser).toHaveBeenCalled()
    expect(m.signoutRedirect).toHaveBeenCalledWith({ id_token_hint: 'idt' })
    expect(sessionStorage.getItem('ph-auth:callback-at')).toBeNull()
  })

  it('a sign-in asked for while the page leaves for PhotonID does not race the sign-out', async () => {
    const { auth, m } = make()
    await auth.signOut()
    await auth.signIn('/')
    expect(m.signinRedirect).not.toHaveBeenCalled()
  })

  it('works without a stored session (a new tab)', async () => {
    const { auth, m } = make(fakeManager(null))
    await auth.signOut()
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
