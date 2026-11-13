"""Who may make which change (app/document/policy.py, security review H1), and the review's other document-level fixes: keys and texts
constrained (C1, L6), numbers only from the organization's (C2), whole country codes only (M1)."""
import copy

import pytest
from pydantic import ValidationError

from app.compiler import classes
from app.compiler.compile import CompileError, Context, compile_plan
from app.document import policy
from app.document.model import PhoneSystem
from app.document.validate import problems
from tests.unit.test_compiler import CTX
from tests.unit.test_document import S1, S2, SAMPLE, VALID

OWNER = lambda cap: True                                       # noqa: E731
ADMIN = lambda cap: cap not in ("vox.calling.policy",)        # noqa: E731
NO_NUMBERS = lambda cap: cap != "vox.number.manage"           # noqa: E731


def doc(**over):
    d = copy.deepcopy(SAMPLE)
    for path, value in over.items():
        node = d
        *parts, last = path.split("__")
        for p in parts:
            node = node.setdefault(p, {})
        node[last] = value
    return PhoneSystem.model_validate(d)


BASE = doc()


@pytest.mark.parametrize("over,words", [
    ({"calling__international": ["44", "52"]}, "international countries switched on: 52"),
    ({"calling__national": True}, None),
    ({"calling__blocking": {"allow": ["satellite"]}}, "blocked categories let through: satellite"),
    ({"calling__blocking": {"allow_numbers": ["+1876555"]}}, "blocked numbers let through"),
    ({"calling__spend_limit_usd": 500}, "daily spend limit raised to $500"),
    ({"features": {"eavesdrop": True}}, "eavesdrop switched on"),
    ({"features": {"intercept": True}}, "intercept switched on"),
])
def test_what_opens_up_calling_is_named(over, words):
    got = policy.widened(BASE, doc(**over))
    assert (words in got) if words else got == []


def test_switching_national_toll_free_back_on_and_removing_a_block_open_things_up_too():
    off = doc(calling__national=False, calling__toll_free=False, calling__blocking={"block": ["+1212555"]})
    assert policy.widened(off, BASE) == ["national calls switched on", "toll-free calls switched on", "numbers no longer blocked"]
    assert policy.widened(BASE, off) == []                     # closing is always allowed


def test_owners_open_up_calling_admins_cannot_and_narrowing_needs_nothing():
    wider = doc(calling__international=["44", "33"])
    assert "Only an owner" in policy.refusal(BASE, wider, ADMIN, True, set())
    assert policy.refusal(BASE, wider, OWNER, True, set()) == ""
    assert policy.refusal(wider, BASE, ADMIN, True, set()) == ""


def test_changing_numbers_needs_the_numbers_capability():
    more = copy.deepcopy(SAMPLE)
    more["numbers"]["+17245550199"] = {"site": S1, "open": {"user": "u-ada"}}
    assert "numbers" in policy.refusal(BASE, PhoneSystem.model_validate(more), NO_NUMBERS, True, set())


def test_site_limited_people_change_only_their_sites():
    d = copy.deepcopy(SAMPLE)
    d["users"]["u-cy"]["name"] = "Cy Renamed"                       # u-cy is at S2
    cy = PhoneSystem.model_validate(d)
    assert policy.refusal(BASE, cy, OWNER, False, {S2}) == ""
    assert "another site" in policy.refusal(BASE, cy, OWNER, False, {S1})
    d = copy.deepcopy(SAMPLE)
    d["sites"][S1]["unreachable"] = "none"
    assert policy.touched_sites(BASE, PhoneSystem.model_validate(d)) == {S1}
    hours = doc(hours={"office": {"week": {"mon": ["09:00-17:00"]}}})
    assert "whole organization's" in policy.refusal(BASE, hours, OWNER, False, {S1, S2})
    d = copy.deepcopy(SAMPLE)
    d["numbers"].pop("+17245550110")
    assert policy.touched_sites(BASE, PhoneSystem.model_validate(d)) == {S2}


@pytest.mark.parametrize("path,value", [
    ("groups", {'x"/><action application="system"': {"members": ["u-ada"]}}),
    ("menus", {"Main Menu": {"greeting": "Hi", "timeout": {"user": "u-ada"}}}),
    ("boxes", {"../x": {"name": "x"}}),
    ("hours", {"9 to 5": {}}),
    ("users", {"U ADA": {"name": "A", "site": S1, "extension": "100"}}),
    ("sites", {"main-office": {"emergency_location": "main", "emergency_number": "+17245550100", "caller_id": "+17245550100"}}),
])
def test_every_key_is_a_short_name_or_a_site_id(path, value):
    d = copy.deepcopy(SAMPLE)
    d[path] = value
    with pytest.raises(ValidationError):
        PhoneSystem.model_validate(d)


@pytest.mark.parametrize("field,value", [
    ("name", "<script>"), ("name", "100% Ada"), ("name", "Ada\nBcc: x"), ("email", "ada@example.com\r\nBcc: x"), ("email", '"a"@b.co'),
])
def test_names_and_emails_cannot_carry_markup_or_line_breaks(field, value):
    d = copy.deepcopy(SAMPLE)
    d["users"]["u-ada"][field] = value
    with pytest.raises(ValidationError):
        PhoneSystem.model_validate(d)


def test_a_greeting_cannot_carry_control_characters_and_a_north_american_block_has_ten_digits_at_most():
    d = copy.deepcopy(SAMPLE)
    d["menus"]["main"]["greeting"] = "Hello\x00"
    with pytest.raises(ValidationError):
        PhoneSystem.model_validate(d)
    d = copy.deepcopy(SAMPLE)
    d["calling"]["blocking"] = {"block": ["+121255500000"]}
    with pytest.raises(ValidationError):
        PhoneSystem.model_validate(d)


def test_only_numbers_assigned_to_the_organization_compile():
    found = problems(BASE, VALID, {"+17245550100", "+17245550110"})
    assert [(p.path, p.code) for p in found if p.code == "number_not_assigned"] == [("numbers.+17245550123", "number_not_assigned")]
    with pytest.raises(CompileError):
        compile_plan(BASE, Context(**{**CTX.__dict__, "assigned_numbers": {"+17245550100"}}))
    assert compile_plan(BASE, Context(**{**CTX.__dict__, "assigned_numbers": set(SAMPLE["numbers"])}))


@pytest.mark.parametrize("code,ok", [("44", True), ("7", True), ("212", True), ("2", False), ("21", False), ("8", False), ("881", False),
                                     ("800", False), ("979", False), ("1876", True), ("1212", False)])
def test_only_whole_country_codes_can_be_switched_on(code, ok):
    assert classes.is_valid_international(code) is ok
