// GENERATED from @photon/ui by scripts/sync-vendored.mjs. Do not edit here: change photon-ui, then re-run it.
/**
 * Sign-in with PhotonID, the same in every Photon product (photonid/docs/SIGNIN-PLAN.md section 4, decided by Connor 2026-11-13).
 *
 *  1. No sign-in card: a visitor without a session goes straight to PhotonID (`signIn`). With a PhotonID session that comes straight back.
 *  2. Renewal by refresh token only, never a hidden iframe (the products' CSP forbids it); when that fails, a top-level redirect again.
 *  3. Deep links survive: the same-site path, query and hash travel in the OIDC state.
 *  4. No loops: a 401 from the product's own API soon after coming back from PhotonID is a problem to show, not a reason to redirect again
 *     (`unauthorized` says which). A 403 is never a redirect: the product shows a page (`pages.tsx`).
 *  5. Sign-out ends the PhotonID session, which sends the browser back to `/auth/signed-out`; that route goes straight to PhotonID's sign-in
 *     form (`prompt=login`), so nobody is signed in again silently and there is no signed-out page of our own.
 *  6. Tokens live in sessionStorage only.
 * Each product registers two addresses at PhotonID: `<origin>/auth/callback` (redirect) and `<origin>/auth/signed-out` (post-logout).
 */
import { UserManager, WebStorageStateStore, type User } from 'oidc-client-ts'

export const CALLBACK_PATH = '/auth/callback'
export const SIGNED_OUT_PATH = '/auth/signed-out'
/** How long after coming back from PhotonID a 401 counts as "sign-in did not work" rather than "the session ended". */
export const LOOP_WINDOW_MS = 60_000
/** A token this close to its end is renewed before it is used. */
export const RENEW_EARLY_S = 30
const STAMP = 'ph-auth:callback-at'

export interface SignInConfig {
  issuer: string
  clientId: string
  /** The product's PhotonID project id: Zitadel adds it to the token audience only when asked, and the API checks for it. */
  audienceProject: string
  /** Defaults to `location.origin`. */
  origin?: string
  /** More scopes, space separated (e.g. a Zitadel organization scope for a sign-up). */
  extraScope?: string
}

/** The part of oidc-client-ts's UserManager this module uses (tests pass a fake). */
export type UserManagerLike = Pick<UserManager, 'getUser' | 'removeUser' | 'signinRedirect' | 'signinRedirectCallback' | 'signinSilent' | 'signoutRedirect'>

export type Prompt = 'login' | 'create' | 'select_account'

/** Why coming back from PhotonID did not sign the person in. `code` is the OIDC error (`access_denied`, `login_required`, ...) or `callback_failed`. */
export class SignInError extends Error {
  readonly code: string
  constructor(code: string, message?: string) {
    super(message || code)
    this.name = 'SignInError'
    this.code = code
  }
}

/** Only same-site paths: one leading slash, never `//host` or `/\host` (browsers treat those as other sites); never the auth routes themselves. */
export function safeReturnPath(value: unknown): string {
  if (typeof value !== 'string' || !/^\/(?![/\\])/.test(value)) return '/'
  const path = value.split(/[?#]/, 1)[0]
  return path === CALLBACK_PATH || path === SIGNED_OUT_PATH ? '/' : value
}

export function currentPath(loc: Pick<Location, 'pathname' | 'search' | 'hash'> = window.location): string {
  return loc.pathname + loc.search + loc.hash
}

export class PhotonSignIn {
  private readonly mgr: UserManagerLike
  private readonly store: Storage
  private readonly now: () => number
  private readonly scope: string
  private redirecting = false
  private callback: Promise<string> | null = null

  constructor(cfg: SignInConfig, mgr?: UserManagerLike, store: Storage = window.sessionStorage, now: () => number = Date.now) {
    const origin = cfg.origin ?? window.location.origin
    this.scope = ['openid profile email offline_access', `urn:zitadel:iam:org:project:id:${cfg.audienceProject}:aud`, cfg.extraScope].filter(Boolean).join(' ')
    this.store = store
    this.now = now
    this.mgr = mgr ?? new UserManager({
      authority: cfg.issuer,
      client_id: cfg.clientId,
      redirect_uri: origin + CALLBACK_PATH,
      post_logout_redirect_uri: origin + SIGNED_OUT_PATH,
      response_type: 'code', // authorization code + PKCE (the default for a public client)
      scope: this.scope,
      userStore: new WebStorageStateStore({ store }),
      stateStore: new WebStorageStateStore({ store }),
      automaticSilentRenew: false, // renewed on demand in getAccessToken, by refresh token only
    })
  }

  /** The access token to send, renewed by refresh token when it is (nearly) out of date; null when there is no usable session. Never opens an iframe. */
  async getAccessToken(): Promise<string | null> {
    const u = await this.mgr.getUser()
    if (!u) return null
    if (!this.needsRenewal(u)) return u.access_token
    if (!u.refresh_token) { await this.mgr.removeUser(); return null }
    try {
      return (await this.mgr.signinSilent())?.access_token ?? null
    } catch {
      await this.mgr.removeUser()
      return null
    }
  }

  private needsRenewal(u: User): boolean {
    return u.expired === true || (typeof u.expires_in === 'number' && u.expires_in <= RENEW_EARLY_S)
  }

  /** Go to PhotonID now (once: a second call while the page is already leaving does nothing). `extraScope` is added for this request only:
   * PhotonBoard's sign-up asks for its buyers' organization (`urn:zitadel:iam:org:id:<id>`) with `prompt: 'create'`, the only place sign-up is open. */
  async signIn(returnTo: string = currentPath(), opts: { prompt?: Prompt; extraScope?: string; extraQueryParams?: Record<string, string> } = {}): Promise<void> {
    if (this.redirecting) return
    this.redirecting = true
    try {
      await this.mgr.signinRedirect({
        state: safeReturnPath(returnTo), prompt: opts.prompt, extraQueryParams: opts.extraQueryParams,
        ...(opts.extraScope ? { scope: `${this.scope} ${opts.extraScope}` } : {}),
      })
    } catch (e) {
      this.redirecting = false
      throw e
    }
  }

  /** On `/auth/callback`: finish the sign-in and say where to go. Safe to call twice (React StrictMode): the code is used once. */
  handleCallback(url?: string): Promise<string> {
    this.callback ??= this.finish(url)
    return this.callback
  }

  private async finish(url?: string): Promise<string> {
    try {
      const u = await this.mgr.signinRedirectCallback(url)
      this.store.setItem(STAMP, String(this.now()))
      return safeReturnPath(u.state)
    } catch (e) {
      // The callback address opened again (back button, reload): already signed in is fine, go home.
      const have = await this.mgr.getUser().catch(() => null)
      if (have && !have.expired) return '/'
      const code = (e as { error?: unknown })?.error
      throw new SignInError(typeof code === 'string' && code ? code : 'callback_failed', (e as Error)?.message)
    }
  }

  /** The product's API answered 401. The token is forgotten. 'redirect': send the person to PhotonID (the session ended).
   * 'problem': they came back from PhotonID a moment ago and are still refused, so redirecting again would loop: show `SignInProblem`. */
  async unauthorized(): Promise<'redirect' | 'problem'> {
    await this.mgr.removeUser()
    const at = Number(this.store.getItem(STAMP) || 0)
    if (at && this.now() - at < LOOP_WINDOW_MS) {
      this.store.removeItem(STAMP) // "Try again" then starts a fresh sign-in, which is allowed to fail once more
      return 'problem'
    }
    return 'redirect'
  }

  /** Sign out: end the PhotonID session; PhotonID then sends the browser to `/auth/signed-out`. */
  async signOut(): Promise<void> {
    this.redirecting = true // the page is leaving for PhotonID: a sign-in asked for now (the app saw "signed out") must not race it
    this.store.removeItem(STAMP)
    const u = await this.mgr.getUser()
    await this.mgr.removeUser()
    await this.mgr.signoutRedirect(u?.id_token ? { id_token_hint: u.id_token } : undefined)
  }

  /** On `/auth/signed-out`: straight to PhotonID's sign-in form (never a silent sign-in), and home afterwards. */
  afterSignOut(): Promise<void> {
    return this.signIn('/', { prompt: 'login' })
  }
}
