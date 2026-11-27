"""Operator commands, run inside the API container (`docker compose … exec -T api python -m app.manage …`). They do what Photon staff do in
Platform, as the system, each written to the audit log with the operator's name; for steps run by hand from a reviewed file (the takeover,
decision 32), where no browser sign-in is involved. Secrets come on standard input, never on a command line, and are never printed.

    add-instance <name> <hostname> <own gateway key>=<gateway id> [simulated] < database-url
                                                                                    an engine with its own gateways and no vox-agent; "simulated":
                                                                                    its phones and calls are simulated, for the demo only
    set-agent <instance name> <agent url> < agent-secret                            its vox-agent, proved by a signed status call first
    set-agent <instance name> off                                                   no vox-agent (publishes that need one are refused)
    adopt <instance name> <organization id> <site id> <domain>                      read, import, prove a no-op, keep (writes nothing to the engine)
    publish <organization id> <note>                                                queue the draft and publish it now (the worker's own code)
    republish <organization id> <version number> <note>                             an earlier version again (the undo), as the draft too
    drift <organization id>                                                         compare the engine with what is published
    set-format <instance name> <upstream key>=<e164|nanp10>                         how an upstream wants North American numbers
    readopt <organization id>                                                       prove the takeover again with this build's importer (no engine write)
    protect <organization id> <caller extension> [<dial plan to retire> ...]       the protections version as a dry run (reads only)
    protect-apply <organization id> [<dial plan to retire> ...]                     mark it protected (the next publish is the protections version)
    show <organization id>                                                          the phone system's state, versions and last drift check
    busy                                                                            how many versions are queued or being published (deploys wait for 0)
    recover <organization id>                                                       a version left "publishing" by a stopped process: marked failed now
    set-911 <organization id> <site id> <key> <street> <city> <state> <zip> <note>    a site's 911 address, validated (the carrier has it on file:
                                                                                    the note says who confirmed it, and when)
    demo seed <simulated instance name>                                             the demo organization's phone system (docs/DEMO.md): made if it
                                                                                    is missing, its document put back as written, published. Run
                                                                                    again, it is as written again (scripts/demo-sim.sh reset does the
                                                                                    engine's side: the call history re-made, the voicemails cleared)
    demo remove                                                                     the demo's phone system removed from PhotonVox, and everything
                                                                                    it wrote from the simulated engine
"""
from __future__ import annotations

import json
import sys
import uuid
from typing import List

from sqlalchemy import delete, select

from app import audit, crypto, demo
from app.db import SystemSession
from app.engine import service, takeover
from app.engine.agent import HttpAgent
from app.models import (CarrierRequest, EmergencyLocation, EmergencyNumber, EngineObject, EngineSecret, HeldNumber, PbxInstance, PhoneSystem,
                        PhoneSystemVersion, Site, Tenant, utcnow)

OPERATOR = "operator (app.manage)"


def _ps(s, tenant: str) -> PhoneSystem:
    ps = s.execute(select(PhoneSystem).where(PhoneSystem.tenant_id == uuid.UUID(tenant))).scalar_one_or_none()
    if ps is None:
        raise SystemExit("this organization has no phone system")
    return ps


def _not_busy(s, ps: PhoneSystem) -> None:
    """The operator waits for a version in flight like everyone else (audit VOX-A-3): two versions written at once would race on the engine."""
    v = service.busy(s, ps)
    if v is not None:
        raise SystemExit(f"version {v.number} is still {v.state}; wait for it (or, if a stopped process left it, `recover <organization id>`)")


def _demo_seed(s, name: str) -> PhoneSystem:
    """The demo organization as docs/DEMO.md has it, ready to publish: its phone system on the simulated instance (made if missing), the sites'
    911 locations (a city only, plainly not an address), its fictional numbers assigned, and the document as written. Where no directory has
    brought the organization (dev), it and its sites are made with the directory's ids. Everything else refuses: an instance that is not
    simulated, an organization the directory does not mark as a demo, a phone system that is somewhere else."""
    i = s.execute(select(PbxInstance).where(PbxInstance.name == name)).scalar_one_or_none()
    if i is None or not i.simulated or i.role != "active":
        raise SystemExit("the demo goes only on an active simulated instance (docs/DEMO.md)")
    org = uuid.UUID(demo.ORG)
    tenant = s.get(Tenant, org)
    if tenant is None:
        s.add(Tenant(id=org, name="Photon Demo", slug="demo", status="active", products=["vox"], demo=True))
    elif not tenant.demo:
        raise SystemExit("the directory does not mark this organization as a demo")
    for sid, (slug, site_name, city, state) in demo.SITES.items():
        if s.get(Site, uuid.UUID(sid)) is None:
            s.add(Site(id=uuid.UUID(sid), tenant_id=org, slug=slug, name=site_name, address=f"{city}, {state}", timezone="America/New_York"))
    doc = demo.document()
    for number in doc["numbers"]:
        held = s.get(HeldNumber, number)
        if held is None:
            s.add(HeldNumber(number=number, tenant_id=org, carrier="simulated", note="demo: fictional, at no carrier"))
        elif held.tenant_id != org:
            raise SystemExit(f"{number} is held for someone else")
    for sid, address in demo.emergency_locations().items():
        loc = s.execute(select(EmergencyLocation).where(EmergencyLocation.site_id == uuid.UUID(sid), EmergencyLocation.key == "main")).scalar_one_or_none()
        if loc is None:
            loc = EmergencyLocation(tenant_id=org, site_id=uuid.UUID(sid), key="main")
            s.add(loc)
        loc.address, loc.status, loc.note = address, "validated", "demo: not a real address, never sent to a carrier"
        loc.validated_by_label, loc.validated_at = OPERATOR, utcnow()
    ps = s.execute(select(PhoneSystem).where(PhoneSystem.tenant_id == org)).scalar_one_or_none()
    if ps is None:
        # Fixed ids: every engine row's id derives from them, so the demo seeded again after a removal is the same rows on the engine.
        ps = PhoneSystem(id=uuid.uuid5(org, "phone-system"), tenant_id=org, instance_id=i.id, domain_name=demo.DOMAIN,
                         domain_uuid=uuid.uuid5(org, "domain:" + demo.DOMAIN), draft=doc)
        s.add(ps)
    elif ps.instance_id != i.id or ps.domain_name != demo.DOMAIN:
        raise SystemExit(f"the demo already has a phone system elsewhere ({ps.domain_name}); `demo remove` first")
    s.flush()
    _not_busy(s, ps)
    ps.draft = doc
    return ps


def _demo_remove(s, connect: service.Connect) -> dict:
    """The demo's phone system gone from PhotonVox and everything it wrote gone from the simulated engine. Only ever the demo on a simulated
    instance: a customer's phone system is not removed this way. The organization and its sites stay (they are the directory's)."""
    ps = _ps(s, demo.ORG)
    i, tenant = s.get(PbxInstance, ps.instance_id), s.get(Tenant, ps.tenant_id)
    if not (tenant is not None and tenant.demo and i.simulated):
        raise SystemExit("only the demo organization on a simulated instance is removed this way")
    _not_busy(s, ps)
    removed = service.remove(s, ps, i, connect) if ps.published_version or service.manifest(s, ps) else 0
    for model in (PhoneSystemVersion, EngineObject, EngineSecret):
        s.execute(delete(model).where(model.phone_system_id == ps.id))
    for model in (EmergencyNumber, CarrierRequest, EmergencyLocation, HeldNumber):
        s.execute(delete(model).where(model.tenant_id == ps.tenant_id))
    out = {"removed": str(ps.id), "domain": ps.domain_name, "instance": i.name, "engine_rows_removed": removed}
    audit.record(s, actor_id=None, actor_label=OPERATOR, actor_source="platform", action="phone_system.removed", tenant_id=ps.tenant_id,
                 target_type="phone_system", target_id=ps.id, domain=ps.domain_name, instance=str(i.id), engine_rows_removed=removed)
    s.delete(ps)
    return out


def main(argv: List[str], stdin=sys.stdin, out=sys.stdout, connect: service.Connect = service.connect, agent=None) -> int:
    if not argv:
        out.write(__doc__ or "")
        return 2
    cmd, args = argv[0], argv[1:]
    with SystemSession() as s:
        if cmd == "add-instance":
            name, host, gw = args[:3]
            if args[3:] not in ([], ["simulated"]):
                raise SystemExit("after the gateway: nothing, or `simulated`")
            key, _, gid = gw.partition("=")
            url = stdin.readline().strip()
            if not url.startswith("postgresql+psycopg://"):
                raise SystemExit("the database URL (postgresql+psycopg://…) goes on standard input")
            i = PbxInstance(name=name, hostname=host, region="us-east", role="active", database_url_sealed=crypto.seal(url), agent={"kind": "none"},
                            agent_secret_sealed="", upstreams=[], routing={"national": [key]}, emergency_upstream=key, own_gateways={key: str(uuid.UUID(gid))},
                            simulated=bool(args[3:]))
            s.add(i)
            s.flush()
            audit.record(s, actor_id=None, actor_label=OPERATOR, actor_source="platform", action="instance.added", target_type="pbx_instance",
                         target_id=i.id, name=name)
            s.commit()
            json.dump({"instance": str(i.id), "name": name, "own_gateways": i.own_gateways, "simulated": i.simulated}, out)
        elif cmd == "set-agent" and args[1:] == ["off"]:
            i = s.execute(select(PbxInstance).where(PbxInstance.name == args[0])).scalar_one()
            i.agent, i.agent_secret_sealed = {"kind": "none"}, ""
            audit.record(s, actor_id=None, actor_label=OPERATOR, actor_source="platform", action="instance.agent_off", target_type="pbx_instance",
                         target_id=i.id)
            s.commit()
            json.dump({"instance": args[0], "agent": None}, out)
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
            _not_busy(s, ps)
            v = service.queue(s, ps, ps.draft, None, OPERATOR, note)
            s.flush()
            audit.record(s, actor_id=None, actor_label=OPERATOR, actor_source="platform", action="phone_system.publish_requested",
                         tenant_id=ps.tenant_id, target_type="phone_system", target_id=ps.id, version=v.number, note=note)
            s.commit()
            state = service.publish_version(s, v.id, connect)
            v = s.get(PhoneSystemVersion, v.id)
            json.dump({"version": v.number, "state": state, "error": v.error, "checks": (v.check or {}).get("results", [])}, out)
        elif cmd == "republish":
            tenant, number, note = args
            ps = _ps(s, tenant)
            old = s.execute(select(PhoneSystemVersion).where(PhoneSystemVersion.phone_system_id == ps.id,
                                                             PhoneSystemVersion.number == int(number))).scalar_one_or_none()
            if old is None:
                raise SystemExit(f"this phone system has no version {number}")
            _not_busy(s, ps)
            ps.draft = old.document                 # the draft too: the next publish does not bring back what was undone
            v = service.queue(s, ps, old.document, None, OPERATOR, note)
            s.flush()
            audit.record(s, actor_id=None, actor_label=OPERATOR, actor_source="platform", action="phone_system.publish_requested",
                         tenant_id=ps.tenant_id, target_type="phone_system", target_id=ps.id, version=v.number, note=note, again=int(number))
            s.commit()
            state = service.publish_version(s, v.id, connect)
            v = s.get(PhoneSystemVersion, v.id)
            json.dump({"version": v.number, "as_version": int(number), "state": state, "error": v.error,
                       "checks": (v.check or {}).get("results", [])}, out)
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
        elif cmd == "set-911":
            tenant, site, key, street, city, state, zip_, note = args
            tid, sid = uuid.UUID(tenant), uuid.UUID(site)
            if s.execute(select(Site).where(Site.id == sid, Site.tenant_id == tid)).scalar_one_or_none() is None:
                raise SystemExit("that site is not the organization's")
            if len(state) != 2 or not zip_.isdigit() or len(zip_) != 5 or not street.strip() or not city.strip() or not note.strip():
                raise SystemExit("the address is <street> <city> <two-letter state> <five-digit zip>, and the note says who confirmed it")
            loc = s.execute(select(EmergencyLocation).where(EmergencyLocation.site_id == sid, EmergencyLocation.key == key)).scalar_one_or_none()
            if loc is None:
                loc = EmergencyLocation(tenant_id=tid, site_id=sid, key=key)
                s.add(loc)
            loc.address = {"street": street.strip(), "city": city.strip(), "state": state.upper(), "zip": zip_}
            loc.status, loc.note, loc.validated_by_label, loc.validated_at = "validated", note.strip(), OPERATOR, utcnow()
            s.flush()
            audit.record(s, actor_id=None, actor_label=OPERATOR, actor_source="platform", action="emergency_location.validated", tenant_id=tid,
                         target_type="emergency_location", target_id=loc.id, site=str(sid), key=key, note=note.strip())
            s.commit()
            json.dump({"id": str(loc.id), "site_id": site, "key": key, "address": loc.address, "status": loc.status}, out)
        elif cmd == "demo" and args[:1] == ["seed"] and len(args) == 2:
            ps = _demo_seed(s, args[1])
            note = "the demo, as written (docs/DEMO.md)"
            v = service.queue(s, ps, ps.draft, None, OPERATOR, note)
            s.flush()
            audit.record(s, actor_id=None, actor_label=OPERATOR, actor_source="platform", action="phone_system.publish_requested",
                         tenant_id=ps.tenant_id, target_type="phone_system", target_id=ps.id, version=v.number, note=note, demo=True)
            s.commit()
            state = service.publish_version(s, v.id, connect)
            v = s.get(PhoneSystemVersion, v.id)
            checks = (v.check or {}).get("results", [])
            json.dump({"organization": demo.ORG, "instance": args[1], "domain": ps.domain_name, "version": v.number, "state": state, "error": v.error,
                       "checks": len(checks), "checks_failed": [f"{c['kind']} {c['number']}" for c in checks if not c["ok"]]}, out)
        elif cmd == "demo" and args == ["remove"]:
            res = _demo_remove(s, connect)
            s.commit()
            json.dump(res, out)
        elif cmd == "busy":
            out.write(str(len(s.execute(select(PhoneSystemVersion.id).where(PhoneSystemVersion.state.in_(service.BUSY))).all())))
        elif cmd == "recover":
            ps = _ps(s, args[0])
            json.dump({"recovered": service.recover_interrupted(s, 0, ps.id)}, out)
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
