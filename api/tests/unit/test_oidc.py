"""Token verification: CRITICAL. A token must be signed by the issuer's key, for us, unexpired, with a subject; and cannot choose its algorithm."""
from datetime import datetime, timedelta, timezone

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

import app.oidc as oidc
from app.config import settings
from app.oidc import ResilientKeys, TokenError, TokenVerifier

KEY, OTHER = rsa.generate_private_key(public_exponent=65537, key_size=2048), rsa.generate_private_key(public_exponent=65537, key_size=2048)
V = TokenVerifier("https://idp", "gd", ["RS256"], lambda _t: KEY.public_key())


def tok(key=KEY, **over):
    claims = {"sub": "u1", "iss": "https://idp", "aud": "gd", "exp": datetime.now(timezone.utc) + timedelta(minutes=5)}
    claims.update(over)
    return jwt.encode({k: v for k, v in claims.items() if v is not None}, key, algorithm="RS256")


def test_a_valid_token_verifies():
    assert V.verify(tok())["sub"] == "u1"


@pytest.mark.parametrize("bad", [
    lambda: tok(key=OTHER), lambda: tok(iss="https://evil"), lambda: tok(aud="other"),
    lambda: tok(exp=datetime.now(timezone.utc) - timedelta(minutes=1)), lambda: tok(sub=None), lambda: "not-a-jwt",
])
def test_bad_tokens_are_rejected(bad):
    with pytest.raises(TokenError):
        V.verify(bad())


def test_alg_none_and_hs256_confusion_are_rejected():
    forged = jwt.encode({"sub": "u1", "iss": "https://idp", "aud": "gd", "exp": datetime.now(timezone.utc) + timedelta(minutes=5)}, key=None, algorithm="none")
    with pytest.raises(TokenError):
        V.verify(forged)
    pem = KEY.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
    try:
        hs = jwt.encode({"sub": "u1", "iss": "https://idp", "aud": "gd", "exp": datetime.now(timezone.utc) + timedelta(minutes=5)}, pem, algorithm="HS256")
    except Exception:
        return    # the library refuses to build the forgery: fine
    with pytest.raises(TokenError):
        V.verify(hs)


def test_a_verifier_needs_an_issuer_and_an_audience():
    for issuer, audience in (("", "gd"), ("https://idp", "")):
        with pytest.raises(ValueError):
            TokenVerifier(issuer, audience, ["RS256"], lambda t: None)


def test_signing_keys_survive_an_idp_outage_but_never_trust_anything_new():
    now, up = [1000.0], [True]

    def fetch(token):
        if not up[0]:
            raise jwt.PyJWKClientConnectionError("IdP unreachable")
        return "KEY-" + jwt.get_unverified_header(token)["kid"]
    make = lambda kid: jwt.encode({"sub": "x"}, "secret", algorithm="HS256", headers={"kid": kid})
    keys = ResilientKeys(fetch, grace_s=100, clock=lambda: now[0])
    assert keys(make("a")) == "KEY-a"
    up[0] = False
    now[0] += 60
    assert keys(make("a")) == "KEY-a"                      # outage: the last good key keeps working
    with pytest.raises(jwt.PyJWTError):
        keys(make("never-seen"))                           # a key we never confirmed is not invented
    now[0] += 100
    with pytest.raises(jwt.PyJWTError):
        keys(make("a"))                                    # the grace ends
    up[0] = True
    assert keys(make("a")) == "KEY-a"                      # and it recovers by itself


def test_resilient_keys_use_the_real_clock_by_default():
    keys = ResilientKeys(lambda t: "K")
    assert keys(jwt.encode({"sub": "x"}, "secret", algorithm="HS256", headers={"kid": "k"})) == "K"


def test_the_default_verifier_reads_the_settings_asks_the_idp_with_a_timeout_and_is_built_once(monkeypatch):
    monkeypatch.setattr(oidc, "_verifier", None)
    monkeypatch.setattr(settings, "oidc_issuer", "https://id.example/")
    monkeypatch.setattr(settings, "oidc_audience", "gd")
    monkeypatch.setattr(settings, "oidc_jwks_url", "")
    made = {}
    real = oidc.jwt.PyJWKClient
    monkeypatch.setattr(oidc.jwt, "PyJWKClient", lambda *a, **k: made.setdefault("client", real(*a, **k)))
    v = oidc.default_verifier()
    assert v is oidc.default_verifier()
    assert made["client"].uri == "https://id.example/oauth/v2/keys" and made["client"].timeout == 5
    assert (v.issuer, v.audience, v.algorithms) == ("https://id.example/", "gd", ["RS256"])


def test_an_explicit_jwks_url_and_algorithm_list_are_honoured(monkeypatch):
    monkeypatch.setattr(oidc, "_verifier", None)
    monkeypatch.setattr(settings, "oidc_issuer", "https://id.example")
    monkeypatch.setattr(settings, "oidc_audience", "gd")
    monkeypatch.setattr(settings, "oidc_jwks_url", "https://id.example/keys.json")
    monkeypatch.setattr(settings, "oidc_algorithms", "RS256, ES256")
    made = {}
    real = oidc.jwt.PyJWKClient
    monkeypatch.setattr(oidc.jwt, "PyJWKClient", lambda *a, **k: made.setdefault("client", real(*a, **k)))
    assert oidc.default_verifier().algorithms == ["RS256", "ES256"] and made["client"].uri == "https://id.example/keys.json"
    monkeypatch.setattr(oidc, "_verifier", None)
