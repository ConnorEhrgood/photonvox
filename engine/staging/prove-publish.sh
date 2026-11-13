#!/usr/bin/env bash
# Step 3: PhotonVox's adapter publishes the staging test phone system (engine/staging/system.py) and SIPp proves it with calls from LXC 800.
#   engine/staging/prove-publish.sh
# Publishes the full system, calls out (classes, prefixes, 911 and 933 with the emergency caller ID, the block route) and in (every number, in
# each form a carrier may send it), runs the post-publish check (and breaks a number to see it fail), finds hand edits, checks features and
# scoping, republishes unchanged (nothing new, secrets kept), then publishes the reduced system (what left is gone). Staging only; the SIPp containers are removed at the end.
set -uo pipefail
cd "$(dirname "$0")/../.."
DOMAIN=adapter.vox.test
PHONES="301:5092 302:5093"
pw() { python3 -c "import json,pathlib; print(json.loads(pathlib.Path('~/.config/photonvox/staging-secrets.json').expanduser().read_text())['$DOMAIN']['extension:$1'])"; }
. engine/staging/lib.sh
publish() { PYTHONPATH=api "$PY" engine/staging/publish.py "$@"; }
spike_rows() { q "select count(*) from v_dialplans d join v_domains o using (domain_uuid) where o.domain_name = 'spike.vox.test'"; }

before_spike=$(spike_rows)
$SIPP mailpit stop; $SIPP mailpit start
python3 engine/staging/system.py full > /dev/null
check "publish the full system (greetings spoken by a stand-in provider)" "$(publish engine/staging/.state/adapter.json --speech | grep -c '"domain"')" 1
check "staging-check passes" "$(bash scripts/staging-check.sh > /dev/null; echo $?)" 0
check "eavesdrop and intercept are off in the domain" \
  "$(q "select string_agg(dialplan_name || '=' || dialplan_enabled, ',' order by dialplan_name) from v_dialplans d join v_domains o using (domain_uuid) where o.domain_name = '$DOMAIN' and dialplan_name in ('eavesdrop', 'intercept-ext', 'group-intercept')")" \
  "eavesdrop=false,group-intercept=false,intercept-ext=false"

# ---- calls out (the upstream's address taken out of the providers list meanwhile) ----
check "upstream address out of providers for the outbound tests" "$(acl_off)" false
check "301 registers" "$(register 301 5092)" 0
check "302 registers" "$(register 302 5093)" 0
fresh; check "301 calls a national number" "$(out o1 301 2125550123)" 0
check "  through the upstream, showing 301's direct number" "$(invites up)/$($SIPP log up | grep -c 'sip:+12125550301@')" 1/1
check "  dialing +1 and the ten digits" "$($SIPP log up | grep -c '^INVITE sip:+12125550123@')" 1
fresh; check "301 dials 9 for an outside line, then the number" "$(out o2 301 92125550123)" 0
check "  sent as +1 and ten digits" "$($SIPP log up | grep -c '^INVITE sip:+12125550123@')" 1
for n in 911 9911 933; do
  fresh; check "301 dials $n" "$(out o-$n 301 $n)" 0
  check "  it reaches the upstream with the site's emergency number" "$($SIPP log up | grep -c 'sip:+12125550300@')" 1
  check "  dialing ${n: -3} itself" "$($SIPP log up | grep -c "^INVITE sip:${n: -3}@")" 1
done
fresh; check "301 dials 988 (always allowed)" "$(out o-988 301 988)" 0
check "  dialing 988" "$($SIPP log up | grep -c '^INVITE sip:988@')" 1
for n in 9005550100:premium 7249765100:premium 8765560100:high_cost_nanp 2125559990:listed 01133123456789:international 011881234567:satellite; do
  d=${n%:*}; fresh
  check "301 dials $d: refused (${n#*:})" "$( [ "$(out o-$d 301 $d)" != 0 ] && echo refused)" refused
  check "  nothing reached the upstream" "$(invites up)" 0
done
fresh; check "301 dials 18765550123 (let through the high-cost block)" "$(out o-876 301 18765550123)" 0
check "  it reached the upstream" "$(invites up)/$($SIPP log up | grep -c '^INVITE sip:+18765550123@')" 1/1
check "the engine logged the blocks with their categories" \
  "$(S "grep -c 'PhotonVox blocked' /var/log/freeswitch/freeswitch.log" | awk '{print ($1 >= 6) ? "yes" : "no"}')" yes

# ---- calls in ----
check "upstream address back in providers (republished upstreams)" "$(publish --upstreams > /dev/null; S "fs_cli -x 'acl 10.10.0.80 providers'")" true
for form in +12125550300 12125550300 2125550300; do
  fresh; check "the main number as $form: the menu answers" "$(inbound i-$form $form call.xml -d 1000)" 0
done
fresh; check "the main number, key 1: the desk group" "$(inbound i-key1 +12125550300 call-dtmf.xml -set digit 1 -d 4000)" 0
check "  the menu played its spoken greeting (a file vox-agent put on the engine)" \
  "$(S "grep -c 'done playing file /var/lib/freeswitch/recordings/$DOMAIN/photonvox-' /var/log/freeswitch/freeswitch.log" | awk '{print ($1 >= 1) ? "yes" : "no"}')" yes
check "  both desk phones rang" "$(( $(invites ph301) + $(invites ph302) ))" 2
fresh; check "the desk number rings the group" "$(inbound i-desk 2125550305 call.xml -d 1000)" 0
check "  both desk phones rang" "$(( $(invites ph301) + $(invites ph302) ))" 2
fresh; check "open hours (open now in Los Angeles) ring 301" "$(inbound i-open 12125550301 call.xml -d 1000)" 0
check "  301 rang, 302 did not" "$(invites ph301)/$(invites ph302)" 1/0
fresh; check "the same hours in UTC are closed in Los Angeles: 302" "$(inbound i-utc 12125550302 call.xml -d 1000)" 0
check "  302 rang, 301 did not" "$(invites ph302)/$(invites ph301)" 1/0
check "an unregistered user at a hang-up site: not answered" "$( [ "$(inbound i-303 12125550303 call.xml -d 1000)" != 0 ] && echo unanswered)" unanswered
check "  forwarded to the hang-up dial plan" "$(S "grep -c 'photonvox-hangup XML $DOMAIN' /var/log/freeswitch/freeswitch.log" | awk '{print ($1 >= 1) ? "yes" : "no"}')" yes
check "an unregistered user at a voicemail site: voicemail answers" "$(inbound i-304 12125550304 call.xml -d 2000)" 0
check "a caller leaves a message (a spoken tone, past the greeting)" "$(inbound i-304vm 12125550304 call-speak.xml -mi 10.10.0.80 -d 18000)" 0
sleep 12      # FusionPBX's email queue sends every few seconds
check "  it arrives by email at 304's address, with the recording attached" \
  "$($SIPP mailpit messages | python3 -c 'import json,sys; m=[x for x in json.load(sys.stdin)["messages"] if x["To"][0]["Address"]=="di@example.test"]; print(len(m), m[0]["Attachments"] if m else 0, "Voicemail from 3105550199" in (m[0]["Subject"] if m else ""))')" "1 1 True"

# ---- the post-publish check (synthetic calls: nothing rings, nothing leaves the engine) ----
checks() { publish engine/staging/.state/adapter.json --check --only --speech | python3 -c 'import json,sys; c=json.load(sys.stdin)["check"]; print(sum(x["ok"] for x in c), len(c), ",".join(x["number"] for x in c if not x["ok"]))'; }
check "the post-publish check: every number, 911 and 933 with and without 9, a premium number" "$(checks)" "11 11 "
q "delete from v_destinations where destination_number = '2125550305' and domain_uuid = (select domain_uuid from v_domains where domain_name = '$DOMAIN')" > /dev/null
S "rm -f /var/cache/fusionpbx/dialplan.public.*2125550305"
check "  a number broken by hand: its check fails, the others pass" "$(checks)" "10 11 +12125550305"
publish engine/staging/.state/adapter.json --speech > /dev/null
check "  republishing repairs it" "$(checks)" "11 11 "

# ---- hand edits ----
drift() { publish engine/staging/.state/adapter.json --drift --only --speech | python3 -c 'import json,sys; d=json.load(sys.stdin)["drift"]; print(len(d["changed"]), len(d["missing"]), ",".join(x["label"] for x in d["extra"]))'; }
check "no hand edits after a publish" "$(drift)" "0 0 "
q "update v_extensions set effective_caller_id_name = 'Hand Edit' where extension = '301' and user_context = '$DOMAIN'" > /dev/null
q "update v_dialplans set dialplan_enabled = true where dialplan_name = 'eavesdrop' and dialplan_context = '$DOMAIN'" > /dev/null
q "insert into v_extensions (extension_uuid, domain_uuid, extension, user_context, enabled) select gen_random_uuid(), domain_uuid, '555', '$DOMAIN', true from v_domains where domain_name = '$DOMAIN'" > /dev/null
check "  a renamed user, eavesdrop switched on and an extension added by hand are found" "$(drift)" "2 0 555"
publish engine/staging/.state/adapter.json --speech > /dev/null
check "  the next publish puts PhotonVox's version back and leaves the added extension alone" "$(drift)" "0 0 555"
q "delete from v_extensions where extension = '555' and user_context = '$DOMAIN'" > /dev/null

# ---- republish: unchanged, then reduced ----
first=$(publish engine/staging/.state/adapter.json --speech)
check "republishing unchanged inserts and removes nothing" "$(echo "$first" | python3 -c 'import json,sys; r=json.load(sys.stdin); print(r["inserted"], r["removed"], r["new_secrets"])')" "0 0 0"
check "  301 still registers with the same password" "$(register 301 5092)" 0
python3 engine/staging/system.py reduced > /dev/null
check "publishing the reduced system removes what left" "$(publish engine/staging/.state/adapter.json --speech | python3 -c 'import json,sys; print(json.load(sys.stdin)["removed"] > 0)')" True
check "  extension 304 is gone" "$(q "select count(*) from v_extensions where extension = '304' and user_context = '$DOMAIN'")" 0
check "  its number no longer answers" "$( [ "$(inbound i-304b 12125550304 call.xml -d 1000)" != 0 ] && echo gone)" gone
check "  the menu's key 2 is gone" "$(q "select count(*) from v_ivr_menu_options o join v_ivr_menus m using (ivr_menu_uuid) where m.ivr_menu_context = '$DOMAIN'")" 1
check "the spike's domain was not touched" "$(spike_rows)" "$before_spike"
check "staging-check still passes" "$(bash scripts/staging-check.sh > /dev/null; echo $?)" 0

$SIPP mailpit stop
$SIPP clean
echo "$pass passed, $fail failed"; [ $fail = 0 ]
