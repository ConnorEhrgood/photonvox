import { describe, expect, it } from 'vitest'
import { readConfig } from './config'

const VITE = { VITE_API_URL: 'http://dev-api', VITE_OIDC_ISSUER: 'http://dev-id', VITE_OIDC_CLIENT_ID: 'dev-client', VITE_OIDC_AUDIENCE_PROJECT: 'dev-project' }

describe('web settings', () => {
  it('development reads Vite’s variables and defaults the directory app', () => {
    expect(readConfig(undefined, VITE)).toEqual({ apiUrl: 'http://dev-api', oidcIssuer: 'http://dev-id', oidcClientId: 'dev-client', oidcAudienceProject: 'dev-project', directoryAppUrl: 'https://account.photonind.com',
      directoryApiUrl: 'https://api.account.photonind.com', directoryAudienceProject: '' })
  })
  it('a release image’s injected values win, name by name; an empty one counts as unset', () => {
    const c = readConfig({ VITE_API_URL: 'https://api.vox.photonind.com', VITE_OIDC_ISSUER: '', VITE_DIRECTORY_APP_URL: 'https://account.example' }, VITE)
    expect(c.apiUrl).toBe('https://api.vox.photonind.com')
    expect(c.oidcIssuer).toBe('http://dev-id')
    expect(c.directoryAppUrl).toBe('https://account.example')
  })
  it('missing everywhere is an empty string, which the app reports as a misconfiguration rather than crashing', () => {
    expect(readConfig(undefined, {}).apiUrl).toBe('')
  })
})
