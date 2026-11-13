/// <reference types="vite/client" />
interface ImportMetaEnv {
  readonly VITE_API_URL: string
  readonly VITE_OIDC_ISSUER: string
  readonly VITE_OIDC_CLIENT_ID: string
  readonly VITE_OIDC_AUDIENCE_PROJECT: string
  /** Where "Manage organization" goes: the PhotonID directory app. */
  readonly VITE_DIRECTORY_APP_URL?: string
  readonly VITE_DEV_TOKEN_LOGIN?: string
  readonly VITE_DEV_TOKEN?: string
}
interface ImportMeta {
  readonly env: ImportMetaEnv
}
