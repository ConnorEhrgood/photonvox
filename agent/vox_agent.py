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
                             {"calls": [{"call", "started", "answered", "user", "dest"}]} (PhotonEntry's door-calls, through PhotonVox)
    POST /v1/check           {"kind": "inbound"|"route", "number", "domain_name", "domain_uuid", "token"}: one synthetic call of the
                             post-publish check; answers {"found": "reached 301" | "<route> <gateways> <number sent>" | "blocked <category>" | null}

Every request carries `X-PhotonVox-Signature: t=<unix seconds>,n=<random hex nonce>,v1=<hex HMAC-SHA256(secret,
"<t>.<n>.<METHOD>.<path>.<body>")>`. A signature older or newer than five minutes, or whose nonce was seen before, is refused. Nothing the caller sends reaches a shell: values are checked against fixed patterns and
passed to FreeSWITCH or to programs as arguments.

Configuration (environment, from /etc/vox-agent.env): VOX_AGENT_SECRET (required, 32+ characters), VOX_AGENT_BIND (default 127.0.0.1:8780),
and optionally VOX_AGENT_ESL (host:port), VOX_AGENT_ESL_PASSWORD (default: read from FreeSWITCH's event_socket.conf.xml), VOX_AGENT_CACHE,
VOX_AGENT_LOG, VOX_AGENT_FUSIONPBX, VOX_AGENT_PHP, and VOX_AGENT_OPERATIONS: the operations this engine allows, comma-separated (default all).
An engine PhotonVox only adopted (decision 32) allows "status,cache/delete,check": it never seeds a domain, rescans profiles, reloads the ACL or
takes a greeting; anything else is refused as if it did not exist.
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
MAX_BODY = 8 * 1024 * 1024        # a greeting's audio; everything else is a few hundred bytes
MAX_SOUND = 6 * 1024 * 1024
SAFE = re.compile(r"^[A-Za-z0-9@.+_:-]{1,200}$")
UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
PROFILE = re.compile(r"^[a-z0-9_-]{1,40}$")
NUMBER = re.compile(r"^\+?[0-9*#]{1,20}$")
DOMAIN = re.compile(r"^(?=.{1,200}$)[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+$")   # dotted labels; never ".."
TOKEN = re.compile(r"^[0-9a-f]{16,64}$")
SOUND = re.compile(r"^photonvox-[0-9a-f]{32}\.wav$")
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
        names = {path[len("/v1/"):]: key for key in ROUTES for _m, path in [key]}
        wanted = [w.strip() for w in e.get("VOX_AGENT_OPERATIONS", ",".join(names)).split(",") if w.strip()]
        unknown = [w for w in wanted if w not in names]
        if unknown or not wanted:
            raise SystemExit(f"VOX_AGENT_OPERATIONS: unknown operation {', '.join(unknown) or '(none listed)'}; known: {', '.join(sorted(names))}")
        self.operations = frozenset(names[w] for w in wanted)


def esl_password(path: str) -> str:
    try:
        for p in ET.parse(path).getroot().iter("param"):
            if p.get("name") == "password":
                return p.get("value", "")
    except (OSError, ET.ParseError):
        pass
    return "ClueCon"


# ---- FreeSWITCH's event socket (inbound mode, localhost) ----

def esl_api(cfg: Config, command: str, timeout: float = 30.0) -> str:
    """Run one `api` command and return its body."""
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
    if not isinstance(values, list) or len(values) > limit or not all(isinstance(v, str) and pattern.match(v) for v in values):
        raise Refused(f"{key}: a list of up to {limit} values matching {pattern.pattern}")
    return values


def _str(body: Dict[str, Any], key: str, pattern: re.Pattern) -> str:
    v = body.get(key)
    if not isinstance(v, str) or not pattern.match(v):
        raise Refused(f"{key}: must match {pattern.pattern}")
    return v


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
    domain, name = _str(body, "domain_name", DOMAIN), _str(body, "name", SOUND)
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


DOOR_LINE = re.compile(r"PhotonVox-door domain=(\S+) door=([0-9]+) call=([0-9a-f-]{36}) (?:started=([0-9]+)|answered=([0-9]+) user=(\S*) dest=(\S*))")
EXTENSION = re.compile(r"^[1-8][0-9]{1,4}$")


def door_calls(cfg: Config, body: Dict[str, Any]) -> Dict[str, Any]:
    """The door station's calls since `since`, from the lines its dial plan logs (FreeSWITCH's log; the newest 32 MB, minutes on a busy
    engine): when each started, and when it was answered and by whom (the answering leg's user, or the number it was sent to). Read only."""
    domain, ext = _str(body, "domain_name", DOMAIN), _str(body, "extension", EXTENSION)
    since = body.get("since")
    if not isinstance(since, int) or isinstance(since, bool) or since < 0:
        raise Refused("since: unix seconds")
    calls: Dict[str, Dict[str, Any]] = {}
    for m in DOOR_LINE.finditer(_tail(cfg.log, 32 * 1024 * 1024)):
        if m.group(1) != domain or m.group(2) != ext:
            continue
        c = calls.setdefault(m.group(3), {"call": m.group(3), "started": None, "answered": None, "user": None, "dest": None})
        if m.group(4):
            c["started"] = int(m.group(4))
        elif c["answered"] is None:             # the first leg to answer is the one bridged
            c["answered"], c["user"], c["dest"] = int(m.group(5)), m.group(6) or None, m.group(7) or None
    return {"calls": [c for c in calls.values() if max(c["started"] or 0, c["answered"] or 0) >= since]}


def _tail(path: str, size: int = 512 * 1024) -> str:
    with open(path, "rb") as f:
        f.seek(0, os.SEEK_END)
        f.seek(max(0, f.tell() - size))
        return f.read().decode("utf-8", "replace")


def check(cfg: Config, body: Dict[str, Any], wait_s: float = 3.0) -> Dict[str, Any]:
    kind = _str(body, "kind", re.compile(r"^(inbound|route)$"))
    number, domain = _str(body, "number", NUMBER), _str(body, "domain_name", DOMAIN)
    domain_uuid, token = _str(body, "domain_uuid", UUID), _str(body, "token", TOKEN)
    context = "public" if kind == "inbound" else domain
    synthetic = "inbound" if kind == "inbound" else "route"
    variables = (f"photonvox_synthetic={synthetic},photonvox_token={token},domain_name={domain},domain_uuid={domain_uuid},"
                 "origination_caller_id_number=2125550000,originate_timeout=10,ignore_early_media=true")
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


def verify(secret: str, header: str, method: str, path: str, body: bytes, replay: Replay, now: Optional[float] = None) -> bool:
    now = time.time() if now is None else now
    try:
        parts = dict(p.split("=", 1) for p in header.split(","))
        t, nonce, given = int(parts["t"]), parts["n"], parts["v1"]
    except (ValueError, KeyError):
        return False
    if abs(now - t) > SKEW_S or not re.match(r"^[0-9a-f]{16,64}$", nonce):
        return False
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
            if length > MAX_BODY:
                return self._send(413, {"error": "too large"})
            body = self.rfile.read(length) if length else b""
            if not verify(cfg.secret, self.headers.get("X-PhotonVox-Signature", ""), self.command, self.path, body, replay):
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


def serve(cfg: Config) -> ThreadingHTTPServer:
    return ThreadingHTTPServer(cfg.bind, make_handler(cfg, Replay()))


if __name__ == "__main__":  # pragma: no cover
    config = Config()
    print(f"vox-agent {VERSION} listening on {config.bind[0]}:{config.bind[1]}", flush=True)
    serve(config).serve_forever()
