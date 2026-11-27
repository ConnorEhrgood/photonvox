#!/usr/bin/env python3
"""vox-agent: PhotonVox's agent on a FusionPBX engine (ARCHITECTURE §5). Fixed operations only, each request signed; the event socket never
leaves the host. Python 3 standard library only (Debian 12's), run by systemd as www-data, the user that owns FusionPBX's cache and logs.

Operations (JSON over HTTP, on the management network only):
    GET  /v1/status          FreeSWITCH's version and uptime, its SIP profiles and gateways, the registration count
    POST /v1/cache/delete    {"keys": [file names under the cache directory]}
    POST /v1/rescan          {"profiles": [...], "kill": [gateway uuids]}: stop removed gateways, rescan the profiles
    POST /v1/reloadacl       {}
    POST /v1/seed-domain     {}: FusionPBX's own `upgrade.php --defaults` (a new domain's standard dial plans)
    POST /v1/sound           {"domain_name", "name": "photonvox-<hash>.wav", "data": base64 WAV}: a spoken greeting into the domain's recordings
    POST /v1/door-calls      {"domain_name", "extension", "since": unix seconds}: what a door station's calls logged since then (read only):
                             {"calls": [{"call", "started", "answered", "callee"}]} (PhotonEntry's door-calls, through PhotonVox)
    POST /v1/live            {"domain_name"}: right now, read only: the domain's registrations (extension, the phone's name for itself, seconds
                             until it must register again; never its address), its calls' channels, and every gateway's health
                             (PhotonVox's dashboard)
    POST /v1/check           {"kind": "inbound"|"route", "number", "domain_name", "domain_uuid", "token"}: one synthetic call of the
                             post-publish check; answers {"found": "reached 301" | "<route> <gateways> <number sent>" | "blocked <category>" | null}

Every request carries `X-PhotonVox-Signature: t=<unix seconds>,n=<random hex nonce>,v1=<hex HMAC-SHA256(secret,
"<t>.<n>.<METHOD>.<path>.<body>")>`. A signature older or newer than five minutes, or whose nonce was seen before, is refused. Nothing the caller sends reaches a shell: values are checked against fixed patterns and
passed to FreeSWITCH or to programs as arguments.

Configuration (environment, from /etc/vox-agent.env): VOX_AGENT_SECRET (required, 32+ characters), VOX_AGENT_BIND (default 127.0.0.1:8780),
and optionally VOX_AGENT_ESL (host:port), VOX_AGENT_ESL_PASSWORD (default: read from FreeSWITCH's event_socket.conf.xml; when neither gives
one, every operation that needs the event socket fails rather than trying FreeSWITCH's well-known default), VOX_AGENT_CACHE, VOX_AGENT_LOG,
VOX_AGENT_FUSIONPBX, VOX_AGENT_PHP, VOX_AGENT_OPERATIONS: the operations this engine allows, comma-separated (default all), and
VOX_AGENT_DOMAINS: the domains PhotonVox manages here, comma-separated (default any); `check`, `sound`, `live` and `door-calls` refuse any
other. An engine PhotonVox only adopted (decision 32) allows "status,cache/delete,check": it never seeds a domain, rescans profiles, reloads
the ACL or takes a greeting; anything else is refused as if it did not exist.

Whatever the caller asks, a synthetic call is never placed to an emergency or service number (911, 933, 988, N11, with or without a leading
1 or an outside-line digit): the operator's rule, kept here too so a mistake in the caller cannot place one (audit VOX-B-3).
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import socket
import subprocess
import threading
import time
import xml.etree.ElementTree as ET
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable, Dict, List, Optional, Tuple

VERSION = "0.1.0"
SKEW_S = 300
MAX_BODY = 8 * 1024 * 1024        # a greeting's audio (POST /v1/sound only)
MAX_SMALL = 256 * 1024            # every other operation: a few hundred bytes, a cache delete's 500 keys at most
MAX_CONNECTIONS = 16              # requests served at once; more are dropped (each may hold a thread and its body)
MAX_SOUND = 6 * 1024 * 1024
SAFE = re.compile(r"^[A-Za-z0-9@.+_:-]{1,200}$")
UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
PROFILE = re.compile(r"^[a-z0-9_-]{1,40}$")
NUMBER = re.compile(r"^\+?[0-9*#]{1,20}$")
DOMAIN = re.compile(r"^(?=.{1,200}$)[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+$")   # dotted labels; never ".."
TOKEN = re.compile(r"^[0-9a-f]{16,64}$")
SOUND = re.compile(r"^photonvox-[0-9a-f]{32}\.wav$")
# The digits of a number no synthetic call may go to: 911, 933 (emergency), 988 (crisis line), N11 service codes, each also after a 1 or an
# outside-line digit (9911, 1911, 8933...). The same list as engine/live/test_calls.sh.
NEVER_DIALED = re.compile(r"1?[0-9]?(?:911|933|988|[2-8]11)")
FOUND = re.compile(r"PhotonVox-synthetic token=(\w+) (?:reached=([^\s)]+)|route=([^\s)]+) gateways=([^\s)]+) dial=([^\s)]*))"
                   r"|PhotonVox blocked (\w+) .* token=(\w+)")


class Refused(Exception):
    """A request the agent will not act on (bad input): 400, with the reason."""


# ---- configuration ----

class Config:
    def __init__(self, env: Optional[Dict[str, str]] = None) -> None:
        e = os.environ if env is None else env
        self.secret = e.get("VOX_AGENT_SECRET", "")
        if len(self.secret) < 32:
            raise SystemExit("VOX_AGENT_SECRET must be set (32 characters or more)")
        host, _, port = e.get("VOX_AGENT_BIND", "127.0.0.1:8780").rpartition(":")
        self.bind = (host, int(port))
        esl_host, _, esl_port = e.get("VOX_AGENT_ESL", "127.0.0.1:8021").rpartition(":")
        self.esl = (esl_host, int(esl_port))
        self.esl_password = e.get("VOX_AGENT_ESL_PASSWORD") or esl_password(e.get("VOX_AGENT_ESL_CONF", "/etc/freeswitch/autoload_configs/event_socket.conf.xml"))
        self.cache = e.get("VOX_AGENT_CACHE", "/var/cache/fusionpbx")
        self.log = e.get("VOX_AGENT_LOG", "/var/log/freeswitch/freeswitch.log")
        self.fusionpbx = e.get("VOX_AGENT_FUSIONPBX", "/var/www/fusionpbx")
        self.php = e.get("VOX_AGENT_PHP", "/usr/bin/php")
        self.recordings = e.get("VOX_AGENT_RECORDINGS", "/var/lib/freeswitch/recordings")
        self.domains = frozenset(d.strip() for d in e.get("VOX_AGENT_DOMAINS", "").split(",") if d.strip())
        bad = [d for d in self.domains if not DOMAIN.fullmatch(d)]
        if bad:
            raise SystemExit(f"VOX_AGENT_DOMAINS: not a domain name: {', '.join(sorted(bad))}")
        names = {path[len("/v1/"):]: key for key in ROUTES for _m, path in [key]}
        wanted = [w.strip() for w in e.get("VOX_AGENT_OPERATIONS", ",".join(names)).split(",") if w.strip()]
        unknown = [w for w in wanted if w not in names]
        if unknown or not wanted:
            raise SystemExit(f"VOX_AGENT_OPERATIONS: unknown operation {', '.join(unknown) or '(none listed)'}; known: {', '.join(sorted(names))}")
        self.operations = frozenset(names[w] for w in wanted)


def esl_password(path: str) -> str:
    """The event socket's password from FreeSWITCH's configuration, or "" when it cannot be read: then nothing is tried (never the
    well-known default, audit VOX-B-11) and every operation that needs the event socket fails."""
    try:
        for p in ET.parse(path).getroot().iter("param"):
            if p.get("name") == "password":
                return p.get("value", "")
    except (OSError, ET.ParseError):
        pass
    return ""


# ---- FreeSWITCH's event socket (inbound mode, localhost) ----

def esl_api(cfg: Config, command: str, timeout: float = 30.0) -> str:
    """Run one `api` command and return its body."""
    if not cfg.esl_password:
        raise ConnectionError("no event socket password configured")
    with socket.create_connection(cfg.esl, timeout=timeout) as s:
        f = s.makefile("rb")

        def read() -> Tuple[Dict[str, str], bytes]:
            headers: Dict[str, str] = {}
            while True:
                line = f.readline()
                if not line:
                    raise ConnectionError("event socket closed")
                line = line.decode("utf-8", "replace").rstrip("\n")
                if not line:
                    if headers:
                        break
                    continue
                k, _, v = line.partition(":")
                headers[k.strip()] = v.strip()
            body = f.read(int(headers["Content-Length"])) if "Content-Length" in headers else b""
            return headers, body

        read()                                           # auth/request
        s.sendall(f"auth {cfg.esl_password}\n\n".encode())
        h, _ = read()
        if not h.get("Reply-Text", "").startswith("+OK"):
            raise ConnectionError("event socket refused the password")
        s.sendall(f"api {command}\n\n".encode())
        _, body = read()
        return body.decode("utf-8", "replace")


# ---- the operations ----

def _list(body: Dict[str, Any], key: str, pattern: re.Pattern, limit: int = 500) -> List[str]:
    values = body.get(key, [])
    if not isinstance(values, list) or len(values) > limit or not all(isinstance(v, str) and pattern.fullmatch(v) for v in values):
        raise Refused(f"{key}: a list of up to {limit} values matching {pattern.pattern}")
    return values


def _str(body: Dict[str, Any], key: str, pattern: re.Pattern) -> str:
    v = body.get(key)
    if not isinstance(v, str) or not pattern.fullmatch(v):      # fullmatch: `$` alone lets a trailing newline through (VOX-B-17)
        raise Refused(f"{key}: must match {pattern.pattern}")
    return v


def _domain(cfg: Config, body: Dict[str, Any]) -> str:
    """The request's domain, which must be one this engine lets PhotonVox manage (VOX_AGENT_DOMAINS; any when that is empty)."""
    domain = _str(body, "domain_name", DOMAIN)
    if cfg.domains and domain not in cfg.domains:
        raise Refused("domain_name: not a domain PhotonVox manages on this engine")
    return domain


def status(cfg: Config, _body: Dict[str, Any]) -> Dict[str, Any]:
    version = esl_api(cfg, "version").strip()
    uptime = esl_api(cfg, "uptime s").strip()
    profiles, gateways = [], []
    for line in esl_api(cfg, "sofia status").splitlines():
        parts = line.split()
        if len(parts) >= 4 and parts[1] == "profile":
            profiles.append({"name": parts[0], "state": parts[-2]})
    for line in esl_api(cfg, "sofia status gateway").splitlines():
        parts = line.split()
        if len(parts) >= 3 and "::" in parts[0] and parts[0] != "Profile::Gateway-Name":
            profile, _, gw = parts[0].partition("::")
            gateways.append({"profile": profile, "gateway": gw, "state": parts[2]})
    regs = esl_api(cfg, "show registrations count").strip().split()
    return {"agent": VERSION, "freeswitch": version, "uptime_s": int(uptime) if uptime.isdigit() else None, "profiles": profiles,
            "gateways": gateways, "registrations": int(regs[0]) if regs and regs[0].isdigit() else None}


def cache_delete(cfg: Config, body: Dict[str, Any]) -> Dict[str, Any]:
    deleted = 0
    for k in _list(body, "keys", SAFE):
        try:
            os.remove(os.path.join(cfg.cache, k))
            deleted += 1
        except FileNotFoundError:
            pass
    return {"deleted": deleted}


def rescan(cfg: Config, body: Dict[str, Any]) -> Dict[str, Any]:
    profiles, kill = _list(body, "profiles", PROFILE, 10), _list(body, "kill", UUID, 100)
    for p in profiles:
        for g in kill:
            esl_api(cfg, f"sofia profile {p} killgw {g}")
        esl_api(cfg, f"sofia profile {p} rescan")
    return {"profiles": profiles, "killed": len(kill)}


def reloadacl(cfg: Config, _body: Dict[str, Any]) -> Dict[str, Any]:
    return {"result": esl_api(cfg, "reloadacl").strip()}


def seed_domain(cfg: Config, _body: Dict[str, Any]) -> Dict[str, Any]:
    r = subprocess.run([cfg.php, "core/upgrade/upgrade.php", "--defaults"], cwd=cfg.fusionpbx, capture_output=True, text=True, timeout=300)
    if r.returncode != 0:
        raise RuntimeError(f"upgrade.php --defaults exited {r.returncode}")
    return {"seeded": True}


def sound(cfg: Config, body: Dict[str, Any]) -> Dict[str, Any]:
    """A greeting spoken at publish (PhotonVox's text-to-speech), written whole or not at all into the domain's recordings."""
    domain, name = _domain(cfg, body), _str(body, "name", SOUND)
    data = body.get("data")
    try:
        audio = base64.b64decode(data, validate=True) if isinstance(data, str) else b""
    except ValueError:
        audio = b""
    if not (0 < len(audio) <= MAX_SOUND) or audio[:4] != b"RIFF" or audio[8:12] != b"WAVE":
        raise Refused("data: a base64 WAV file of up to 6 MB")
    folder = os.path.join(cfg.recordings, domain)
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, name)
    tmp = path + ".part"
    with open(tmp, "wb") as f:
        f.write(audio)
    os.replace(tmp, path)
    return {"written": name, "bytes": len(audio)}


def parse(log: str, token: str) -> Optional[str]:
    for m in FOUND.finditer(log):
        if m.group(1) == token:
            return f"reached {m.group(2)}" if m.group(2) else f"{m.group(3)} {m.group(4)} {m.group(5)}"
        if m.group(7) == token:
            return f"blocked {m.group(6)}"
    return None


DOOR_LINE = re.compile(r"\[NOTICE\] \S+ PhotonVox-door domain=(\S+) door=([0-9]+) call=([0-9a-f-]{36}) (?:started=([0-9]+)|answered=([0-9]+) callee=(\S*))")
EXTENSION = re.compile(r"^[1-8][0-9]{1,4}$")


def door_calls(cfg: Config, body: Dict[str, Any]) -> Dict[str, Any]:
    """The door station's calls since `since`, from the lines its dial plan logs (FreeSWITCH's log; the newest 32 MB, minutes on a busy
    engine; only NOTICE lines, not FreeSWITCH's echo of the dial plan): when each started, and when it was answered and by whom (the
    extension it was bridged to, or the number sent out). Read only."""
    domain, ext = _domain(cfg, body), _str(body, "extension", EXTENSION)
    since = body.get("since")
    if not isinstance(since, int) or isinstance(since, bool) or since < 0:
        raise Refused("since: unix seconds")
    calls: Dict[str, Dict[str, Any]] = {}
    for m in DOOR_LINE.finditer(_tail(cfg.log, 32 * 1024 * 1024)):
        if m.group(1) != domain or m.group(2) != ext:
            continue
        c = calls.setdefault(m.group(3), {"call": m.group(3), "started": None, "answered": None, "callee": None})
        if m.group(4):
            c["started"] = int(m.group(4))
        elif c["answered"] is None:
            c["answered"], c["callee"] = int(m.group(5)), m.group(6) or None
    return {"calls": [c for c in calls.values() if max(c["started"] or 0, c["answered"] or 0) >= since]}


EXPSECS = re.compile(r"expsecs\((\d+)\)")
GATEWAY_FIELDS = {"state": str, "status": str, "pingtime": float, "calls-in": int, "calls-out": int, "failed-calls-in": int, "failed-calls-out": int,
                  "uptime-usec": int}


def _num(kind: Callable[[str], Any], text: Optional[str]) -> Any:
    try:
        return kind(text) if kind is not str else (text or "")
    except (TypeError, ValueError):
        return None


def live(cfg: Config, body: Dict[str, Any]) -> Dict[str, Any]:
    """One domain right now, read only. Registrations from every running SIP profile, the domain's users only: the extension, the phone's
    name for itself (its User-Agent, cut to 80 characters), seconds until it must register again, whether it answers FreeSWITCH's pings.
    Never its network address. Channels whose call is in the domain (its context, first or now, its account code or its presence): each
    leg's direction, whether it is on a gateway, its numbers, state and start. Every gateway's state, status and call counts since
    FreeSWITCH started (no names, logins or addresses besides the gateway's id)."""
    domain = _domain(cfg, body)
    profiles = [line.split()[0] for line in esl_api(cfg, "sofia status").splitlines()
                if len(line.split()) >= 4 and line.split()[1] == "profile" and "RUNNING" in line and PROFILE.match(line.split()[0])]
    registrations = []
    for p in profiles:
        try:
            root = ET.fromstring(esl_api(cfg, f"sofia xmlstatus profile {p} reg").strip() or "<profile/>")
        except ET.ParseError:
            continue
        for r in root.iter("registration"):
            user, _, realm = (r.findtext("user") or "").partition("@")
            if realm != domain or not user:
                continue
            m = EXPSECS.search(r.findtext("status") or "")
            registrations.append({"extension": user, "agent": (r.findtext("agent") or "")[:80], "expires_s": int(m.group(1)) if m else None,
                                  "reachable": (r.findtext("ping-status") or "") == "Reachable", "profile": p})
    try:
        rows = json.loads(esl_api(cfg, "show channels as json") or "{}").get("rows") or []
    except ValueError:
        rows = []
    channels = []
    for c in rows:
        if not (domain in (c.get("context"), c.get("initial_context"), c.get("accountcode")) or (c.get("presence_id") or "").endswith("@" + domain)):
            continue
        name = c.get("name") or ""
        channels.append({"uuid": c.get("uuid"), "call": c.get("call_uuid") or c.get("uuid"), "direction": c.get("direction"),
                         "gateway": name.startswith(("sofia/gateway/", "sofia/external/")), "cid_num": c.get("cid_num") or "",
                         "dest": c.get("dest") or "", "callee_num": c.get("callee_num") or "", "callstate": c.get("callstate") or "",
                         "presence": (c.get("presence_id") or "").partition("@")[0], "created": _num(int, c.get("created_epoch"))})
    gateways = []
    try:
        for g in ET.fromstring(esl_api(cfg, "sofia xmlstatus gateway").strip() or "<gateways/>").iter("gateway"):
            gw = {"gateway": g.findtext("name") or "", "profile": g.findtext("profile") or ""}
            gw.update({k.replace("-", "_"): _num(kind, g.findtext(k)) for k, kind in GATEWAY_FIELDS.items()})
            gateways.append(gw)
    except ET.ParseError:
        pass
    return {"registrations": registrations, "channels": channels, "gateways": gateways}


def _tail(path: str, size: int = 512 * 1024) -> str:
    """The newest `size` bytes of FreeSWITCH's log, across a rotation: when the current file is shorter, the end of the one rotated before it
    (`<path>.1`) comes first, so a line written just before the rotation is still read (a check once missed its line that way)."""
    out = b""
    for p in (path, path + ".1"):
        try:
            with open(p, "rb") as f:
                f.seek(0, os.SEEK_END)
                f.seek(max(0, f.tell() - (size - len(out))))
                out = f.read() + out
        except FileNotFoundError:
            pass
        if len(out) >= size:
            break
    return out.decode("utf-8", "replace")


def check(cfg: Config, body: Dict[str, Any], wait_s: float = 3.0) -> Dict[str, Any]:
    kind = _str(body, "kind", re.compile(r"^(inbound|route)$"))
    number, domain = _str(body, "number", NUMBER), _domain(cfg, body)
    if NEVER_DIALED.fullmatch(re.sub(r"[^0-9]", "", number)):
        raise Refused("number: an emergency or service number is never dialed, not even by a synthetic call")
    domain_uuid, token = _str(body, "domain_uuid", UUID), _str(body, "token", TOKEN)
    context = "public" if kind == "inbound" else domain
    synthetic = "inbound" if kind == "inbound" else "route"
    variables = (f"photonvox_synthetic={synthetic},photonvox_token={token},domain_name={domain},domain_uuid={domain_uuid},"
                 "origination_caller_id_number=2125550000,originate_timeout=10,ignore_early_media=true,process_cdr=false")    # not a call: no record
    esl_api(cfg, f"originate {{{variables}}}loopback/{number}/{context} &park()")
    deadline = time.monotonic() + wait_s
    while True:
        found = parse(_tail(cfg.log), token)
        if found or time.monotonic() >= deadline:
            return {"found": found}
        time.sleep(0.2)


ROUTES: Dict[Tuple[str, str], Callable[[Config, Dict[str, Any]], Dict[str, Any]]] = {
    ("GET", "/v1/status"): status, ("POST", "/v1/cache/delete"): cache_delete, ("POST", "/v1/rescan"): rescan,
    ("POST", "/v1/reloadacl"): reloadacl, ("POST", "/v1/seed-domain"): seed_domain, ("POST", "/v1/check"): check, ("POST", "/v1/door-calls"): door_calls, ("POST", "/v1/sound"): sound,
    ("POST", "/v1/live"): live,
}


# ---- signatures ----

def sign(secret: str, method: str, path: str, body: bytes, t: Optional[int] = None, nonce: Optional[str] = None) -> str:
    """A fresh nonce in every signature: two identical requests in the same second (a republish's cache deletes) are not a replay."""
    t = int(time.time()) if t is None else t
    nonce = nonce or os.urandom(12).hex()
    mac = hmac.new(secret.encode(), f"{t}.{nonce}.{method}.{path}.".encode() + body, hashlib.sha256).hexdigest()
    return f"t={t},n={nonce},v1={mac}"


class Replay:
    """Signatures seen in the last window: a captured request cannot be sent again."""

    def __init__(self) -> None:
        self.seen: Dict[str, float] = {}
        self.lock = threading.Lock()

    def first(self, sig: str, now: float) -> bool:
        with self.lock:
            for k in [k for k, t in self.seen.items() if t < now - 2 * SKEW_S]:
                del self.seen[k]
            if sig in self.seen:
                return False
            self.seen[sig] = now
            return True


def _parts(header: str, now: float) -> Optional[Tuple[int, str, str]]:
    """The signature header's time, nonce and MAC, provided it is well formed and within the window; None otherwise."""
    try:
        parts = dict(p.split("=", 1) for p in header.split(","))
        t, nonce, given = int(parts["t"]), parts["n"], parts["v1"]
    except (ValueError, KeyError):
        return None
    if abs(now - t) > SKEW_S or not re.fullmatch(r"[0-9a-f]{16,64}", nonce):
        return None
    return t, nonce, given


def plausible(header: str, now: Optional[float] = None) -> bool:
    """Checked before a body is read (VOX-B-11): a request without a well-formed, current signature header is refused unread."""
    return _parts(header, time.time() if now is None else now) is not None


def verify(secret: str, header: str, method: str, path: str, body: bytes, replay: Replay, now: Optional[float] = None) -> bool:
    now = time.time() if now is None else now
    found = _parts(header, now)
    if found is None:
        return False
    t, nonce, given = found
    want = sign(secret, method, path, body, t, nonce).split("v1=", 1)[1]
    return hmac.compare_digest(want, given) and replay.first(nonce, now)


# ---- the HTTP side ----

def make_handler(cfg: Config, replay: Replay):
    class Handler(BaseHTTPRequestHandler):
        server_version = f"vox-agent/{VERSION}"
        sys_version = ""
        timeout = 30          # a client that stops sending is dropped

        def log_message(self, fmt: str, *args: Any) -> None:     # one line per request, never bodies
            print(f"{self.address_string()} {self.command} {self.path} {args[1] if len(args) > 1 else ''}", flush=True)

        def _send(self, code: int, payload: Dict[str, Any]) -> None:
            data = json.dumps(payload).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _handle(self) -> None:
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                length = -1
            if length < 0:
                return self._send(400, {"error": "bad length"})
            if length > (MAX_BODY if self.path == "/v1/sound" else MAX_SMALL):
                return self._send(413, {"error": "too large"})
            signature = self.headers.get("X-PhotonVox-Signature", "")
            if not plausible(signature):          # nothing is read for a request that cannot be signed (VOX-B-11)
                return self._send(401, {"error": "bad signature"})
            body = self.rfile.read(length) if length else b""
            if not verify(cfg.secret, signature, self.command, self.path, body, replay):
                return self._send(401, {"error": "bad signature"})
            op = ROUTES.get((self.command, self.path)) if (self.command, self.path) in cfg.operations else None
            if op is None:
                return self._send(404, {"error": "no such operation"})
            try:
                payload = json.loads(body) if body else {}
                if not isinstance(payload, dict):
                    raise Refused("the body must be a JSON object")
                return self._send(200, op(cfg, payload))
            except (Refused, json.JSONDecodeError) as e:
                return self._send(400, {"error": str(e)})
            except Exception as e:  # noqa: BLE001 - the engine failed: say what kind, never details that could leak
                return self._send(500, {"error": type(e).__name__})

        do_GET = _handle
        do_POST = _handle

    return Handler


class Server(ThreadingHTTPServer):
    """At most MAX_CONNECTIONS requests at once (VOX-B-11): a connection beyond that is closed unanswered, so nobody can hold every
    thread and its memory."""
    daemon_threads = True

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.slots = threading.BoundedSemaphore(MAX_CONNECTIONS)

    def process_request(self, request: Any, client_address: Any) -> None:
        if not self.slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except Exception:
            self.slots.release()
            raise

    def process_request_thread(self, request: Any, client_address: Any) -> None:
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.slots.release()


def serve(cfg: Config) -> ThreadingHTTPServer:
    return Server(cfg.bind, make_handler(cfg, Replay()))


if __name__ == "__main__":  # pragma: no cover
    config = Config()
    print(f"vox-agent {VERSION} listening on {config.bind[0]}:{config.bind[1]}", flush=True)
    serve(config).serve_forever()
