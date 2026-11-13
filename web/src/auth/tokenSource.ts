import { UserManager, WebStorageStateStore } from 'oidc-client-ts'

/** Where access tokens come from. The OIDC implementation is the real one; the dev one lets a developer
 * paste a token (e.g. a Zitadel machine-user JWT) and exists only in dev builds. Tests use a fake. */
export interface TokenSource {
  getAccessToken(): Promise<string | null>
  /** `create` opens the IdP's registration form instead of its sign-in form. */
  signIn(returnTo: string, opts?: SignInOptions): Promise<void>
  signOut(): Promise<void>
  /** Completes the redirect flow; resolves to the path to return to. */
  handleCallback(): Promise<string>
  readonly supportsPaste: boolean
  paste?(token: string): void
}

export interface SignInOptions { create?: boolean }

export interface OidcConfig {
  issuer: string
  clientId: string
  audienceProject: string
  redirectUri: string
  postLogoutUri: string
}

/** Only same-site paths: one leading slash, never `//host` or `/\host` (browsers treat those as other sites). */
export function safeReturnPath(state: unknown): string {
  return typeof state === 'string' && /^\/(?![/\\])/.test(state) ? state : '/'
}

export class OidcTokenSource implements TokenSource {
  readonly supportsPaste = false
  private mgr: UserManager

  constructor(cfg: OidcConfig, mgr?: UserManager) {
    this.mgr = mgr ?? new UserManager({
      authority: cfg.issuer,
      client_id: cfg.clientId,
      redirect_uri: cfg.redirectUri,
      post_logout_redirect_uri: cfg.postLogoutUri,
      response_type: 'code', // authorization code + PKCE (oidc-client-ts default for public clients)
      // Zitadel adds the project to the token audience only when asked; the API checks for it.
      scope: `openid profile email offline_access urn:zitadel:iam:org:project:id:${cfg.audienceProject}:aud`,
      userStore: new WebStorageStateStore({ store: window.sessionStorage }),
      automaticSilentRenew: true,
    })
  }

  async getAccessToken() {
    const u = await this.mgr.getUser()
    if (!u) return null
    if (u.expired) {
      try {
        return (await this.mgr.signinSilent())?.access_token ?? null
      } catch {
        return null
      }
    }
    return u.access_token
  }

  async signIn(returnTo: string, opts?: SignInOptions) {
    await this.mgr.signinRedirect(opts?.create ? { state: returnTo, prompt: 'create' } : { state: returnTo })
  }

  async signOut() {
    await this.mgr.signoutRedirect()
  }

  async handleCallback() {
    const u = await this.mgr.signinRedirectCallback()
    return safeReturnPath(u.state)
  }
}

const DEV_KEY = 'pv-dev-token'

/** Development only: use a token you obtained yourself. Never constructed in production builds. */
export class DevTokenSource implements TokenSource {
  readonly supportsPaste = true
  async getAccessToken() {
    // VITE_DEV_TOKEN (from a git-ignored .env.development.local) is a developer convenience, dev builds only.
    return sessionStorage.getItem(DEV_KEY) ?? (import.meta.env.DEV ? (import.meta.env.VITE_DEV_TOKEN ?? null) : null)
  }
  async signIn() { /* nothing to redirect to: the login page shows a paste box */ }
  async signOut() { sessionStorage.removeItem(DEV_KEY) }
  async handleCallback() { return '/' }
  paste(token: string) { sessionStorage.setItem(DEV_KEY, token.trim()) }
}

/** Dev builds only: real OIDC sign-in, plus the option to paste a token instead. */
export class HybridTokenSource implements TokenSource {
  readonly supportsPaste = true
  private oidc: TokenSource
  private dev: DevTokenSource
  constructor(oidc: TokenSource, dev: DevTokenSource) { this.oidc = oidc; this.dev = dev }
  async getAccessToken() { return (await this.dev.getAccessToken()) ?? this.oidc.getAccessToken() }
  signIn(returnTo: string, opts?: SignInOptions) { return opts ? this.oidc.signIn(returnTo, opts) : this.oidc.signIn(returnTo) }
  async signOut() { const had = await this.dev.getAccessToken(); await this.dev.signOut(); if (!had) await this.oidc.signOut() }
  handleCallback() { return this.oidc.handleCallback() }
  paste(t: string) { this.dev.paste(t) }
}
