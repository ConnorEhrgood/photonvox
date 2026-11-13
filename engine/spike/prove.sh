#!/usr/bin/env bash
# Step 0.7: prove the directly written prototype (engine/spike/direct.py, domain proto.vox.test) with SIPp calls from LXC 800.
# Phones 2001 and 2002 register and answer; upstream B (the directly written gateway) answers on 10.10.0.80:5071.
set -uo pipefail
cd "$(dirname "$0")/../.."
SIPP=scripts/sipp.sh
pw() { ssh -i ~/.ssh/vox_staging root@10.10.0.60 "sudo -u postgres psql -d fusionpbx -qtAX -c \"select password from v_extensions where extension='$1' and user_context='proto.vox.test'\""; }
invites() { $SIPP log "$1" | grep -c '^INVITE '; }
pass=0; fail=0
check() { if [ "$2" = "$3" ]; then echo "ok    $1"; pass=$((pass+1)); else echo "FAIL  $1 (got $2, wanted $3)"; fail=$((fail+1)); fi; }
fresh() {   # restart the answering phones and the upstream, so each test counts only its own INVITEs
  for n in phone2001 phone2002 upstreamB; do $SIPP stop $n; done
  $SIPP start phone2001 -sf /scenarios/phone-answer.xml -i 10.10.0.80 -p 5082 -mi 10.10.0.80
  $SIPP start phone2002 -sf /scenarios/phone-answer.xml -i 10.10.0.80 -p 5083 -mi 10.10.0.80
  $SIPP start upstreamB -sf /scenarios/upstream-uas.xml -i 10.10.0.80 -p 5071 -mi 10.10.0.80
  sleep 1
}
out() {     # <name> <ext> <number> [scenario args]: a phone calls out; prints SIPp's exit code
  local name=$1 ext=$2 num=$3; shift 3
  $SIPP run "$name" -sf /scenarios/call.xml -s "$num" -set from "$ext" -set domain proto.vox.test -au "$ext" -ap "$(pw "$ext")" \
    -i 10.10.0.80 -p 5084 -m 1 -d 1000 -timeout 15s 10.10.0.60:5060 > /dev/null 2>&1; echo $?
}
inbound() { # <name> <number> <scenario> [args]: the upstream calls a number in
  local name=$1 num=$2 sf=$3; shift 3
  $SIPP run "$name" -sf /scenarios/$sf -s "$num" -set from 3105550199 -set domain 10.10.0.60 -i 10.10.0.80 -p 5086 -m 1 -timeout 25s "$@" \
    10.10.0.60:5080 > /dev/null 2>&1; echo $?
}

# The upstream and the phones share LXC 800's address. FusionPBX's internal profile applies the "providers" list too, so while LXC 800 is in it
# a phone's call skips authentication and lands in the public context (404). The list entry is therefore written directly (another direct-write
# proof) and removed for the outbound tests, added for the inbound ones; each change is followed by `reloadacl` and the cache entry's deletion.
acl() {     # on | off
  local q="delete from v_access_control_nodes where node_cidr = '10.10.0.80/32';"
  [ "$1" = on ] && q="$q insert into v_access_control_nodes (access_control_node_uuid, access_control_uuid, node_type, node_cidr, node_description, insert_date) select gen_random_uuid(), access_control_uuid, 'allow', '10.10.0.80/32', 'SIPp upstream (LXC 800)', now() from v_access_controls where access_control_name = 'providers';"
  ssh -i ~/.ssh/vox_staging root@10.10.0.60 "sudo -u postgres psql -d fusionpbx -qtAX -c \"$q\" > /dev/null && rm -f /var/cache/fusionpbx/configuration.acl.conf && fs_cli -x reloadacl > /dev/null && fs_cli -x 'acl 10.10.0.80 providers'"
}
check "the upstream's address removed from providers (direct write)" "$(acl off)" false

for e in 2001:5082 2002:5083; do
  x=${e%:*}; $SIPP run reg$x -sf /scenarios/phone-register.xml -s $x -au $x -ap "$(pw $x)" -set domain proto.vox.test -i 10.10.0.80 -p ${e#*:} \
    -m 1 -timeout 10s 10.10.0.60:5060 > /dev/null 2>&1
  check "extension $x registers" $? 0
done

fresh; check "2001 calls a national number" "$(out o-national 2001 2125550123)" 0
check "  it leaves by the directly written gateway" "$(invites upstreamB)" 1
check "  with the outbound caller ID" "$($SIPP log upstreamB | grep -c 'sip:+12125550200@')" 1
fresh; check "2001 calls 911" "$(out o-911 2001 911)" 0
check "  with the emergency caller ID" "$($SIPP log upstreamB | grep -c 'sip:+12125550299@')" 1
fresh; check "2002 (allowed only international-44) calls a national number: refused" "$( [ "$(out o-refused 2002 2125550123)" != 0 ] && echo refused)" refused
check "  nothing reached the upstream" "$(invites upstreamB)" 0
fresh; check "2002 calls 911 (no call class needed)" "$(out o-911b 2002 911)" 0

check "the upstream's address added to providers (direct write)" "$(acl on)" true
fresh; check "+12125550200 rings 2001" "$(inbound i-ext +12125550200 call.xml -d 1000)" 0
check "  2001 got it" "$(invites phone2001)" 1
fresh; check "+12125550201 rings the ring group" "$(inbound i-rg +12125550201 call.xml -d 1000)" 0
check "  both phones rang" "$(( $(invites phone2001) + $(invites phone2002) ))" 2
fresh; check "+12125550202: the menu, key 1 → the ring group" "$(inbound i-ivr +12125550202 call-dtmf.xml -set digit 1 -d 4000)" 0
check "  the ring group rang (2 INVITEs)" "$(( $(invites phone2001) + $(invites phone2002) ))" 2
fresh; check "+12125550203: hours Monday–Thursday, today Friday → closed → 2002" "$(inbound i-tc +12125550203 call.xml -d 1000)" 0
check "  2002 got it, 2001 did not" "$(invites phone2002)/$(invites phone2001)" 1/0

for n in phone2001 phone2002 upstreamB; do $SIPP stop $n; done
echo "$pass passed, $fail failed"; [ $fail = 0 ]
