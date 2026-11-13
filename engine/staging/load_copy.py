"""A copy of a live domain on the staging instance, for rehearsing its takeover (ARCHITECTURE §17.5): SQL on standard output, from an export
(engine/live/export_domain.py), to pipe into staging's psql as postgres.

- The domain keeps its name and id, and every row keeps its id, so the takeover runs exactly as it will on the live engine.
- The export has no secrets: SIP passwords and voicemail PINs are generated here (random, never the live ones).
- Gateways are never copied (Connor's staging rule): the domain's upstream keeps its id, so its dial plans still name it, but it points at the
  SIPp stand-in on LXC 800, owned by another domain as on the live engine, with no credentials.
- Only the domain's own dial plans are copied (staging keeps its own global ones). FusionPBX users are not copied.
    python3 engine/staging/load_copy.py <export.json> <owner domain uuid on staging> | ssh … 'sudo -u postgres psql -d fusionpbx -v ON_ERROR_STOP=1'
"""
from __future__ import annotations

import json
import secrets
import string
import sys

TABLES = ("v_extensions", "v_voicemails", "v_ivr_menus", "v_ivr_menu_options", "v_dialplans", "v_dialplan_details", "v_destinations", "v_recordings")
JSON_COLUMNS = {("v_destinations", "destination_actions"), ("v_destinations", "destination_conditions")}
STANDIN = "10.10.0.80:5071"


def lit(v) -> str:
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, (list, dict)):
        v = json.dumps(v)
    return "'" + str(v).replace("'", "''") + "'"


def main(path: str, owner: str) -> None:
    e = json.load(open(path))
    D = e["domain"]["domain_uuid"]
    out = ["begin;", f"insert into v_domains (domain_uuid, domain_name, domain_enabled, insert_date) values ({lit(D)}, {lit(e['domain']['domain_name'])}, true, now());"]
    dialplans = {r["dialplan_uuid"] for r in e["tables"]["v_dialplans"] if r.get("domain_uuid") == D}
    for t in TABLES:
        for r in e["tables"].get(t) or []:
            if t == "v_dialplan_details" and r["dialplan_uuid"] not in dialplans:
                continue
            if t != "v_dialplan_details" and r.get("domain_uuid") != D:
                continue
            row = dict(r)
            if t == "v_extensions":
                row["password"] = "".join(secrets.choice(string.ascii_letters + string.digits) for _ in range(24))
            if t == "v_voicemails":
                row["voicemail_password"] = "".join(secrets.choice(string.digits) for _ in range(4))
            cols = list(row)
            vals = [f"cast({lit(row[c])} as json)" if (t, c) in JSON_COLUMNS and row[c] is not None else lit(row[c]) for c in cols]
            out.append(f"insert into {t} ({', '.join(cols)}) values ({', '.join(vals)});")
    for g in e["tables"].get("v_gateways") or []:
        out.append("insert into v_gateways (gateway_uuid, domain_uuid, gateway, username, password, proxy, register, expire_seconds, retry_seconds, "
                   "distinct_to, caller_id_in_from, supress_cng, contact_in_ping, channels, context, profile, enabled, description, insert_date) values "
                   f"({lit(g['gateway_uuid'])}, {lit(owner)}, {lit(g['gateway'] + ' (SIPp stand-in)')}, 'staging', 'ip-authenticated', {lit(STANDIN)}, "
                   "false, 800, 30, false, false, false, false, 0, 'public', 'external', true, 'stand-in for the takeover rehearsal: never a carrier', now());")
    out.append("commit;")
    print("\n".join(out))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
