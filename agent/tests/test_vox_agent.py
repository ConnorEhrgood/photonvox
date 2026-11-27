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
    "sofia xmlstatus profile internal reg": """<?xml version="1.0"?><profile><registrations>
<registration><user>100@x.test</user><contact>&lt;sip:100@192.0.2.7:5101&gt;</contact><agent>Grandstream GRP2614 1.0.11.7</agent>
<status>Registered(UDP)(unknown) exp(2026-11-14 16:48:35) expsecs(648)</status><ping-status>Reachable</ping-status>
<network-ip>192.0.2.7</network-ip><network-port>5101</network-port></registration>
<registration><user>100@y.test</user><agent>other</agent><status>Registered(UDP) expsecs(9)</status><network-ip>192.0.2.8</network-ip></registration>
</registrations></profile>""",
    "sofia xmlstatus profile external reg": "<profile><registrations></registrations></profile>",
    "show channels as json": json.dumps({"row_count": 4, "rows": [
        {"uuid": "a1", "call_uuid": "a1", "direction": "inbound", "name": "sofia/internal/100@x.test", "context": "x.test", "initial_context": "x.test",
         "cid_num": "100", "dest": "2125550123", "callee_num": "", "callstate": "ACTIVE", "presence_id": "100@x.test", "accountcode": "x.test",
         "created_epoch": "1794674261", "ip_addr": "192.0.2.7"},
        {"uuid": "a2", "call_uuid": "a1", "direction": "outbound", "name": "sofia/external/+12125550123", "context": "x.test", "cid_num": "+12125550400",
         "dest": "+12125550123", "callee_num": "+12125550123", "callstate": "ACTIVE", "presence_id": "", "created_epoch": "1794674262"},
        {"uuid": "b1", "call_uuid": "b1", "direction": "inbound", "name": "sofia/external/3105550199@10.0.0.1", "context": "x.test",
         "initial_context": "public", "cid_num": "3105550199", "dest": "2125550400", "callstate": "RINGING", "created_epoch": "1794674263"},
        {"uuid": "c1", "call_uuid": "c1", "direction": "inbound", "name": "sofia/internal/100@y.test", "context": "y.test", "presence_id": "100@y.test",
         "cid_num": "100", "dest": "101", "callstate": "ACTIVE", "created_epoch": "1794674264"}]}),
    "sofia xmlstatus gateway": f"""<gateways><gateway><name>{UUID1}</name><profile>external</profile><username>secretuser</username>
<password>yes</password><state>NOREG</state><status>UP</status><pingtime>0.00</pingtime><uptime-usec>79396114739</uptime-usec><calls-in>4</calls-in>
<calls-out>155</calls-out><failed-calls-in>0</failed-calls-in><failed-calls-out>2</failed-calls-out></gateway></gateways>""",
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
    assert FakeESL.commands[-1].endswith(",process_cdr=false}loopback/+17245550100/public &park()")       # a check is not a call: no call record
    code, r = call(agent, "POST", "/v1/check", {**body, "kind": "route", "number": "+12125550123"})
    assert code == 200 and FakeESL.commands[-1].endswith("}loopback/+12125550123/x.sip.test &park()")
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
    assert va.esl_password(str(tmp_path / "missing.xml")) == ""          # never FreeSWITCH's well-known default (VOX-B-11)
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


def test_live_reads_one_domains_phones_and_calls_and_every_gateways_health_without_addresses(agent):
    code, r = call(agent, "POST", "/v1/live", {"domain_name": "x.test"})
    assert code == 200
    assert r["registrations"] == [{"extension": "100", "agent": "Grandstream GRP2614 1.0.11.7", "expires_s": 648, "reachable": True,
                                   "profile": "internal"}]
    assert [(c["uuid"], c["call"], c["direction"], c["gateway"], c["callstate"], c["presence"], c["created"]) for c in r["channels"]] == [
        ("a1", "a1", "inbound", False, "ACTIVE", "100", 1794674261), ("a2", "a1", "outbound", True, "ACTIVE", "", 1794674262),
        ("b1", "b1", "inbound", True, "RINGING", "", 1794674263)]
    assert r["gateways"] == [{"gateway": UUID1, "profile": "external", "state": "NOREG", "status": "UP", "pingtime": 0.0, "calls_in": 4,
                              "calls_out": 155, "failed_calls_in": 0, "failed_calls_out": 2, "uptime_usec": 79396114739}]
    text = json.dumps(r)
    assert "192.0.2" not in text and "secretuser" not in text and "y.test" not in text
    assert {"sofia xmlstatus profile internal reg", "sofia xmlstatus profile external reg", "show channels as json"} <= set(FakeESL.commands)
    for bad in ({}, {"domain_name": "x.test; hupall"}, {"domain_name": "*"}):
        assert call(agent, "POST", "/v1/live", bad)[0] == 400


def test_live_with_nothing_registered_and_no_calls(agent, monkeypatch):
    monkeypatch.setitem(REPLIES, "show channels as json", '{"row_count": 0}')
    monkeypatch.setitem(REPLIES, "sofia xmlstatus profile internal reg", "")
    monkeypatch.setitem(REPLIES, "sofia xmlstatus gateway", "not xml")
    assert call(agent, "POST", "/v1/live", {"domain_name": "x.test"}) == (200, {"registrations": [], "channels": [], "gateways": []})


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
    assert va.esl_password(str(conf)) == ""


def test_photonvoxs_own_client_speaks_to_this_agent(agent):
    """The API's HttpAgent (api/app/engine/agent.py) against the real agent: the two sign the same way and agree on every operation."""
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "api"))
    from app.engine.agent import AgentError, HttpAgent
    a = HttpAgent(agent["url"], SECRET)
    a.clear_cache(["dialplan.x.test"])
    a.rescan(["external"], [UUID1])
    a.reload_acl()
    a.seed_domain()
    assert a.check("route", "19005550100", "x.sip.test", UUID1, "fedcba9876543210") == "reached 301" and a.status()["registrations"] == 2
    with pytest.raises(AgentError, match="400"):
        a.check("route", "911", "x.sip.test", UUID1, "fedcba9876543211")
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


@pytest.mark.parametrize("number", ["911", "+911", "9911", "1911", "*911", "933", "8933", "988", "+1988", "211", "311", "711", "811", "9711"])
def test_an_emergency_or_service_number_is_never_dialed_whatever_the_caller_asks(agent, number):
    """Audit VOX-B-3: the agent itself refuses, so a mistake in the control plane (or a holder of the secret) cannot place such a call."""
    before = list(FakeESL.commands)
    for kind in ("route", "inbound"):
        body = {"kind": kind, "number": number, "domain_name": "x.sip.test", "domain_uuid": UUID1, "token": "0123456789abcdef"}
        code, r = call(agent, "POST", "/v1/check", body)
        assert code == 400 and "never dialed" in r["error"]
    assert FakeESL.commands == before


@pytest.mark.parametrize("number", ["19005550100", "+17245550100", "7245550100", "100", "9112", "4111"])
def test_ordinary_numbers_are_still_checked(agent, number):
    body = {"kind": "route", "number": number, "domain_name": "x.sip.test", "domain_uuid": UUID1, "token": "0123456789abcdef"}
    assert call(agent, "POST", "/v1/check", body)[0] == 200


def test_with_a_domain_list_only_those_domains_are_served(agent):
    """VOX_AGENT_DOMAINS (audit VOX-B-3): checks, live reads, door calls and greetings for other domains are refused."""
    agent["cfg"].domains = va.Config({"VOX_AGENT_SECRET": SECRET, "VOX_AGENT_ESL_PASSWORD": "pw", "VOX_AGENT_DOMAINS": "x.test, x.sip.test"}).domains
    check = {"kind": "route", "number": "19005550100", "domain_uuid": UUID1, "token": "0123456789abcdef"}
    assert call(agent, "POST", "/v1/check", {**check, "domain_name": "x.sip.test"})[0] == 200
    for path, body in (("/v1/check", check), ("/v1/live", {}), ("/v1/door-calls", {"extension": "150", "since": 0}),
                       ("/v1/sound", {"name": "photonvox-" + "d" * 32 + ".wav", "data": ""})):
        code, r = call(agent, "POST", path, {**body, "domain_name": "other.test"})
        assert code == 400 and "not a domain PhotonVox manages" in r["error"]
    assert call(agent, "POST", "/v1/live", {"domain_name": "x.test"})[0] == 200
    with pytest.raises(SystemExit, match="VOX_AGENT_DOMAINS"):
        va.Config({"VOX_AGENT_SECRET": SECRET, "VOX_AGENT_DOMAINS": "x.test,bad domain"})


@pytest.mark.parametrize("field,value", [("domain_name", "x.sip.test\n"), ("number", "100\n"), ("token", "0123456789abcdef\n"),
                                         ("domain_uuid", UUID1 + "\n")])
def test_a_trailing_newline_is_refused(agent, field, value):
    """Audit VOX-B-17: Python's `$` matches before a final newline; the agent's patterns are matched whole."""
    body = {"kind": "route", "number": "19005550100", "domain_name": "x.sip.test", "domain_uuid": UUID1, "token": "0123456789abcdef"}
    assert call(agent, "POST", "/v1/check", {**body, field: value})[0] == 400
    assert call(agent, "POST", "/v1/cache/delete", {"keys": ["dialplan.x.test\n"]})[0] == 400


def test_without_an_event_socket_password_nothing_is_tried(agent):
    agent["cfg"].esl_password = ""
    n = len(FakeESL.commands)
    assert call(agent, "POST", "/v1/reloadacl", {}) == (500, {"error": "ConnectionError"})
    assert len(FakeESL.commands) == n


def test_a_body_is_read_only_with_a_current_signature_header_and_small_except_for_a_greeting(agent):
    """Audit VOX-B-11: an unsigned or stale request is refused before its body is read; only a greeting may be large."""
    import http.client
    host, port = agent["url"][7:].split(":")

    def send(path, length, sig=None):
        conn = http.client.HTTPConnection(host, int(port), timeout=5)
        conn.putrequest("POST", path)
        conn.putheader("Content-Length", str(length))
        if sig is not None:
            conn.putheader("X-PhotonVox-Signature", sig)
        conn.endheaders()          # the body is never sent: an answer proves it was not waited for
        return conn.getresponse().status

    assert send("/v1/cache/delete", 1000) == 401
    assert send("/v1/cache/delete", 1000, va.sign(SECRET, "POST", "/v1/cache/delete", b"", int(time.time()) - 400)) == 401
    assert send("/v1/cache/delete", va.MAX_SMALL + 1, va.sign(SECRET, "POST", "/v1/cache/delete", b"")) == 413
    assert send("/v1/sound", va.MAX_BODY + 1, va.sign(SECRET, "POST", "/v1/sound", b"")) == 413
    assert va.plausible(va.sign(SECRET, "GET", "/v1/status", b"")) and not va.plausible("t=1,n=zz,v1=x")


def test_connections_beyond_the_limit_are_closed(agent, monkeypatch):
    import socket
    srv = va.serve(agent["cfg"])
    srv.slots = threading.BoundedSemaphore(1)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    held = socket.create_connection(srv.server_address)          # takes the one slot and sends nothing
    time.sleep(0.2)
    extra = socket.create_connection(srv.server_address)
    extra.settimeout(5)
    assert extra.recv(10) == b""                                  # closed unanswered
    held.close()
    time.sleep(0.2)
    url = f"http://127.0.0.1:{srv.server_address[1]}"
    assert call({"url": url}, "GET", "/v1/status")[0] == 200      # the slot is free again
    srv.shutdown()


def _installer(tmp_path):
    """agent/install.sh with ssh, scp, chown and systemctl played locally: the engine's /etc and /opt are folders under tmp_path."""
    import subprocess
    root, bin_ = tmp_path / "engine", tmp_path / "bin"
    (root / "etc" / "systemd" / "system").mkdir(parents=True)
    bin_.mkdir()
    (bin_ / "ssh").write_text(f'#!/bin/bash\ncmd="${{@: -1}}"\ncmd="${{cmd//\\/etc\\//{root}/etc/}}"\ncmd="${{cmd//\\/opt\\//{root}/opt/}}"\nexec bash -c "$cmd"\n')
    (bin_ / "scp").write_text(f'#!/bin/bash\nsrc="${{@: -2:1}}"; dst="${{@: -1}}"; cp "$src" "{root}${{dst#*:}}"\n')
    for name in ("chown", "systemctl"):
        (bin_ / name).write_text("#!/bin/bash\n[ \"$1\" = is-active ] && echo active\nexit 0\n")
    for f in bin_.iterdir():
        f.chmod(0o755)
    env = {**os.environ, "PATH": f"{bin_}:{os.environ['PATH']}", "HOME": str(tmp_path / "home")}
    script = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "install.sh")

    def run(*args):
        return subprocess.run(["bash", script, "root@engine", "key", *args], env=env, capture_output=True, text=True, timeout=30)
    return root / "etc" / "vox-agent.env", run


def test_an_update_keeps_the_engines_settings_and_changes_only_what_it_is_given(tmp_path):
    """Audit VOX-B-7: re-running the installer on the live engine must not switch every operation back on (nor move its address or secret)."""
    envfile, run = _installer(tmp_path)
    live = "VOX_AGENT_SECRET=" + "k" * 64 + "\nVOX_AGENT_BIND=10.10.0.21:8781\nVOX_AGENT_OPERATIONS=status,cache/delete,check\nVOX_AGENT_DOMAINS=x.test\n"
    envfile.write_text(live)
    r = run()
    assert r.returncode == 0, r.stderr
    assert envfile.read_text() == live and "is kept" in r.stdout
    assert not (tmp_path / "home" / ".config").exists()                        # no local secret needed or made for an update
    r = run("", "status,cache/delete,check,door-calls")
    assert r.returncode == 0, r.stderr
    assert envfile.read_text() == live.replace("VOX_AGENT_OPERATIONS=status,cache/delete,check\n", "") + \
        "VOX_AGENT_OPERATIONS=status,cache/delete,check,door-calls\n"
    assert run("", "status,reboot").returncode != 0                             # an unknown operation is refused before anything is touched
    assert "door-calls" in envfile.read_text()
    envfile.write_text("VOX_AGENT_BIND=1.2.3.4:1\n")
    assert run().returncode != 0                                                 # a file without a secret is not "repaired"


def test_a_first_install_writes_the_secret_bind_and_operations(tmp_path):
    envfile, run = _installer(tmp_path)
    r = run("10.10.0.60:8780", "status,check")
    assert r.returncode == 0, r.stderr
    lines = envfile.read_text().splitlines()
    secret = (tmp_path / "home" / ".config" / "photonvox" / "agent-engine.secret").read_text().strip()
    assert lines == [f"VOX_AGENT_SECRET={secret}", "VOX_AGENT_BIND=10.10.0.60:8780", "VOX_AGENT_OPERATIONS=status,check"]
    assert (envfile.parent.parent / "opt" / "vox-agent" / "vox_agent.py").exists()
