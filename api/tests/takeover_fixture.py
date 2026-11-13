"""A hand-built FusionPBX domain, as engine/live/export_domain.py exports one, for the takeover's tests (ARCHITECTURE §17). Fictional: it has the
shape of the live engine's one customer (a menu on the main numbers, a direct number, voicemail switched off on some phones, a phone that shows
a second number, hold music, hand-built outside-call and block routes, a gateway owned by another domain) and none of its data."""
from __future__ import annotations

import copy
from typing import Any, Dict

D = "5c0a0000-0000-4000-8000-0000000000d1"
DOMAIN = "church.example.test"
OTHER = "5c0a0000-0000-4000-8000-0000000000d2"
GATEWAY = "5c0a0000-0000-4000-8000-0000000000f1"
MAIN, SECOND, DIRECT = "7245550100", "7245550101", "7245550102"
MENU = "5c0a0000-0000-4000-8000-0000000000b1"
INBOUND_APP = "c03b422e-13a8-bd1b-e42b-b6b9b4d27ce4"
OUTBOUND_APP = "8c914ec3-9fc0-8ab5-4cda-6c9288bdc9a3"
IVR_APP = "a5788e9b-58bc-bd1b-df59-fff5d51253ab"
WHEN = "2026-10-01T12:00:00+00:00"


def _u(n: int) -> str:
    return f"5c0a0000-0000-4000-8000-{n:012d}"


def _ext(n: int, ext: str, name: str, cid: str, **over: Any) -> Dict[str, Any]:
    row = {"extension_uuid": _u(n), "domain_uuid": D, "extension": ext, "number_alias": None, "accountcode": DOMAIN,
           "effective_caller_id_name": name, "effective_caller_id_number": ext, "outbound_caller_id_name": "Grace Church", "outbound_caller_id_number": cid,
           "emergency_caller_id_name": None, "emergency_caller_id_number": None, "directory_first_name": name, "directory_last_name": None,
           "directory_visible": False, "directory_exten_visible": False, "limit_max": "5", "limit_destination": "!USER_BUSY", "user_context": DOMAIN,
           "toll_allow": None, "call_timeout": 30, "call_group": None, "call_screen_enabled": False, "hold_music": f"/{DOMAIN}/Music.wav",
           "extension_dialect": "us", "extension_voice": "callie", "extension_type": "default", "enabled": True, "description": None,
           "forward_all_enabled": None, "forward_user_not_registered_enabled": None, "forward_user_not_registered_destination": None,
           "do_not_disturb": None, "force_ping": False, "insert_date": WHEN, "insert_user": None, "update_date": WHEN, "update_user": None}
    row.update(over)
    return row


def _box(n: int, box: str, enabled: bool = True) -> Dict[str, Any]:
    return {"voicemail_uuid": _u(n), "domain_uuid": D, "voicemail_id": box, "voicemail_mail_to": None, "voicemail_file": "attach",
            "voicemail_local_after_email": True, "voicemail_enabled": enabled, "voicemail_description": None, "greeting_id": None,
            "insert_date": WHEN, "update_date": WHEN}


def _dialplan(n: int, name: str, order: int, app: Any, xml: str, context: str = DOMAIN, number: Any = None, domain: Any = D, enabled: bool = True):
    return {"dialplan_uuid": _u(n), "domain_uuid": domain, "app_uuid": app, "hostname": None, "dialplan_context": context, "dialplan_name": name,
            "dialplan_number": number, "dialplan_destination": None, "dialplan_continue": False, "dialplan_xml": xml, "dialplan_order": order,
            "dialplan_enabled": enabled, "dialplan_description": None, "insert_date": WHEN, "update_date": WHEN}


def _detail(n: int, dp: int, tag: str, typ: str, data: str, order: int) -> Dict[str, Any]:
    return {"dialplan_detail_uuid": _u(n), "domain_uuid": D, "dialplan_uuid": _u(dp), "dialplan_detail_tag": tag, "dialplan_detail_type": typ,
            "dialplan_detail_data": data, "dialplan_detail_break": None, "dialplan_detail_inline": None, "dialplan_detail_group": 0,
            "dialplan_detail_order": order, "dialplan_detail_enabled": True, "insert_date": WHEN, "update_date": WHEN}


def _number(n: int, dp: int, number: str, to: str, hold: Any = None) -> Dict[str, Any]:
    return {"destination_uuid": _u(n), "domain_uuid": D, "dialplan_uuid": _u(dp), "destination_type": "inbound", "destination_prefix": None,
            "destination_number": number, "destination_number_regex": f"^({number})$", "destination_context": "public",
            "destination_caller_id_name": None, "destination_caller_id_number": None, "destination_record": False, "destination_hold_music": hold,
            "destination_actions": [{"destination_app": "transfer", "destination_data": f"{to} XML {DOMAIN}"}], "destination_app": "transfer",
            "destination_data": f"{to} XML {DOMAIN}", "destination_conditions": None, "destination_order": 100, "destination_enabled": True,
            "destination_description": None, "insert_date": WHEN, "update_date": WHEN}


def _inbound_xml(number: str, to: str) -> str:
    return (f'<extension name="{number}" continue="false">\n\t<condition field="destination_number" expression="^({number})$">\n'
            f'\t\t<action application="transfer" data="{to} XML {DOMAIN}"/>\n\t</condition>\n</extension>')


def hand_built() -> Dict[str, Any]:
    t: Dict[str, Any] = {
        "v_extensions": [
            _ext(1, "100", "Main Office", MAIN),
            _ext(2, "101", "Pastor", MAIN),
            _ext(3, "102", "Office Direct", DIRECT),
            _ext(4, "701", "Elevator", SECOND, call_timeout=120),
        ],
        "v_voicemails": [_box(11, "100"), _box(12, "101"), _box(13, "102"), _box(14, "701", enabled=False)],
        "v_destinations": [_number(21, 31, MAIN, "900", hold=f"/{DOMAIN}/Menu.wav"), _number(22, 32, SECOND, "900"), _number(23, 33, DIRECT, "102")],
        "v_ivr_menus": [{"ivr_menu_uuid": MENU, "domain_uuid": D, "dialplan_uuid": _u(34), "ivr_menu_name": "Main Menu", "ivr_menu_extension": "900",
                         "ivr_menu_greet_long": "MainMenu.wav", "ivr_menu_greet_short": "MenuShort.wav", "ivr_menu_timeout": 5000,
                         "ivr_menu_exit_app": None, "ivr_menu_exit_data": None, "ivr_menu_direct_dial": True, "ivr_menu_digit_len": 3,
                         "ivr_menu_max_failures": 3, "ivr_menu_max_timeouts": 3, "ivr_menu_ringback": "${us-ring}", "ivr_menu_context": DOMAIN,
                         "ivr_menu_enabled": True, "ivr_menu_description": None, "insert_date": WHEN, "update_date": WHEN}],
        "v_ivr_menu_options": [
            {"ivr_menu_option_uuid": _u(41), "ivr_menu_uuid": MENU, "domain_uuid": D, "ivr_menu_option_digits": "1", "ivr_menu_option_action": "menu-exec-app",
             "ivr_menu_option_param": f"transfer 100 XML {DOMAIN}", "ivr_menu_option_order": 0, "ivr_menu_option_enabled": True, "insert_date": WHEN, "update_date": WHEN},
            {"ivr_menu_option_uuid": _u(42), "ivr_menu_uuid": MENU, "domain_uuid": D, "ivr_menu_option_digits": "2", "ivr_menu_option_action": "menu-exec-app",
             "ivr_menu_option_param": f"transfer 101 XML {DOMAIN}", "ivr_menu_option_order": 0, "ivr_menu_option_enabled": True, "insert_date": WHEN, "update_date": WHEN},
            {"ivr_menu_option_uuid": _u(43), "ivr_menu_uuid": MENU, "domain_uuid": D, "ivr_menu_option_digits": "*", "ivr_menu_option_action": "menu-top",
             "ivr_menu_option_param": "", "ivr_menu_option_order": 0, "ivr_menu_option_enabled": True, "insert_date": WHEN, "update_date": WHEN},
        ],
        "v_ring_groups": [], "v_ring_group_destinations": [],
        "v_dialplans": [
            _dialplan(31, MAIN, 100, INBOUND_APP, _inbound_xml(MAIN, "900"), context="public", number=MAIN),
            _dialplan(32, SECOND, 100, INBOUND_APP, _inbound_xml(SECOND, "900"), context="public", number=SECOND),
            _dialplan(33, DIRECT, 100, INBOUND_APP, _inbound_xml(DIRECT, "102"), context="public", number=DIRECT),
            _dialplan(34, "Main Menu", 101, IVR_APP, f'<extension name="Main Menu"><condition field="destination_number" expression="^900$">'
                      f'<action application="ivr" data="{MENU}"/></condition></extension>', number="900"),
            _dialplan(35, "Block-premium", 45, OUTBOUND_APP, '<extension name="Block-premium"><condition field="destination_number" expression="^1?900\\d{7}$">'
                      '<action application="hangup" data="CALL_REJECTED"/></condition></extension>'),
            _dialplan(36, "Outbound NANP", 60, None, f'<extension name="Outbound NANP"><condition field="destination_number" expression="^1?(\\d{{10}})$">'
                      f'<action application="bridge" data="sofia/gateway/{GATEWAY}/1$1"/></condition></extension>'),
            _dialplan(37, "old route", 70, None, "<extension name=\"old route\"/>", enabled=False),
            _dialplan(38, "global thing", 10, None, "<extension name=\"global thing\"/>", context="global", domain=None),
        ],
        "v_dialplan_details": [
            _detail(51, 31, "condition", "destination_number", f"^({MAIN})$", 10), _detail(52, 31, "action", "transfer", f"900 XML {DOMAIN}", 20),
            _detail(53, 36, "condition", "destination_number", "^1?(\\d{10})$", 10),
        ],
        "v_gateways": [{"gateway_uuid": GATEWAY, "domain_uuid": OTHER, "gateway": "Hickory Telephone", "proxy": "198.51.100.9", "register": False,
                        "context": "public", "profile": "htc", "enabled": True, "description": None}],
        "v_recordings": [{"recording_uuid": _u(61), "domain_uuid": D, "recording_filename": "MainMenu.wav", "recording_name": "Main Menu"}],
        "v_users": [{"user_uuid": _u(71), "domain_uuid": D, "username": "office", "user_enabled": True}],
        "v_extension_users": [{"extension_user_uuid": _u(72), "domain_uuid": D, "extension_uuid": _u(1), "user_uuid": _u(71)}],
    }
    return {"exported_at": WHEN, "domain": {"domain_uuid": D, "domain_name": DOMAIN, "domain_enabled": True}, "tables": copy.deepcopy(t),
            "other_domains": 1, "calls_30_days": []}
