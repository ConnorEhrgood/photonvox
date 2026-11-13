#!/usr/bin/env bash
# The takeover rehearsal's calls (ARCHITECTURE §17.5) on staging's copy of a live domain (engine/staging/load_copy.py), run before and after the
# takeover publish: the two runs must print the same lines. SIPp on LXC 800 plays the phones and the carrier (the copy's gateway points at it).
#   engine/staging/takeover-calls.sh <export.json>
# The domain, its numbers and its extensions come from the export (kept out of git); the output names numbers by their last four digits.
# Never 911 or 933: the 911 route is read, not called.
set -uo pipefail
cd "$(dirname "$0")/../.."
EXPORT=${1:?usage: takeover-calls.sh <export.json>}
read -r DOMAIN MENU N_MENU N_EXT EXT_OF_N < <(python3 - "$EXPORT" <<'PY'
import json, sys
d = json.load(open(sys.argv[1])); t = d["tables"]; D = d["domain"]["domain_uuid"]
menu = t["v_ivr_menus"][0]["ivr_menu_extension"]
dest = [x for x in t["v_destinations"] if x["domain_uuid"] == D]
to_menu = sorted(x["destination_number"] for x in dest if x["destination_data"].startswith(menu + " "))
to_ext = sorted((x["destination_number"], x["destination_data"].split()[0]) for x in dest if not x["destination_data"].startswith(menu + " "))
print(d["domain"]["domain_name"], menu, ",".join(to_menu), to_ext[0][0], to_ext[0][1])
PY
)
PHONES="100:5101 101:5102 102:5103"
pw() { q "select password from v_extensions where extension = '$1' and user_context = '$DOMAIN'"; }
. engine/staging/lib.sh
last4() { echo "…${1: -4}"; }

echo "== phones and internal calls"
check "the upstream's address out of providers" "$(acl_off)" false
for p in $PHONES; do check "extension ${p%:*} registers" "$(register ${p%:*} ${p#*:})" 0; done
fresh; check "101 calls 100" "$(out i-101-100 101 100)" 0
check "  100 rang, nobody else" "$(invites ph100)/$(( $(invites ph101) + $(invites ph102) ))" 1/0
fresh; check "101 dials the menu ($MENU): it answers" "$(out i-menu 101 $MENU)" 0
check "  no phone rang" "$(( $(invites ph100) + $(invites ph101) + $(invites ph102) ))" 0

echo "== a call out (to the carrier stand-in)"
fresh; check "101 calls a national number" "$(out o-101 101 2125550123)" 0
SENT=$($SIPP log up | grep -m1 '^INVITE sip:' | sed -E 's/^INVITE sip:([^@]*)@.*/\1/')
FROM=$($SIPP log up | grep -m1 -i '^From:' | sed -E 's/.*sip:([^@]*)@.*/\1/')
check "  the carrier got the number as dialed (…0123)" "$(last4 "$SENT")" "…0123"
echo "   the carrier saw: number sent $(echo "$SENT" | sed -E 's/[0-9]{4}$/XXXX/'), caller ID $(last4 "$FROM")"
check "  one call reached the carrier" "$(invites up)" 1

echo "== calls in (from the carrier stand-in, 10 digits as the carrier sends them)"
check "the upstream's address back in providers" "$(q "insert into v_access_control_nodes (access_control_node_uuid, access_control_uuid, node_type, node_cidr, node_description) select gen_random_uuid(), access_control_uuid, 'allow', '10.10.0.80/32', 'takeover rehearsal' from v_access_controls where access_control_name = 'providers'" > /dev/null; S "rm -f /var/cache/fusionpbx/configuration.acl.conf; fs_cli -x reloadacl > /dev/null; fs_cli -x 'acl 10.10.0.80 providers'")" true
for n in ${N_MENU//,/ }; do
  fresh; check "the number $(last4 $n) answers with the menu" "$(inbound i-$n $n call.xml -d 3000)" 0
  check "  no phone rang" "$(( $(invites ph100) + $(invites ph101) + $(invites ph102) ))" 0
done
FIRST=${N_MENU%%,*}
fresh; check "the number $(last4 $FIRST), key 2 in the menu" "$(inbound i-key2 $FIRST call-dtmf.xml -set digit 2 -d 6000)" 0
check "  101 rang, nobody else" "$(invites ph101)/$(( $(invites ph100) + $(invites ph102) ))" 1/0
fresh; check "the number $(last4 $N_EXT) rings $EXT_OF_N" "$(inbound i-direct $N_EXT call.xml -d 1000)" 0
check "  $EXT_OF_N rang, nobody else" "$(invites ph$EXT_OF_N)" 1
q "delete from v_access_control_nodes where node_description = 'takeover rehearsal'" > /dev/null

echo "== the 911 route, read (never called)"
q "select dialplan_name || ' order ' || dialplan_order || ' ' || md5(dialplan_xml) from v_dialplans d join v_domains o using (domain_uuid) where o.domain_name = '$DOMAIN' and dialplan_xml ~ '911' order by dialplan_order" | sed 's/^/   /'
$SIPP clean
echo "$pass passed, $fail failed"; [ $fail = 0 ]
