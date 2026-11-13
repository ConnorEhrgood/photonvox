"""Bulk import and templates (app/document): pasted rows, with or without a header, tabs or commas, each with its problems in words."""
import pytest

from app.document import importer, templates
from app.document.model import PhoneSystem

SITES = {"s1": "Main office", "s2": "Annex"}
DOC = {"users": {"u-ann": {"name": "Ann", "site": "s1", "extension": "100"}}, "numbers": {"+17245550123": {}},
       "groups": {"everyone": {"members": ["u-ann"]}}}


def test_columns_by_position_tabs_and_auto_extensions():
    rows = importer.preview("Bo Smith\t\tbo@example.com\t724-555-0123\tAnnex\nCy\n", DOC, "s1", SITES)
    assert rows[0]["user"] == {"name": "Bo Smith", "site": "s2", "extension": "101", "email": "bo@example.com", "direct_number": "+17245550123",
                               "show": "direct"} and rows[0]["problems"] == [] and rows[0]["line"] == 1
    assert rows[1]["user"]["extension"] == "102" and rows[1]["user"]["site"] == "s1"


def test_a_header_names_the_columns_in_any_order_with_common_aliases():
    rows = importer.preview("E-mail,Full name,Location,DID\nann2@example.com,Ann,s2,+1 (724) 555-0123\n", DOC, "s1", SITES)
    assert rows[0]["user"]["direct_number"] == "+17245550123" and rows[0]["user"]["site"] == "s2" and rows[0]["line"] == 2
    assert rows[0]["id"] == "u-ann-2"                        # "u-ann" is taken


@pytest.mark.parametrize("line,problem", [
    ("Dee,911", "'911' cannot be an extension"), ("Dee,9001", "'9001' cannot be an extension"), ("Dee,100", "extension 100 is taken"),
    ("Dee,,,555-0100", "'555-0100' is not a North American number"), ("Dee,,,724-555-0199", "+17245550199 is not one of the organization's numbers"),
    ("Dee,,,,Warehouse", "no site called 'Warehouse'"),
    ("<b>Dee</b>", "the name has characters that cannot be used"), ("Dee 100%", "the name has characters that cannot be used"),
    ("Dee,,dee@example.com%0a", "'dee@example.com%0a' is not an email address"),
])
def test_each_problem_is_said_in_words(line, problem):
    assert any(p.startswith(problem) for p in importer.preview(line, DOC, "s1", SITES)[0]["problems"])


def test_blank_input_and_blank_lines():
    assert importer.preview("  \n", DOC, "s1", SITES) == []
    assert len(importer.preview("A\n,,\nB\n", DOC, "s1", SITES)) == 2


def test_apply_adds_only_good_rows_and_joins_the_group_once():
    rows = importer.preview("Bo\nCy,100\n", DOC, "s1", SITES)
    d = importer.apply(DOC, rows, "everyone")
    assert set(d["users"]) == {"u-ann", "u-bo"} and d["groups"]["everyone"]["members"] == ["u-ann", "u-bo"]
    assert importer.apply(d, rows, "everyone")["groups"]["everyone"]["members"] == ["u-ann", "u-bo"]
    assert "groups" not in importer.apply({"users": {}}, rows, "everyone") and importer.apply(DOC, rows)["groups"] == DOC["groups"]


@pytest.mark.parametrize("key", list(templates.TEMPLATES))
def test_every_template_makes_a_valid_document(key):
    site = "11111111-1111-4111-8111-111111111111"
    d = templates.build(key, site, "main", "+17245550100", {"u-ann": {"name": "Ann", "site": site, "extension": "100"}})
    PhoneSystem.model_validate(d)
    assert d["sites"][site]["emergency_number"] == "+17245550100" and d["numbers"]["+17245550100"]["closed"] == {"voicemail": "general"}


def test_a_row_without_a_name_or_with_a_bad_email_is_refused():
    rows = importer.preview(",205\nEve,,not-an-email\n", DOC, "s1", SITES)
    assert rows[0]["problems"] == ["no name"] and rows[1]["problems"] == ["'not-an-email' is not an email address"]
    assert importer.preview("Fay,206\n", DOC, "s1", SITES)[0]["user"]["extension"] == "206"


def test_the_catalog_lists_every_template():
    assert [t["key"] for t in templates.catalog()] == list(templates.TEMPLATES)
