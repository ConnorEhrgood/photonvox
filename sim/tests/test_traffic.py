"""The demo's traffic model and back-fill: business-like days, only fictional numbers and the demo's extensions (never an emergency or service
code), the same day the same every time, and call records shaped as the dashboard reads them."""
import os
import re
import sys
from datetime import date, datetime, timedelta, timezone

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import backfill  # noqa: E402
import traffic  # noqa: E402

THURSDAY, SUNDAY = date(2026, 11, 12), date(2026, 11, 15)


def test_a_business_day_looks_like_one():
    hq = traffic.day("demo-hq", THURSDAY)
    assert 120 <= len(hq) <= 220
    by_hour = [sum(1 for c in hq if datetime.fromtimestamp(c.start, traffic.NY).hour == h) for h in range(24)]
    assert max(range(24), key=lambda h: by_hour[h]) in range(9, 16) and sum(by_hour[:6]) == 0
    assert len(traffic.day("demo-hq", SUNDAY)) < 15
    kinds = {c.kind for c in hq}
    assert kinds == {"inbound", "outbound", "internal"}
    statuses = {c.status for c in hq if c.kind == "inbound"}
    assert statuses == {"answered", "missed", "voicemail"}
    wh = traffic.day("demo-warehouse", THURSDAY)
    assert any(c.kind == "page" and c.dialed == "290" for c in wh)
    assert traffic.day("demo-hq", THURSDAY) == hq                 # deterministic


def test_only_fictional_numbers_and_the_demos_extensions():
    calls = traffic.between(datetime(2026, 10, 1, tzinfo=timezone.utc), datetime(2026, 11, 15, tzinfo=timezone.utc))
    for c in calls:
        for v in (c.caller, c.dialed):
            assert re.fullmatch(r"41255501\d\d|[1-8]\d{1,4}", v) and v not in ("911", "933", "988", "211", "311", "411", "511", "611", "711", "811")
    for bad in ("911", "9911", "933", "988", "211", "7243564424", "18005550100"):
        with pytest.raises(ValueError):
            traffic.check(traffic.Call(0, "demo-hq", "outbound", "101", bad, "", "missed", 1, 0))


def test_the_backfill_rows_and_sql():
    now = datetime(2026, 11, 12, 20, 0, tzinfo=timezone.utc)
    calls = [c for c in traffic.between(now - timedelta(days=2), now) if c.end < now.timestamp()]
    rows = [backfill.row(c) for c in calls]
    assert len({r[0] for r in rows}) == len(rows)                   # a stable, unique id per call
    inbound = [dict(zip(backfill.COLUMNS, r)) for r in rows if r[1] == "inbound"]
    answered = next(r for r in inbound if r["status"] == "answered")
    assert re.fullmatch(r"41255501\d\d", answered["caller_destination"]) and answered["billsec"] > 0 and answered["ext"]
    missed = next(r for r in inbound if r["status"] == "missed")
    assert missed["missed_call"] is True and missed["billsec"] == 0 and missed["answer_epoch"] is None and missed["ext"] is None
    out = backfill.sql(calls, int(now.timestamp()))
    assert out.startswith("begin;") and out.rstrip().endswith("commit;") and "'photonvox-sim'" in out
    assert out.count("domain_name = 'demo.vox.test'") == 2 and "x'); drop" not in out
    with pytest.raises(SystemExit):
        backfill.sql(calls, 0, "huepc.pbx-pa.example")
