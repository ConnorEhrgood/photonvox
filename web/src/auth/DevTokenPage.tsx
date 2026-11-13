import { useState } from 'react'
import { Navigate } from 'react-router-dom'
import logo from '../assets/photon-logo.png'
import { useAuth } from './AuthContext'

/** Development builds only (VITE_DEV_TOKEN_LOGIN): paste an access token instead of signing in with PhotonID. Production has no sign-in page at all:
 *  a signed-out visitor goes straight to PhotonID (App.tsx, ph-auth), and `/login` is only an old address for home. */
export function DevTokenPage() {
  const { source, status, pasteToken } = useAuth()
  const [token, setToken] = useState('')
  if (!source.supportsPaste || status === 'ready') return <Navigate to="/" replace />
  return (
    <div className="ph-auth">
      <div className="ph-card">
        <img className="ph-auth-logo" src={logo} alt="Photon" />
        <h1>Developer sign-in</h1>
        <p className="ph-hint">Development build: paste an access token, or sign in with the development PhotonID.</p>
        <div className="ph-field">
          <label htmlFor="devtoken">Access token</label>
          <textarea id="devtoken" className="ph-input" rows={4} value={token} onChange={(e) => setToken(e.target.value)} />
        </div>
        <div className="ph-actions">
          <button className="ph-btn" disabled={!token.trim()} onClick={() => void pasteToken(token)}>Use token</button>
          {source.auth && <button className="ph-btn ph-btn-secondary" onClick={() => void source.signIn('/')}>Sign in with PhotonID</button>}
        </div>
      </div>
    </div>
  )
}
