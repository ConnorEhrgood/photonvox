"""Clone (app/document/clone.py): another customer's call flows, matched to this customer's people by extension."""
from app.document.clone import clone

SOURCE = {
    "version": 1, "sites": {"x1": {}}, "numbers": {"+17245550100": {}},
    "users": {"a": {"extension": "100"}, "b": {"extension": "101"}, "c": {"extension": "199"}},
    "hours": {"office": {"week": {"mon": ["08:00-17:00"]}}}, "calling": {"national": True}, "features": {"eavesdrop": False},
    "boxes": {"general": {"name": "General"}},
    "groups": {"desk": {"members": ["a", "c"], "then": {"voicemail": "general"}}, "far": {"members": ["c"]}},
    "menus": {"main": {"greeting": "Hi", "options": {"1": {"group": "desk"}, "2": {"user": "b"}, "3": {"voicemail": "c"}}, "timeout": {"user": "a"}}},
}
TARGET = {"version": 1, "sites": {"t1": {}}, "numbers": {"+17245550199": {}}, "users": {"ann": {"extension": "100"}, "bo": {"extension": "101"}},
          "hours": {"old": {}}, "groups": {"old": {"members": ["ann"]}}}


def test_flows_hours_and_policy_are_copied_and_this_customers_sites_numbers_and_people_stay():
    d = clone(SOURCE, TARGET)
    assert d["sites"] == {"t1": {}} and d["numbers"] == {"+17245550199": {}} and d["users"] == TARGET["users"]
    assert d["hours"] == SOURCE["hours"] and d["calling"] == {"national": True} and d["boxes"] == SOURCE["boxes"] and d["features"] == {"eavesdrop": False}


def test_people_are_matched_by_extension_and_the_unmatched_are_left_out_or_left_for_the_integrator():
    d = clone(SOURCE, TARGET)
    assert d["groups"] == {"desk": {"members": ["ann"], "then": {"voicemail": "general"}}}       # "far" had nobody here: dropped
    assert d["menus"]["main"]["options"] == {"1": {"group": "desk"}, "2": {"user": "bo"}, "3": {"voicemail": "c"}}
    assert d["menus"]["main"]["timeout"] == {"user": "ann"}


def test_an_empty_source_clears_flows_and_keeps_the_rest():
    d = clone({"version": 1}, TARGET)
    assert d["groups"] == {} and d["menus"] == {} and "hours" not in d and d["users"] == TARGET["users"]
