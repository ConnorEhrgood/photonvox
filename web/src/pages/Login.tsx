import { useEffect, useRef, useState } from 'react'
import { Navigate, useLocation, useNavigate } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'
import { ErrorText } from '../components/ui'
import logo from '@photon/ui/assets/photon-logo.png'

export function LoginPage() {
  const { status, signIn, source, pasteToken, error } = useAuth()
  const [token, setToken] = useState('')
  const [err, setErr] = useState<string | null>(null)
  // Where the person was headed (a scanned label opens /claim?c=...): signing in returns there, not to this page.
  const from = (useLocation().state as { from?: string } | null)?.from
  const returnTo = from && from.startsWith('/') && !from.startsWith('//') && from !== '/login' ? from : '/'
  // A deep link (a scanned label, a shared link) goes straight on to PhotonID: someone signed in there comes back without a click. Not for an error or the paste box.
  const auto = returnTo !== '/' && status === 'signedOut' && !source.supportsPaste
  const started = useRef(false)
  useEffect(() => {
    if (!auto || started.current) return
    started.current = true
    void signIn(undefined, returnTo).catch((e) => setErr(String(e)))
  }, [auto, returnTo, signIn])
  if (status === 'ready' || status === 'pending' || status === 'noAccess') return <Navigate to={returnTo} replace />
  return (
    <div className="ph-auth">
      <div className="ph-card">
        <img className="ph-auth-logo" src={logo} alt="Photon Industries" />
        <h1>PhotonVox</h1>
        <p className="ph-hint">Sign in with your PhotonID account to set up and look after phone systems.</p>
        <button className="ph-btn ph-btn-block" style={{ marginTop: '1rem' }} onClick={() => void signIn(undefined, returnTo).catch((e) => setErr(String(e)))}>
          Sign in
        </button>
        <p className="ph-hint" style={{ marginTop: '.75rem' }}>
          There is no sign-up here: your organization’s administrator adds you, and PhotonID emails you an invitation.
        </p>
        <ErrorText>{err ?? (status === 'error' ? error : null)}</ErrorText>
        {source.supportsPaste && (
          <details style={{ marginTop: '1.25rem' }}>
            <summary className="ph-hint">Developer: paste an access token</summary>
            <div className="ph-field">
              <label htmlFor="devtoken">Access token</label>
              <textarea id="devtoken" className="ph-input" rows={4} value={token} onChange={(e) => setToken(e.target.value)} />
              <button className="ph-btn ph-btn-secondary" disabled={!token.trim()} onClick={() => void pasteToken(token)}>Use token</button>
            </div>
          </details>
        )}
      </div>
    </div>
  )
}

/** The IdP redirects here with ?code=…; finish the exchange, then go where the person was headed. */
export function CallbackPage() {
  const { source, refreshMe } = useAuth()
  const nav = useNavigate()
  const [err, setErr] = useState<string | null>(null)
  useEffect(() => {
    let live = true
    source.handleCallback()
      .then(async (to) => { await refreshMe(); if (live) nav(to, { replace: true }) })
      .catch((e) => live && setErr(e instanceof Error ? e.message : String(e)))
    return () => { live = false }
  }, [source, refreshMe, nav])
  return (
    <div className="ph-auth">
      <div className="ph-card">
        {err ? (<><ErrorText>{`Sign-in failed: ${err}`}</ErrorText><a href="/login">Try again</a></>) : <p className="ph-hint">Signing you in…</p>}
      </div>
    </div>
  )
}
