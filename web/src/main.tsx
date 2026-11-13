import './tokens.css'
import './ph-base.css'
import './ph-components.css'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import { App } from './App'
import './app.css'
import { AuthProvider } from './auth/AuthContext'
import { config } from './config'
import { DevTokenSource, HybridTokenSource, OidcTokenSource, type TokenSource } from './auth/tokenSource'
import { PhotonSignIn } from './ph-auth/signin'

const env = import.meta.env
// The suite's shared sign-in. Registered at PhotonID: <origin>/auth/callback (redirect) and <origin>/auth/signed-out (post-logout).
const oidc = new OidcTokenSource(new PhotonSignIn({
  issuer: config.oidcIssuer,
  clientId: config.oidcClientId,
  audienceProject: config.oidcAudienceProject,
}))
// The paste-a-token escape hatch exists only in development builds; Vite removes this branch from production.
const source: TokenSource = import.meta.env.DEV && env.VITE_DEV_TOKEN_LOGIN ? new HybridTokenSource(oidc, new DevTokenSource()) : oidc

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <BrowserRouter>
      <AuthProvider source={source} baseUrl={config.apiUrl}>
        <App />
      </AuthProvider>
    </BrowserRouter>
  </StrictMode>,
)
