"""The vox-agent client (app/engine/agent.py), the mailer and the secrets box. The agent itself is tested in agent/tests, against this client too."""
import json

import httpx
import pytest

from app import crypto, mail
from app.config import settings
from app.engine import agent
from app.engine.agent import HttpAgent

T = "0123abcd"


def test_the_http_agent_signs_each_call_and_speaks_the_agents_operations():
    seen = []

    def handler(req):
        seen.append((req.method, req.url.path, req.headers["X-PhotonVox-Signature"], req.content))
        reply = {"/v1/check": {"found": "reached 301"}, "/v1/status": {"agent": "0.1.0"}}.get(req.url.path, {})
        return httpx.Response(200, json=reply)

    a = HttpAgent("http://engine:8780/", "s" * 40, httpx.Client(transport=httpx.MockTransport(handler)))
    a.seed_domain()
    a.clear_cache(["dialplan.x.test"])
    a.clear_cache([])
    a.rescan(["external"], ["g1"])
    a.rescan([])
    a.reload_acl()
    assert a.check("inbound", "+17245550100", "x.test", "d0", T) == "reached 301" and a.status() == {"agent": "0.1.0"}
    a.put_sound("x.test", "photonvox-" + "a" * 32 + ".wav", b"RIFF")
    assert [p for _m, p, _s, _c in seen] == ["/v1/seed-domain", "/v1/cache/delete", "/v1/rescan", "/v1/reloadacl", "/v1/check", "/v1/status", "/v1/sound"]
    assert json.loads(seen[-1][3]) == {"domain_name": "x.test", "name": "photonvox-" + "a" * 32 + ".wav", "data": "UklGRg=="}
    method, path, sig, body = seen[1]
    parts = dict(p.split("=", 1) for p in sig.split(","))
    assert sig == agent.sign("s" * 40, method, path, body, int(parts["t"]), parts["n"]) and json.loads(body) == {"keys": ["dialplan.x.test"]}
    assert len({s for _m, _p, s, _c in seen}) == len(seen) and agent.sign("k" * 40, "GET", "/v1/status", b"", 1) != agent.sign("k" * 40, "GET", "/v1/status", b"", 1)


def test_an_agent_that_refuses_is_an_error_with_its_reason():
    a = HttpAgent("http://engine:8780", "s" * 40, httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(401, json={"error": "bad signature"}))))
    with pytest.raises(agent.AgentError, match="HTTP 401 bad signature"):
        a.reload_acl()
    a = HttpAgent("http://engine:8780", "s" * 40, httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(502))))
    with pytest.raises(agent.AgentError, match="HTTP 502"):
        a.reload_acl()


def test_mail_is_not_sent_without_a_token_and_is_sent_with_one(monkeypatch):
    assert mail.send("a@b.c", "s", "b") is None
    sent = {}

    class R:
        def raise_for_status(self):
            pass

        def json(self):
            return {"MessageID": "m-1"}

    monkeypatch.setattr(settings, "postmark_token", "tok")
    monkeypatch.setattr(mail.httpx, "post", lambda url, **kw: sent.update(url=url, **kw) or R())
    assert mail.send("a@b.c", "Subject", "Body") == "m-1"
    assert sent["headers"]["X-Postmark-Server-Token"] == "tok" and sent["json"]["To"] == "a@b.c" and sent["json"]["TextBody"] == "Body"


def test_secrets_are_sealed_with_the_key_and_need_one(monkeypatch):
    monkeypatch.setattr(settings, "secrets_key", "dGVzdC1zZWNyZXRzLWtleS1mb3ItcGhvdG9udm94LTA=")
    token = crypto.seal("pw")
    assert token != "pw" and crypto.unseal(token) == "pw"
    monkeypatch.setattr(settings, "secrets_key", "")
    with pytest.raises(RuntimeError):
        crypto.seal("pw")
