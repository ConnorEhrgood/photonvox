import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { ApiError, createApi, RENEWAL_FAILED, type Api } from '../api/client'
import { RenewalError } from '../ph-auth/signin'
import type { Me } from '../api/types'
import type { TokenSource } from './tokenSource'

/** The suite's sign-in contract (photonid docs/SIGNIN-PLAN.md, through the shared `ph-auth` module):
 *  `signedOut`: go straight to PhotonID. `problem`: PhotonID signed the person in a moment ago and the API still refuses (401): shown, never
 *  redirected again (no loop). `pending`: signed in, but the directory has not told us about this person yet (a fresh invitation); we keep asking.
 *  `noAccess`: signed in with an account that has no access to PhotonVox. A 403 is always one of those pages, never a redirect.
 *  `signOutFailed`: Sign out could not reach PhotonID, so the PhotonID session may still be open: a page that offers to try again (never the
 *  app, whose next request would sign the person straight back in). */
type Status = 'loading' | 'signedOut' | 'problem' | 'ready' | 'pending' | 'noAccess' | 'error' | 'signOutFailed'

interface AuthState {
  status: Status
  me: Me | null
  error: string | null
  api: Api
  source: TokenSource
  /** Straight to PhotonID; back to `returnTo` (default: this page, query and hash included). */
  signIn: (returnTo?: string) => Promise<void>
  signOut: () => Promise<void>
  refreshMe: () => Promise<void>
  /** Dev-only: accept a pasted token. */
  pasteToken: (token: string) => Promise<void>
}

const Ctx = createContext<AuthState | null>(null)

export function useAuth(): AuthState {
  const v = useContext(Ctx)
  if (!v) throw new Error('useAuth outside AuthProvider')
  return v
}

/** How soon to ask again while a new person's access is being set up. */
export const PENDING_RETRY_MS = 5000

export function AuthProvider({ source, baseUrl, children }: { source: TokenSource; baseUrl: string; children: ReactNode }) {
  const [status, setStatus] = useState<Status>('loading')
  const [me, setMe] = useState<Me | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [pendingTries, setPendingTries] = useState(0)    // counts "still pending" answers, so each one re-arms the retry timer below
  const unauthorizedRef = useRef(() => {})

  const api = useMemo(
    () => createApi({ baseUrl, getToken: () => source.getAccessToken(), onUnauthorized: () => unauthorizedRef.current() }),
    [baseUrl, source],
  )

  const load = useCallback(async () => {
    let token: string | null
    try {
      token = await source.getAccessToken()
    } catch (e) {
      // PhotonID unreachable while renewing: the session is kept, so this is an error to retry, not "signed out"
      setStatus('error')
      setError(e instanceof RenewalError ? RENEWAL_FAILED : e instanceof Error ? e.message : String(e))
      return
    }
    if (!token) { setStatus('signedOut'); return }
    try {
      setMe(await api.get<Me>('/me'))
      setError(null)
      setStatus('ready')
    } catch (e) {
      const code = e instanceof ApiError ? (e.data?.code as string | undefined) : undefined
      if (code === 'access_pending') { setStatus('pending'); setPendingTries((n) => n + 1); return }
      if (code === 'no_access' || (e instanceof ApiError && e.status === 403)) { setStatus('noAccess'); setError(e instanceof Error ? e.message : null); return }
      // A 401: onUnauthorized decides (PhotonID again, or the problem page). Anything else is a real error.
      if (e instanceof ApiError && e.status === 401) return
      setStatus('error')
      setError(e instanceof Error ? e.message : String(e))
    }
  }, [api, source])

  unauthorizedRef.current = () => {
    setMe(null)
    void source.unauthorized().then((next) => setStatus(next === 'problem' ? 'problem' : 'signedOut'))
  }

  useEffect(() => { void load() }, [load])
  // The directory's notice, or the next periodic pull, makes a freshly invited person known within moments: keep asking, quietly.
  useEffect(() => {
    if (status !== 'pending') return
    const t = setTimeout(() => void load(), PENDING_RETRY_MS)
    return () => clearTimeout(t)
  }, [status, pendingTries, load])

  const value: AuthState = {
    status, me, error, api, source,
    signIn: (returnTo) => source.signIn(returnTo ?? location.pathname + location.search + location.hash),
    signOut: async () => {
      try {
        await source.signOut()
      } catch {
        setStatus('signOutFailed') // PhotonID unreachable: say so and offer to try again (the shared sign-in released its latch)
        return
      }
      setMe(null)
      setStatus('signedOut')
    },
    refreshMe: load,
    pasteToken: async (t) => { source.paste?.(t); setStatus('loading'); await load() },
  }
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>
}
