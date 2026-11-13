#!/usr/bin/env python3
"""Step 0.7 spike: write a small phone system straight into FusionPBX's database, the way the adapter will, then clear exactly the cache
entries FusionPBX's Lua handler reads. Rows and dial plan XML copy what FusionPBX 5.5.12's own pages wrote on staging (docs/SPIKES.md §1a).

    python3 engine/spike/direct.py > /tmp/proto.sql      the SQL (one transaction) and, at the end, the cache files to delete

Staging only. The domain row is written separately and seeded with `upgrade.php --defaults` (§1c). Dial plans get `dialplan_xml` only (what
FreeSWITCH reads); whether the adapter also writes detail rows for FusionPBX's editor is open (§1c).
"""
import json
import uuid
from xml.sax.saxutils import quoteattr

DOMAIN = "proto.vox.test"
DOMAIN_UUID = "5a1d0000-0000-4000-8000-000000000001"
GATEWAY_UUID = "5a1d0000-0000-4000-8000-0000000000a1"      # a second SIPp upstream, written directly, on 10.10.0.80:5071
NS = uuid.UUID("5a1d0000-0000-4000-8000-000000000000")

OUTBOUND_APP = "8c914ec3-9fc0-8ab5-4cda-6c9288bdc9a3"
INBOUND_APP = "c03b422e-13a8-bd1b-e42b-b6b9b4d27ce4"
TIME_APP = "4b821450-926b-175a-af93-a03c441818b1"
RING_GROUP_APP = "1d61fb65-1eec-bc73-a6ee-a6203b4fe6f2"
IVR_APP = "a5788e9b-58bc-bd1b-df59-fff5d51253ab"
CONTINUE_ON_FAIL = "1,2,3,6,18,21,27,28,31,34,38,41,42,44,58,88,111,403,501,602,607,809"

sql: list = []
cache: list = []


def uid(name: str) -> str:
    """Stable ids, so a rerun replaces the same rows (the adapter's engine_object table plays this part)."""
    return str(uuid.uuid5(NS, name))


def lit(v) -> str:
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, (list, dict)):
        v = json.dumps(v)
    return "'" + str(v).replace("'", "''") + "'"


def row(table: str, **cols) -> None:
    cols.setdefault("insert_date", "now()")
    names = ", ".join(cols)
    values = ", ".join("now()" if v == "now()" else lit(v) for v in cols.values())
    sql.append(f"insert into {table} ({names}) values ({values});")


def action(app: str, data: str, inline: bool = False) -> str:
    flag = ' inline="true"' if inline else ""
    return f"\t\t<action application={quoteattr(app)} data={quoteattr(data)}{flag}/>\n"


def extension_xml(name: str, dp_uuid: str, cont: str, body: str) -> str:
    return f'<extension name={quoteattr(name)} continue="{cont}" uuid="{dp_uuid}">\n{body}</extension>'


def dialplan(name: str, context: str, order: int, xml: str, app_uuid=None, number=None, cont=False, domain=DOMAIN_UUID, desc="prototype"):
    dp = uid("dialplan:" + context + ":" + name)
    row("v_dialplans", domain_uuid=domain, dialplan_uuid=dp, app_uuid=app_uuid, dialplan_context=context, dialplan_name=name,
        dialplan_number=number, dialplan_continue=cont, dialplan_xml=xml.replace("{uuid}", dp), dialplan_order=order, dialplan_enabled=True,
        dialplan_description=desc)
    return dp


# ---- extensions and their voicemail boxes ----
def extension(ext: str, name: str, password: str, pin: str, outbound: str, emergency: str, classes: list):
    row("v_extensions", extension_uuid=uid("ext:" + ext), domain_uuid=DOMAIN_UUID, extension=ext, password=password, accountcode=DOMAIN,
        effective_caller_id_name=name, effective_caller_id_number=ext, outbound_caller_id_name="Proto Office", outbound_caller_id_number=outbound,
        emergency_caller_id_name="Proto Office", emergency_caller_id_number=emergency, directory_visible=False, directory_exten_visible=False,
        limit_max="5", limit_destination="!USER_BUSY", user_context=DOMAIN, toll_allow=":".join(classes), call_timeout=30,
        call_screen_enabled=False, extension_dialect="us", extension_voice="callie", extension_type="default", enabled=True,
        description="prototype", force_ping=False)
    row("v_voicemails", voicemail_uuid=uid("vm:" + ext), domain_uuid=DOMAIN_UUID, voicemail_id=ext, voicemail_password=pin,
        voicemail_file="attach", voicemail_local_after_email=True, voicemail_enabled=True, voicemail_recording_instructions=True,
        voicemail_recording_options=True, voicemail_description="prototype")
    cache.append(f"directory.{ext}@{DOMAIN}")


# ---- outbound routes ----
def outbound_route(name: str, order: int, pattern: str, caller_id: str, toll_class=None):
    """One route per call class. The call-class condition is anchored (FusionPBX's page writes the bare class name, which `national` would
    also match inside `international-44`)."""
    conds = '\t<condition field="${user_exists}" expression="false"/>\n'
    if toll_class:
        conds += f'\t<condition field="${{toll_allow}}" expression="(^|:){toll_class}(:|$)"/>\n'
    conds += f'\t<condition field="destination_number" expression={quoteattr(pattern)}>\n'
    acts = (action("export", "call_direction=outbound", True) + action("unset", "call_timeout") + action("set", "hangup_after_bridge=true")
            + action("set", f"effective_caller_id_name=${{{caller_id}_caller_id_name}}")
            + action("set", f"effective_caller_id_number=${{{caller_id}_caller_id_number}}")
            + action("set", "inherit_codec=true") + action("set", "ignore_display_updates=true") + action("set", "callee_id_number=$1")
            + action("set", f"continue_on_fail={CONTINUE_ON_FAIL}") + action("bridge", f"sofia/gateway/{GATEWAY_UUID}/$1"))
    dialplan(name, DOMAIN, order, extension_xml(name, "{uuid}", "", conds + acts + "\t</condition>\n"), app_uuid=OUTBOUND_APP)


# ---- inbound numbers: the destination row and its public dial plan must describe the same number (single mode) ----
def inbound(number: str, target: str):
    data = f"{target} XML {DOMAIN}"
    regex = "^\\+(" + number.lstrip("+") + ")$"
    body = (f'\t<condition field="destination_number" expression={quoteattr(regex)}>\n' + action("export", "call_direction=inbound", True)
            + action("set", f"domain_uuid={DOMAIN_UUID}", True) + action("set", f"domain_name={DOMAIN}", True) + action("transfer", data)
            + "\t</condition>\n")
    dp = dialplan(number, "public", 100, extension_xml(number, "{uuid}", "false", body), app_uuid=INBOUND_APP, number=number)
    row("v_destinations", destination_uuid=uid("dest:" + number), domain_uuid=DOMAIN_UUID, dialplan_uuid=dp, destination_type="inbound",
        destination_number=number, destination_number_regex=regex, destination_context="public", destination_record=False,
        destination_actions=[{"destination_app": "transfer", "destination_data": data}], destination_app="transfer", destination_data=data,
        destination_order=100, destination_enabled=True, destination_description="prototype")
    # Single mode caches per number as the carrier sent it; delete every form a carrier may use.
    digits = number.lstrip("+")
    cache.extend(f"dialplan.public.{n}" for n in (number, digits, digits[1:]))


# ---- ring group ----
def ring_group(ext: str, name: str, members: list, timeout_target: str):
    rg = uid("rg:" + ext)
    body = (f'\t<condition field="destination_number" expression="^{ext}$">\n' + action("ring_ready", "") + action("set", f"ring_group_uuid={rg}")
            + action("set", "record_stereo=true") + action("lua", "app.lua ring_groups") + "\t</condition>\n")
    dp = dialplan(name, DOMAIN, 101, extension_xml(name, "{uuid}", "", body), app_uuid=RING_GROUP_APP, number=ext)
    row("v_ring_groups", ring_group_uuid=rg, domain_uuid=DOMAIN_UUID, ring_group_name=name, ring_group_extension=ext, ring_group_call_timeout=30,
        ring_group_forward_enabled=False, ring_group_strategy="simultaneous", ring_group_timeout_app="transfer",
        ring_group_timeout_data=f"{timeout_target} XML {DOMAIN}", ring_group_call_screen_enabled=False, ring_group_call_forward_enabled=False,
        ring_group_follow_me_enabled=False, ring_group_context=DOMAIN, ring_group_enabled=True, ring_group_description="prototype",
        dialplan_uuid=dp)
    for m in members:
        row("v_ring_group_destinations", ring_group_destination_uuid=uid(f"rgd:{ext}:{m}"), domain_uuid=DOMAIN_UUID, ring_group_uuid=rg,
            destination_number=m, destination_delay=0, destination_timeout=30, destination_enabled=True)


# ---- IVR menu ----
def ivr(ext: str, name: str, options: dict, exit_target: str):
    menu = uid("ivr:" + ext)
    body = (f'\t<condition field="destination_number" expression="^{ext}$">\n' + action("ring_ready", "") + action("answer", "")
            + action("sleep", "1000") + action("set", "hangup_after_bridge=true") + action("set", "ringback=local_stream://default")
            + action("set", "transfer_ringback=local_stream://default") + action("set", f"ivr_menu_uuid={menu}") + action("ivr", menu)
            + action("transfer", f"{exit_target} XML {DOMAIN}") + "\t</condition>\n")
    dp = dialplan(name, DOMAIN, 101, extension_xml(name, "{uuid}", "false", body), app_uuid=IVR_APP, number=ext)
    row("v_ivr_menus", ivr_menu_uuid=menu, domain_uuid=DOMAIN_UUID, dialplan_uuid=dp, ivr_menu_name=name, ivr_menu_extension=ext,
        ivr_menu_dialect="us", ivr_menu_voice="callie", ivr_menu_tts_engine="flite", ivr_menu_tts_voice="rms", ivr_menu_confirm_attempts=1,
        ivr_menu_timeout=2000, ivr_menu_exit_app="transfer", ivr_menu_exit_data=f"{exit_target} XML {DOMAIN}", ivr_menu_inter_digit_timeout=2000,
        ivr_menu_max_failures=1, ivr_menu_max_timeouts=1, ivr_menu_digit_len=5, ivr_menu_direct_dial=False,
        ivr_menu_ringback="local_stream://default", ivr_menu_context=DOMAIN, ivr_menu_enabled=True, ivr_menu_description="prototype")
    for i, (digits, target) in enumerate(options.items()):
        row("v_ivr_menu_options", ivr_menu_option_uuid=uid(f"ivro:{ext}:{digits}"), ivr_menu_uuid=menu, domain_uuid=DOMAIN_UUID,
            ivr_menu_option_digits=digits, ivr_menu_option_action="menu-exec-app", ivr_menu_option_param=f"transfer {target} XML {DOMAIN}",
            ivr_menu_option_order=i, ivr_menu_option_enabled=True)
    cache.append(f"configuration.ivr.conf.{menu}")


# ---- time condition (FreeSWITCH's wday: 1 = Sunday … 7 = Saturday; the engine's clock is UTC) ----
def time_condition(ext: str, name: str, wday: str, open_target: str, closed_target: str):
    body = (f'\t<condition field="destination_number" expression="^{ext}$"/>\n\t<condition wday="{wday}"  break="never">\n'
            + action("transfer", f"{open_target} XML {DOMAIN}") + "\t</condition>\n"
            + f'\t<condition field="destination_number" expression="^{ext}$">\n' + action("transfer", f"{closed_target} XML {DOMAIN}")
            + "\t</condition>\n")
    dialplan(name, DOMAIN, 300, extension_xml(name, "{uuid}", "", body), app_uuid=TIME_APP, number=ext)


# ---- the prototype phone system ----
sql.append("begin;")
sql.append(f"delete from v_destinations where domain_uuid = '{DOMAIN_UUID}';")
for t in ("v_ring_group_destinations", "v_ring_groups", "v_ivr_menu_options", "v_ivr_menus", "v_voicemails", "v_extensions"):
    sql.append(f"delete from {t} where domain_uuid = '{DOMAIN_UUID}';")
sql.append(f"delete from v_dialplans where dialplan_description = 'prototype';")
sql.append(f"delete from v_gateways where gateway_uuid = '{GATEWAY_UUID}';")

row("v_gateways", gateway_uuid=GATEWAY_UUID, gateway="sipp-upstream", username="photonvox", password="not-used-ip-auth", distinct_to=False,
    proxy="10.10.0.80:5071", expire_seconds=800, register=False, retry_seconds=30, contact_in_ping=False, caller_id_in_from=False,
    supress_cng=False, channels=0, context="public", profile="external", enabled=True, description="SIPp upstream B (direct write)")

extension("2001", "Proto One", "proto-2001-Xq7v9Lm3Kd", "4826", "+12125550200", "+12125550299", ["national", "toll_free"])
extension("2002", "Proto Two", "proto-2002-Rp4t8Wn6Jc", "5937", "+12125550200", "+12125550299", ["international-44"])

body = '\t<condition field="${user_exists}" expression="false"/>\n\t<condition field="${call_direction}" expression="^$"/>\n'
body += '\t<condition field="destination_number" expression="^.+$">\n' + action("export", "call_direction=outbound", True) + "\t</condition>\n"
dialplan("call_direction-outbound", DOMAIN, 22, extension_xml("call_direction-outbound", "{uuid}", "1", body), app_uuid=OUTBOUND_APP, cont=True)
outbound_route("emergency", 100, "(^911$|^933$)", "emergency")
outbound_route("national", 110, "^(?:\\+1|1)?([2-9]\\d{2}[2-9]\\d{2}\\d{4})$", "outbound", toll_class="national")

ring_group("2100", "Proto desk", ["2001", "2002"], "2001")
ivr("2300", "Proto menu", {"1": "2100"}, "2002")
time_condition("2400", "Proto hours", "2-5", "2001", "2002")     # Monday–Thursday: on a Friday, closed

inbound("+12125550200", "2001")
inbound("+12125550201", "2100")
inbound("+12125550202", "2300")
inbound("+12125550203", "2400")
cache.append(f"dialplan.{DOMAIN}")
cache.append("vox-staging.configuration.sofia.conf")
sql.append("commit;")

print("\n".join(sql))
print("-- cache: " + " ".join(cache))
