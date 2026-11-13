"""The FusionPBX builder (app/engine/fusionpbx.py): scoping, stable ids, and the rows and dial plans that run each part of the plan, checked
against what FusionPBX's own pages wrote on staging (docs/SPIKES.md §1). The same rows are proven by calls on staging (engine/staging)."""
import copy
import re
import xml.etree.ElementTree as ET

import pytest

from app.engine import fusionpbx
from app.engine.fusionpbx import Secret, Target, _before
from tests.unit.test_compiler import plan
from tests.unit.test_document import SAMPLE

PS = "0b5e8c1a-0000-4000-8000-000000000001"
DOMAIN = "0b5e8c1a-0000-4000-8000-0000000000d0"
GW = {"htc": "0b5e8c1a-0000-4000-8000-0000000000a1", "upstream-b": "0b5e8c1a-0000-4000-8000-0000000000a2"}
TARGET = Target(PS, DOMAIN, GW)


def built(d=None):
    return fusionpbx.build(plan(d), TARGET)


def rows(b, table, **match):
    return [r for r in b.rows[table] if all(r.get(k) == v for k, v in match.items())]


def dp(b, name):
    return rows(b, "v_dialplans", dialplan_name=name)[0]


def test_every_row_is_in_the_phone_systems_domain():
    b = built()
    assert all(r["domain_uuid"] == DOMAIN for t in fusionpbx.TABLES for r in b.rows[t])


def test_ids_are_stable_per_phone_system_and_differ_between_phone_systems():
    assert built().manifest() == built().manifest()
    other = fusionpbx.build(plan(), Target("0b5e8c1a-0000-4000-8000-000000000002", DOMAIN, GW))
    assert {m["uuid"] for m in other.manifest()}.isdisjoint({m["uuid"] for m in built().manifest()})


def test_every_dial_plan_is_well_formed_xml_carrying_its_own_id():
    for r in built().rows["v_dialplans"]:
        root = ET.fromstring(r["dialplan_xml"])
        assert root.get("uuid") == r["dialplan_uuid"] and root.get("name") == r["dialplan_name"]


def test_secrets_are_left_to_the_writer_and_kept_out_of_the_manifest():
    b = built()
    ext = rows(b, "v_extensions", extension="100")[0]
    assert isinstance(ext["password"], Secret) and ext["password"] == "sip"
    assert isinstance(rows(b, "v_voicemails", voicemail_id="100")[0]["voicemail_password"], Secret)
    assert b.secrets[("v_extensions", ext["extension_uuid"])] == "password"
    changed = fusionpbx.build(plan(), TARGET)
    changed.rows["v_extensions"][0]["password"] = Secret("pin")       # a different secret kind does not change the hash
    assert changed.manifest() == b.manifest()


# ---- extensions and voicemail ----

def test_an_extension_row_carries_its_caller_ids_and_call_classes_in_fusionpbx_form():
    ext = rows(built(), "v_extensions", extension="102")[0]
    assert ext["outbound_caller_id_number"] == "+17245550123" and ext["emergency_caller_id_number"] == "+17245550100"
    assert ext["toll_allow"] == "international:national:service:toll_free"          # colons, as FusionPBX's page stores them
    assert ext["user_context"] == ext["accountcode"] == "k3x9q2.sip.photoninfra.xyz"
    assert ext["forward_user_not_registered_enabled"] is False and ext["forward_user_not_registered_destination"] is None


def test_unreachable_none_forwards_to_the_hang_up_dial_plan():
    b = built()
    ext = rows(b, "v_extensions", extension="200")[0]
    assert ext["forward_user_not_registered_enabled"] is True and ext["forward_user_not_registered_destination"] == fusionpbx.HANGUP
    assert 'expression="^photonvox-hangup$"' in dp(b, fusionpbx.HANGUP)["dialplan_xml"]


def test_every_user_and_shared_box_has_a_voicemail_box_and_shared_boxes_are_numbered_from_9901():
    b = built()
    assert sorted(r["voicemail_id"] for r in b.rows["v_voicemails"]) == ["100", "101", "102", "200", "9901"]
    general = rows(b, "v_voicemails", voicemail_id="9901")[0]
    assert general["voicemail_mail_to"] == "office@example.com" and general["voicemail_file"] == "attach"
    assert rows(b, "v_voicemails", voicemail_id="101")[0]["voicemail_file"] is None          # no email: nothing to attach to


# ---- outbound routes ----

def test_routes_are_ordered_emergency_block_then_classes_within_fusionpbxs_range():
    b = built()
    order = {r["dialplan_name"]: r["dialplan_order"] for r in b.rows["v_dialplans"] if r["dialplan_name"].startswith("photonvox.")}
    names = [n for n in sorted(order, key=order.get) if n.split(".")[1] in ("emergency", "block", "service", "national", "toll_free")
             or n.startswith("photonvox.international")]
    assert names[:5] == ["photonvox.emergency", "photonvox.block", "photonvox.service", "photonvox.national", "photonvox.toll_free"]
    assert all(100 <= order[n] <= 300 for n in names) and order["photonvox.international-44"] > order["photonvox.toll_free"]


def test_call_classes_are_matched_anchored():
    xml = dp(built(), "photonvox.national")["dialplan_xml"]
    cls = re.search(r'field="\$\{toll_allow\}" expression="([^"]+)"', xml).group(1)
    assert cls == "(^|:)national(:|$)"
    assert re.search(cls, "international:national:service") and re.search(cls, "national")
    assert not re.search(cls, "international:service") and not re.search(cls, "international-44")


def test_the_emergency_route_needs_no_class_shows_the_emergency_caller_id_and_uses_the_emergency_gateway():
    xml = dp(built(), "photonvox.emergency")["dialplan_xml"]
    assert "toll_allow" not in xml
    assert "effective_caller_id_number=${emergency_caller_id_number}" in xml
    assert f"sofia/gateway/{GW['htc']}/$1" in xml and GW["upstream-b"] not in xml


def test_a_route_bridges_through_each_upstream_in_order():
    xml = dp(built(), "photonvox.international-44")["dialplan_xml"]
    assert xml.index(f"sofia/gateway/{GW['upstream-b']}/+$1") < xml.index(f"sofia/gateway/{GW['htc']}/+$1")
    assert "effective_caller_id_number=${outbound_caller_id_number}" in xml


def test_routes_inbound_numbers_and_hours_have_detail_rows_for_fusionpbxs_editor_others_do_not():
    b = built()
    with_details = {r["dialplan_uuid"] for r in b.rows["v_dialplan_details"]}
    names = {r["dialplan_name"] for r in b.rows["v_dialplans"] if r["dialplan_uuid"] in with_details}
    assert "photonvox.national" in names and "+17245550123" in names and "photonvox.hours.number-17245550100" in names
    assert not names & {"photonvox.block", "photonvox.group.office", "photonvox.menu.main", fusionpbx.HANGUP, "call_direction-outbound"}


def test_one_call_direction_dial_plan_per_domain():
    assert len(rows(built(), "v_dialplans", dialplan_name="call_direction-outbound")) == 1


# ---- the block route ----

def test_the_block_route_rejects_by_category_and_records_it():
    xml = dp(built(), "photonvox.block")["dialplan_xml"]
    root = ET.fromstring(xml)
    conds = root.findall("condition")
    assert [c.find("action").get("data") for c in conds] == [f"photonvox_blocked={c}" for c in ("premium", "high_cost_nanp", "satellite", "international")]
    assert all(c.get("break") == "on-true" and c.findall("action")[-1].get("data") == "CALL_REJECTED" for c in conds)


def test_numbers_let_through_are_a_gate_before_the_categories():
    d = copy.deepcopy(SAMPLE)
    d["calling"]["blocking"] = {"allow_numbers": ["+1876555"]}
    first = ET.fromstring(dp(built(d), "photonvox.block")["dialplan_xml"]).find("condition")
    gate = first.get("expression")
    assert first.get("break") is None and not first.findall("action")
    assert re.match(gate, "18765550100") is None and re.match(gate, "18765560100") and re.match(gate, "98765550100") is None


# ---- inbound numbers, groups, menus, hours ----

@pytest.mark.parametrize("form", ["+17245550123", "17245550123", "7245550123"])
def test_an_inbound_number_matches_every_form_a_carrier_may_send(form):
    b = built()
    dest = rows(b, "v_destinations", destination_number="7245550123")[0]
    assert re.match(dest["destination_number_regex"], form)
    assert dest["destination_prefix"] == "1" and dest["dialplan_uuid"] == dp(b, "+17245550123")["dialplan_uuid"]
    assert f"dialplan.public.{form}" in b.cache
    assert dest["destination_actions"] == [{"destination_app": "transfer", "destination_data": "102 XML k3x9q2.sip.photoninfra.xyz"}]


def test_an_inbound_dial_plan_sets_the_domain_before_transferring():
    root = ET.fromstring(dp(built(), "+17245550110")["dialplan_xml"])
    acts = [(a.get("application"), a.get("data")) for a in root.iter("action")]
    assert acts[1] == ("set", f"domain_uuid={DOMAIN}") and acts[-1] == ("transfer", "group-annex XML k3x9q2.sip.photoninfra.xyz")


def test_ring_groups_carry_their_members_strategy_and_next_step():
    b = built()
    annex = rows(b, "v_ring_groups", ring_group_name="annex")[0]
    assert (annex["ring_group_strategy"], annex["ring_group_call_timeout"]) == ("sequence", 20)
    assert (annex["ring_group_timeout_app"], annex["ring_group_timeout_data"]) == ("transfer", "*99200 XML k3x9q2.sip.photoninfra.xyz")
    assert [r["destination_number"] for r in rows(b, "v_ring_group_destinations", ring_group_uuid=annex["ring_group_uuid"])] == ["200"]
    office = rows(b, "v_ring_groups", ring_group_name="office")[0]
    assert office["ring_group_timeout_data"] == "*999901 XML k3x9q2.sip.photoninfra.xyz"


def test_a_group_with_no_next_step_hangs_up():
    d = copy.deepcopy(SAMPLE)
    d["groups"]["office"].pop("then")
    office = rows(built(d), "v_ring_groups", ring_group_name="office")[0]
    assert (office["ring_group_timeout_app"], office["ring_group_timeout_data"]) == ("hangup", "NORMAL_CLEARING")


def test_a_menu_has_its_options_and_timeout_and_its_cache_entry():
    b = built()
    menu = rows(b, "v_ivr_menus", ivr_menu_name="main")[0]
    opts = {o["ivr_menu_option_digits"]: o["ivr_menu_option_param"] for o in b.rows["v_ivr_menu_options"]}
    assert opts == {"1": "transfer group-office XML k3x9q2.sip.photoninfra.xyz", "2": "transfer 102 XML k3x9q2.sip.photoninfra.xyz"}
    assert (menu["ivr_menu_exit_app"], menu["ivr_menu_exit_data"]) == ("transfer", "group-office XML k3x9q2.sip.photoninfra.xyz")
    assert f"configuration.ivr.conf.{menu['ivr_menu_uuid']}" in b.cache
    assert f'ivr" data="{menu["ivr_menu_uuid"]}"' in dp(b, "photonvox.menu.main")["dialplan_xml"]


def test_hours_set_the_sites_time_zone_first_close_on_holidays_and_open_on_each_span():
    root = ET.fromstring(dp(built(), "photonvox.hours.number-17245550100")["dialplan_xml"])
    conds = root.findall("condition")
    first = conds[0].find("action")
    assert (first.get("data"), first.get("inline")) == ("timezone=America/New_York", "true")
    holidays = [c for c in conds if c.get("mon")]
    assert len(holidays) == 11 and all(c.find("action").get("data").startswith("*999901 ") for c in holidays)
    spans = [(c.get("wday"), c.get("time-of-day")) for c in conds if c.get("wday") and not c.get("mon")]
    assert ("6", "08:00-11:59:59") in spans and ("6", "13:00-16:59:59") in spans and len(spans) == 6
    assert conds[-1].get("field") == "destination_number" and conds[-1].find("action").get("data").startswith("*999901 ")


def test_hours_without_holidays_have_no_holiday_conditions():
    d = copy.deepcopy(SAMPLE)
    d["hours"]["office"]["holidays"] = "none"
    root = ET.fromstring(dp(built(d), "photonvox.hours.number-17245550100")["dialplan_xml"])
    assert not [c for c in root.findall("condition") if c.get("mon")]


@pytest.mark.parametrize("end,expected", [("17:00", "16:59:59"), ("24:00", "23:59:59"), ("08:30", "08:29:59"), ("00:01", "00:00:59")])
def test_a_span_ends_one_second_before_its_end(end, expected):
    assert _before(end) == expected


# ---- features and the cache ----

def test_eavesdrop_and_intercept_are_switched_off_unless_the_document_says_so():
    assert set(built().features.values()) == {False} and len(built().features) == 3
    d = copy.deepcopy(SAMPLE)
    d["features"] = {"eavesdrop": True}
    f = built(d).features
    assert f[fusionpbx.FEATURE_APPS["eavesdrop"][0]] is True and f[fusionpbx.FEATURE_APPS["intercept"][0]] is False


def test_the_cache_list_covers_the_domain_its_users_and_is_sorted_without_repeats():
    c = built().cache
    assert "dialplan.k3x9q2.sip.photoninfra.xyz" in c and "directory.100@k3x9q2.sip.photoninfra.xyz" in c
    assert c == sorted(set(c))
