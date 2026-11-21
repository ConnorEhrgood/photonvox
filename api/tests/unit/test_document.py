"""The phone-system document: its shape (app/document/model.py) and the rules for publishing it (app/document/validate.py)."""
import copy
import json
import pathlib

import pytest
from pydantic import ValidationError

from app.document.model import Hours, PhoneSystem
from app.document.validate import SERVICE_CODES, problems

SAMPLE = json.loads((pathlib.Path(__file__).resolve().parents[3] / "contract/phone-system/small-office.sample.json").read_text())
S1, S2 = "11111111-1111-4111-8111-111111111111", "22222222-2222-4222-8222-222222222222"
VALID = {S1: {"loc-main"}, S2: {"loc-annex"}}


def doc(**changes):
    d = copy.deepcopy(SAMPLE)
    for path, value in changes.items():
        node = d
        keys = path.split("__")
        for k in keys[:-1]:
            node = node[k]
        if value is None:
            node.pop(keys[-1], None)
        else:
            node[keys[-1]] = value
    return PhoneSystem.model_validate(d)


def codes(d, valid=VALID):
    return [(p.path, p.code) for p in problems(d, valid)]


def test_the_sample_is_valid_and_publishable():
    assert problems(doc(), VALID) == []


# ---- shape ----

@pytest.mark.parametrize("bad", [
    {"numbers": {"7245550100": SAMPLE["numbers"]["+17245550100"]}},          # not +1 form
    {"users": {"u": {"name": "X", "site": S1, "extension": "0100"}}},        # extensions start 1-8
    {"users": {"u": {"name": "X", "site": S1, "extension": "9100"}}},
    {"users": {"u": {"name": "X", "site": S1, "extension": "1"}}},           # at least two digits
    {"menus": {"main": {"greeting": "Hi", "options": {"*": {"user": "u-ada"}}, "timeout": {"user": "u-ada"}}}},
    {"groups": {"g": {"members": []}}},
    {"sites": {S1: {**SAMPLE["sites"][S1], "outside_prefix": "7"}}},
    {"surprise": 1},                                                          # nothing unknown is stored
])
def test_shapes_that_are_refused(bad):
    with pytest.raises(ValidationError):
        PhoneSystem.model_validate({**copy.deepcopy(SAMPLE), **bad})


@pytest.mark.parametrize("span", ["8:00-17:00", "17:00-08:00", "09:00-09:00", "25:00-26:00", "08:00"])
def test_hours_must_be_real_spans(span):
    with pytest.raises(ValidationError):
        Hours(week={"mon": [span]})


def test_hours_may_end_at_midnight_and_a_document_starts_empty():
    assert Hours(week={"sat": ["00:00-24:00"]}).week["sat"] == ["00:00-24:00"]
    assert problems(PhoneSystem(), {}) == []


# ---- 911 comes first ----

def test_a_site_without_a_validated_emergency_location_cannot_be_published():
    assert (f"sites.{S2}.emergency_location", "emergency_location_unvalidated") in codes(doc(), {S1: {"loc-main"}})
    assert (f"sites.{S1}.emergency_location", "emergency_location_unvalidated") in codes(doc(), {S1: {"another"}, S2: {"loc-annex"}})


def test_the_emergency_number_and_caller_id_must_be_held_numbers():
    d = doc(**{f"sites__{S1}__emergency_number": "+17245559999", f"sites__{S1}__caller_id": "+17245558888"})
    assert {(f"sites.{S1}.emergency_number", "not_held"), (f"sites.{S1}.caller_id", "not_held")} <= set(codes(d))


# ---- references ----

def test_every_kind_of_dangling_reference_is_named_by_its_path():
    d = doc(**{
        "numbers__+17245550100__open": {"menu": "nope"}, "numbers__+17245550100__closed": {"voicemail": "nobody"},
        "numbers__+17245550110__site": "99999999-9999-4999-8999-999999999999", "menus__main__options__1": {"group": "ghost"}, "menus__main__timeout": {"user": "ghost"},
        "groups__office__members": ["u-ada", "ghost"], "groups__annex__then": {"menu": "nope"}, "users__u-cy__site": "99999999-9999-4999-8999-999999999999",
        f"sites__{S1}__hours": "missing",
    })
    got = set(codes(d))
    assert {("numbers.+17245550100.open", "unknown_menu"), ("numbers.+17245550100.closed", "unknown_voicemail"),
            ("numbers.+17245550110.site", "unknown_site"), ("menus.main.options.1", "unknown_group"), ("menus.main.timeout", "unknown_user"),
            ("groups.office.members.1", "unknown_user"), ("groups.annex.then", "unknown_menu"), ("users.u-cy.site", "unknown_site"),
            (f"sites.{S1}.hours", "unknown_hours")} <= got


def test_a_number_with_a_closed_outcome_needs_hours():
    d = doc(**{f"sites__{S1}__hours": None})
    assert ("numbers.+17245550100.closed", "no_hours") in codes(d)
    d = doc(**{"numbers__+17245550100__hours": "weekend"})
    assert ("numbers.+17245550100.hours", "unknown_hours") in codes(d)
    d = doc(**{"numbers__+17245550110__site": "99999999-9999-4999-8999-999999999999", "numbers__+17245550110__closed": {"user": "u-cy"}})
    assert ("numbers.+17245550110.closed", "no_hours") in codes(d)       # an unknown site has no hours to lend


def test_a_number_may_have_its_own_hours():
    d = doc(**{"hours__weekend": {"week": {"sat": ["09:00-12:00"]}}, "numbers__+17245550110__hours": "weekend",
               "numbers__+17245550110__closed": {"voicemail": "u-cy"}})
    assert problems(d, VALID) == []


# ---- extensions and numbers ----

@pytest.mark.parametrize("ext", sorted(SERVICE_CODES))
def test_service_codes_are_never_extensions(ext):
    if ext.startswith("9"):
        pytest.skip("9xx is refused by the shape already")
    assert ("users.u-cy.extension", "extension_reserved") in codes(doc(**{"users__u-cy__extension": ext}))


def test_a_site_that_dials_9_for_outside_lines_has_no_extension_starting_with_its_prefix():
    d = doc(**{f"sites__{S1}__outside_prefix": "8", "users__u-ada__extension": "800"})
    assert ("users.u-ada.extension", "extension_prefix") in codes(d)
    assert ("users.u-cy.extension", "extension_prefix") not in codes(doc(**{"users__u-cy__extension": "800"}))   # the annex has no prefix


def test_extensions_and_direct_numbers_are_unique_and_direct_numbers_held():
    d = doc(**{"users__u-ben__extension": "100", "users__u-ben__direct_number": "+17245550123", "users__u-cy__direct_number": "+17245557777"})
    got = set(codes(d))
    assert {("users.u-ben.extension", "extension_taken"), ("users.u-pastor.direct_number", "direct_taken"), ("users.u-cy.direct_number", "not_held")} <= got   # the first in the document keeps it


def test_showing_a_direct_number_needs_one():
    assert ("users.u-ben.show", "no_direct_number") in codes(doc(**{"users__u-ben__show": "direct"}))


def test_a_group_member_twice_is_refused():
    assert ("groups.office.members", "duplicate_member") in codes(doc(**{"groups__office__members": ["u-ada", "u-ada"]}))


# ---- loops ----

def test_a_loop_of_automatic_forwards_is_found_once():
    d = doc(**{"groups__office__then": {"group": "annex"}, "groups__annex__then": {"menu": "main"}})       # main times out to office: a ring
    loops = [p for p in problems(d, VALID) if p.code == "loop"]
    assert len(loops) == 1 and "forever" in loops[0].message


def test_a_group_that_forwards_to_itself_is_a_loop_and_a_chain_into_a_loop_is_reported_at_the_loop():
    d = doc(**{"groups__annex__then": {"group": "annex"}})
    assert ("groups.annex", "loop") in codes(d)
    d = doc(**{"groups__office__then": {"group": "annex"}, "groups__annex__then": {"group": "annex"}, "menus__main__timeout": {"user": "u-ada"}})
    assert [p for p, c in codes(d) if c == "loop"] == ["groups.annex"]


def test_menu_options_are_choices_not_loops_and_a_chain_to_a_person_ends():
    d = doc(**{"menus__main__options__1": {"menu": "main"}, "menus__main__timeout": {"group": "annex"}})
    assert problems(d, VALID) == []


def test_a_users_own_caller_id_must_be_one_of_the_organizations_numbers():
    assert ("users.u-cy.caller_id", "not_held") in codes(doc(**{"users__u-cy__caller_id": "+17245557777"}))
    assert ("users.u-cy.caller_id", "not_held") not in codes(doc(**{"users__u-cy__caller_id": "+17245550123"}))


@pytest.mark.parametrize("ext", ["8911", "8933", "8988", "8711", "8311"])
def test_a_service_code_after_an_outside_line_digit_is_never_an_extension_at_any_site(ext):
    """Audit VOX-B-2: with one site dialing 8 for outside lines, an extension 8911 at another site would take that site's 8-911 calls."""
    assert ("users.u-cy.extension", "extension_reserved") in codes(doc(**{"users__u-cy__extension": ext}))


@pytest.mark.parametrize("span", ["09:00-17:00\n", "09:00-24:30", "09:00-24:01"])
def test_a_span_with_a_trailing_newline_or_past_midnight_is_refused(span):
    """Audit VOX-B-16: Python's `$` lets a final newline through; 24 is an end only as 24:00."""
    from app.document.model import Hours
    with pytest.raises(ValidationError):
        Hours.model_validate({"week": {"mon": [span]}})
    assert Hours.model_validate({"week": {"mon": ["09:00-24:00"]}})


def test_a_number_key_with_a_trailing_newline_is_refused():
    d = copy.deepcopy(SAMPLE)
    d["numbers"]["+17245550100\n"] = d["numbers"].pop(next(iter(d["numbers"])))
    with pytest.raises(ValidationError):
        PhoneSystem.model_validate(d)
