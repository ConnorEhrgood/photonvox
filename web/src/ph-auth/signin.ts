// GENERATED from @photon/ui by scripts/sync-vendored.mjs. Do not edit here: change photon-ui, then re-run it. photon-ui 031c370e5fa1
/**
 * Sign-in with PhotonID, the same in every Photon product (photonid/docs/SIGNIN-PLAN.md section 4, decided by Connor 2026-11-13).
 *
 *  1. No sign-in card: a visitor without a session goes straight to PhotonID (`signIn`). With a PhotonID session that comes straight back.
 *  2. Renewal by refresh token only, never a hidden iframe (the products' CSP forbids it); when that fails, a top-level redirect again.
 *  3. Deep links survive: the same-site path, query and hash travel in the OIDC state.
 *  4. No loops: a 401 from the product's own API soon after coming back from PhotonID is a problem to show, not a reason to redirect again
 *     (`unauthorized` says which). A 403 is never a redirect: the product shows a page (`pages.tsx`).
 *  5. Sign-out revokes the refresh token at PhotonID, forgets the tokens and ends the PhotonID session, which sends the browser back to
 *     `/auth/signed-out`; that route goes straight to PhotonID's sign-in form (`prompt=login`), so nobody is signed in again silently and
 *     there is no signed-out page of our own.
 *  6. Tokens live in sessionStorage only.
 *  7. One renewal at a time: callers that find the token due while a renewal is running wait for that one (refresh tokens may be single use).
 *     Only a refusal from PhotonID (`invalid_grant` and the like) ends the session; a network error, a timeout or a 5xx keeps it and is
 *     reported as `RenewalError` (retryable) when the stored token is already out of date.
 * Each product registers two addresses at PhotonID: `<origin>/auth/callback` (redirect) and `<origin>/auth/signed-out` (post-logout).
 */
import { UserManager, WebStorageStateStore, type User } from 'oidc-client-ts'

export const CALLBACK_PATH = '/auth/callback'
export const SIGNED_OUT_PATH = '/auth/signed-out'
/** How long after coming back from PhotonID a 401 counts as "sign-in did not work" rather than "the session ended". */
export const LOOP_WINDOW_MS = 60_000
/** Where the scope a session was last dropped for (it lacked part of it) is kept, so that happens once per scope. */
const RESCOPED_KEY = 'photon-signin-rescoped'
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
export type UserManagerLike = Pick<UserManager, 'getUser' | 'removeUser' | 'revokeTokens' | 'signinRedirect' | 'signinRedirectCallback' | 'signinSilent' | 'signoutRedirect'>

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

/** The renewal could not reach PhotonID (network, timeout, 5xx) and the stored token is out of date. The session is kept: try again later. */
export class RenewalError extends Error {
  readonly retryable = true
  constructor(message?: string) {
    super(message || 'renewal_failed')
    this.name = 'RenewalError'
  }
}

/** OIDC error codes from the token endpoint that mean "this refresh token is finished", not "try again". */
const TRANSIENT_OIDC_ERRORS = new Set(['server_error', 'temporarily_unavailable'])

/** PhotonID answered the refresh with an OIDC error (oidc-client-ts's ErrorResponse), other than a temporary one. */
function isRefusal(e: unknown): boolean {
  const err = e as { name?: unknown; error?: unknown } | null
  return !!err && err.name === 'ErrorResponse' && typeof err.error === 'string' && !TRANSIENT_OIDC_ERRORS.has(err.error)
}

const PROBE_ORIGIN = 'https://photon.invalid'

/** Only same-site paths: one leading slash, never `//host` or `/\host` (browsers treat those as other sites), no control characters (browsers drop
 * tab, CR and LF, so `/<tab>/host` is `//host`), and it must resolve on this site; never the auth routes themselves. */
export function safeReturnPath(value: unknown): string {
  if (typeof value !== 'string' || !/^\/(?![/\\])/.test(value) || /[\u0000-\u001f\u007f]/.test(value)) return '/'
  try {
    if (new URL(value, PROBE_ORIGIN).origin !== PROBE_ORIGIN) return '/'
  } catch {
    return '/'
  }
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
  private renewing: Promise<string | null> | null = null

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
    // Back from the back/forward cache after leaving for PhotonID: the page did not leave after all, so a sign-in may start again.
    if (typeof window !== 'undefined') window.addEventListener('pageshow', (e) => { if (e.persisted) this.redirecting = false })
  }

  /** The access token to send, renewed by refresh token when it is (nearly) out of date; null when there is no usable session. Never opens an iframe.
   * Throws `RenewalError` when PhotonID cannot be reached and the stored token has already run out (the session is kept: retry). */
  async getAccessToken(): Promise<string | null> {
    if (this.renewing) return this.renewing
    const u = await this.mgr.getUser()
    if (!u) return null
    if (this.startedWithLessScope(u)) { await this.mgr.removeUser(); return null }
    if (!this.needsRenewal(u)) return u.access_token
    if (!u.refresh_token) { await this.mgr.removeUser(); return null }
    this.renewing ??= this.renew(u).finally(() => { this.renewing = null })
    return this.renewing
  }

  private async renew(u: User): Promise<string | null> {
    try {
      return (await this.mgr.signinSilent())?.access_token ?? null
    } catch (e) {
      if (isRefusal(e)) {
        // The refresh token is finished. Forget the session, unless something stored a newer one meanwhile.
        const now = await this.mgr.getUser()
        if (!now || now.refresh_token === u.refresh_token) await this.mgr.removeUser()
        return null
      }
      if (!u.expired) return u.access_token // renewed early and PhotonID is unreachable: the token still works for a moment
      throw new RenewalError((e as Error)?.message)
    }
  }

  /** A session begun before this app asked for a scope it asks for now (the directory's audience for the app switcher, added later) never gains it:
   * renewal by refresh token keeps the scopes of the first sign-in. Such a session is dropped, so the app signs in again (at once, with the PhotonID
   * session); once per scope, never in a loop, should PhotonID not grant one. A session that records no scope is taken as it is. */
  private startedWithLessScope(u: User): boolean {
    if (!u.scope) return false
    const have = new Set(u.scope.split(' '))
    if (this.scope.split(' ').every((s) => have.has(s))) return false
    if (this.store.getItem(RESCOPED_KEY) === this.scope) return false
    this.store.setItem(RESCOPED_KEY, this.scope)
    return true
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

  /** Sign out: revoke the refresh token at PhotonID (so no copy of it works any more), forget the tokens, end the PhotonID session;
   * PhotonID then sends the browser to `/auth/signed-out`. Rejects when PhotonID cannot be reached: the product should say that sign-out did
   * not complete and offer to try again (the tokens of this tab are gone either way). */
  async signOut(): Promise<void> {
    this.redirecting = true // the page is leaving for PhotonID: a sign-in asked for now (the app saw "signed out") must not race it
    this.store.removeItem(STAMP)
    try {
      const u = await this.mgr.getUser()
      if (u?.refresh_token) {
        try {
          await this.mgr.revokeTokens(['refresh_token'])
        } catch {
          // Best effort: the session end below is still attempted, and fails loudly if PhotonID is unreachable.
        }
      }
      await this.mgr.removeUser()
      await this.mgr.signoutRedirect(u?.id_token ? { id_token_hint: u.id_token } : undefined)
    } catch (e) {
      this.redirecting = false // still on this page: let the person try again
      throw e
    }
  }

  /** On `/auth/signed-out`: straight to PhotonID's sign-in form (never a silent sign-in), and home afterwards. */
  afterSignOut(): Promise<void> {
    return this.signIn('/', { prompt: 'login' })
  }
}
