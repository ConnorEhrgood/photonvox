"""Door stations (PhotonEntry's intercoms; docs/VOX.md in photonaccess): the document, the plan and the engine's rows. A door reaches only its
own flow (911 and 933 excepted), has no voicemail, is recognized by a toll_allow no phone can set, and logs when it was answered and by whom."""
import copy
import re

import pytest

from app.compiler.compile import CompileError
from app.engine import fusionpbx
from tests.unit.test_compiler import plan
from tests.unit.test_document import S1, S2, SAMPLE
from tests.unit.test_engine_build import TARGET, dp, rows

DOOR = {"name": "Front door", "site": S1, "extension": "701", "open": {"group": "office"}, "closed": {"user": "u-pastor"}}


def with_doors(**doors):
    d = copy.deepcopy(SAMPLE)
    d["doors"] = doors
    return d


def test_a_door_is_an_extension_with_no_voicemail_and_no_call_class():
    p = plan(with_doors(front=DOOR, side={**DOOR, "extension": "702", "closed": None, "open": {"user": "u-ada"}}))
    x = next(e for e in p["extensions"] if e["extension"] == "701")
    assert x["door"] == "front" and x["toll_allow"] == [] and x["voicemail"] is False and x["unreachable"] == "hangup"
    assert [e["extension"] for e in p["extensions"]] == sorted(e["extension"] for e in p["extensions"])
    assert p["doors"] == [{"key": "front", "extension": "701", "name": "Front door", "site": S1, "to": "time_condition:door-front"},
                          {"key": "side", "extension": "702", "name": "Front door", "site": S1, "to": "extension:100"}]
    tc = next(t for t in p["time_conditions"] if t["key"] == "door-front")
    assert tc["open"] == "ring_group:office" and tc["closed"] == "extension:102" and tc["hours"] == "office"
    assert "doors" not in plan(SAMPLE)                    # documents without doors: the plan as it was


def test_door_problems():
    bad = with_doors(a={**DOOR, "extension": "100"}, b={**DOOR, "site": "33333333-3333-4333-8333-333333333333"},
                     c={**DOOR, "extension": "311"}, d={**DOOR, "open": {"group": "nope"}, "closed": {"user": "nope"}, "hours": "nope"})
    with pytest.raises(CompileError) as e:
        plan(bad)
    codes = {(p.path, p.code) for p in e.value.problems}
    assert {("doors.a.extension", "extension_taken"), ("doors.b.site", "unknown_site"), ("doors.c.extension", "extension_reserved"),
            ("doors.d.open", "unknown_group"), ("doors.d.closed", "unknown_user"), ("doors.d.hours", "unknown_hours")} <= codes
    nohours = with_doors(front=DOOR)
    nohours["sites"][S1]["hours"] = None
    with pytest.raises(CompileError, match="after-hours outcome needs hours"):
        plan(nohours)
    prefix = with_doors(front={**DOOR, "extension": "801"})
    prefix["sites"][S1]["outside_prefix"] = "8"
    with pytest.raises(CompileError, match="starts an outside call"):
        plan(prefix)
    from pydantic import ValidationError
    for target in ({"menu": "main"}, {"voicemail": "u-ada"}):        # a menu would take the "#"; voicemail has nobody to open the door
        with pytest.raises(ValidationError):
            plan(with_doors(front={**DOOR, "open": target}))


def test_the_engine_rows_of_a_door():
    b = fusionpbx.build(plan(with_doors(front=DOOR, side={**DOOR, "site": S2, "extension": "703", "closed": None, "open": {"user": "u-cy"}})), TARGET)
    ext = rows(b, "v_extensions", extension="701")[0]
    assert ext["toll_allow"] == "door:701" and ext["effective_caller_id_name"] == "Front door"
    assert not rows(b, "v_voicemails", voicemail_id="701") and rows(b, "v_voicemails", voicemail_id="100")
    door = dp(b, "photonvox.door.front")
    assert door["dialplan_order"] == 2 < dp(b, "photonvox.emergency")["dialplan_order"]
    xml = door["dialplan_xml"]
    assert 'field="${toll_allow}" expression="^door:701$"' in xml and 'field="${photonvox_door}" expression="^$"' in xml
    assert 'data="hours-door-front XML ' in xml and 'data="photonvox_door=front" inline="true"' in xml
    assert 'data="103 XML ' not in xml and 'data="200 XML ' in dp(b, "photonvox.door.side")["dialplan_xml"]
    answered = re.search(r'data="(api_on_answer=[^"]*)"', xml).group(1)
    assert fusionpbx.DOOR_ANSWERED.match(answered)
    assert r"answered=\\\${strepoch()} callee=\\\${callee_id_number}" in answered      # expanded when the door's leg is answered
    details = rows(b, "v_dialplan_details", dialplan_uuid=door["dialplan_uuid"])
    assert [d["dialplan_detail_type"] for d in details][:3] == ["${toll_allow}", "${photonvox_door}", "destination_number"]


@pytest.mark.parametrize("dialed,goes_to_the_flow", [("0", True), ("100", True), ("2125550123", True), ("*97", True), ("12125550123", True),
                                                     ("911", False), ("9911", False), ("8911", False), ("933", False), ("9933", False),
                                                     ("9110", True), ("19115", True)])
def test_whatever_a_door_dials_goes_to_its_flow_except_911_and_933(dialed, goes_to_the_flow):
    assert bool(re.match(fusionpbx.DOOR_NOT_EMERGENCY, dialed)) is goes_to_the_flow


def test_no_dial_plan_may_have_the_engine_run_a_command_but_the_doors_answer_log():
    ok = ('<extension name="x"><condition><action application="set" data="api_on_answer=log NOTICE PhotonVox-door domain=a.b '
          'door=701 call=${uuid} answered=\\\\\\${strepoch()} callee=\\\\\\${callee_id_number}"/></condition></extension>')
    fusionpbx.check_xml(ok)
    for data in ("nolocal:api_on_answer=system rm -rf /", "api_hangup_hook=system x", "execute_on_answer=system x", "exec_after_bridge_app=system",
                 "api_on_answer=log NOTICE PhotonVox-door domain=a.b door=701 call=${uuid} answered=1 callee=x; system",
                 "bridge_pre_execute_bleg_app=system"):
        with pytest.raises(ValueError, match="never sets"):
            fusionpbx.check_xml(f'<extension name="x"><condition><action application="set" data="{data}"/></condition></extension>')
