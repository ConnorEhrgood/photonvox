"""The FusionPBX adapter's writer: applies a build (app/engine/fusionpbx.py) to an engine's database, in the caller's transaction.

- **Upserts** each row on its id, updating only PhotonVox's columns, so what FusionPBX or a phone user set elsewhere on the same row (call
  forwarding by feature code, do-not-disturb) survives a republish.
- **Removes** what the previous publish wrote and this one does not (the previous manifest), children first.
- **Scoped:** every statement names the phone system's `domain_uuid`; a row of another domain is never read, changed or removed.
- **Secrets:** a SIP password or voicemail PIN is generated only when its row is new; an existing one is kept. New ones are returned once so
  PhotonVox can keep its encrypted copy; they are never logged.
- Returns the cache entries vox-agent must delete (this build's, and those of removed objects).

Gateways and the providers list are the instance's, not a phone system's: app/engine/upstreams.py.
"""
from __future__ import annotations

import json
import secrets as _secrets
import string
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence

from sqlalchemy import text
from sqlalchemy.engine import Connection

from app.engine.fusionpbx import KEYS, TABLES, Build, Secret

JSON_COLUMNS = {("v_destinations", "destination_actions")}


def new_secret(kind: str) -> str:
    """SIP passwords: 24 random letters and digits (ARCHITECTURE §15). Voicemail PINs: 4 random digits (Connor, 2026-11-13)."""
    if kind == "pin":
        return "".join(_secrets.choice(string.digits) for _ in range(4))
    return "".join(_secrets.choice(string.ascii_letters + string.digits) for _ in range(24))


@dataclass
class Result:
    manifest: List[Dict[str, str]]
    inserted: int = 0
    updated: int = 0
    removed: int = 0
    new_secrets: Dict[str, str] = field(default_factory=dict)      # "extension:1001" / "voicemail:1001" -> value (only rows created now)
    cache: List[str] = field(default_factory=list)


def ensure_domain(conn: Connection, domain_uuid: str, name: str) -> bool:
    """Create the FusionPBX domain if it is not there. True when created: the caller then has vox-agent seed its standard dial plans
    (`upgrade.php --defaults`, SPIKES §1c) before writing the phone system."""
    found = conn.execute(text("select domain_name from v_domains where domain_uuid = :d"), {"d": domain_uuid}).scalar()
    if found is not None:
        if found != name:
            raise ValueError(f"domain {domain_uuid} is {found!r} on the engine, not {name!r}")
        return False
    conn.execute(text("insert into v_domains (domain_uuid, domain_name, domain_enabled, domain_description, insert_date) "
                      "values (:d, :n, true, 'PhotonVox', now())"), {"d": domain_uuid, "n": name})
    return True


def write(conn: Connection, b: Build, domain_uuid: str, previous: Sequence[Mapping[str, str]] = (),
          generate: Callable[[str], str] = new_secret) -> Result:
    for table in TABLES:
        for r in b.rows[table]:
            if r["domain_uuid"] != domain_uuid:          # the builder guarantees it; checked again before anything is written
                raise ValueError(f"{table} row {r[KEYS[table]]} is not in domain {domain_uuid}")
    res = Result(manifest=b.manifest())
    current = {(m["table"], m["uuid"]) for m in res.manifest}
    gone = [m for m in previous if (m["table"], m["uuid"]) not in current]
    res.cache = sorted(set(b.cache) | set(_cache_of(conn, gone, domain_uuid)))

    for m in sorted(gone, key=lambda m: -TABLES.index(m["table"])):
        res.removed += conn.execute(text(f"delete from {m['table']} where {KEYS[m['table']]} = :u and domain_uuid = :d"),
                                    {"u": m["uuid"], "d": domain_uuid}).rowcount

    for table in TABLES:
        for r in b.rows[table]:
            inserted, values = _upsert(conn, table, r, domain_uuid, generate)
            if inserted:
                res.inserted += 1
                res.new_secrets.update(values)
            else:
                res.updated += 1

    for app_uuid, enabled in sorted(b.features.items()):
        conn.execute(text("update v_dialplans set dialplan_enabled = :e, update_date = now() where domain_uuid = :d and app_uuid = :a "
                          "and dialplan_enabled is distinct from :e"), {"e": enabled, "d": domain_uuid, "a": app_uuid})
    return res


def _upsert(conn: Connection, table: str, r: Mapping[str, Any], domain_uuid: str, generate: Callable[[str], str]):
    key = KEYS[table]
    secret_cols = {c: v for c, v in r.items() if isinstance(v, Secret)}
    params: Dict[str, Any] = {}
    names, values = [], []
    for c, v in r.items():
        names.append(c)
        params[c] = generate(str(v)) if c in secret_cols else (json.dumps(v) if (table, c) in JSON_COLUMNS else v)
        values.append(f"cast(:{c} as json)" if (table, c) in JSON_COLUMNS else f":{c}")
    sets = [f"{c} = excluded.{c}" for c in names if c not in secret_cols and c != key] + ["update_date = now()"]
    sql = (f"insert into {table} ({', '.join(names)}, insert_date) values ({', '.join(values)}, now()) "
           f"on conflict ({key}) do update set {', '.join(sets)} where {table}.domain_uuid = :domain_uuid "
           f"returning (xmax = 0) as inserted")
    row = conn.execute(text(sql), params).first()
    if row is None:      # the id exists in another domain: never touch it
        raise ValueError(f"{table} row {r[key]} belongs to another domain")
    if row.inserted and secret_cols:
        return True, {_label(table, r): params[c] for c in secret_cols}
    return bool(row.inserted), {}


def _label(table: str, r: Mapping[str, Any]) -> str:
    if table == "v_extensions":
        return f"extension:{r['extension']}"
    return f"voicemail:{r['voicemail_id']}"         # the only other table with a secret


def _cache_of(conn: Connection, gone: Sequence[Mapping[str, str]], domain_uuid: str) -> List[str]:
    """Cache entries of objects about to be removed: their directory entry or their public number entries."""
    keys: List[str] = []
    ids = {t: [m["uuid"] for m in gone if m["table"] == t] for t in ("v_extensions", "v_destinations")}
    if ids["v_extensions"]:
        rows = conn.execute(text("select extension, user_context from v_extensions where extension_uuid = any(cast(:u as uuid[])) "
                                 "and domain_uuid = :d"), {"u": ids["v_extensions"], "d": domain_uuid}).all()
        keys += [f"directory.{x.extension}@{x.user_context}" for x in rows]
    if ids["v_destinations"]:
        rows = conn.execute(text("select destination_prefix, destination_number from v_destinations where "
                                 "destination_uuid = any(cast(:u as uuid[])) and domain_uuid = :d"),
                            {"u": ids["v_destinations"], "d": domain_uuid}).all()
        for x in rows:
            prefix: Optional[str] = x.destination_prefix or ""
            keys += [f"dialplan.public.+{prefix}{x.destination_number}", f"dialplan.public.{prefix}{x.destination_number}",
                     f"dialplan.public.{x.destination_number}"]
    return keys
