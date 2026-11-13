"""Verification of access tokens issued by the shared identity provider (Zitadel).

The key resolver is injectable so tests can sign tokens with a local key; production resolves keys from
the IdP's JWKS endpoint. Algorithms are pinned to the configured list: a token cannot choose its own
(in particular never `none`).
"""
from __future__ import annotations

from typing import Any, Callable, Dict, List

import jwt

from app.config import settings


class TokenError(Exception):
    pass


class TokenVerifier:
    def __init__(self, issuer: str, audience: str, algorithms: List[str], key_resolver: Callable[[str], Any]) -> None:
        if not issuer or not audience:
            raise ValueError("issuer and audience are required")
        self.issuer = issuer
        self.audience = audience
        self.algorithms = algorithms
        self.key_resolver = key_resolver

    def verify(self, token: str) -> Dict[str, Any]:
        try:
            key = self.key_resolver(token)
            claims = jwt.decode(
                token,
                key,
                algorithms=self.algorithms,
                audience=self.audience,
                issuer=self.issuer,
                options={"require": ["exp", "iss", "aud", "sub"]},
            )
        except jwt.PyJWTError as e:
            raise TokenError(str(e)) from e
        return claims


class ResilientKeys:
    """Signing keys from the IdP's JWKS endpoint, remembered for up to `grace_s` seconds past the point the live fetch starts failing.

    PyJWKClient refreshes its cache hourly. If the IdP is down at that moment, every request would fail token verification and every signed-in
    person would be bounced to a login page that is also down. Keys rotate rarely and a token's own signature still has to verify, so
    continuing with the last good key for a signed token is safe; an unknown `kid` still fails (nothing new is trusted without the IdP).
    """

    def __init__(self, fetch: Callable[[str], Any], grace_s: int = 86_400, clock: Callable[[], float] = None) -> None:
        import time
        self._fetch, self._grace, self._clock = fetch, grace_s, clock or time.time
        self._last: Dict[str, tuple] = {}   # kid -> (key, when it was last confirmed by the IdP)

    def __call__(self, token: str) -> Any:
        kid = jwt.get_unverified_header(token).get("kid", "")
        try:
            key = self._fetch(token)
        except jwt.PyJWTError:
            known = self._last.get(kid)
            if known is not None and self._clock() - known[1] <= self._grace:
                return known[0]
            raise
        self._last[kid] = (key, self._clock())
        return key


JWKS_TIMEOUT_S = 5
_verifier: "TokenVerifier | None" = None


def default_verifier() -> TokenVerifier:
    global _verifier
    if _verifier is None:
        jwks_url = settings.oidc_jwks_url or f"{settings.oidc_issuer.rstrip('/')}/oauth/v2/keys"
        # timeout: the library's default is 30 s, and a PhotonID that accepts the connection and then says nothing would hold a request thread
        # for each sign-in that long. Five seconds, then the last good keys are used (ResilientKeys).
        client = jwt.PyJWKClient(jwks_url, cache_keys=True, lifespan=3600, timeout=JWKS_TIMEOUT_S)
        _verifier = TokenVerifier(
            settings.oidc_issuer,
            settings.oidc_audience,
            [a.strip() for a in settings.oidc_algorithms.split(",") if a.strip()],
            ResilientKeys(lambda token: client.get_signing_key_from_jwt(token).key),
        )
    return _verifier
