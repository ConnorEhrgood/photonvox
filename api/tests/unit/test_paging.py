"""Paging groups: dialing the group's extension speaks one way through every member's phone at once, as FusionPBX's own page dial plan does it
(page.lua, muted members, auto-answer), with nothing from the document's text in the dial plan."""
import copy

import pytest

from app.compiler.compile import CompileError
from app.engine import fusionpbx
from tests.unit.test_compiler import plan
from tests.unit.test_document import S1, S2, SAMPLE
from tests.unit.test_engine_build import TARGET, dp, rows

PAGE = {"name": "Warehouse ${uuid_kill(x)}", "site": S1, "extension": "290", "members": ["u-ada", "u-ben"]}


def with_pages(**pages):
    d = copy.deepcopy(SAMPLE)
    d["pages"] = pages
    return d


def test_a_paging_group_in_the_plan_and_the_engine():
    p = plan(with_pages(floor=PAGE))
    assert p["pages"] == [{"key": "floor", "extension": "290", "name": PAGE["name"], "site": S1, "members": ["100", "101"]}]
    assert "pages" not in plan(SAMPLE)                    # documents without paging: the plan as it was
    b = fusionpbx.build(p, TARGET)
    page = dp(b, "photonvox.page.floor")
    assert page["dialplan_number"] == "290" and page["dialplan_order"] == fusionpbx.ORDER["page"]
    xml = page["dialplan_xml"]
    for want in ('expression="^290$"', 'data="destinations=100,101"', 'data="mute=true"', 'data="moderator=false"', 'application="lua" data="page.lua"',
                 'data="caller_id_name=Page"'):
        assert want in xml
    assert "uuid_kill" not in xml and "Warehouse" not in xml     # the group's name never reaches the dial plan
    assert not rows(b, "v_extensions", extension="290")          # a paging group is a dial plan, not a phone


def test_paging_group_problems():
    bad = with_pages(a={**PAGE, "extension": "100"}, b={**PAGE, "site": "33333333-3333-4333-8333-333333333333", "extension": "291"},
                     c={**PAGE, "extension": "311"}, d={**PAGE, "extension": "292", "members": ["nope", "u-ada", "u-ada"]})
    with pytest.raises(CompileError) as e:
        plan(bad)
    codes = {(x.path, x.code) for x in e.value.problems}
    assert {("pages.a.extension", "extension_taken"), ("pages.b.site", "unknown_site"), ("pages.c.extension", "extension_reserved"),
            ("pages.d.members.0", "unknown_user"), ("pages.d.members", "duplicate_member")} <= codes
    prefix = with_pages(floor={**PAGE, "extension": "801"})
    prefix["sites"][S1]["outside_prefix"] = "8"
    with pytest.raises(CompileError, match="starts an outside call"):
        plan(prefix)
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        plan(with_pages(floor={**PAGE, "members": []}))


def test_only_fusionpbxs_ring_group_and_page_scripts_run():
    fusionpbx.check_xml('<extension name="x"><condition><action application="lua" data="page.lua"/></condition></extension>')
    with pytest.raises(ValueError, match="only Lua"):
        fusionpbx.check_xml('<extension name="x"><condition><action application="lua" data="other.lua"/></condition></extension>')


def test_a_paging_group_belongs_to_its_site_for_site_limited_people():
    from app.document import policy
    from app.document.model import PhoneSystem
    before = PhoneSystem.model_validate(with_pages(floor=PAGE))
    moved = PhoneSystem.model_validate(with_pages(floor={**PAGE, "site": S2}))
    assert policy.touched_sites(before, moved) == {S1, S2}
