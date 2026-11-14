"""The demo's live simulator (docs/DEMO.md §2): the demo's phones registered on the staging engine and answering like phones, and the traffic
model's calls (sim/traffic.py) placed as they come due, in real time, through SIPp. Runs in its own container (compose project vox-demo-sim).

    python3 scheduler.py /config/sim.json

The configuration (mode 600; scripts/demo-sim.sh writes it): {"engine": "10.10.0.60", "domain": "demo.vox.test", "carrier_port": 5071,
"phones": {"100": "<SIP password>", ...}, "offline": ["110"], "first_port": 5200}. Calls in come from the simulated carrier (SIPp to the engine's
external profile, as the build test's upstream does); calls out reach the carrier through the demo's gateway; the carrier answers them.

Never an emergency number, a service code or a number outside (412) 555-0100 to 0199: every call is checked (traffic.check) before it is placed,
and the engine's own guard drops anything bound for a real carrier. No audio: calls carry no RTP, except a voicemail caller's generated tone.
"""
from __future__ import annotations

import json
import logging
import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import traffic  # noqa: E402

log = logging.getLogger("vox-demo-sim")
SCENARIOS = os.environ.get("SIM_SCENARIOS", "/scenarios")
REGISTER_EVERY_S = 300           # phones register for 600 s and renew every 5 minutes
MAX_TALK_S = 270                 # FreeSWITCH ends a call with no media after 300 s; the simulated calls stay under it
MAX_CONCURRENT = 12


@dataclass
class Config:
    engine: str
    domain: str
    phones: Dict[str, str]
    carrier_port: int = 5071
    first_port: int = 5200
    offline: tuple = ()

    @staticmethod
    def load(path: str) -> "Config":
        with open(path) as f:
            c = json.load(f)
        return Config(c["engine"], c["domain"], {str(k): str(v) for k, v in c["phones"].items()}, int(c.get("carrier_port", 5071)),
                      int(c.get("first_port", 5200)), tuple(c.get("offline") or ()))

    def port(self, ext: str) -> int:
        return self.first_port + sorted(self.phones).index(ext)


def phone_command(cfg: Config, ext: str) -> List[str]:
    """A phone answering on its own port: rings, then answers or (sometimes) not, holds until the caller hangs up (sim-phone.xml)."""
    return ["sipp", "-nostdin", "-sf", f"{SCENARIOS}/sim-phone.xml", "-p", str(cfg.port(ext)), "-m", "1000000", "-l", "20", "-trace_err",
            "-error_file", f"/tmp/phone-{ext}.err"]


def register_command(cfg: Config, ext: str) -> List[str]:
    """A registration for the phone's extension, its Contact the phone's answering port (sent from another port, which is then closed)."""
    return ["sipp", "-nostdin", "-sf", f"{SCENARIOS}/sim-register.xml", "-s", ext, "-au", ext, "-ap", cfg.phones[ext], "-set", "domain", cfg.domain,
            "-set", "contact_port", str(cfg.port(ext)), "-p", "0", "-m", "1", "-timeout", "10s", f"{cfg.engine}:5060"]


def call_command(cfg: Config, c: traffic.Call) -> Optional[List[str]]:
    """The SIPp command that places one call of the traffic model, or None when the live engine cannot make it look so (a page is a call from a
    phone to the paging extension; a missed call is one the caller gives up on while it rings)."""
    traffic.check(c)
    talk_ms = str(1000 * min(MAX_TALK_S, max(5, c.talk_s)))
    ring_ms = str(1000 * max(3, c.ring_s))
    if c.kind == "inbound":
        base = ["-set", "from", c.caller, "-set", "domain", cfg.engine, "-s", c.dialed, f"{cfg.engine}:5080"]
        if c.status == "missed":
            return ["sipp", "-nostdin", "-sf", f"{SCENARIOS}/call-cancel.xml", "-d", ring_ms, "-m", "1", "-p", "0", "-timeout", "60s", *base]
        if c.status == "voicemail":
            return ["sipp", "-nostdin", "-sf", f"{SCENARIOS}/call-speak.xml", "-d", str(1000 * (12 + min(30, c.talk_s))), "-m", "1", "-p", "0",
                    "-timeout", "120s", "-mi", "0.0.0.0", *base]
        return ["sipp", "-nostdin", "-sf", f"{SCENARIOS}/call.xml", "-d", talk_ms, "-m", "1", "-p", "0", "-timeout", f"{MAX_TALK_S + 90}s", *base]
    if c.caller not in cfg.phones or c.caller in cfg.offline:
        return None
    auth = ["-set", "from", c.caller, "-set", "domain", cfg.domain, "-au", c.caller, "-ap", cfg.phones[c.caller], "-s", c.dialed, f"{cfg.engine}:5060"]
    if c.status == "missed":
        return ["sipp", "-nostdin", "-sf", f"{SCENARIOS}/call-cancel.xml", "-d", ring_ms, "-m", "1", "-p", "0", "-timeout", "60s", *auth]
    return ["sipp", "-nostdin", "-sf", f"{SCENARIOS}/call.xml", "-d", talk_ms, "-m", "1", "-p", "0", "-timeout", f"{MAX_TALK_S + 90}s", *auth]


class Simulator:
    def __init__(self, cfg: Config, now=lambda: datetime.now(timezone.utc), spawn=subprocess.Popen) -> None:
        self.cfg, self.now, self.spawn = cfg, now, spawn
        self.phones: Dict[str, subprocess.Popen] = {}
        self.calls: List[subprocess.Popen] = []
        self.registered_at = 0.0
        self.stopping = False

    def online(self) -> List[str]:
        return [x for x in sorted(self.cfg.phones) if x not in self.cfg.offline]

    def keep_phones(self) -> None:
        for ext in self.online():
            p = self.phones.get(ext)
            if p is None or p.poll() is not None:
                self.phones[ext] = self.spawn(phone_command(self.cfg, ext), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if time.monotonic() - self.registered_at >= REGISTER_EVERY_S:
            for ext in self.online():
                self.spawn(register_command(self.cfg, ext), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self.registered_at = time.monotonic()

    def place(self, c: traffic.Call) -> bool:
        self.calls = [p for p in self.calls if p.poll() is None]
        if len(self.calls) >= MAX_CONCURRENT:
            log.info("skipped a call: %d in progress", len(self.calls))
            return False
        cmd = call_command(self.cfg, c)
        if cmd is None:
            return False
        self.calls.append(self.spawn(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
        log.info("%s %s call at %s (%s)", c.status, c.kind, c.site, "page" if c.kind == "page" else "")
        return True

    def run(self) -> None:
        signal.signal(signal.SIGTERM, lambda *_: setattr(self, "stopping", True))
        horizon = self.now()
        due: List[traffic.Call] = []
        while not self.stopping:
            now = self.now()
            if now >= horizon - timedelta(minutes=5):
                due += [c for c in traffic.between(horizon, horizon + timedelta(hours=1)) if c.start >= now.timestamp()]
                horizon += timedelta(hours=1)
            self.keep_phones()
            while due and due[0].start <= now.timestamp():
                self.place(due.pop(0))
            time.sleep(1)
        for p in list(self.phones.values()) + self.calls:
            p.terminate()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    Simulator(Config.load(sys.argv[1])).run()
