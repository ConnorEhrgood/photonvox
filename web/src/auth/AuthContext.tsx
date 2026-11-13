import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { ApiError, createApi, type Api } from '../api/client'
import type { Me } from '../api/types'
import type { SignInOptions, TokenSource } from './tokenSource'

/** `pending`: signed in, but the directory has not told us about this person yet (a fresh invitation); we keep asking.
 *  `noAccess`: signed in with an account that has no access to PhotonVox. */
type Status = 'loading' | 'signedOut' | 'ready' | 'pending' | 'noAccess' | 'error'

interface AuthState {
  status: Status
  me: Me | null
  error: string | null
  api: Api
  source: TokenSource
  /** `returnTo`: where to land after signing in (default: this page). */
  signIn: (opts?: SignInOptions, returnTo?: string) => Promise<void>
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
  const signedOutRef = useRef(() => {})

  const api = useMemo(
    () => createApi({ baseUrl, getToken: () => source.getAccessToken(), onUnauthorized: () => signedOutRef.current() }),
    [baseUrl, source],
  )

  const load = useCallback(async () => {
    if (!(await source.getAccessToken())) { setStatus('signedOut'); return }
    try {
      setMe(await api.get<Me>('/me'))
      setError(null)
      setStatus('ready')
    } catch (e) {
      const code = e instanceof ApiError ? (e.data?.code as string | undefined) : undefined
      if (code === 'access_pending') { setStatus('pending'); setPendingTries((n) => n + 1); return }
      if (code === 'no_access') { setStatus('noAccess'); return }
      // A 401 already flipped us to signedOut via onUnauthorized; anything else is a real error.
      setStatus((s) => (s === 'signedOut' ? s : 'error'))
      setError(e instanceof Error ? e.message : String(e))
    }
  }, [api, source])

  signedOutRef.current = () => { setMe(null); setStatus('signedOut') }

  useEffect(() => { void load() }, [load])
  // The directory's notice, or the next periodic pull, makes a freshly invited person known within moments: keep asking, quietly.
  useEffect(() => {
    if (status !== 'pending') return
    const t = setTimeout(() => void load(), PENDING_RETRY_MS)
    return () => clearTimeout(t)
  }, [status, pendingTries, load])

  const value: AuthState = {
    status, me, error, api, source,
    signIn: (opts, returnTo) => {
      const to = returnTo ?? location.pathname + location.search
      return opts ? source.signIn(to, opts) : source.signIn(to)
    },
    signOut: async () => { await source.signOut(); setMe(null); setStatus('signedOut') },
    refreshMe: load,
    pasteToken: async (t) => { source.paste?.(t); setStatus('loading'); await load() },
  }
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>
}
