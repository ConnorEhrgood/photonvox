"""Operator commands, run inside the API container (`docker compose … exec -T api python -m app.manage …`). They do what Photon staff do in
Platform, as the system, each written to the audit log with the operator's name; for steps run by hand from a reviewed file (the takeover,
decision 32), where no browser sign-in is involved. Secrets come on standard input, never on a command line, and are never printed.

    add-instance <name> <hostname> <own gateway key>=<gateway id> < database-url    an engine with its own gateways and no vox-agent
    set-agent <instance name> <agent url> < agent-secret                            its vox-agent, proved by a signed status call first
    adopt <instance name> <organization id> <site id> <domain>                      read, import, prove a no-op, keep (writes nothing to the engine)
    publish <organization id> <note>                                                queue the draft and publish it now (the worker's own code)
    drift <organization id>                                                         compare the engine with what is published
    set-format <instance name> <upstream key>=<e164|nanp10>                         how an upstream wants North American numbers
    readopt <organization id>                                                       prove the takeover again with this build's importer (no engine write)
    protect <organization id> <caller extension> [<dial plan to retire> ...]       the protections version as a dry run (reads only)
    protect-apply <organization id> [<dial plan to retire> ...]                     mark it protected (the next publish is the protections version)
    show <organization id>                                                          the phone system's state, versions and last drift check
"""
from __future__ import annotations

import json
import sys
import uuid
from typing import List

from sqlalchemy import select

from app import audit, crypto
from app.db import SystemSession
from app.engine import service, takeover
from app.engine.agent import HttpAgent
from app.models import PbxInstance, PhoneSystem, PhoneSystemVersion

OPERATOR = "operator (app.manage)"


def _ps(s, tenant: str) -> PhoneSystem:
    ps = s.execute(select(PhoneSystem).where(PhoneSystem.tenant_id == uuid.UUID(tenant))).scalar_one_or_none()
    if ps is None:
        raise SystemExit("this organization has no phone system")
    return ps


def main(argv: List[str], stdin=sys.stdin, out=sys.stdout, connect: service.Connect = service.connect, agent=None) -> int:
    if not argv:
        out.write(__doc__ or "")
        return 2
    cmd, args = argv[0], argv[1:]
    with SystemSession() as s:
        if cmd == "add-instance":
            name, host, gw = args
            key, _, gid = gw.partition("=")
            url = stdin.readline().strip()
            if not url.startswith("postgresql+psycopg://"):
                raise SystemExit("the database URL (postgresql+psycopg://…) goes on standard input")
            i = PbxInstance(name=name, hostname=host, region="us-east", role="active", database_url_sealed=crypto.seal(url), agent={"kind": "none"},
                            agent_secret_sealed="", upstreams=[], routing={"national": [key]}, emergency_upstream=key, own_gateways={key: str(uuid.UUID(gid))})
            s.add(i)
            s.flush()
            audit.record(s, actor_id=None, actor_label=OPERATOR, actor_source="platform", action="instance.added", target_type="pbx_instance",
                         target_id=i.id, name=name)
            s.commit()
            json.dump({"instance": str(i.id), "name": name, "own_gateways": i.own_gateways}, out)
        elif cmd == "set-agent":
            name, url = args
            secret = stdin.readline().strip()
            if len(secret) < 32 or not url.startswith(("http://", "https://")):
                raise SystemExit("the agent's URL is http(s)://host:port, and its secret (32+ characters) goes on standard input")
            i = s.execute(select(PbxInstance).where(PbxInstance.name == name)).scalar_one()
            st = (agent or HttpAgent)(url, secret).status()        # reached, and the secret is the agent's: before anything is kept
            i.agent, i.agent_secret_sealed = {"kind": "http", "url": url}, crypto.seal(secret)
            audit.record(s, actor_id=None, actor_label=OPERATOR, actor_source="platform", action="instance.agent_set", target_type="pbx_instance",
                         target_id=i.id, url=url, agent_version=st.get("agent"))
            s.commit()
            json.dump({"instance": name, "agent": url, "agent_version": st.get("agent"), "freeswitch": st.get("freeswitch"),
                       "registrations": st.get("registrations")}, out)
        elif cmd == "adopt":
            name, tenant, site, domain = args
            i = s.execute(select(PbxInstance).where(PbxInstance.name == name)).scalar_one()
            eng, _agent = connect(i)
            try:
                with eng.connect() as conn:
                    res = takeover.adopt(s, i, uuid.UUID(tenant), uuid.UUID(site), domain, conn)
            finally:
                eng.dispose()
            audit.record(s, actor_id=None, actor_label=OPERATOR, actor_source="platform", action="phone_system.adopted", tenant_id=uuid.UUID(tenant),
                         target_type="phone_system", target_id=res["phone_system_id"], instance=str(i.id), objects=res["objects"], extras=res["extras"])
            s.commit()
            json.dump(res, out, indent=1)
        elif cmd == "publish":
            tenant, note = args
            ps = _ps(s, tenant)
            v = service.queue(s, ps, ps.draft, None, OPERATOR, note)
            s.flush()
            audit.record(s, actor_id=None, actor_label=OPERATOR, actor_source="platform", action="phone_system.publish_requested",
                         tenant_id=ps.tenant_id, target_type="phone_system", target_id=ps.id, version=v.number, note=note)
            s.commit()
            state = service.publish_version(s, v.id, connect)
            v = s.get(PhoneSystemVersion, v.id)
            json.dump({"version": v.number, "state": state, "error": v.error, "checks": (v.check or {}).get("results", [])}, out)
        elif cmd == "set-format":
            name, kv = args
            key, _, fmt = kv.partition("=")
            if fmt not in ("e164", "nanp10"):
                raise SystemExit("the format is e164 or nanp10")
            i = s.execute(select(PbxInstance).where(PbxInstance.name == name)).scalar_one()
            i.dial_formats = {**(i.dial_formats or {}), key: fmt}
            audit.record(s, actor_id=None, actor_label=OPERATOR, actor_source="platform", action="instance.dial_format", target_type="pbx_instance",
                         target_id=i.id, upstream=key, format=fmt)
            s.commit()
            json.dump({"instance": name, "dial_formats": i.dial_formats}, out)
        elif cmd in ("readopt", "protect", "protect-apply"):
            ps = _ps(s, args[0])
            i = s.get(PbxInstance, ps.instance_id)
            eng, _agent = connect(i)
            try:
                with eng.connect() as conn:
                    if cmd == "readopt":
                        res = takeover.readopt(s, ps, i, conn)
                    elif cmd == "protect":
                        res = takeover.protect_preview(s, ps, i, conn, list(args[2:]), args[1])
                    else:
                        res = takeover.protect_apply(ps, takeover.read_domain(conn, ps.domain_name), list(args[1:]))
            finally:
                eng.dispose()
            if cmd == "protect":
                s.rollback()                        # a dry run: nothing kept
            else:
                audit.record(s, actor_id=None, actor_label=OPERATOR, actor_source="platform", action=f"phone_system.{cmd.replace('-', '_')}",
                             tenant_id=ps.tenant_id, target_type="phone_system", target_id=ps.id, **({"retire": args[1:]} if cmd == "protect-apply" else {}))
                s.commit()
            json.dump(res, out, indent=1, default=str)
        elif cmd == "drift":
            ps = _ps(s, args[0])
            json.dump(service.check_drift(s, ps, connect), out, indent=1, default=str)
        elif cmd == "show":
            ps = _ps(s, args[0])
            versions = s.execute(select(PhoneSystemVersion).where(PhoneSystemVersion.phone_system_id == ps.id).order_by(PhoneSystemVersion.number)).scalars()
            json.dump({"status": ps.status, "published_version": ps.published_version, "adopted": ps.adoption is not None,
                       "versions": [{"number": v.number, "state": v.state, "error": v.error} for v in versions], "drift": ps.drift}, out, indent=1, default=str)
        else:
            out.write(__doc__ or "")
            return 2
    out.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
