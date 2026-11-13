/** The web app's settings. A release image is built once and runs in any environment, so the host serves them at /config.js (deploy/web/Caddyfile writes it from the
 *  container's environment) as `window.PV_CONFIG`; a development build reads the same names from Vite's VITE_* variables. */
export interface AppConfig {
  apiUrl: string
  oidcIssuer: string
  oidcClientId: string
  oidcAudienceProject: string
  directoryAppUrl: string
}

type Raw = Partial<Record<'VITE_API_URL' | 'VITE_OIDC_ISSUER' | 'VITE_OIDC_CLIENT_ID' | 'VITE_OIDC_AUDIENCE_PROJECT' | 'VITE_DIRECTORY_APP_URL', string>>

/** `injected` wins over `vite` per name, and an empty value counts as unset (an unfilled template must not hide a development value). */
export function readConfig(injected: Raw | undefined, vite: Raw): AppConfig {
  const pick = (k: keyof Raw) => (injected?.[k] ? injected[k]! : vite[k] ?? '')
  return {
    apiUrl: pick('VITE_API_URL'), oidcIssuer: pick('VITE_OIDC_ISSUER'), oidcClientId: pick('VITE_OIDC_CLIENT_ID'),
    oidcAudienceProject: pick('VITE_OIDC_AUDIENCE_PROJECT'), directoryAppUrl: pick('VITE_DIRECTORY_APP_URL') || 'https://account.photonind.com',
  }
}

declare global { interface Window { PV_CONFIG?: Raw } }

export const config: AppConfig = readConfig(typeof window === 'undefined' ? undefined : window.PV_CONFIG, import.meta.env as unknown as Raw)
