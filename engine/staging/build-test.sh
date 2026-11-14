#!/usr/bin/env bash
# BUILD-GUIDE Step 3's build test on staging:   engine/staging/build-test.sh
# 1. The API and worker (the test suite's container on LXC 800) build a phone system as the web app's screens would (a template, 30 pasted
#    people, two sites, four numbers, a ring group per site), publish it to the staging engine through vox-agent with the post-publish check,
#    then find a hand edit and put it back (api/tests/api/test_staging_build.py).
# 2. SIPp proves the result with calls: each number by its schedule, the menu's key, both groups, a direct line; calls out showing each site's
#    number or a user's direct line; international and premium refused, toll-free allowed. 911 is never dialed (the operator's rule,
#    2026-11-14): each site's emergency route is read instead.
set -uo pipefail
cd "$(dirname "$0")/../.."
DOMAIN=build.vox.test
PHONES="100:5101 120:5102 130:5103"        # Person 00 (main office), Person 20 (annex), Person 02 (shows a direct line)
pw() { q "select password from v_extensions where extension = '$1' and user_context = '$DOMAIN'"; }
. engine/staging/lib.sh

echo "== the build (API and worker against the staging engine)"
# Each run starts from the same empty test domain: rows an earlier run wrote (its PhotonVox records died with the test database) are removed.
for t in v_destinations v_dialplan_details v_dialplans v_ivr_menu_options v_ivr_menus v_ring_group_destinations v_ring_groups v_voicemails v_extensions; do
  q "delete from $t where domain_uuid = '7a6b0000-0000-4000-8000-0000000000b1' $( [ $t = v_dialplans ] || [ $t = v_dialplan_details ] && echo "and dialplan_uuid in (select dialplan_uuid from v_dialplans where domain_uuid = '7a6b0000-0000-4000-8000-0000000000b1' and (dialplan_description = 'PhotonVox' or dialplan_context = 'public'))")" > /dev/null
done
S "rm -f /var/cache/fusionpbx/dialplan.build.vox.test /var/cache/fusionpbx/directory.*@build.vox.test /var/cache/fusionpbx/dialplan.public.*21255504*"
export VOX_STAGING_E2E=1 VOX_STAGING_AGENT_URL=http://10.10.0.60:8780
export VOX_STAGING_DB_URL="postgresql+psycopg://photonvox_adapter:$(cat ~/.config/photonvox/staging-adapter.pass)@10.10.0.60:5432/fusionpbx"
export VOX_STAGING_AGENT_SECRET="$(cat ~/.config/photonvox/agent-10.10.0.60.secret)"
OUT=$(scripts/remote-test.sh tests/api/test_staging_build.py -s -q -p no:warnings 2>&1)
RESULT=$(grep -o 'BUILD-TEST .*' <<<"$OUT" | head -1 | cut -d' ' -f2-)
# The result line is printed only after every assertion of the test held.
check "built, published, checked, a hand edit found and put back" "$( [ -n "$RESULT" ] && ! grep -qE '^(FAILED|ERROR)|^E ' <<<"$OUT" && echo yes)" yes
[ -n "$RESULT" ] || { grep -E "^E |Error|FAILED" <<<"$OUT" | head -20; exit 1; }
field() { python3 -c "import json,sys; print(json.loads(sys.argv[1])[sys.argv[2]])" "$RESULT" "$1"; }
echo "   $(field users) people, 4 numbers, two sites in $(field requests) requests; the API's part took $(field integrator_api_seconds) s, publishing and the check $(field publish_and_check_seconds) s"
MAIN=$(field main) ANNEX=$(field annex) DIRECT=$(field direct) MAILBOX=$(field mailbox)

echo "== calls out"
check "the upstream's address out of providers" "$(acl_off)" false
for p in $PHONES; do check "extension ${p%:*} registers" "$(register ${p%:*} ${p#*:})" 0; done
for c in "100:+12125550400:the main office's number" "120:+12125550401:the annex's number" "130:+12125550402:its user's direct line"; do
  IFS=: read -r ext shown why <<<"$c"
  fresh; check "$ext calls a national number" "$(out o-$ext $ext 2125550123)" 0
  check "  showing $why" "$($SIPP log up | grep -c "sip:$shown@")/$($SIPP log up | grep -c '^INVITE sip:+12125550123@')" 1/1
done
for c in "100:+12125550400:main office" "120:+12125550401:annex"; do
  IFS=: read -r ext shown site <<<"$c"
  check "  $ext's 911 caller ID is the $site's emergency number (read, never dialed)" \
    "$(q "select emergency_caller_id_number from v_extensions where extension = '$ext' and user_context = '$DOMAIN'")" "$shown"
done
fresh; check "100 calls toll-free" "$(out o-tf 100 8005550100)" 0
check "  dialing +1 800" "$($SIPP log up | grep -c '^INVITE sip:+18005550100@')" 1
for c in "01144207946000:international (not switched on)" "9005550100:premium"; do
  IFS=: read -r num why <<<"$c"
  fresh; check "100 dials $num: refused, $why" "$( [ "$(out o-$num 100 $num)" != 0 ] && echo refused)" refused
  check "  nothing reached the upstream" "$(invites up)" 0
done

echo "== calls in"
check "the upstream's address back in providers" "$(PYTHONPATH=api "$PY" engine/staging/publish.py --upstreams > /dev/null; S "fs_cli -x 'acl 10.10.0.80 providers'")" true
OPEN=$(python3 - <<'PY'
import datetime as dt
from zoneinfo import ZoneInfo
now = dt.datetime.now(ZoneInfo("America/New_York"))
y, m, d, wd = now.year, now.month, now.day, now.weekday()          # Monday = 0
def nth(n, weekday, month):                                          # the nth weekday of the month (n = -1: the last)
    first = dt.date(y, month, 1)
    days = [first + dt.timedelta(i) for i in range(31) if (first + dt.timedelta(i)).month == month and (first + dt.timedelta(i)).weekday() == weekday]
    return days[n - 1] if n > 0 else days[-1]
holidays = {dt.date(y, 1, 1), nth(3, 0, 1), nth(3, 0, 2), nth(-1, 0, 5), dt.date(y, 6, 19), dt.date(y, 7, 4), nth(1, 0, 9), nth(2, 0, 10),
            dt.date(y, 11, 11), nth(4, 3, 11), dt.date(y, 12, 25)}
print("open" if wd < 5 and 8 <= now.hour < 17 and now.date() not in holidays else "closed")
PY
)
if [ "$OPEN" = open ]; then
  fresh; check "the main number in office hours: the menu, key 1 → everyone" "$(inbound i-main $MAIN call-dtmf.xml -set digit 1 -d 4000)" 0
  check "  the main office's and the annex's phones rang" "$(( $(invites ph100) + $(invites ph120) ))" 2
else
  fresh; check "the main number after hours: the general mailbox answers" "$(inbound i-main $MAIN call.xml -d 2000)" 0
  check "  no phone rang" "$(( $(invites ph100) + $(invites ph120) + $(invites ph130) ))" 0
fi
echo "   (the main number was tested $OPEN; its other half is the post-publish check's, which accepts either)"
fresh; check "the annex's number rings the annex's group" "$(inbound i-annex $ANNEX call.xml -d 1000)" 0
check "  the annex phone rang, the main office's did not" "$(invites ph120)/$(invites ph100)" 1/0
fresh; check "the direct line rings its user" "$(inbound i-direct $DIRECT call.xml -d 1000)" 0
check "  130 rang, nobody else" "$(invites ph130)/$(( $(invites ph100) + $(invites ph120) ))" 1/0
fresh; check "the mailbox number: the general mailbox answers" "$(inbound i-mailbox $MAILBOX call.xml -d 2000)" 0
check "  no phone rang" "$(( $(invites ph100) + $(invites ph120) + $(invites ph130) ))" 0

check "staging-check still passes" "$(bash scripts/staging-check.sh > /dev/null; echo $?)" 0
$SIPP clean
echo "$pass passed, $fail failed"; [ $fail = 0 ]
