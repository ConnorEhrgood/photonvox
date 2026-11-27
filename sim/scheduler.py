"""The demo's live simulator (docs/DEMO.md §2): the demo's phones registered on the staging engine and answering like phones, and the traffic
model's calls (sim/traffic.py) placed as they come due, in real time, through SIPp (sim/scenarios.py). Two containers of one compose project
(vox-demo-sim), one for each side of the engine, each running this with its role:

    python3 scheduler.py carrier /config/sim.json     on the host's network, at the address the engine knows as its carrier (and where the phones'
                                                      registrations point): everything that answers, the registrations, and the calls in
    python3 scheduler.py phones /config/sim.json      on the project's own routed network, an address the engine does not take for a carrier,
                                                      so it asks for the phone's password as it would of a phone: calls out, internal calls, pages

Both read the same model, which is the same every time for a given day, so neither needs to hear from the other. The configuration (no secret
in it): {"engine": "10.10.0.60", "domain": "demo.vox.test", "address": "10.10.0.80", "answer_port": 5200, "carrier_port": 5071}. The phones'
SIP passwords are in /config/phones.csv (mode 600; scripts/demo-sim.sh writes it from the engine), read by SIPp itself: never on a command
line, never logged, and nothing here traces a message.

Never an emergency number, a service code or a number outside (412) 555-0100 to 0199: every call is checked (traffic.check) before it is placed,
and the engine's own guard drops anything bound for a real carrier. No audio, except a voicemail caller's generated tone.
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
from typing import Callable, Dict, List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import scenarios  # noqa: E402
import traffic  # noqa: E402

log = logging.getLogger("vox-demo-sim")
ROLES = ("carrier", "phones")
TONE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tone-ulaw.wav")
REGISTER_EVERY_S = 300           # the phones register for 600 s and again every 5 minutes
MAX_TALK_S = 270                 # FreeSWITCH ends a call with no media after 300 s; the simulated calls stay under it
MAX_CONCURRENT = 10              # calls in progress from one role; one more is skipped
LATE_S = 60                      # a call this late (the container was stopped) is skipped, not placed
MEDIA_PORTS = (6100, 100)        # a voicemail caller's tone: a port of its own, from 6100, four apart


@dataclass(frozen=True)
class Config:
    engine: str
    domain: str
    address: str                          # where the answering side listens: the carrier's address, and the phones' registered Contact
    answer_port: int = 5200               # the phones
    carrier_port: int = 5071              # the carrier (the demo's gateway on the engine points here)
    credentials: str = "/config/phones.csv"
    work: str = "/run/sim"                # scenarios and one credentials file per phone, written at start (a tmpfs)

    @staticmethod
    def load(path: str) -> "Config":
        with open(path) as f:
            c = json.load(f)
        return Config(**{k: c[k] for k in ("engine", "domain", "address", "answer_port", "carrier_port", "credentials", "work") if k in c})


@dataclass(frozen=True)
class Placement:
    """How one call of the model is made to happen on the live engine."""
    role: str
    scenario: str
    answer: str                  # X-Sim-Answer: the extension that answers, `any`, or `none`
    ring_ms: int = 0             # X-Sim-Ring: how long it rings there first
    hold_ms: int = 0             # from the answer (or the menu key) to the caller hanging up
    give_up_ms: int = 0          # or: the caller gives up after this long with no answer
    digit: str = ""
    speak: bool = False


def placement(c: traffic.Call) -> Placement:
    traffic.check(c)
    ring, talk, key = 1000 * c.ring_s, 1000 * min(MAX_TALK_S, c.talk_s), bool(c.digit)
    if c.kind == "inbound":
        if c.closed and c.status == "voicemail":        # straight to the box
            return Placement("carrier", scenarios.name(False, speak=True), "none", hold_ms=talk, speak=True)
        if c.closed:                                    # hung up in the box's greeting
            return Placement("carrier", scenarios.name(False), "none", hold_ms=ring)
        if c.status == "answered":                      # through the menu, the caller is "answered" from the menu on
            return Placement("carrier", scenarios.name(False, digit=key), c.reached, ring, hold_ms=talk + (ring if key else 0), digit=c.digit)
        if c.status == "voicemail":                     # nobody answers; the engine rings them out (ring_s) and the box takes it
            return Placement("carrier", scenarios.name(False, digit=key, speak=True), "none",
                             hold_ms=(ring if key else 0) + talk, digit=c.digit, speak=True)
        if key:                                         # gave up while the group rang: past the menu there is nothing to cancel, so a hang-up
            return Placement("carrier", scenarios.name(False, digit=True), "none", hold_ms=ring, digit=c.digit)
        return Placement("carrier", scenarios.name(False, cancel=True), "none", give_up_ms=ring)
    if c.status != "answered":
        return Placement("phones", scenarios.name(True, cancel=True), "none", give_up_ms=ring)
    if c.kind == "internal":
        return Placement("phones", scenarios.name(True), c.dialed, ring, hold_ms=talk)
    return Placement("phones", scenarios.name(True), "any", 0 if c.kind == "page" else ring, hold_ms=talk)      # the carrier, or every paged phone


def call_command(cfg: Config, c: traffic.Call, n: int) -> List[str]:
    """SIPp for one call (`n`: this role's count of calls, for a Call-ID and a media port of its own)."""
    p = placement(c)
    cmd = ["sipp", "-nostdin", "-sf", f"{cfg.work}/scn/{p.scenario}", "-m", "1", "-s", c.dialed, "-set", "answer", p.answer, "-set", "ring",
           str(p.ring_ms), "-d", str(max(1000, p.hold_ms)), "-timeout", "420s", "-cid_str", f"%u-sim-{int(c.start)}-{n}@%s"]
    if p.digit:
        cmd += ["-set", "digit", p.digit]
    if p.give_up_ms:
        cmd += ["-recv_timeout", str(p.give_up_ms)]
    if p.role == "carrier":                             # as the build test's upstream calls in: ten digits to the engine's external profile
        cmd += ["-set", "from", c.caller, "-set", "domain", cfg.engine, "-i", cfg.address]
        if p.speak:
            cmd += ["-mi", cfg.address, "-mp", str(MEDIA_PORTS[0] + 4 * (n % MEDIA_PORTS[1]))]
        return cmd + [f"{cfg.engine}:5080"]
    return cmd + ["-inf", f"{cfg.work}/phone/{c.caller}.csv", "-set", "domain", cfg.domain, f"{cfg.engine}:5060"]


def answer_command(cfg: Config, port: int) -> List[str]:
    """What answers on one port, for every phone or for the carrier, for as long as it runs."""
    return ["sipp", "-nostdin", "-sf", f"{cfg.work}/scn/sim-answer.xml", "-i", cfg.address, "-p", str(port)]


def register_command(cfg: Config, phones: int) -> List[str]:
    """Every phone's registration in one run; their Contact is where `answer` listens."""
    return ["sipp", "-nostdin", "-sf", f"{cfg.work}/scn/sim-register.xml", "-inf", cfg.credentials, "-m", str(phones), "-r", "5", "-i", cfg.address,
            "-set", "domain", cfg.domain, "-set", "contact_port", str(cfg.answer_port), "-timeout", "60s", f"{cfg.engine}:5060"]


def credentials(path: str) -> Dict[str, str]:
    """The phones' lines of the credentials file, by extension (SIPp reads the file itself: `SEQUENTIAL`, then a line a phone)."""
    with open(path) as f:
        lines = [x.strip() for x in f if ";" in x]
    return {x.split(";", 1)[0]: x for x in lines}


class Simulator:
    def __init__(self, role: str, cfg: Config, now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
                 spawn: Callable[..., subprocess.Popen] = subprocess.Popen) -> None:
        if role not in ROLES:
            raise SystemExit(f"a role: {' or '.join(ROLES)}")
        self.role, self.cfg, self.now, self.spawn = role, cfg, now, spawn
        self.phones: Tuple[str, ...] = ()
        self.answering: Dict[int, subprocess.Popen] = {}
        self.registering: Optional[subprocess.Popen] = None
        self.registered_at: Optional[datetime] = None
        self.calls: List[subprocess.Popen] = []
        self.due: List[traffic.Call] = []
        self.horizon: Optional[datetime] = None
        self.placed = self.failed = self.skipped = 0
        self.stopping = False

    def _run(self, cmd: List[str]) -> subprocess.Popen:
        return self.spawn(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def prepare(self) -> None:
        """The scenarios, and for the calling phones a credentials file each (SIPp takes who is calling from a file's first line)."""
        scenarios.write(os.path.join(self.cfg.work, "scn"), TONE)
        lines = credentials(self.cfg.credentials)
        self.phones = tuple(sorted(lines))
        if self.role == "phones":
            folder = os.path.join(self.cfg.work, "phone")
            os.makedirs(folder, mode=0o700, exist_ok=True)
            for ext, line in lines.items():
                with os.fdopen(os.open(os.path.join(folder, f"{ext}.csv"), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w") as f:
                    f.write("SEQUENTIAL\n" + line + "\n")
        log.info("%s: %d phones", self.role, len(self.phones))

    def keep(self, now: datetime) -> None:
        """The carrier's side: something always answering on both ports, and the phones registered."""
        for port in (self.cfg.answer_port, self.cfg.carrier_port):
            p = self.answering.get(port)
            if p is None or p.poll() is not None:
                if p is not None:
                    log.warning("what answers on %d stopped (%s): started again", port, p.returncode)
                self.answering[port] = self._run(answer_command(self.cfg, port))
        if self.registering is not None and self.registering.poll() is not None:
            if self.registering.returncode:                    # the engine restarting, say: again in half a minute
                log.warning("not every phone registered (SIPp ended %s)", self.registering.returncode)
                self.registered_at = now - timedelta(seconds=REGISTER_EVERY_S - 30)
            self.registering = None
        if self.registering is None and (self.registered_at is None or (now - self.registered_at).total_seconds() >= REGISTER_EVERY_S):
            self.registering, self.registered_at = self._run(register_command(self.cfg, len(self.phones))), now

    def load(self, now: datetime) -> None:
        """This role's calls of the model, an hour at a time, from now on."""
        if self.horizon is None:
            self.horizon = now
        while now >= self.horizon - timedelta(minutes=5):
            ahead = traffic.between(self.horizon, self.horizon + timedelta(hours=1))
            self.due += [c for c in ahead if c.start >= now.timestamp() and placement(c).role == self.role]
            self.horizon += timedelta(hours=1)

    def place(self, c: traffic.Call, now: datetime) -> bool:
        if now.timestamp() - c.start > LATE_S or len(self.calls) >= MAX_CONCURRENT or (self.role == "phones" and c.caller not in self.phones):
            self.skipped += 1
            return False
        self.placed += 1
        self.calls.append(self._run(call_command(self.cfg, c, self.placed)))
        log.info("%s: %s %s, %s to %s%s", c.site, c.status, "page" if c.kind == "page" else c.kind + " call", c.caller, c.dialed,
                 f", key {c.digit}" if c.digit else "")
        return True

    def step(self) -> None:
        now = self.now()
        if self.role == "carrier":
            self.keep(now)
        self.load(now)
        for p in [p for p in self.calls if p.poll() is not None]:
            self.calls.remove(p)
            if p.returncode:
                self.failed += 1
                log.warning("a call did not go as meant (SIPp ended %s); %d of %d so far", p.returncode, self.failed, self.placed)
        while self.due and self.due[0].start <= now.timestamp():
            self.place(self.due.pop(0), now)

    def stop(self) -> None:
        for p in [*self.answering.values(), *self.calls, *([self.registering] if self.registering else [])]:
            if p.poll() is None:
                p.terminate()

    def run(self) -> None:
        signal.signal(signal.SIGTERM, lambda *_: setattr(self, "stopping", True))
        self.prepare()
        while not self.stopping:
            self.step()
            time.sleep(1)
        self.stop()
        log.info("%s: stopped after %d calls (%d did not go as meant, %d skipped)", self.role, self.placed, self.failed, self.skipped)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", stream=sys.stdout)
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    Simulator(sys.argv[1], Config.load(sys.argv[2])).run()
