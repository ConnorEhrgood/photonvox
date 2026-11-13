import type { PhotonSignIn } from '../ph-auth/signin'

/** Where access tokens come from. The real one is PhotonID through the suite's shared sign-in (`ph-auth`, vendored from @photon/ui); the dev
 * one lets a developer paste a token (e.g. a Zitadel machine-user JWT) and exists only in dev builds. Tests use a fake. */
export interface TokenSource {
  getAccessToken(): Promise<string | null>
  /** Straight to PhotonID (no sign-in card), coming back to `returnTo`. */
  signIn(returnTo: string): Promise<void>
  /** Ends the PhotonID session; PhotonID then sends the browser to `/auth/signed-out`, which goes on to the sign-in form. */
  signOut(): Promise<void>
  /** The API answered 401: 'problem' when that happened just after signing in (show it, do not redirect again), else 'redirect'. */
  unauthorized(): Promise<'redirect' | 'problem'>
  /** The shared sign-in, for the callback and signed-out routes; null for the paste-only dev source. */
  readonly auth: PhotonSignIn | null
  readonly supportsPaste: boolean
  paste?(token: string): void
}

export class OidcTokenSource implements TokenSource {
  readonly supportsPaste = false
  readonly auth: PhotonSignIn
  constructor(auth: PhotonSignIn) { this.auth = auth }
  getAccessToken() { return this.auth.getAccessToken() }
  signIn(returnTo: string) { return this.auth.signIn(returnTo) }
  signOut() { return this.auth.signOut() }
  unauthorized() { return this.auth.unauthorized() }
}

const DEV_KEY = 'pv-dev-token'

/** Development only: use a token you obtained yourself. Never constructed in production builds. */
export class DevTokenSource implements TokenSource {
  readonly supportsPaste = true
  readonly auth = null
  async getAccessToken() {
    // VITE_DEV_TOKEN (from a git-ignored .env.development.local) is a developer convenience, dev builds only.
    return sessionStorage.getItem(DEV_KEY) ?? (import.meta.env.DEV ? (import.meta.env.VITE_DEV_TOKEN ?? null) : null)
  }
  async signIn() { /* nothing to redirect to: the dev sign-in page shows a paste box */ }
  async signOut() { sessionStorage.removeItem(DEV_KEY) }
  async unauthorized() { sessionStorage.removeItem(DEV_KEY); return 'redirect' as const }
  paste(token: string) { sessionStorage.setItem(DEV_KEY, token.trim()) }
}

/** Dev builds only: real PhotonID sign-in, plus the option to paste a token instead. */
export class HybridTokenSource implements TokenSource {
  readonly supportsPaste = true
  readonly auth: PhotonSignIn | null
  private oidc: TokenSource
  private dev: DevTokenSource
  constructor(oidc: TokenSource, dev: DevTokenSource) { this.oidc = oidc; this.dev = dev; this.auth = oidc.auth }
  async getAccessToken() { return (await this.dev.getAccessToken()) ?? this.oidc.getAccessToken() }
  signIn(returnTo: string) { return this.oidc.signIn(returnTo) }
  async signOut() { const had = await this.dev.getAccessToken(); await this.dev.signOut(); if (!had) await this.oidc.signOut() }
  async unauthorized() { return (await this.dev.getAccessToken()) ? this.dev.unauthorized() : this.oidc.unauthorized() }
  paste(t: string) { this.dev.paste(t) }
}
