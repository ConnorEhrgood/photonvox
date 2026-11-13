"""An instance's upstreams (Photon trunking, ARCHITECTURE §9): one FusionPBX gateway each, and the addresses each calls from in FusionPBX's
`providers` list, so the external profile takes its calls without a challenge (SPIKES §1a). Instance-wide rows, so `domain_uuid` is empty: the
one place the adapter writes outside a phone system's domain.

Note (SPIKES §1c): FusionPBX applies the providers list on the internal profile too, so a phone calling from an upstream's address would skip
authentication. Upstreams' addresses never host phones.
"""
from __future__ import annotations

import ipaddress
import uuid
from dataclasses import dataclass
from typing import Dict, List, Sequence, Tuple

from sqlalchemy import text
from sqlalchemy.engine import Connection

MARK = "PhotonVox upstream "      # the description of every providers-list entry PhotonVox owns


@dataclass(frozen=True)
class Upstream:
    key: str                         # the plan's gateway key ("htc"); also the gateway's name in FusionPBX
    proxy: str                       # host[:port] calls are sent to
    addresses: Tuple[str, ...]       # networks it calls from (CIDR)
    profile: str = "external"


def gateway_uuid(instance_id: str, key: str) -> str:
    return str(uuid.uuid5(uuid.UUID(instance_id), "gateway:" + key))


def write_upstreams(conn: Connection, instance_id: str, hostname: str, upstreams: Sequence[Upstream]) -> Dict[str, object]:
    """Make the engine's PhotonVox gateways and providers entries exactly these. Returns the gateway ids by key and what vox-agent must do
    afterwards (delete these cache entries, rescan the profiles, reload the access lists)."""
    keep = {gateway_uuid(instance_id, u.key) for u in upstreams}
    owned = [r.gateway_uuid for r in conn.execute(text("select gateway_uuid::text from v_gateways where domain_uuid is null and "
                                                       "description like :m"), {"m": MARK + "%"})]
    removed = sorted(g for g in owned if g not in keep)
    for g in removed:      # a rescan does not stop a gateway that is gone from the database: vox-agent kills it (`killgw`)
        conn.execute(text("delete from v_gateways where gateway_uuid = :g and domain_uuid is null"), {"g": g})
    for u in upstreams:
        conn.execute(text(
            "insert into v_gateways (gateway_uuid, domain_uuid, gateway, username, password, proxy, register, expire_seconds, retry_seconds, "
            "distinct_to, caller_id_in_from, supress_cng, contact_in_ping, channels, context, profile, enabled, description, insert_date) "
            "values (:g, null, :k, 'photonvox', 'ip-authenticated', :p, false, 800, 30, false, false, false, false, 0, 'public', :prof, true, "
            ":desc, now()) on conflict (gateway_uuid) do update set gateway = excluded.gateway, proxy = excluded.proxy, profile = excluded.profile, "
            "enabled = true, description = excluded.description, update_date = now()"),
            {"g": gateway_uuid(instance_id, u.key), "k": u.key, "p": u.proxy, "prof": u.profile, "desc": MARK + u.key})

    providers = conn.execute(text("select access_control_uuid from v_access_controls where access_control_name = 'providers'")).scalar()
    if providers is None:
        raise ValueError("this engine has no providers access list")
    wanted: List[Tuple[str, str]] = sorted({(str(ipaddress.ip_network(a)), u.key) for u in upstreams for a in u.addresses})
    conn.execute(text("delete from v_access_control_nodes where access_control_uuid = :a and node_description like :m"),
                 {"a": providers, "m": MARK + "%"})
    for cidr, key in wanted:
        conn.execute(text("insert into v_access_control_nodes (access_control_node_uuid, access_control_uuid, node_type, node_cidr, "
                          "node_description, insert_date) values (:n, :a, 'allow', :c, :d, now())"),
                     {"n": str(uuid.uuid5(uuid.UUID(instance_id), f"acl:{key}:{cidr}")), "a": providers, "c": cidr, "d": MARK + key})
    return {"gateways": {u.key: gateway_uuid(instance_id, u.key) for u in upstreams},
            "cache": [f"{hostname}.configuration.sofia.conf", "configuration.acl.conf"], "rescan": sorted({u.profile for u in upstreams}),
            "kill": removed, "reload_acl": True}
