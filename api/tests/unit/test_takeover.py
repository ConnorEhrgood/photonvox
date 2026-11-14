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
    assert not [i for i in imported().report if i.what == "extension 701" and i.outcome == "decide"]     # its own number: expressed
    assert imported().document["users"]["u-701"]["caller_id"] == "+1" + F.SECOND
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
    # Regenerating would change only what the report already names: the direct line's 911 caller ID, and the menu's * key. The elevator shows
    # its own number (caller_id), regenerated exactly.
    assert [u.split(":")[0] for u in proof["understanding"]] == ["extensions 102", "menus the menu"]
    assert '"*": "menu-top "' in proof["understanding"][1]
    assert sorted(i["what"] for i in proof["report"] if i["outcome"] == "decide") == ["extension 102"]
    assert set(proof["adoption"]["fresh"]) >= {f"v_extensions:{F._u(1)}", f"v_ivr_menus:{F.MENU}"}


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


# ---- the protections version and later changes (column by column) ----

def adopted(meanings_from=None):
    imp = imported()
    proof = takeover.prove(F.hand_built(), PS, SITE, "htc")
    a = proof["adoption"]
    return imp, fusionpbx.Adoption(imp.objects, imp.rows, imp.ids, a["meanings"], fresh=a["fresh"])


def test_a_later_change_writes_only_the_columns_the_document_now_gives_differently():
    imp, a = adopted()
    doc = copy.deepcopy(imp.document)
    doc["users"]["u-701"]["name"] = "Elevator Car"
    b = build_with(doc, a)
    ext = next(r for r in b.rows["v_extensions"] if r["extension"] == "701")
    assert ext["effective_caller_id_name"] == "Elevator Car" and ext["directory_first_name"] == "Elevator Car"
    assert ext["call_timeout"] == 120 and ext["description"] is None and ext["limit_max"] == "5"      # not the document's to say: kept
    assert ext["outbound_caller_id_number"] == F.SECOND                                                 # unchanged in the document: the live form kept


def test_the_protections_version_sets_classes_and_911_numbers_and_switches_off_what_it_retires():
    imp, a = adopted()
    hand = {f"v_dialplans:{F._u(36)}": next(r for r in F.hand_built()["tables"]["v_dialplans"] if r["dialplan_uuid"] == F._u(36))}
    pa = fusionpbx.Adoption(a.objects, a.rows, a.ids, a.meanings, fresh=a.fresh, retire=[F._u(36)], retired_rows=hand)
    b = build_with({**imp.document, "protections": True}, pa, protected=True)
    ext = {r["extension"]: r for r in b.rows["v_extensions"]}
    assert ext["100"]["toll_allow"] == "national:service:toll_free" and ext["701"]["emergency_caller_id_number"] == "+1" + F.SECOND
    assert ext["701"]["call_timeout"] == 120
    retired = next(r for r in b.rows["v_dialplans"] if r["dialplan_uuid"] == F._u(36))
    assert retired["dialplan_enabled"] is False and retired["dialplan_xml"] == hand[f"v_dialplans:{F._u(36)}"]["dialplan_xml"]
    # Undone (a version without protections): the hand-built route back on exactly as it was; no PhotonVox route.
    back = build_with(imp.document, pa)
    assert next(r for r in back.rows["v_dialplans"] if r["dialplan_uuid"] == F._u(36))["dialplan_enabled"] is True
    assert not any(r["dialplan_name"].startswith("photonvox.") for r in back.rows["v_dialplans"])
    assert {"photonvox.emergency", "photonvox.block", "photonvox.synthetic"} <= {r["dialplan_name"] for r in b.rows["v_dialplans"]}
    assert f"dialplan.{F.DOMAIN}" in b.cache and f"directory.701@{F.DOMAIN}" in b.cache
    # Protected again with the classes already on the engine: nothing more to write on those rows.
    rows2 = {k: ({**r, "toll_allow": "national:service:toll_free", "emergency_caller_id_number": ext[r["extension"]]["emergency_caller_id_number"]}
                 if k.startswith("v_extensions:") else r) for k, r in a.rows.items()}
    pa2 = fusionpbx.Adoption(a.objects, rows2, a.ids, a.meanings, fresh=a.fresh)
    b2 = build_with({**imp.document, "protections": True}, pa2, protected=True)
    assert f"directory.701@{F.DOMAIN}" not in b2.cache


def build_with(document, adoption, protected=False):
    doc = PhoneSystem.model_validate(document)
    plan = compile_plan(doc, Context(domain=F.DOMAIN, timezones={SITE: "America/New_York"}, upstreams={"national": ["htc"]}, emergency_gateway="htc",
                                     assigned_numbers=set(doc.numbers), adopted=True, validated_locations={SITE: {"main"}} if protected else {}))
    return fusionpbx.build(plan, fusionpbx.Target(PS, F.D, {"htc": F.GATEWAY}, adoption=adoption))


def test_values_from_json_and_from_the_engine_compare_the_same_in_the_builder():
    assert fusionpbx.norm(5) == "5" and fusionpbx.norm("[1]") == [1] and fusionpbx.norm("[x") == "[x" and fusionpbx.norm(True) is True


def test_the_outbound_reading_handles_unusual_dial_plans():
    assert compare._evaluate("<not xml", "2125550123", "100", "") is None
    assert compare._evaluate('<extension><condition><action application="hangup" data="X"/></condition></extension>', "1", "100", "") == "hangup X"
    assert compare._evaluate('<extension><condition field="destination_number" expression="(("><action application="hangup"/></condition></extension>',
                             "1", "100", "") is None
    assert compare._evaluate('<extension><condition field="destination_number" expression="^1$"><action application="set" data="x=1"/></condition>'
                             '</extension>', "1", "100", "") is None                                   # sets something, routes nothing


def test_a_non_compiling_document_stops_the_dry_run():
    with pytest.raises(takeover.TakeoverError, match="the phone system has no site"):
        takeover.readopt(None, type("PS", (), {"domain_name": F.DOMAIN, "draft": {}, "adoption": {}})(), type("I", (), {"emergency_upstream": "htc", "routing": {}})(),
                         _Conn(F.hand_built()))


class _Conn:
    """Answers takeover.read_domain from an export (enough for the error paths)."""
    def __init__(self, export):
        self.export = export

    def execute(self, *_a, **_k):
        e = self.export

        class R:
            domain_uuid, domain_name, domain_enabled = e["domain"]["domain_uuid"], e["domain"]["domain_name"], True

            def first(self):
                return self

            def __iter__(self):
                return iter([])

            def mappings(self):
                return []
        return R()
