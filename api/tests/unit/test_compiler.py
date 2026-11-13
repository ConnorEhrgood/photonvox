"""The compiler: the golden plan for the sample, and the properties that must hold for any document (911 first and locked; premium never routed;
high-cost codes only when switched on; deterministic)."""
import copy
import json
import pathlib
import re

import pytest

from app.compiler import classes
from app.compiler.compile import CompileError, Context, compile_plan
from app.document.model import PhoneSystem
from tests.unit.test_document import S1, S2, SAMPLE, VALID

GOLDEN = pathlib.Path(__file__).resolve().parents[1] / "golden/small-office.plan.json"
CTX = Context(domain="k3x9q2.sip.photoninfra.xyz", timezones={S1: "America/New_York", S2: "America/New_York"},
              upstreams={"national": ["htc"], "international": ["upstream-b", "htc"]}, emergency_gateway="htc", validated_locations=VALID)


def plan(d=None, ctx=CTX):
    return compile_plan(PhoneSystem.model_validate(d or SAMPLE), ctx)


def route(p, key):
    return next(r for r in p["outbound_routes"] if r["key"] == key)


def routed(p, digits):
    """The first route whose pattern takes these digits (FreeSWITCH tries routes in order), and what it sends."""
    for r in p["outbound_routes"]:
        m = re.match(r["pattern"], digits)
        if m:
            return r["key"], r["send"].replace("$1", m.group(1))
    return None, None


def test_the_sample_compiles_to_the_reviewed_golden_plan():
    assert json.loads(json.dumps(plan(), sort_keys=True)) == json.loads(GOLDEN.read_text())


def test_compiling_twice_gives_the_same_bytes():
    assert json.dumps(plan(), sort_keys=True) == json.dumps(plan(copy.deepcopy(SAMPLE)), sort_keys=True)


# ---- 911 ----

@pytest.mark.parametrize("digits", ["911", "9911", "933", "9933"])
def test_911_and_933_with_or_without_the_prefix_go_to_the_emergency_upstream(digits):
    p = plan()
    assert routed(p, digits) == ("emergency", digits[-3:])
    e = route(p, "emergency")
    assert p["outbound_routes"][0] is e and e["locked"] and e["requires"] is None and e["gateways"] == ["htc"]


def test_a_911_call_shows_the_sites_emergency_number_even_for_a_user_who_shows_a_direct_line():
    exts = {x["user"]: x for x in plan()["extensions"]}
    assert exts["u-pastor"]["caller_id_number"] == "+17245550123" and exts["u-pastor"]["emergency_caller_id_number"] == "+17245550100"
    assert exts["u-cy"]["emergency_caller_id_number"] == "+17245550110"
    assert route(plan(), "emergency")["caller_id"] == "emergency_caller_id_number"


def test_911_stays_when_every_outside_call_is_switched_off():
    d = copy.deepcopy(SAMPLE)
    d["calling"] = {"national": False, "toll_free": False, "international": [], "spend_limit_usd": 0}
    p = plan(d)
    assert [r["key"] for r in p["outbound_routes"]] == ["emergency", "service"]
    assert routed(p, "911")[0] == "emergency" and routed(p, "988")[0] == "service" and routed(p, "7245550100") == (None, None)
    assert p["extensions"][0]["toll_allow"] == ["service"]


def test_without_an_outside_prefix_anywhere_the_patterns_take_plain_digits_only():
    d = copy.deepcopy(SAMPLE)
    d["sites"][S1].pop("outside_prefix")
    p = plan(d)
    assert routed(p, "911")[0] == "emergency" and routed(p, "9911") == (None, None)


# ---- call classes ----

@pytest.mark.parametrize("digits,expected", [
    ("7245550100", ("national", "+17245550100")), ("17245550100", ("national", "+17245550100")), ("917245550100", ("national", "+17245550100")),
    ("8005550100", ("toll_free", "+18005550100")), ("18885550100", ("toll_free", "+18885550100")),
    ("9005550100", (None, None)), ("19005550100", (None, None)), ("7249765100", (None, None)),          # premium: never
    ("8765550100", (None, None)), ("18095550100", (None, None)),                                        # high-cost NANP: off
    ("01144207946000", ("international-44", "+44207946000")), ("01133123456789", (None, None)),         # UK on, France not
    ("988", ("service", "988")), ("711", ("service", "711")), ("411", (None, None)),
    ("1234567890", (None, None)), ("7240555010", (None, None)),
])
def test_what_each_number_routes_to(digits, expected):
    assert routed(plan(), digits) == expected


def test_a_high_cost_area_code_switched_on_by_an_owner_routes_internationally_and_bad_codes_are_ignored():
    d = copy.deepcopy(SAMPLE)
    d["calling"]["international"] = ["1876", "1724", "0", "x"]
    p = plan(d)
    assert routed(p, "18765550100") == ("international-1876", "+18765550100")
    assert [r["key"] for r in p["outbound_routes"] if r["key"].startswith("international")] == ["international-1876"]


def test_upstream_order_comes_from_the_instance_and_falls_back_to_national():
    ctx = Context(domain="d", timezones={}, upstreams={"national": ["htc", "b"], "toll_free": ["b"], "service": ["htc"]}, emergency_gateway="htc",
                  validated_locations=VALID)
    p = plan(ctx=ctx)
    assert route(p, "toll_free")["gateways"] == ["b"] and route(p, "national")["gateways"] == ["htc", "b"]
    assert route(p, "international-44")["gateways"] == ["htc", "b"] and route(p, "service")["gateways"] == ["htc"]
    assert p["time_conditions"][0]["timezone"] == "America/New_York"       # a site with no time zone known yet: the default


# ---- outcomes ----

def test_outcomes_become_engine_destinations():
    p = plan()
    tc = p["time_conditions"][0]
    assert (tc["open"], tc["closed"], tc["holidays"]) == ("ivr:main", "voicemail_box:general", "us-federal")
    assert {i["number"]: i["to"] for i in p["inbound"]} == {
        "+17245550100": "time_condition:number-17245550100", "+17245550110": "ring_group:annex", "+17245550123": "extension:102"}
    groups = {g["key"]: g for g in p["ring_groups"]}
    assert groups["annex"]["then"] == "voicemail:200" and groups["office"]["members"] == ["100", "101"]
    assert {x["user"]: x["unreachable"] for x in p["extensions"]} == {"u-ada": "voicemail:100", "u-ben": "voicemail:101", "u-pastor": "voicemail:102", "u-cy": "hangup"}


def test_a_group_with_no_next_step_hangs_up():
    d = copy.deepcopy(SAMPLE)
    d["groups"]["office"].pop("then")
    assert {g["key"]: g["then"] for g in plan(d)["ring_groups"]}["office"] == "hangup"


# ---- refusals ----

def test_a_document_with_problems_is_not_compiled():
    d = copy.deepcopy(SAMPLE)
    d["users"]["u-ben"]["extension"] = "100"
    with pytest.raises(CompileError) as e:
        plan(d)
    assert [p.code for p in e.value.problems] == ["extension_taken"] and "users.u-ben.extension" in str(e.value)


@pytest.mark.parametrize("ctx", [
    Context(domain="d", timezones={}, upstreams={"national": ["htc"]}, emergency_gateway="", validated_locations=VALID),
    Context(domain="d", timezones={}, upstreams={}, emergency_gateway="htc", validated_locations=VALID),
])
def test_an_instance_with_no_911_or_national_upstream_gets_nothing(ctx):
    with pytest.raises(CompileError) as e:
        plan(ctx=ctx)
    assert e.value.problems[0].code == "no_upstream"


def test_a_compile_error_with_no_problems_still_says_something():
    assert str(CompileError([])) == "no upstream"


def test_the_class_helpers():
    assert classes.international_pattern("1876") == r"^1?(876[2-9]\d{6})$"
    assert classes.is_valid_international("52") and not classes.is_valid_international("1999") and not classes.is_valid_international("1234")
