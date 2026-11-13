"""The agent's side of the post-publish check and the interim SSH agent (app/engine/agent.py), the mailer and the secrets box."""
import subprocess

import pytest

from app import crypto, mail
from app.config import settings
from app.engine import agent
from app.engine.agent import SshAgent, parse

T = "0123abcd"


@pytest.mark.parametrize("log,found", [
    (f"x log(NOTICE PhotonVox-synthetic token={T} reached=301)\n", "reached 301"),
    (f"NOTICE PhotonVox-synthetic token={T} route=emergency gateways=g1,g2 dial=911)", "emergency g1,g2 911"),
    (f"NOTICE PhotonVox-synthetic token={T} route=national gateways=g1 dial=", "national g1 "),        # nothing to send: the check fails
    (f"WARNING PhotonVox blocked premium call to 19005550100 from 301 token={T})", "blocked premium"),
    ("PhotonVox-synthetic token=other reached=301", None), ("PhotonVox blocked premium call to x from y token=other", None), ("", None),
])
def test_what_a_synthetic_call_found_is_read_from_its_own_log_lines(log, found):
    assert parse(log, T) == found


class Ran:
    def __init__(self, out=""):
        self.commands, self.out = [], out

    def __call__(self, args, **kw):
        self.commands.append(args[-1])
        return subprocess.CompletedProcess(args, 0, stdout=self.out)


@pytest.fixture()
def ran(monkeypatch):
    r = Ran(f"PhotonVox-synthetic token={T} reached=301\n")
    monkeypatch.setattr(agent.subprocess, "run", r)
    return r


def test_the_ssh_agent_runs_fixed_commands_only(ran):
    a = SshAgent("root@engine", "~/k")
    a.seed_domain()
    a.clear_cache(["dialplan.x.test", "directory.100@x.test"])
    a.clear_cache([])
    a.rescan(["external"], ["g1"])
    a.rescan([])
    a.reload_acl()
    assert a.check("inbound", "+17245550100", "x.test", "d0", T) == "reached 301"
    assert a.check("route", "911", "x.test", "d0", T) == "reached 301"
    c = ran.commands
    assert "upgrade.php --defaults" in c[0] and c[1] == "cd /var/cache/fusionpbx && rm -f dialplan.x.test directory.100@x.test"
    assert "killgw g1" in c[2] and "external rescan" in c[2] and c[3] == "fs_cli -x reloadacl > /dev/null"
    assert "loopback/+17245550100/public" in c[4] and "photonvox_synthetic=inbound" in c[4]
    assert "loopback/911/x.test" in c[5] and "photonvox_synthetic=route" in c[5]


@pytest.mark.parametrize("bad", ["a b", "x;rm", "$(id)", "../etc"])
def test_nothing_unexpected_reaches_the_engines_shell(ran, bad):
    with pytest.raises(ValueError):
        SshAgent("h", "k").clear_cache([bad])
    with pytest.raises(ValueError):
        SshAgent("h", "k").check("inbound", bad, "x", "d", T)
    assert ran.commands == []


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
