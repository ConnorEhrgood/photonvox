"""What the adapter needs from vox-agent on an instance (ARCHITECTURE §5), and the client that asks it (agent/vox_agent.py is the agent).
Fixed operations only; every request signed with the instance's agent secret (`X-PhotonVox-Signature: t=…,n=…,v1=…`), which vox-agent
checks for age and for a nonce seen before. Reached over the management network."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from typing import Any, Dict, Optional, Protocol, Sequence

import httpx


class Agent(Protocol):
    def seed_domain(self) -> None:
        """Run FusionPBX's own `upgrade.php --defaults`, which gives a new domain its standard dial plans (SPIKES §1c)."""

    def clear_cache(self, keys: Sequence[str]) -> None:
        """Delete these entries from FusionPBX's cache (file names under /var/cache/fusionpbx)."""

    def rescan(self, profiles: Sequence[str], kill: Sequence[str] = ()) -> None:
        """Stop these gateways (removed ones), then rescan these SIP profiles so new and changed gateways start."""

    def reload_acl(self) -> None:
        """Reload FreeSWITCH's access lists (`reloadacl`)."""

    def put_sound(self, domain_name: str, name: str, audio: bytes) -> None:
        """Write a spoken greeting (a WAV file) into the domain's recordings on the engine."""

    def check(self, kind: str, number: str, domain_name: str, domain_uuid: str, token: str) -> Optional[str]:
        """Place one synthetic call (the post-publish check) and say what it found: "reached <destination>" for an inbound number, "<route>
        <gateways> <number sent>" or "blocked <category>" for a dialed one; None if it found nothing. No phone rings and nothing leaves the engine."""


class AgentError(Exception):
    pass


def sign(secret: str, method: str, path: str, body: bytes, t: Optional[int] = None, nonce: Optional[str] = None) -> str:
    """vox-agent's signature: time, a fresh nonce (it refuses one seen before), method, path and body under the instance's secret."""
    t = int(time.time()) if t is None else t
    nonce = nonce or secrets.token_hex(12)
    return f"t={t},n={nonce},v1=" + hmac.new(secret.encode(), f"{t}.{nonce}.{method}.{path}.".encode() + body, hashlib.sha256).hexdigest()


class HttpAgent:
    """vox-agent over HTTP: `{"kind": "http", "url": "http://10.2.1.21:8780"}` in the instance's agent settings, the secret sealed beside it."""

    def __init__(self, url: str, secret: str, client: Optional[httpx.Client] = None) -> None:
        self.url, self.secret = url.rstrip("/"), secret
        self.client = client or httpx.Client(timeout=310)        # seeding a domain can take minutes on a busy engine

    def call(self, method: str, path: str, body: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        data = json.dumps(body).encode() if body is not None else b""
        r = self.client.request(method, self.url + path, content=data or None,
                                headers={"X-PhotonVox-Signature": sign(self.secret, method, path, data), "Content-Type": "application/json"})
        if r.status_code != 200:
            raise AgentError(f"vox-agent {path}: HTTP {r.status_code} {r.json().get('error', '') if r.content else ''}".strip())
        return r.json()

    def status(self) -> Dict[str, Any]:
        return self.call("GET", "/v1/status")

    def seed_domain(self) -> None:
        self.call("POST", "/v1/seed-domain", {})

    def clear_cache(self, keys: Sequence[str]) -> None:
        if keys:
            self.call("POST", "/v1/cache/delete", {"keys": list(keys)})

    def rescan(self, profiles: Sequence[str], kill: Sequence[str] = ()) -> None:
        if profiles:
            self.call("POST", "/v1/rescan", {"profiles": list(profiles), "kill": list(kill)})

    def reload_acl(self) -> None:
        self.call("POST", "/v1/reloadacl", {})

    def put_sound(self, domain_name: str, name: str, audio: bytes) -> None:
        self.call("POST", "/v1/sound", {"domain_name": domain_name, "name": name, "data": base64.b64encode(audio).decode()})

    def check(self, kind: str, number: str, domain_name: str, domain_uuid: str, token: str) -> Optional[str]:
        return self.call("POST", "/v1/check", {"kind": kind, "number": number, "domain_name": domain_name, "domain_uuid": domain_uuid,
                                               "token": token})["found"]
