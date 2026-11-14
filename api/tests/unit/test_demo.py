"""The demo organization's phone system (app/demo.py): a valid, publishable document of three sites, numbers only from (412) 555-0100 to 0199,
paging at the warehouse, and the engine rows it makes."""
import re

from app import demo
from app.compiler.compile import Context, compile_plan
from app.document.model import PhoneSystem
from app.document.validate import problems
from app.engine import fusionpbx
from tests.unit.test_engine_build import TARGET, dp

TZ = {s: "America/New_York" for s in demo.PHONE_SITES}
VALID = {s: {"main"} for s in demo.PHONE_SITES}


def doc():
    return PhoneSystem.model_validate(demo.document())


def test_the_demo_document_is_valid_and_publishable():
    d = doc()
    numbers = set(d.numbers)
    assert problems(d, VALID, numbers) == []
    p = compile_plan(d, Context(domain=demo.DOMAIN, timezones=TZ, upstreams={"national": ["htc"]}, emergency_gateway="htc",
                                validated_locations=VALID, assigned_numbers=numbers))
    assert len(p["extensions"]) == 23 and [x["key"] for x in p["ring_groups"]] == ["leasing", "sales", "shipping", "support"]
    assert p["pages"][0]["members"] == ["200", "201", "202", "203", "204", "220", "221"]
    b = fusionpbx.build(p, TARGET)
    assert 'data="destinations=200,201,202,203,204,220,221"' in dp(b, "photonvox.page.warehouse")["dialplan_xml"]


def test_every_number_is_fictional():
    d = demo.document()
    found = set(re.findall(r"\+1\d{10}", str(d))) | set(demo.OUTSIDE)
    assert found and all(re.fullmatch(r"\+14125550(1\d\d)", x) for x in found)
    assert not set(d["numbers"]) & set(demo.OUTSIDE)            # 0180–0199 are the outside world, never the organization's


def test_three_phone_sites_and_their_911_location_is_a_city_only():
    assert set(doc().sites) == set(demo.PHONE_SITES) and demo.BILLBOARDS not in doc().sites
    for s, a in demo.emergency_locations().items():
        assert a["street"] == "Demo site, not a real address" and a["zip"] == "" and a["city"] == demo.SITES[s][2]
