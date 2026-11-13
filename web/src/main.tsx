import '@photon/ui/all.css'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import { App } from './App'
import './app.css'
import { AuthProvider } from './auth/AuthContext'
import { config } from './config'
import { DevTokenSource, HybridTokenSource, OidcTokenSource, type TokenSource } from './auth/tokenSource'

const env = import.meta.env
const oidc = new OidcTokenSource({
  issuer: config.oidcIssuer,
  clientId: config.oidcClientId,
  audienceProject: config.oidcAudienceProject,
  redirectUri: `${location.origin}/auth/callback`,
  postLogoutUri: `${location.origin}/`,
})
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
