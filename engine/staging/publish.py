#!/usr/bin/env python3
"""Publish a phone-system document to the staging engine with PhotonVox's adapter (BUILD-GUIDE Step 3), as the worker does (vox-agent on the
engine, reached through an SSH tunnel standing in for the management network), except that the records PhotonVox would keep are files:
  - the manifest of what was written: engine/staging/.state/<name>.manifest.json (not in git), so the next publish can remove what left;
  - new SIP passwords and PINs: ~/.config/photonvox/staging-secrets.json (mode 600; staging test values, never printed).

    PYTHONPATH=api ~/.venvs/photonvox/bin/python engine/staging/publish.py <document.json> [--name adapter]
    ... publish.py --upstreams            only the instance's upstreams (gateways, providers entries)

The engine's database is reached through an SSH tunnel, as the role photonvox_adapter (password in ~/.config/photonvox/staging-adapter.pass).
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import socket
import subprocess
import sys
import time
import uuid
from types import SimpleNamespace

from sqlalchemy import create_engine

HOST = os.environ.get("VOX_STAGING", "root@10.10.0.60")
KEY = os.path.expanduser(os.environ.get("VOX_STAGING_KEY", "~/.ssh/vox_staging"))
from app.compiler.compile import Context, compile_plan  # noqa: E402
from app.document.model import PhoneSystem  # noqa: E402
from app.engine import fusionpbx, publish, service, upstreams  # noqa: E402
from app.engine.agent import HttpAgent  # noqa: E402
from app import speech  # noqa: E402

HERE = pathlib.Path(__file__).resolve().parent
STATE = HERE / ".state"
SECRETS = pathlib.Path("~/.config/photonvox/staging-secrets.json").expanduser()
INSTANCE = "7a6b0000-0000-4000-8000-000000000001"           # the staging instance (PhotonVox's pbx_instance id, later)
HOSTNAME = "vox-staging"
# The SIPp upstream on LXC 800 plays every carrier (Step 0.6); it answers on 5071 and calls in from LXC 800's address.
UPSTREAMS = [upstreams.Upstream("sipp-upstream", "10.10.0.80:5071", ("10.10.0.80/32",))]


def tunnel(port: int = 15432, agent_port: int = 18780) -> subprocess.Popen:
    """The engine's database and its vox-agent both listen on the engine's localhost; one SSH tunnel carries both (the management network will)."""
    p = subprocess.Popen(["ssh", "-i", KEY, "-N", "-o", "ExitOnForwardFailure=yes", "-L", f"{port}:127.0.0.1:5432",
                          "-L", f"{agent_port}:10.10.0.60:8780", HOST])
    for _ in range(50):
        try:
            socket.create_connection(("127.0.0.1", port), 0.2).close()
            return p
        except OSError:
            time.sleep(0.2)
    p.terminate()
    raise SystemExit("no tunnel to the staging database")


def engine(port: int = 15432):
    pw = pathlib.Path("~/.config/photonvox/staging-adapter.pass").expanduser().read_text().strip()
    # FusionPBX creates its database as SQL_ASCII: without a client encoding, psycopg returns bytes. UTF-8 is what its PHP reads and writes.
    return create_engine(f"postgresql+psycopg://photonvox_adapter:{pw}@127.0.0.1:{port}/fusionpbx", connect_args={"client_encoding": "utf8"})


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("document", nargs="?")
    ap.add_argument("--name", default="adapter")
    ap.add_argument("--upstreams", action="store_true")
    ap.add_argument("--check", action="store_true", help="after publishing, run the post-publish check's synthetic calls")
    ap.add_argument("--only", action="store_true", help="with --check or --drift: do not publish, only look")
    ap.add_argument("--drift", action="store_true", help="compare the engine with what this document builds (hand edits)")
    ap.add_argument("--speech", action="store_true", help="speak greetings with a stand-in provider (a tone) and put them on the engine")
    a = ap.parse_args()
    secret = pathlib.Path("~/.config/photonvox/agent-10.10.0.60.secret").expanduser().read_text().strip()
    agent = HttpAgent("http://127.0.0.1:18780", secret)
    t = tunnel()
    try:
        eng = engine()
        # The instance's own settings through the same path as Platform → Apply (app/engine/service.py): upstreams and outgoing mail, which
        # on staging is Mailpit on LXC 800 (scripts/sipp.sh mailpit) standing in for Postmark.
        inst = SimpleNamespace(id=INSTANCE, hostname=HOSTNAME, upstreams=[{"key": u.key, "proxy": u.proxy, "addresses": list(u.addresses)} for u in UPSTREAMS],
                               email={"host": "10.10.0.80", "port": 2525, "secure": "none", "from": "voicemail@vox-staging.test", "from_name": "Voicemail"},
                               email_password_sealed="")
        applied = service.apply_instance(inst, lambda _i: (eng, agent))
        if a.upstreams:
            print(json.dumps({"upstreams": applied["gateways"]}))
            return
        up = {"gateways": {u.key: upstreams.gateway_uuid(INSTANCE, u.key) for u in UPSTREAMS}}
        doc = PhoneSystem.model_validate(json.loads(pathlib.Path(a.document).read_text()))
        meta = json.loads(pathlib.Path(a.document).with_suffix(".context.json").read_text())
        ctx = Context(domain=meta["domain"], timezones=meta["timezones"], upstreams={"national": ["sipp-upstream"]}, emergency_gateway="sipp-upstream",
                      validated_locations={k: set(v) for k, v in meta["validated_locations"].items()})
        plan = compile_plan(doc, ctx)
        ps = meta["phone_system_id"]
        target = fusionpbx.Target(ps, str(uuid.uuid5(uuid.UUID(ps), "domain")), up["gateways"], a.speech)
        if a.speech:     # Google stands behind the same interface in production; staging uses a tone (no account, nothing paid)
            tone = (HERE.parent.parent / "sipp/scenarios/tone-ulaw.wav").read_bytes()
            for m in plan["ivr_menus"]:
                agent.put_sound(meta["domain"], speech.file_name(m["greeting"], plan["voice"]), tone)
        STATE.mkdir(exist_ok=True)
        mf = STATE / f"{a.name}.manifest.json"
        previous = json.loads(mf.read_text()) if mf.exists() else []
        if a.only:
            res = None
        else:
            res = publish.publish(eng, agent, plan, target, previous)
            mf.write_text(json.dumps(res.manifest, indent=1))
        if res and res.new_secrets:
            old = json.loads(SECRETS.read_text()) if SECRETS.exists() else {}
            old.setdefault(meta["domain"], {}).update(res.new_secrets)
            fd = os.open(SECRETS, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w") as f:
                json.dump(old, f, indent=1)
        out = {"domain": meta["domain"]}
        if res:
            out.update(inserted=res.inserted, updated=res.updated, removed=res.removed, new_secrets=len(res.new_secrets), cache_cleared=len(res.cache))
        if a.drift:
            with eng.connect() as conn:
                out["drift"] = service.compare(conn, fusionpbx.build(plan, target), target.domain_uuid)
        if a.check:
            results = []
            for c in fusionpbx.checks(plan, target):
                got = agent.check(c["kind"], c["number"], meta["domain"], target.domain_uuid, uuid.uuid4().hex)
                results.append({**c, "got": got, "ok": got in c["expect"]})
            out["check"] = results
        print(json.dumps(out))
    finally:
        t.terminate()


if __name__ == "__main__":
    main()
