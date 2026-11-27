"""The customer dashboard's numbers (app/dashboard.py) from plain rows: which site a call belongs to, today against a usual day, missed
calls and voicemail, calls in progress and phones from the engine's live view, the outside lines in plain words, emergency calls, and the
parts the engine could not give."""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from app import dashboard as d
from app.document.model import PhoneSystem
from tests.unit.test_document import S1, S2, SAMPLE

NY = ZoneInfo("America/New_York")
NOW = datetime(2026, 11, 12, 15, 30, tzinfo=NY).astimezone(timezone.utc)     # a Thursday, 15:30 in New York
SITES = [{"id": S1, "slug": "main", "name": "Main office", "timezone": "America/New_York"},
         {"id": S2, "slug": "annex", "name": "Annex", "timezone": "America/New_York"}]
DOC = PhoneSystem.model_validate(SAMPLE)
EXT = {"e-100": "100", "e-101": "101", "e-102": "102", "e-200": "200"}
GW = "0b5e8c1a-0000-4000-8000-00000000aaaa"


def at(days_ago=0, hour=10, minute=0):
    return int((datetime(2026, 11, 12, hour, minute, tzinfo=NY) - timedelta(days=days_ago)).timestamp())


def cdr(kind, start, secs=60, status="answered", ext=None, caller="", dest="", called="", cause="NORMAL_CLEARING"):
    return {"id": f"c{start}{kind}{ext}", "direction": {"internal": "local"}.get(kind, kind), "caller_id_number": caller,
            "caller_destination": called or dest, "destination_number": dest, "start_epoch": start, "answer_epoch": start + 5 if secs else None,
            "end_epoch": start + 5 + secs, "billsec": secs, "status": status, "missed_call": status == "missed", "voicemail_message": status == "voicemail",
            "extension_uuid": ext, "hangup_cause": cause}


def raw(calls=(), live=None, voicemail=None, problems=()):
    return d.Raw(calls=list(calls), extensions=EXT, voicemail=voicemail, live=live, problems=list(problems))


def page(r, site=None, address=None):
    return d.compute(DOC, SITES, site, r, NOW, address or {S1: "210 Example St, Somewhere, PA 15000"}, {GW})


def test_calls_are_counted_by_site_and_kind_today():
    calls = [cdr("inbound", at(0, 9), 120, ext="e-100", caller="4125550188", called="7245550100"),        # main's number
             cdr("inbound", at(0, 9, 30), 0, status="missed", caller="4125550188", called="+17245550110"),  # the annex's number, missed
             cdr("outbound", at(0, 11), 300, ext="e-200", caller="7245550110", dest="4125550190"),          # from the annex
             cdr("internal", at(0, 14), 30, ext="e-101", caller="100", dest="101"),                          # main, internal
             cdr("inbound", at(0, 14, 10), 20, status="voicemail", ext="e-102", caller="4125550188", called="+17245550123"),
             cdr("inbound", at(1, 9), 60, caller="4125550188", called="7245550100")]                         # yesterday
    p = page(raw(calls))
    t = p["today"]
    assert (t["calls"], t["minutes"], t["missed"], t["to_voicemail"]) == (5, 8, 1, 1)
    assert (t["inbound"], t["outbound"], t["internal"]) == (3, 1, 1)
    assert t["by_hour"][9] == {"inbound": 2, "outbound": 0, "internal": 0} and t["by_hour"][14]["internal"] == 1
    main = page(raw(calls), site=S1)["today"]
    annex = page(raw(calls), site=S2)["today"]
    assert (main["calls"], annex["calls"]) == (3, 2) and annex["missed"] == 1 and annex["outbound"] == 1
    assert [(n["number"], n["calls_today"], n["rings"]) for n in page(raw(calls), site=S1)["numbers"]] == [
        ("+17245550100", 1, "the main menu"), ("+17245550123", 1, "Pat Pastor (102)")]


def test_today_is_compared_with_the_last_four_same_weekdays_up_to_this_time():
    calls = [cdr("inbound", at(7 * w, h), 60, caller="4125550188", called="7245550100") for w in (1, 2) for h in (9, 10, 16)]
    calls += [cdr("inbound", at(0, 9), 60, caller="4125550188", called="7245550100")]
    ty = page(raw(calls))["typical"]
    assert ty["days"] == 2 and ty["weekday"] == "Thursday" and ty["calls_so_far"] == 2.0 and ty["by_hour"][16] == 1.0
    assert page(raw([]))["typical"]["calls_so_far"] is None                 # a new system has no usual day yet


def test_busiest_hours_over_four_weeks():
    calls = [cdr("inbound", at(7 * w + 1, 10), 60, caller="1", called="7245550100") for w in range(4) for _ in range(3)]
    b = page(raw(calls))["busiest"]
    assert b["top"] == {"weekday": 2, "hour": 10, "calls": 3.0} and b["grid"][2][10] == 3.0
    assert page(raw([]))["busiest"]["top"] is None


def test_calls_in_progress_phones_and_lines_from_the_live_view():
    live = {"registrations": [{"extension": "100", "agent": "Grandstream GRP2614"}, {"extension": "101", "agent": "Yealink"},
                              {"extension": "200", "agent": "x"}, {"extension": "999", "agent": "someone else's"}],
            "channels": [
                {"uuid": "a", "call": "a", "direction": "inbound", "gateway": True, "cid_num": "+14125550188", "dest": "7245550100",
                 "callstate": "ACTIVE", "presence": "", "created": int(NOW.timestamp()) - 95},
                {"uuid": "a2", "call": "a", "direction": "outbound", "gateway": False, "cid_num": "4125550188", "dest": "100",
                 "callstate": "ACTIVE", "presence": "100", "created": int(NOW.timestamp()) - 90},
                {"uuid": "b", "call": "b", "direction": "inbound", "gateway": False, "cid_num": "200", "dest": "101", "callstate": "RINGING",
                 "presence": "200", "created": int(NOW.timestamp()) - 3},
                {"uuid": "c", "call": "c", "direction": "inbound", "gateway": False, "cid_num": "101", "dest": "4125550190",
                 "callstate": "ACTIVE", "presence": "101", "created": int(NOW.timestamp()) - 20},
                {"uuid": "c2", "call": "c", "direction": "outbound", "gateway": True, "cid_num": "7245550100", "dest": "4125550190",
                 "callstate": "ACTIVE", "presence": "", "created": int(NOW.timestamp()) - 19}],
            "gateways": [{"gateway": GW, "state": "NOREG", "status": "UP"}, {"gateway": "other", "status": "DOWN"}]}
    p = page(raw([], live=live))
    n = p["now"]
    assert (n["count"], n["lines"]) == (3, 2)
    first = n["calls"][0]
    assert first["kind"] == "inbound" and first["other"] == "…0188" and first["number"] == "+17245550100" and first["who"][0]["name"] == "Ada Front"
    assert first["state"] == "talking" and first["seconds"] == 95
    internal = next(c for c in n["calls"] if c["kind"] == "internal")
    assert internal["state"] == "ringing" and internal["site"] == S2
    assert next(c for c in n["calls"] if c["kind"] == "outbound")["other"] == "…0190"
    ph = p["phones"]
    assert (p["today"]["calls"], p["today"]["in_progress"], p["today"]["internal"], p["today"]["minutes"]) == (3, 3, 1, 2)   # 95 s + 20 s talking
    assert sum(sum(h.values()) for h in p["today"]["by_hour"]) == 3
    assert (ph["online"], ph["total"]) == (3, 4) and ph["offline"] == [{"extension": "102", "name": "Pat Pastor", "site": S1}]
    assert p["trunk"]["state"] == "ok" and p["trunk"]["words"] == "Calls in and out are working."      # only the carrier's gateway counts
    annex = page(raw([], live=live), site=S2)
    assert annex["now"]["count"] == 1 and (annex["phones"]["online"], annex["phones"]["total"]) == (1, 1)
    assert "4125550188" not in str(p["now"]) and "4125550190" not in str(p["now"])


def test_the_outside_lines_in_plain_words():
    up = {"registrations": [], "channels": [], "gateways": [{"gateway": GW, "status": "UP"}]}
    down = {**up, "gateways": [{"gateway": GW, "status": "DOWN"}]}
    assert page(raw([], live=down))["trunk"]["state"] == "trouble"
    failing = [cdr("outbound", int(NOW.timestamp()) - 600 + i * 60, 0, status="failed", ext="e-100", dest="4125550190",
                   cause="NORMAL_TEMPORARY_FAILURE") for i in range(3)]
    t = page(raw(failing, live=up))["trunk"]
    assert t["state"] == "trouble" and t["words"].startswith("Outside calls are not getting through since ")
    blocked = [dict(c, hangup_cause="CALL_REJECTED") for c in failing]          # our own blocks are not the carrier's trouble
    assert page(raw(blocked, live=up))["trunk"]["state"] == "ok"
    assert page(raw([cdr("inbound", at(0, 9), 60, called="7245550100")]))["trunk"]["state"] == "unknown"


def test_an_emergency_call_today_shows_who_where_and_the_sites_address():
    calls = [cdr("outbound", at(0, 10, 42), 180, ext="e-101", caller="7245550100", dest="911"),
             cdr("outbound", at(0, 10, 50), 0, ext="e-200", caller="7245550110", dest="9911", status="failed"),
             cdr("outbound", at(1, 10), 60, ext="e-101", dest="911")]                                         # yesterday's is not today's
    e = page(raw(calls))["emergency"]
    assert [(x["dialed"], x["extension"], x["who"], x["site"], x["answered"]) for x in e] == [
        ("911", "101", "Ben Office", "Main office", True), ("9911", "200", "Cy Annex", "Annex", False)]
    assert e[0]["address"] == "210 Example St, Somewhere, PA 15000" and e[0]["seconds"] == 180
    assert page(raw(calls), site=S2)["emergency"][0]["who"] == "Cy Annex" and len(page(raw(calls), site=S2)["emergency"]) == 1
    assert page(raw(calls))["trunk"]["last_out"] is not None


def test_voicemails_waiting_by_box():
    vm = [{"box": "100", "created": at(0, 9), "new": True}, {"box": "100", "created": at(0, 8), "new": True},
          {"box": "200", "created": at(1, 9), "new": True}, {"box": "101", "created": at(2), "new": False},
          {"box": "9901", "name": "General mailbox", "created": at(0, 7), "new": True}]           # the shared box, as the engine numbers it
    v = page(raw([], voicemail=vm))["voicemail"]
    assert v["new"] == 4 and [(b["name"], b["extension"], b["new"]) for b in v["boxes"]] == [
        ("Ada Front", "100", 2), ("Cy Annex", "200", 1), ("General mailbox", None, 1)]
    assert page(raw([], voicemail=vm), site=S2)["voicemail"]["new"] == 1
    assert page(raw([], voicemail=vm), site=S1)["voicemail"]["new"] == 3      # the main number's after-hours box is the main office's


def test_parts_the_engine_could_not_give_are_none_and_named():
    p = page(d.Raw(calls=None, extensions={}, voicemail=None, live=None, problems=["history", "voicemail", "live"]))
    assert p["today"] is None and p["now"] is None and p["phones"] is None and p["voicemail"] is None and p["emergency"] is None
    assert p["unavailable"] == ["history", "live", "voicemail"] and p["trunk"]["state"] == "unknown"
    assert [n["number"] for n in p["numbers"]] == ["+17245550100", "+17245550110", "+17245550123"]


def test_peak_lines_counts_overlapping_outside_calls():
    calls = [cdr("inbound", at(0, 10), 600, caller="1", called="7245550100"), cdr("outbound", at(0, 10, 2), 60, ext="e-100", dest="4125550190"),
             cdr("internal", at(0, 10, 3), 60, ext="e-101", caller="100", dest="101"), cdr("inbound", at(0, 12), 60, caller="1", called="7245550100")]
    assert page(raw(calls))["today"]["peak_lines"] == 2


def test_check_calls_and_a_pages_legs_are_not_calls_and_a_page_is_internal():
    doc = PhoneSystem.model_validate({**SAMPLE, "pages": {"everyone": {"name": "Everyone", "site": S1, "extension": "190", "members": list(SAMPLE["users"])[:1]}}})
    blank = lambda r: {**r, "direction": None}                                                              # noqa: E731
    calls = [cdr("inbound", at(0, 9), 0, status="no_answer", caller=d.CHECK_CALLER, dest="100"),             # the publisher's checks
             blank(cdr("internal", at(0, 9), 0, status="no_answer", caller=d.CHECK_CALLER, dest="7245550100")),
             cdr("outbound", at(0, 9), 0, status="failed", caller=d.CHECK_CALLER, dest="19005550100", cause="CALL_REJECTED"),
             cdr("outbound", at(0, 10), 12, ext="e-100", caller="100", dest="190"),                           # a page, as FusionPBX records it
             blank(cdr("internal", at(0, 10), 12, ext="e-101", caller="101", dest="101")),                    # and its leg to a member's phone
             cdr("inbound", at(0, 11), 60, ext="e-100", caller=d.CHECK_CALLER, called="7245550100")]         # a real call from that number
    p = d.compute(doc, SITES, None, raw(calls), NOW, {}, {GW})
    t = p["today"]
    assert (t["calls"], t["inbound"], t["outbound"], t["internal"], t["missed"], t["peak_lines"]) == (2, 1, 0, 1, 0, 1)
    assert p["trunk"]["last_out"] is None and p["week"] == {"inbound": 1, "outbound": 0, "internal": 1}

