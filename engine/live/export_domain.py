"""A read-only export of one FusionPBX domain, for the takeover importer (ARCHITECTURE §17.2). Runs where a database login can reach the engine
(on the Vultr host: inside PhotonVox's API container, which leaves the host as 10.2.1.5); prints one JSON document to standard output.

Standard input: the first line is the password; the rest of this script follows it (so neither touches a command line):
    { cat ~/.config/photonvox/live-ro.pass; cat engine/live/export_domain.py; } | ssh prod '... exec -T api python -c "import sys; sys.argv=[\\"x\\", <args>]; ..."'
Arguments: host, user, the domain name pattern (SQL LIKE, matching exactly one domain).

What it reads: the domain's rows in the tables the takeover manages, every dial plan of the domain and of the global and public contexts, the
gateways, the domain's recordings (names, not audio) and FusionPBX users (usernames and whether enabled), and call counts. Only the columns the
login may read are selected, and a deny list drops secrets even where a login could read them (so the export never holds one). Nothing is written.
"""
from __future__ import annotations

import datetime as dt
import decimal
import json
import sys
import uuid

import psycopg

DENY = {
    "v_extensions": {"password"}, "v_voicemails": {"voicemail_password"}, "v_ivr_menus": {"ivr_menu_pin_number"},
    "v_gateways": {"username", "password", "auth_username"}, "v_recordings": {"recording_base64"},
    "v_users": {"password", "salt", "api_key", "user_totp_secret", "contact_uuid", "user_email"},
    "v_xml_cdr": {"xml", "json", "pin_number", "network_addr", "record_path", "record_name", "record_length", "record_transcription", "sip_call_id"},
}
# table -> which rows: the domain's (by domain_uuid), or also the shared ones (dial plans of the global and public contexts have no domain or another)
DOMAIN_TABLES = ("v_extensions", "v_extension_users", "v_voicemails", "v_destinations", "v_ivr_menus", "v_ivr_menu_options", "v_ring_groups",
                 "v_ring_group_destinations", "v_recordings", "v_users")


def _plain(v):
    if isinstance(v, (dt.datetime, dt.date)):
        return v.isoformat()
    if isinstance(v, (uuid.UUID, decimal.Decimal)):
        return str(v)
    return v


def columns(c, table: str) -> list:
    rows = c.execute("select column_name from information_schema.columns where table_schema = 'public' and table_name = %s "
                     "and has_column_privilege(current_user, 'public.' || table_name, column_name, 'select') order by ordinal_position", (table,)).fetchall()
    return [r[0] for r in rows if r[0] not in DENY.get(table, set())]


def select(c, table: str, where: str, args: tuple):
    """The rows, or None when this login may read no column of the table (the export then says so)."""
    cols = columns(c, table)
    if not cols:
        return None
    q = f"select {', '.join(chr(34) + x + chr(34) for x in cols)} from {table} where {where}"
    return [{k: _plain(v) for k, v in zip(cols, r)} for r in c.execute(q, args).fetchall()]


def export(c, pattern: str) -> dict:
    doms = c.execute("select domain_uuid, domain_name, domain_enabled from v_domains where domain_name like %s", (pattern,)).fetchall()
    if len(doms) != 1:
        raise SystemExit(f"the pattern matches {len(doms)} domains, not one")
    d = str(doms[0][0])
    out = {"exported_at": dt.datetime.now(dt.timezone.utc).isoformat(), "engine": {"version": c.execute("show server_version").fetchone()[0]},
           "domain": {"domain_uuid": d, "domain_name": doms[0][1], "domain_enabled": doms[0][2]}, "tables": {}}
    for t in DOMAIN_TABLES:
        out["tables"][t] = select(c, t, "domain_uuid = %s", (d,))
    # Every dial plan FreeSWITCH may run for this domain's calls: its own, the public context's (inbound numbers) and the global ones.
    out["tables"]["v_dialplans"] = select(c, "v_dialplans", "domain_uuid = %s or domain_uuid is null or dialplan_context in ('public', 'global')", (d,))
    ids = [r["dialplan_uuid"] for r in out["tables"]["v_dialplans"] or []]
    out["tables"]["v_dialplan_details"] = select(c, "v_dialplan_details", "dialplan_uuid::text = any(%s)", (ids,))
    out["tables"]["v_gateways"] = select(c, "v_gateways", "true", ())
    out["other_domains"] = c.execute("select count(*) from v_domains where domain_uuid <> %s", (d,)).fetchone()[0]
    readable = c.execute("select has_column_privilege(current_user, 'public.v_xml_cdr', 'billsec', 'select')").fetchone()[0]
    out["calls_30_days"] = None if not readable else [{"direction": r[0], "calls": r[1], "answered": r[2]} for r in c.execute(
        "select direction, count(*), count(*) filter (where billsec > 0) from v_xml_cdr where domain_uuid = %s and start_stamp > now() - interval '30 days' "
        "group by 1 order by 1", (d,)).fetchall()]
    return out


def main(host: str, user: str, pattern: str, password: str) -> None:
    with psycopg.connect(host=host, dbname="fusionpbx", user=user, password=password, client_encoding="utf8", connect_timeout=10) as c:
        c.execute("set transaction read only")
        doc = export(c, pattern)
    json.dump(doc, sys.stdout, sort_keys=True)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], sys.argv[3], sys.stdin.readline().strip())
