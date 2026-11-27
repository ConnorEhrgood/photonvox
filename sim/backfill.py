"""The demo's call history back-filled (docs/DEMO.md §2): `days` days up to now as FusionPBX call records (`v_xml_cdr`) in the demo domain on the
staging engine, in the columns FreeSWITCH writes (no XML or JSON), each marked accountcode 'photonvox-sim'. Prints SQL for psql as postgres:

    scripts/demo-sim.sh reset        (python3 sim/backfill.py [--days 35] | psql as postgres on the staging engine)

One transaction. The domain's earlier records end where the back-fill begins: all of the domain's records before now are replaced (the reset),
the live simulator's calls after now are kept. Only the demo domain is touched: the SQL names it, and the script refuses any other.
"""
from __future__ import annotations

import argparse
import sys
import uuid
from datetime import datetime, timedelta, timezone
from typing import List, Optional

sys.path.insert(0, __import__("os").path.dirname(__import__("os").path.abspath(__file__)))
import traffic  # noqa: E402

DOMAIN = "demo.vox.test"
NS = uuid.UUID("7a6b0000-0000-4000-8000-00000000de00")
COLUMNS = ("xml_cdr_uuid", "direction", "caller_id_name", "caller_id_number", "caller_destination", "destination_number", "ext", "start_epoch",
           "answer_epoch", "end_epoch", "duration", "billsec", "status", "missed_call", "voicemail_message", "hangup_cause")


def row(c: traffic.Call) -> tuple:
    site = traffic.SITES[c.site]
    answer: Optional[int] = int(c.start + c.ring_s) if c.status in ("answered", "voicemail") else None
    end = int(c.end)
    if c.kind == "inbound":
        ext = c.reached if c.status == "answered" else None
        dest = c.reached if c.status == "answered" else c.dialed
        values = ("inbound", "", c.caller, c.dialed, dest, ext)
    elif c.kind == "outbound":
        values = ("outbound", "", site.caller_id, c.dialed, c.dialed, c.caller)
    elif c.kind == "internal":
        values = ("local", "", c.caller, c.dialed, c.dialed, c.dialed)
    else:
        values = ("local", "", c.caller, c.dialed, c.dialed, None)
    cause = "NORMAL_CLEARING" if c.status != "missed" else ("ORIGINATOR_CANCEL" if c.kind != "outbound" else "NO_ANSWER")
    return (str(uuid.uuid5(NS, f"{c.site}:{c.start}:{c.caller}:{c.dialed}")),) + values + (
        int(c.start), answer, end, end - int(c.start), c.talk_s if answer else 0, c.status if c.kind == "inbound" or c.status == "answered" else "cancelled",
        c.status != "answered" and c.kind == "inbound", c.status == "voicemail", cause)        # as FusionPBX marks them: a voicemail is a missed call too


def lit(v) -> str:
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int):
        return str(v)
    return "'" + str(v).replace("'", "''") + "'"


def sql(calls: List[traffic.Call], until: int, domain: str = DOMAIN) -> str:
    if domain != DOMAIN:
        raise SystemExit(f"the back-fill writes only {DOMAIN}")
    rows = ",\n".join("(" + ", ".join(lit(v) for v in row(c)) + ")" for c in calls)
    return f"""begin;
create temporary table sim_cdr ({", ".join(f"{c} text" for c in COLUMNS)}) on commit drop;
{"insert into sim_cdr values" + chr(10) + rows + ";" if calls else ""}
delete from v_xml_cdr where domain_uuid = (select domain_uuid from v_domains where domain_name = {lit(domain)}) and start_epoch < {until};
insert into v_xml_cdr (xml_cdr_uuid, domain_uuid, domain_name, accountcode, direction, leg, context, caller_id_name, caller_id_number,
  caller_destination, destination_number, extension_uuid, start_epoch, answer_epoch, end_epoch, start_stamp, answer_stamp, end_stamp,
  duration, billsec, status, missed_call, voicemail_message, hangup_cause)
select s.xml_cdr_uuid::uuid, d.domain_uuid, d.domain_name, 'photonvox-sim', s.direction, 'a', d.domain_name, s.caller_id_name, s.caller_id_number,
  s.caller_destination, s.destination_number, (select e.extension_uuid from v_extensions e where e.domain_uuid = d.domain_uuid and e.extension = s.ext),
  s.start_epoch::bigint, s.answer_epoch::bigint, s.end_epoch::bigint, to_timestamp(s.start_epoch::bigint), to_timestamp(s.answer_epoch::bigint),
  to_timestamp(s.end_epoch::bigint), s.duration::int, s.billsec::int, s.status, s.missed_call::boolean, s.voicemail_message::boolean, s.hangup_cause
from sim_cdr s, v_domains d where d.domain_name = {lit(domain)};
commit;
"""


def main() -> None:
    a = argparse.ArgumentParser()
    a.add_argument("--days", type=int, default=35)
    args = a.parse_args()
    now = datetime.now(timezone.utc)
    calls = [c for c in traffic.between(now - timedelta(days=args.days), now) if c.end < now.timestamp()]
    sys.stdout.write(sql(calls, int(now.timestamp())))
    print(f"-- {len(calls)} calls", file=sys.stderr)


if __name__ == "__main__":
    main()
