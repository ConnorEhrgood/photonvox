"""vox-agent end to end: its HTTP server on a free port, a fake FreeSWITCH event socket, a temporary cache directory and log. Signatures,
replay and skew, every operation, and that nothing outside the fixed patterns reaches FreeSWITCH."""
import json
import os
import socketserver
import sys
import threading
import time
import urllib.error
import urllib.request

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import vox_agent as va  # noqa: E402

SECRET = "s" * 40
UUID1 = "6f3212f7-3e30-496b-96b6-2d6b083a4d87"
REPLIES = {
    "version": "FreeSWITCH Version 1.11.1-release+git~20260526T204126Z~c2c59645f6~64bit\n",
    "uptime s": "3600\n",
    "sofia status": "  Name  Type  Data  State\n  external  profile  sip:mod_sofia@10.10.0.60:5080  RUNNING (0)\n  internal  profile  sip:mod_sofia@10.10.0.60:5060  RUNNING (0)\n",
    "sofia status gateway": f"Profile::Gateway-Name\tData\tState\n external::{UUID1}\tsip:x@10.10.0.80:5071\tNOREG\t0.00\n",
    "show registrations count": "2 total.\n",
    "reloadacl": "+OK acl reloaded\n",
}


class FakeESL(socketserver.StreamRequestHandler):
    commands: list = []
    password = "ClueCon"

    def handle(self):
        self.wfile.write(b"Content-Type: auth/request\n\n")
        line = self.rfile.readline().decode().strip()
        self.rfile.readline()
        ok = line == f"auth {self.password}"
        self.wfile.write(f"Content-Type: command/reply\nReply-Text: {'+OK accepted' if ok else '-ERR invalid'}\n\n".encode())
        if not ok:
            return
        cmd = self.rfile.readline().decode().strip()[4:]
        self.rfile.readline()
        FakeESL.commands.append(cmd)
        if cmd.startswith("originate"):
            token = cmd.split("photonvox_token=")[1].split(",")[0]
            with open(os.environ["FAKE_LOG"], "a") as f:
                f.write(f"x log(NOTICE PhotonVox-synthetic token={token} reached=301)\n")
        body = REPLIES.get(cmd, "+OK\n").encode()
        self.wfile.write(f"Content-Type: api/response\nContent-Length: {len(body)}\n\n".encode() + body)


@pytest.fixture()
def agent(tmp_path, monkeypatch):
    FakeESL.commands = []
    esl = socketserver.ThreadingTCPServer(("127.0.0.1", 0), FakeESL)
    threading.Thread(target=esl.serve_forever, daemon=True).start()
    log = tmp_path / "freeswitch.log"
    log.write_text("")
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / "dialplan.x.test").write_text("cached")
    php = tmp_path / "php"
    php.write_text("#!/bin/sh\necho \"$@\" > \"$(dirname \"$0\")/php.ran\"\n")
    php.chmod(0o755)
    monkeypatch.setenv("FAKE_LOG", str(log))
    conf = tmp_path / "event_socket.conf.xml"
    conf.write_text('<configuration><settings><param name="password" value="ClueCon"/></settings></configuration>')
    cfg = va.Config({"VOX_AGENT_SECRET": SECRET, "VOX_AGENT_BIND": "127.0.0.1:0", "VOX_AGENT_ESL": f"127.0.0.1:{esl.server_address[1]}",
                     "VOX_AGENT_ESL_CONF": str(conf), "VOX_AGENT_CACHE": str(cache), "VOX_AGENT_LOG": str(log),
                     "VOX_AGENT_FUSIONPBX": str(tmp_path), "VOX_AGENT_PHP": str(php)})
    srv = va.serve(cfg)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield {"url": f"http://127.0.0.1:{srv.server_address[1]}", "cache": cache, "tmp": tmp_path, "cfg": cfg}
    srv.shutdown()
    esl.shutdown()


def call(a, method, path, body=None, secret=SECRET, t=None, sig=None):
    data = json.dumps(body).encode() if body is not None else b""
    req = urllib.request.Request(a["url"] + path, data=data or None, method=method)
    req.add_header("X-PhotonVox-Signature", sig or va.sign(secret, method, path, data, t))
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def test_status_reports_freeswitch_profiles_gateways_and_registrations(agent):
    code, s = call(agent, "GET", "/v1/status")
    assert code == 200 and s["agent"] == va.VERSION and "1.11.1" in s["freeswitch"] and s["uptime_s"] == 3600
    assert s["profiles"] == [{"name": "external", "state": "RUNNING"}, {"name": "internal", "state": "RUNNING"}]
    assert s["gateways"] == [{"profile": "external", "gateway": UUID1, "state": "NOREG"}] and s["registrations"] == 2


def test_cache_entries_are_deleted_by_name_only(agent):
    assert call(agent, "POST", "/v1/cache/delete", {"keys": ["dialplan.x.test", "directory.100@x.test"]}) == (200, {"deleted": 1})
    assert not (agent["cache"] / "dialplan.x.test").exists()
    for bad in (["../etc/passwd"], ["a b"], ["x;rm -rf /"], "dialplan.x.test", [1]):
        code, r = call(agent, "POST", "/v1/cache/delete", {"keys": bad})
        assert code == 400 and "keys" in r["error"]


def test_rescan_kills_removed_gateways_then_rescans(agent):
    assert call(agent, "POST", "/v1/rescan", {"profiles": ["external"], "kill": [UUID1]})[0] == 200
    assert FakeESL.commands == [f"sofia profile external killgw {UUID1}", "sofia profile external rescan"]
    assert call(agent, "POST", "/v1/rescan", {"profiles": ["external; status"]})[0] == 400
    assert call(agent, "POST", "/v1/rescan", {"profiles": ["external"], "kill": ["not-a-uuid"]})[0] == 400


def test_reloadacl_and_seeding_run_their_fixed_commands(agent):
    assert call(agent, "POST", "/v1/reloadacl", {}) == (200, {"result": "+OK acl reloaded"})
    assert call(agent, "POST", "/v1/seed-domain", {}) == (200, {"seeded": True})
    assert (agent["tmp"] / "php.ran").read_text().strip() == "core/upgrade/upgrade.php --defaults"


def test_a_failed_seed_says_what_kind_of_failure_only(agent):
    (agent["tmp"] / "php").write_text("#!/bin/sh\nexit 3\n")
    assert call(agent, "POST", "/v1/seed-domain", {}) == (500, {"error": "RuntimeError"})


def test_a_synthetic_call_reports_what_it_found(agent):
    body = {"kind": "inbound", "number": "+17245550100", "domain_name": "x.sip.test", "domain_uuid": UUID1, "token": "0123456789abcdef"}
    assert call(agent, "POST", "/v1/check", body) == (200, {"found": "reached 301"})
    assert FakeESL.commands[-1].startswith("originate {photonvox_synthetic=inbound,photonvox_token=0123456789abcdef,")
    assert FakeESL.commands[-1].endswith("}loopback/+17245550100/public &park()")
    code, r = call(agent, "POST", "/v1/check", {**body, "kind": "route", "number": "911"})
    assert code == 200 and FakeESL.commands[-1].endswith("}loopback/911/x.sip.test &park()")
    for field, bad in (("kind", "shell"), ("number", "911;status"), ("domain_name", "X Y"), ("domain_uuid", "x"), ("token", "zz")):
        assert call(agent, "POST", "/v1/check", {**body, field: bad})[0] == 400


def test_a_synthetic_call_that_finds_nothing_says_so(agent, monkeypatch):
    monkeypatch.setattr(va, "esl_api", lambda cfg, cmd, timeout=30.0: "+OK\n")
    body = {"kind": "inbound", "number": "+17245550100", "domain_name": "x.sip.test", "domain_uuid": UUID1, "token": "0123456789abcdef"}
    assert va.check(agent["cfg"], body, wait_s=0.3) == {"found": None}


@pytest.mark.parametrize("log,found", [
    ("PhotonVox-synthetic token=abc route=emergency gateways=g1 dial=911)", "emergency g1 911"),
    ("PhotonVox blocked premium call to 1 from 2 token=abc", "blocked premium"),
    ("PhotonVox-synthetic token=other reached=1", None),
])
def test_log_lines_are_read_for_the_calls_own_token(log, found):
    assert va.parse(log, "abc") == found


def test_unsigned_wrongly_signed_stale_future_and_replayed_requests_are_refused(agent):
    assert call(agent, "GET", "/v1/status", sig="nonsense")[0] == 401
    assert call(agent, "GET", "/v1/status", secret="x" * 40)[0] == 401
    assert call(agent, "GET", "/v1/status", t=int(time.time()) - 400)[0] == 401
    assert call(agent, "GET", "/v1/status", t=int(time.time()) + 400)[0] == 401
    sig = va.sign(SECRET, "GET", "/v1/status", b"")
    assert call(agent, "GET", "/v1/status", sig=sig)[0] == 200
    assert call(agent, "GET", "/v1/status", sig=sig)[0] == 401                      # the same signature twice
    assert call(agent, "POST", "/v1/status", {}, sig=va.sign(SECRET, "GET", "/v1/status", b"{}"))[0] == 401   # signed for another method
    assert call(agent, "GET", "/v1/status", sig=sig.replace(",n=", ",x="))[0] == 401                         # no nonce
    t = int(time.time())
    bad = va.sign(SECRET, "GET", "/v1/status", b"", t, "zz")                                                  # a nonce that is not hex
    assert call(agent, "GET", "/v1/status", sig=bad)[0] == 401


def test_two_identical_requests_in_the_same_second_are_both_accepted(agent):
    t = int(time.time())
    for _ in range(2):          # a publish's cache delete and its republish's, the same keys in the same second: not a replay
        assert call(agent, "POST", "/v1/cache/delete", {"keys": ["dialplan.x.test"]}, t=t)[0] == 200


def test_unknown_operations_bad_bodies_and_large_bodies(agent):
    assert call(agent, "GET", "/v1/nothing")[0] == 404
    assert call(agent, "POST", "/v1/reloadacl", [1])[0] == 400
    import http.client       # a body declared over the 8 MB a greeting may take is refused before it is read
    host, port = agent["url"][7:].split(":")
    conn = http.client.HTTPConnection(host, int(port), timeout=5)
    conn.putrequest("POST", "/v1/cache/delete")
    conn.putheader("Content-Length", str(9 * 1024 * 1024))
    conn.endheaders()
    assert conn.getresponse().status == 413


def test_the_replay_window_forgets_old_signatures():
    r = va.Replay()
    assert r.first("a", 1000) and not r.first("a", 1000)
    assert r.first("b", 1000 + 2 * va.SKEW_S + 1) and r.first("a", 1000 + 2 * va.SKEW_S + 1)


def test_configuration(tmp_path):
    with pytest.raises(SystemExit):
        va.Config({"VOX_AGENT_SECRET": "short"})
    assert va.esl_password(str(tmp_path / "missing.xml")) == "ClueCon"
    cfg = va.Config({"VOX_AGENT_SECRET": SECRET, "VOX_AGENT_ESL_PASSWORD": "pw"})
    assert cfg.bind == ("127.0.0.1", 8780) and cfg.esl_password == "pw" and cfg.cache == "/var/cache/fusionpbx"


def test_an_adopted_engine_allows_only_status_the_cache_and_checks(agent):
    agent["cfg"].operations = va.Config({"VOX_AGENT_SECRET": SECRET, "VOX_AGENT_ESL_PASSWORD": "pw",
                                         "VOX_AGENT_OPERATIONS": "status, cache/delete,check"}).operations
    assert call(agent, "GET", "/v1/status")[0] == 200
    assert call(agent, "POST", "/v1/cache/delete", {"keys": ["dialplan.x.test"]})[0] == 200
    for path, body in (("/v1/seed-domain", {}), ("/v1/rescan", {"profiles": ["external"], "kill": []}), ("/v1/reloadacl", {}),
                       ("/v1/sound", {"domain_name": "x.test", "name": "a.wav", "data": ""})):
        assert call(agent, "POST", path, body) == (404, {"error": "no such operation"})
    assert not (agent["tmp"] / "php.ran").exists()
    for bad in ("status,reboot", " , "):
        with pytest.raises(SystemExit, match="VOX_AGENT_OPERATIONS"):
            va.Config({"VOX_AGENT_SECRET": SECRET, "VOX_AGENT_ESL_PASSWORD": "pw", "VOX_AGENT_OPERATIONS": bad})
    assert len(va.Config({"VOX_AGENT_SECRET": SECRET, "VOX_AGENT_ESL_PASSWORD": "pw"}).operations) == len(va.ROUTES)


def test_a_door_stations_calls_are_read_from_its_own_log_lines(agent, tmp_path):
    log = agent["cfg"].log
    A, B = "0b5e8c1a-0000-4000-8000-00000000c001", "0b5e8c1a-0000-4000-8000-00000000c002"
    N = "2026-11-14 02:57:24.422119 81.03% [NOTICE] mod_commands.c:7227"
    with open(log, "a") as f:
        f.write(f"{A} {N} PhotonVox-door domain=x.test door=701 call={A} started=1000\n"
                f"{A} Dialplan: sofia/internal/701@x.test Action log(NOTICE PhotonVox-door domain=x.test door=701 call={A} started=999)\n"
                f"{N} PhotonVox-door domain=x.test door=701 call={A} answered=1005 callee=101\n"
                f"{N} PhotonVox-door domain=x.test door=701 call={A} answered=1006 callee=102\n"
                f"{B} {N} PhotonVox-door domain=x.test door=701 call={B} started=2000\n"
                f"{N} PhotonVox-door domain=y.test door=701 call={B} answered=2001 callee=2125550123\n"
                f"{N} PhotonVox-door domain=x.test door=702 call={B} answered=2002 callee=2125550123\n")
    code, r = call(agent, "POST", "/v1/door-calls", {"domain_name": "x.test", "extension": "701", "since": 0})
    assert code == 200 and r["calls"] == [{"call": A, "started": 1000, "answered": 1005, "callee": "101"},
                                          {"call": B, "started": 2000, "answered": None, "callee": None}]
    assert call(agent, "POST", "/v1/door-calls", {"domain_name": "x.test", "extension": "701", "since": 1500})[1]["calls"][0]["call"] == B
    for bad in ({"domain_name": "x.test", "extension": "701", "since": "1"}, {"domain_name": "x.test", "extension": "701", "since": True},
                {"domain_name": "x.test", "extension": "9; x", "since": 0}, {"domain_name": "x.test", "extension": "701", "since": -1}):
        assert call(agent, "POST", "/v1/door-calls", bad)[0] == 400


def test_a_line_written_just_before_the_log_rotated_is_still_read(tmp_path):
    log = tmp_path / "freeswitch.log"
    (tmp_path / "freeswitch.log.1").write_text("old " * 10 + "PhotonVox-synthetic token=abc reached=100\n")
    log.write_text("new line\n")
    assert "token=abc reached=100" in va._tail(str(log), 4096) and va._tail(str(log), 4096).endswith("new line\n")
    assert va._tail(str(log), 9) == "new line\n"                          # the current file alone when it is long enough
    (tmp_path / "freeswitch.log.1").unlink()
    assert va._tail(str(log), 4096) == "new line\n"


def test_a_wrong_event_socket_password_is_an_error(agent):
    agent["cfg"].esl_password = "wrong"
    assert call(agent, "POST", "/v1/reloadacl", {}) == (500, {"error": "ConnectionError"})


def test_an_event_socket_that_closes_is_an_error_and_blank_lines_between_messages_are_skipped(tmp_path):
    class Closing(socketserver.StreamRequestHandler):
        def handle(self):
            self.wfile.write(b"\nContent-Type: auth/request\n\n")       # a stray blank line first, then it hangs up

    srv = socketserver.ThreadingTCPServer(("127.0.0.1", 0), Closing)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    cfg = va.Config({"VOX_AGENT_SECRET": SECRET, "VOX_AGENT_ESL": f"127.0.0.1:{srv.server_address[1]}", "VOX_AGENT_ESL_PASSWORD": "pw"})
    with pytest.raises(ConnectionError):
        va.esl_api(cfg, "status")
    srv.shutdown()


def test_the_password_is_read_from_the_event_socket_configuration(tmp_path):
    conf = tmp_path / "c.xml"
    conf.write_text('<c><settings><param name="listen-ip" value="127.0.0.1"/><param name="password" value="Secret1"/></settings></c>')
    assert va.esl_password(str(conf)) == "Secret1"
    conf.write_text('<c><settings><param name="listen-ip" value="127.0.0.1"/></settings></c>')
    assert va.esl_password(str(conf)) == "ClueCon"


def test_photonvoxs_own_client_speaks_to_this_agent(agent):
    """The API's HttpAgent (api/app/engine/agent.py) against the real agent: the two sign the same way and agree on every operation."""
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "api"))
    from app.engine.agent import AgentError, HttpAgent
    a = HttpAgent(agent["url"], SECRET)
    a.clear_cache(["dialplan.x.test"])
    a.rescan(["external"], [UUID1])
    a.reload_acl()
    a.seed_domain()
    assert a.check("route", "911", "x.sip.test", UUID1, "fedcba9876543210") == "reached 301" and a.status()["registrations"] == 2
    with pytest.raises(AgentError, match="401"):
        HttpAgent(agent["url"], "x" * 40).reload_acl()


def test_a_spoken_greeting_is_written_whole_into_the_domains_recordings(agent, tmp_path):
    import base64
    agent["cfg"].recordings = str(tmp_path / "recordings")
    wav = b"RIFF\x24\x00\x00\x00WAVEfmt " + b"\x00" * 28
    name = "photonvox-" + "a" * 32 + ".wav"
    body = {"domain_name": "x.sip.test", "name": name, "data": base64.b64encode(wav).decode()}
    assert call(agent, "POST", "/v1/sound", body) == (200, {"written": name, "bytes": len(wav)})
    assert (tmp_path / "recordings" / "x.sip.test" / name).read_bytes() == wav
    assert not list((tmp_path / "recordings" / "x.sip.test").glob("*.part"))
    for bad in ({"name": "../../etc/passwd"}, {"name": "photonvox-x.wav"}, {"domain_name": "../x"}, {"data": "not base64!"},
                {"data": base64.b64encode(b"ID3 an mp3").decode()}, {"data": 7}):
        assert call(agent, "POST", "/v1/sound", {**body, **bad})[0] == 400


def test_a_greeting_over_the_size_limit_is_refused(agent, monkeypatch):
    import base64
    monkeypatch.setattr(va, "MAX_SOUND", 100)
    wav = b"RIFF\x24\x00\x00\x00WAVE" + b"\x00" * 200
    assert call(agent, "POST", "/v1/sound", {"domain_name": "x.sip.test", "name": "photonvox-" + "b" * 32 + ".wav",
                                             "data": base64.b64encode(wav).decode()})[0] == 400


def test_a_negative_or_unreadable_length_is_refused_before_anything_is_read(agent):
    import http.client
    host, port = agent["url"][7:].split(":")
    for value in ("-5", "lots"):
        conn = http.client.HTTPConnection(host, int(port), timeout=5)
        conn.putrequest("POST", "/v1/reloadacl")
        conn.putheader("Content-Length", value)
        conn.endheaders()
        assert conn.getresponse().status == 400


@pytest.mark.parametrize("domain", ["..", "x..y", ".x", "x.", "x", "-x.test", "x_y.test"])
def test_a_domain_that_is_not_a_dotted_name_is_refused(agent, domain):
    import base64
    body = {"domain_name": domain, "name": "photonvox-" + "c" * 32 + ".wav", "data": base64.b64encode(b"RIFF\x00\x00\x00\x00WAVE").decode()}
    assert call(agent, "POST", "/v1/sound", body)[0] == 400
