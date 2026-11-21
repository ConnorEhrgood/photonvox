// GENERATED from @photon/ui by scripts/sync-vendored.mjs. Do not edit here: change photon-ui, then re-run it. photon-ui 031c370e5fa1
/**
 * The few screens sign-in may need, the same in every product (`ph-auth` card), and the three route pieces that drive `PhotonSignIn`.
 * There is deliberately no sign-in page and no signed-out page: see signin.ts.
 */
import { useEffect, useRef, useState, type ReactNode } from 'react'
import { SignInError, currentPath, type PhotonSignIn } from './signin'

interface Common {
  /** The Photon logo (each product imports its own copy of the asset). */
  logo?: string
}

function Card({ logo, title, children, busy }: Common & { title: string; children?: ReactNode; busy?: boolean }) {
  return (
    <div className="ph-auth">
      <div className="ph-card" role={busy ? 'status' : undefined} aria-live={busy ? 'polite' : undefined}>
        {logo && <img className="ph-auth-logo" src={logo} alt="Photon" />}
        <h1>{busy && <span className="ph-spinner" aria-hidden="true" />}{busy ? ' ' : ''}{title}</h1>
        {children}
      </div>
    </div>
  )
}

function Actions({ children }: { children: ReactNode }) {
  return <div className="ph-actions" style={{ marginTop: '1.25rem', flexWrap: 'wrap' }}>{children}</div>
}

/** Shown for the moment it takes the browser to leave for PhotonID (or to come back from it). */
export function SigningIn({ logo, title = 'Signing you in', hint = 'One moment, PhotonID is checking who you are.' }: Common & { title?: string; hint?: string }) {
  return <Card logo={logo} title={title} busy><p className="ph-hint">{hint}</p></Card>
}

/** Sign-in did not work (PhotonID refused, the product's API refused the new token, a stale link). Never redirects by itself. */
export function SignInProblem({ logo, detail, onRetry, onSignOut }: Common & { detail?: string | null; onRetry: () => void; onSignOut?: () => void }) {
  return (
    <Card logo={logo} title="We couldn't sign you in">
      <p>Signing in with PhotonID did not finish. Try again; if it keeps happening, sign out and sign in with another account, or tell Photon support.</p>
      {detail && <p className="ph-hint">Details: {detail}</p>}
      <Actions>
        <button className="ph-btn" onClick={onRetry}>Try again</button>
        {onSignOut && <button className="ph-btn ph-btn-secondary" onClick={onSignOut}>Sign out</button>}
      </Actions>
    </Card>
  )
}

/** Signed in, and the product is still being told about the person (a moment after an invitation). The product checks again on its own. */
export function AccessPending({ logo, product, onSignOut }: Common & { product: string; onSignOut: () => void }) {
  return (
    <Card logo={logo} title={`Setting up your access to ${product}`} busy>
      <p>Your organization has just given you access. It usually takes a few seconds to reach {product}; this page checks again by itself.</p>
      <Actions><button className="ph-btn ph-btn-secondary" onClick={onSignOut}>Sign out</button></Actions>
    </Card>
  )
}

/** Signed in, and the product refuses this account (no access, or the account is disabled). Sign out is the way forward. */
export function NoAccess({ logo, product, detail, onSignOut }: Common & { product: string; detail?: string | null; onSignOut: () => void }) {
  return (
    <Card logo={logo} title={`No access to ${product}`}>
      <p>{detail || `This PhotonID account has no access to ${product}. Ask an administrator of your organization to give you access, or sign in with another account.`}</p>
      <Actions><button className="ph-btn" onClick={onSignOut}>Sign out</button></Actions>
    </Card>
  )
}

/** Wrap what needs a session. `signedIn` comes from the product (null while it is still finding out). Signed out: straight to PhotonID. */
export function RequireSignIn({ auth, signedIn, logo, children }: Common & { auth: PhotonSignIn; signedIn: boolean | null; children: ReactNode }) {
  const [err, setErr] = useState<string | null>(null)
  useEffect(() => {
    if (signedIn === false) auth.signIn(currentPath()).catch((e) => setErr(e instanceof Error ? e.message : String(e)))
  }, [auth, signedIn])
  if (err) return <SignInProblem logo={logo} detail={err} onRetry={() => { setErr(null); window.location.reload() }} />
  if (signedIn) return <>{children}</>
  return <SigningIn logo={logo} title={signedIn === null ? 'Loading' : 'Signing you in'} />
}

/** The `/auth/callback` route. `onSignedIn(path)` loads the product's own view of the person, then navigates there. */
export function CallbackRoute({ auth, logo, onSignedIn }: Common & { auth: PhotonSignIn; onSignedIn: (returnTo: string) => void | Promise<void> }) {
  const [err, setErr] = useState<SignInError | Error | null>(null)
  const done = useRef(onSignedIn)
  done.current = onSignedIn
  useEffect(() => {
    let live = true
    auth.handleCallback()
      .then((to) => live && done.current(to))
      .catch((e) => live && setErr(e instanceof Error ? e : new Error(String(e))))
    return () => { live = false }
  }, [auth])
  if (err) {
    const detail = err instanceof SignInError ? err.code : err.message
    const signOut = () => auth.signOut().catch((e) => setErr(new Error(`Sign-out did not complete (${e instanceof Error ? e.message : String(e)}). Try again.`)))
    return <SignInProblem logo={logo} detail={detail} onRetry={() => void auth.signIn('/')} onSignOut={() => void signOut()} />
  }
  return <SigningIn logo={logo} />
}

/** The `/auth/signed-out` route (PhotonID's post-logout address): straight on to the sign-in form. */
export function SignedOutRoute({ auth, logo }: Common & { auth: PhotonSignIn }) {
  const [err, setErr] = useState<string | null>(null)
  useEffect(() => { auth.afterSignOut().catch((e) => setErr(e instanceof Error ? e.message : String(e))) }, [auth])
  if (err) return <SignInProblem logo={logo} detail={err} onRetry={() => void auth.signIn('/', { prompt: 'login' })} />
  return <SigningIn logo={logo} title="Signed out" hint="Taking you to the PhotonID sign-in page." />
}
