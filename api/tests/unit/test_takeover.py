"""The takeover in place (decision 32, ARCHITECTURE §17): the importer, the builder's adoption, and the compare, on a fictional hand-built domain."""
import copy
import datetime as dt
import decimal
import uuid

import pytest
from pydantic import ValidationError

from app.compiler.compile import CompileError, Context, compile_plan
from app.document.model import PhoneSystem
from app.engine import compare, fusionpbx, importer, takeover
from tests import takeover_fixture as F

SITE = "5c0a0000-0000-4000-8000-0000000000a1"
PS = "5c0a0000-0000-4000-8000-0000000000c1"


def imported(export=None):
    return importer.import_domain(export or F.hand_built(), SITE)


def report(imp):
    return {i.what: (i.outcome, i.detail) for i in imp.report}


# ---- the importer ----

def test_the_document_says_what_the_domain_does():
    imp = imported()
    d = imp.document
    assert set(d["users"]) == {"u-100", "u-101", "u-102", "u-701"}
    assert d["users"]["u-102"]["direct_number"] == "+1" + F.DIRECT and d["users"]["u-102"]["show"] == "direct"
    assert d["users"]["u-701"]["voicemail"] is False and "voicemail" not in d["users"]["u-100"]
    assert d["numbers"]["+1" + F.MAIN]["open"] == {"menu": "main"} and d["numbers"]["+1" + F.DIRECT]["open"] == {"user": "u-102"}
    assert d["menus"]["main"] == {"greeting": "recording:MainMenu.wav", "options": {"1": {"user": "u-100"}, "2": {"user": "u-101"}}}
    site = d["sites"][SITE]
    assert site["caller_id"] == "+1" + F.MAIN and site["emergency_number"] == "+1" + F.MAIN       # no emergency caller ID set: the site's caller ID
    PhoneSystem.model_validate(d)


def test_every_row_is_claimed_by_an_object_or_listed_as_hand_built():
    imp = imported()
    assert set(imp.objects) == {"extension:100", "extension:101", "extension:102", "extension:701", "inbound:+1" + F.MAIN, "inbound:+1" + F.SECOND,
                                "inbound:+1" + F.DIRECT, "ivr:main"}
    assert ("v_voicemails", F._u(14)) in imp.objects["extension:701"]
    assert ("v_dialplan_details", F._u(52)) in imp.objects["inbound:+1" + F.MAIN]
    extras = {u for _t, u in imp.extras}
    assert {F._u(35), F._u(36), F._u(37), F._u(53)} <= extras and F._u(38) not in extras      # the global context is not the domain's
    assert imp.ids["dialplan:ivr:main"] == F._u(34) and imp.ids["ivr:main:1"] == F._u(41)


def test_the_report_names_what_could_not_be_expressed():
    r = report(imported())
    assert r["911 caller ID"][0] == "different"
    elevator = [(i.outcome, i.detail) for i in imported().report if i.what == "extension 701"]
    assert ("decide" in [o for o, _ in elevator]) and any("911" in d for o, d in elevator if o == "decide")
    assert "keys * do something" in r["menu 900"][1] and "dial an extension directly" in r["menu 900"][1] and "short greeting" in r["menu 900"][1]
    assert "destination_hold_music" in r[f"number {F.MAIN[-4:]} (…{F.MAIN[-4:]})"][1]
    assert r["dial plan 'old route' (order 70, disabled)"][0] == "extra"
    assert "another domain" in r["gateway 'Hickory Telephone'"][1]
    assert r["1 FusionPBX users of this domain (they can still sign in to FusionPBX's screens)"][0] == "extra"


def test_what_the_document_cannot_describe_is_left_as_a_hand_built_extra():
    e = F.hand_built()
    t = e["tables"]
    t["v_destinations"][1]["destination_data"] = "*98 XML " + F.DOMAIN                  # voicemail main: no document outcome
    t["v_destinations"][1]["destination_actions"] = [{"destination_app": "transfer", "destination_data": "*98 XML " + F.DOMAIN}]
    t["v_ivr_menus"][0]["ivr_menu_exit_app"] = "hangup"                                  # an exit the document cannot describe
    t["v_extensions"][1]["emergency_caller_id_number"] = "7245550199"
    t["v_extensions"][1]["forward_all_enabled"] = True
    t["v_voicemails"] = [b for b in t["v_voicemails"] if b["voicemail_id"] != "101"]
    t["v_voicemails"][0]["voicemail_mail_to"] = "office@example.test"
    imp = imported(e)
    r = report(imp)
    assert "+1" + F.SECOND not in imp.document["numbers"] and r[f"number {F.SECOND[-4:]} (…{F.SECOND[-4:]})"][0] == "extra"
    assert "exit action (hangup)" in r["menu 900"][1]
    assert "911 caller ID differs" in r["extension 101"][1] and "forward_all_enabled is set" in r["extension 101"][1] and "no voicemail box" in r["extension 101"][1]
    assert imp.document["users"]["u-100"]["email"] == "office@example.test"


def test_targets_resolve_users_menus_and_voicemail_and_nothing_else():
    users, menus = {"100": "u-100"}, {"900": "main"}
    assert importer._target("transfer", "100 XML d", "d", users, menus) == {"user": "u-100"}
    assert importer._target("transfer", "*99100 XML d", "d", users, menus) == {"voicemail": "u-100"}
    assert importer._target("transfer", "100 XML other", "d", users, menus) is None
    assert importer._target("transfer", "nonsense", "d", users, menus) is None
    assert importer._target("bridge", "x", "d", users, menus) is None
    assert importer._e164("1 (724) 555-0100") == "+17245550100" and importer._e164("555") is None


def test_a_domain_with_several_menus_names_them_and_one_with_ring_groups_lists_them():
    e = F.hand_built()
    menu2 = copy.deepcopy(e["tables"]["v_ivr_menus"][0])
    menu2.update(ivr_menu_uuid=F._u(80), ivr_menu_extension="901", ivr_menu_name="After Hours", dialplan_uuid=None, ivr_menu_greet_long=None,
                 ivr_menu_greet_short=None, ivr_menu_direct_dial=False, ivr_menu_exit_app="transfer", ivr_menu_exit_data=f"101 XML {F.DOMAIN}")
    e["tables"]["v_ivr_menus"].append(menu2)
    e["tables"]["v_ring_groups"] = [{"ring_group_uuid": F._u(81), "domain_uuid": F.D, "ring_group_name": "all"}]
    imp = imported(e)
    assert set(imp.document["menus"]) == {"main-menu", "after-hours"}
    assert imp.document["menus"]["after-hours"] == {"greeting": "recording:none", "options": {}, "timeout": {"user": "u-101"}}
    assert report(imp)["v_ring_groups row"][0] == "extra"


# ---- compile, build and compare ----

def test_the_first_publish_is_identical_to_the_live_rows():
    proof = takeover.prove(F.hand_built(), PS, SITE, "htc")
    assert proof["objects"] == 8 and proof["extras"] == 4            # three hand-built dial plans and one's detail
    # Regenerating would change only what the report already says needs deciding: the elevator's second number.
    # Regenerating would change only what the report already names: the direct line's and the elevator's 911 caller ID, and the menu's * key.
    assert [u.split(":")[0] for u in proof["understanding"]] == ["extensions 102", "extensions 701", "menus the menu"]
    assert '"*": "menu-top "' in proof["understanding"][2]
    assert sorted(i["what"] for i in proof["report"] if i["outcome"] == "decide") == ["extension 102", "extension 701"]


def test_a_proof_that_is_not_a_no_op_adopts_nothing(monkeypatch):
    monkeypatch.setattr(compare, "rows_diff", lambda b, live: [{"table": "v_extensions", "id": "x", "kind": "new row"}])
    with pytest.raises(takeover.TakeoverError, match="1 new rows, 0 changed"):
        takeover.prove(F.hand_built(), PS, SITE, "htc")


def build(document, meanings, imp):
    doc = PhoneSystem.model_validate(document)
    plan = compile_plan(doc, Context(domain=F.DOMAIN, timezones={SITE: "America/New_York"}, upstreams={"national": ["htc"]}, emergency_gateway="htc",
                                     assigned_numbers=set(doc.numbers), adopted=True))
    return fusionpbx.build(plan, fusionpbx.Target(PS, F.D, {"htc": F.GATEWAY}, adoption=fusionpbx.Adoption(imp.objects, imp.rows, imp.ids, meanings)))


def test_a_changed_object_is_regenerated_with_its_ids_over_its_live_columns_and_the_rest_stays_as_it_is():
    imp = imported()
    meanings = build(imp.document, {}, imp).meanings
    doc = copy.deepcopy(imp.document)
    doc["users"]["u-101"]["name"] = "Senior Pastor"
    b = build(doc, meanings, imp)
    assert set(b.adopted) == set(imp.objects) - {"extension:101"}
    ext = next(r for r in b.rows["v_extensions"] if r["extension"] == "101")
    assert ext["extension_uuid"] == F._u(2) and ext["effective_caller_id_name"] == "Senior Pastor"
    assert ext["hold_music"] == f"/{F.DOMAIN}/Music.wav" and "insert_date" not in ext        # what the document does not say stays as it was
    assert b.cache == ["dialplan." + F.DOMAIN, f"directory.101@{F.DOMAIN}"]
    assert not any(r["dialplan_name"].startswith("photonvox.") for r in b.rows["v_dialplans"])   # no routes, gates or checks of PhotonVox's
    assert b.features == {}
    diff = compare.rows_diff(b, compare.live_rows(F.hand_built()))
    assert [(d["table"], d["kind"]) for d in diff if d["kind"] == "changed"] == [("v_extensions", "changed"), ("v_voicemails", "changed")]


def test_an_unchanged_adoption_clears_no_cache_and_a_new_object_is_built_fresh():
    imp = imported()
    meanings = build(imp.document, {}, imp).meanings
    assert build(imp.document, meanings, imp).cache == []
    doc = copy.deepcopy(imp.document)
    doc["users"]["u-103"] = {"name": "New Person", "site": SITE, "extension": "103"}
    b = build(doc, meanings, imp)
    new = next(r for r in b.rows["v_extensions"] if r["extension"] == "103")
    assert new["extension_uuid"] == str(uuid.uuid5(uuid.UUID(PS), "extension:103")) and isinstance(new["password"], fusionpbx.Secret)


def test_rows_diff_names_new_and_changed_rows_and_ignores_bookkeeping_and_secrets():
    b = fusionpbx.Build()
    b.rows["v_extensions"] = [{"extension_uuid": "a", "extension": "100", "password": fusionpbx.Secret("sip"), "update_date": "x"},
                              {"extension_uuid": "b", "extension": "101"}]
    live = {"v_extensions:a": {"extension_uuid": "a", "extension": "100", "update_date": "y"}, "v_extensions:b": {"extension_uuid": "b", "extension": "102"}}
    b.rows["v_destinations"] = [{"destination_uuid": "c", "destination_number": "1"}]
    d = compare.rows_diff(b, live)
    assert [(x["id"], x["kind"]) for x in d] == [("b", "changed"), ("c", "new row")] and d[0]["columns"] == ["extension"]
    assert compare.summary(d) == (1, 1)


def test_values_compare_the_same_however_they_were_read():
    when = dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc)
    assert compare.norm(when) == when.isoformat() and compare.norm(dt.date(2026, 1, 1)) == "2026-01-01"
    assert compare.norm(uuid.UUID(int=1)) == str(uuid.UUID(int=1)) and compare.norm(decimal.Decimal("5")) == "5" == compare.norm(5)
    assert compare.norm('[{"a": 1}]') == [{"a": 1}] and compare.norm("[not json") == "[not json" and compare.norm(True) is True


def test_behavior_reads_numbers_menus_and_phones_by_identity():
    rows = compare.live_rows(F.hand_built())
    rows["v_destinations:x"] = {"domain_uuid": F.D, "destination_number": "7245550199", "destination_enabled": False}
    rows["v_ivr_menu_options:y"] = {"domain_uuid": F.D, "ivr_menu_uuid": F.MENU, "ivr_menu_option_digits": "9", "ivr_menu_option_enabled": True,
                                    "ivr_menu_option_param": "transfer *99100 XML d"}
    rows["v_ivr_menu_options:z"] = {"domain_uuid": F.D, "ivr_menu_uuid": F.MENU, "ivr_menu_option_digits": "8", "ivr_menu_option_enabled": True,
                                    "ivr_menu_option_param": "transfer 555 XML d"}
    rows["v_ivr_menu_options:w"] = {"domain_uuid": F.D, "ivr_menu_uuid": F.MENU, "ivr_menu_option_digits": "7", "ivr_menu_option_enabled": True,
                                    "ivr_menu_option_param": "ivr other"}
    rows["v_ivr_menu_options:off"] = {"domain_uuid": F.D, "ivr_menu_uuid": F.MENU, "ivr_menu_option_digits": "6", "ivr_menu_option_enabled": False,
                                      "ivr_menu_option_param": "transfer 100 XML d"}
    b = compare.behavior(rows, F.D)
    assert b["numbers"][F.MAIN] == f"menu {F.MENU}" and b["numbers"][F.DIRECT] == "extension 102" and b["numbers"]["7245550199"] == "disabled"
    assert b["menus"][F.MENU]["keys"]["9"] == "voicemail 100" and b["menus"][F.MENU]["keys"]["8"] == "transfer 555"
    assert b["menus"][F.MENU]["keys"]["7"] == "menu other" and b["menus"][F.MENU]["keys"]["*"] == "menu-top " and "6" not in b["menus"][F.MENU]["keys"]
    assert b["extensions"]["701"]["911"] == F.SECOND and b["voicemail"]["701"]["enabled"] is False
    rows["v_ivr_menus:" + F.MENU] = {**rows["v_ivr_menus:" + F.MENU], "ivr_menu_exit_app": "transfer", "ivr_menu_exit_data": "100 XML d"}
    assert compare.behavior(rows, F.D)["menus"][F.MENU]["exit"] == "extension 100"
    assert compare.behavior_diff({"numbers": {"7245550100": "a"}}, {"numbers": {"7245550100": "b"}}) == ['numbers 0100: live "a", regenerated "b"']


# ---- the document and compiler for adopted domains ----

def test_a_menu_may_end_the_call_and_greet_with_a_recording():
    doc = PhoneSystem.model_validate(imported().document)
    assert doc.menus["main"].timeout is None and doc.users["u-701"].voicemail is False
    with pytest.raises(ValidationError, match="named by its file"):
        PhoneSystem.model_validate({**imported().document, "menus": {"main": {"greeting": "recording:../etc/x", "options": {}}}})


def test_an_adopted_domain_compiles_without_a_validated_911_address_and_others_do_not():
    doc = PhoneSystem.model_validate(imported().document)
    ctx = dict(domain=F.DOMAIN, timezones={}, upstreams={"national": ["htc"]}, emergency_gateway="htc", assigned_numbers=set(doc.numbers))
    p = compile_plan(doc, Context(**ctx, adopted=True))
    assert p["adopted"] is True and p["ivr_menus"][0]["timeout"] == "hangup"
    assert next(x for x in p["extensions"] if x["extension"] == "701")["voicemail"] is False
    assert "voicemail" not in next(x for x in p["extensions"] if x["extension"] == "100")
    with pytest.raises(CompileError) as e:
        compile_plan(doc, Context(**ctx))
    assert [x.code for x in e.value.problems] == ["emergency_location_unvalidated"]


def test_a_recorded_greeting_is_named_as_it_is_and_never_spoken():
    imp = imported()
    b = build(imp.document, {}, imp)            # nothing adopted: the menu built fresh, with the live id
    menu = b.rows["v_ivr_menus"][0]
    assert menu["ivr_menu_uuid"] == F.MENU and menu["ivr_menu_greet_long"] == "MainMenu.wav" and menu["ivr_menu_exit_app"] == "hangup"
    from app.engine import service

    class Speaker:
        def synthesize(self, *_a):
            raise AssertionError("a recording is never spoken")

    assert service.speak(None, Speaker(), None, {"ivr_menus": [{"greeting": "recording:MainMenu.wav"}], "domain": F.DOMAIN}) == 0
