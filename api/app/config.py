from __future__ import annotations

from typing import List, Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Three database logins (the same split as the sister products): the OWNER runs migrations and nothing else; the API connects as `vox_app`,
    # to which row-level security applies; the worker and the few cross-organization paths (the directory sync, resolving a first sign-in)
    # connect as `vox_system`. Empty `migrate_database_url`: the same as `database_url` (development). Empty `system_database_url`: the same again.
    database_url: str = "postgresql+psycopg://vox_app:vox_app@localhost:5432/photonvox"
    system_database_url: str = ""
    migrate_database_url: str = ""
    # The passwords migration 0001 gives the two login roles. Empty: the role is created without a login (and must be given one by hand).
    app_db_password: str = ""
    system_db_password: str = ""

    # OIDC (PhotonID, Zitadel). PhotonVox never sees passwords; it verifies tokens issued by id.photonind.com. Tokens carry identity only.
    oidc_issuer: str = ""
    oidc_audience: str = ""
    oidc_jwks_url: str = ""  # defaults to {issuer}/oauth/v2/keys
    oidc_algorithms: str = "RS256"
    # Browser origins allowed to call the API (the web app). Comma separated; empty = none. Development: http://localhost:5183.
    cors_origins: str = ""

    # The PhotonID directory (organizations, sites, people, access). Our copy is read-only and kept by notify-then-pull.
    directory_url: str = ""                 # https://api.account.photonind.com
    directory_product: str = "vox"          # our key in the directory
    directory_client_id: str = ""
    directory_client_secret: str = ""
    # The secret the directory signs its data-free notices with (a separate secret from the client one). Two values may be listed during
    # rotation, comma separated: a notice is accepted if either matches.
    directory_notice_secret: str = ""
    directory_pull_every_s: int = 300       # a lost notice delays a change by at most this long, never loses it
    directory_resolve_timeout_s: float = 3.0
    directory_timeout_s: float = 10.0

    # Photon staff, by PhotonID subject (comma separated): the directory's person documents carry no platform flag, so staff are named here,
    # as PhotonGuard and the PhotonEdge hub do.
    platform_admin_subs: str = ""

    # Fernet key for the secrets PhotonVox keeps: engine database logins, the SIP passwords and voicemail PINs it gave phones, agent secrets.
    # Generate with `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`. Comma separated: the first
    # encrypts, all decrypt (rotation).
    secrets_key: str = ""

    # Email (Postmark, paid tier). Empty token: nothing is sent; requests to carriers stay open for staff to send by hand.
    postmark_token: str = ""
    mail_from: str = "PhotonVox <vox@photonind.com>"
    # Hickory Telephone's contact for 911 address changes (decision 31: an email per change, tracked until Hickory confirms).
    htc_e911_email: str = ""

    # Text-to-speech for greetings (decision 30): Google Cloud Text-to-Speech, an API key restricted to that API and this server's address.
    # Empty: menus are published without a spoken greeting (they answer and take keys silently) until a recording or a key is added.
    google_tts_api_key: str = ""

    environment: str = "development"

    @property
    def notice_secrets(self) -> List[str]:
        return [s.strip() for s in self.directory_notice_secret.split(",") if s.strip()]

    @property
    def platform_admins(self) -> List[str]:
        return [s.strip() for s in self.platform_admin_subs.split(",") if s.strip()]

    @property
    def cors_list(self) -> List[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    def production_safe(self) -> Optional[str]:
        """A reason this configuration is unsafe in production, or None."""
        if self.environment != "production":
            return None
        if not self.oidc_issuer or not self.oidc_audience:
            return "OIDC_ISSUER and OIDC_AUDIENCE must be set"
        if not self.directory_url.startswith("https://"):
            return "DIRECTORY_URL must be an https:// URL"
        if not self.directory_client_id or not self.directory_client_secret:
            return "DIRECTORY_CLIENT_ID and DIRECTORY_CLIENT_SECRET must be set (the directory refuses unknown products)"
        if not self.notice_secrets or any(len(s) < 32 for s in self.notice_secrets):
            return "DIRECTORY_NOTICE_SECRET must be set to a long random value (without it anyone could trigger a sync)"
        if not self.system_database_url:
            return "SYSTEM_DATABASE_URL must be set (the worker and the directory sync connect as vox_system)"
        if not self.secrets_key:
            return "SECRETS_KEY must be set (engine credentials and phones' SIP passwords are kept encrypted with it)"
        if not self.cors_list:
            return "CORS_ORIGINS must list the web app's origin"
        if any(not o.startswith("https://") for o in self.cors_list):
            return "CORS_ORIGINS must contain only https:// origins in production"
        return None


settings = Settings()
