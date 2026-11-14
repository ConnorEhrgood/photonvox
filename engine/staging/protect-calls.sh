#!/usr/bin/env bash
# The protections version's calls (ARCHITECTURE §17 stage 5) on staging's copy of a live domain, after tests/api/test_staging_protections.py
# published it there: the takeover's calls again (engine/staging/takeover-calls.sh: phones, the menu, calls in, a call out), then what the
# protections change. Calls out reach the carrier as ten digits, however they were dialed; toll-free goes out; premium and Caribbean numbers
# are refused before the carrier sees them; the service route (988, 711, 311) is read, never dialed. SIPp on LXC 800 plays the phones and the carrier; staging reaches no carrier.
#   engine/staging/protect-calls.sh <export.json>
# Never 911, 933 or 9911: refused below, whatever is listed; the emergency route is read, not called.
set -uo pipefail
cd "$(dirname "$0")/../.."
EXPORT=${1:?usage: protect-calls.sh <export.json>}
engine/staging/takeover-calls.sh "$EXPORT"; first=$?
DOMAIN=$(python3 -c "import json, sys; print(json.load(open(sys.argv[1]))['domain']['domain_name'])" "$EXPORT")
PHONES="100:5101 101:5102 102:5103"
pw() { q "select password from v_extensions where extension = '$1' and user_context = '$DOMAIN'"; }
. engine/staging/lib.sh
never() {     # never 911/933, nor 988 or an N11 code (the operator's rule, 2026-11-14): the service route is read below instead
  case "$1" in *911*|*933*) echo "refused: $1 is never dialed in a test" >&2; exit 2;; esac
  [[ "$1" =~ ^[+]?[19]?(988|[2-8]11)$ ]] && { echo "refused: $1 is a service number, never dialed in a test" >&2; exit 2; }; return 0
}
sent() { $SIPP log up | grep -m1 '^INVITE sip:' | sed -E 's/^INVITE sip:([^@]*)@.*/\1/'; }
mask() { [ ${#1} -ge 10 ] && echo "…${1: -4}" || echo "$1"; }

check "the upstream's address out of providers (phones and the carrier stand-in share it)" "$(acl_off)" false
for p in $PHONES; do check "extension ${p%:*} registers" "$(register ${p%:*} ${p#*:})" 0; done
echo "== calls out the protections let through (the carrier gets ten digits, or the service number)"
for c in "+12125550123:2125550123" "12125550123:2125550123" "2125550123:2125550123" "18005550100:8005550100"; do
  dial=${c%%:*} want=${c#*:}; never "$dial"
  fresh; check "101 dials $(mask "$dial"): answered" "$(out "p-${dial//+/p}" 101 "$dial")" 0
  check "  the carrier got $(mask "$want")" "$(mask "$(sent)")" "$(mask "$want")"
  [ "$(sent)" = "$want" ] || echo "   (the carrier's number differs from the ten digits expected)"
done
echo "== calls out the protections refuse (the carrier never sees them)"
for dial in 19005550100 9005550100 18765550100 8095550100; do
  never "$dial"
  fresh; rc=$(out "b-$dial" 101 "$dial")
  check "101 dials $(mask "$dial"): refused" "$([ "$rc" != 0 ] && echo refused || echo answered)" refused
  check "  the carrier saw nothing" "$(invites up)" 0
done
echo "== the service route, read (988, 711 and 311 are never dialed in a test; decision 33)"
check "photonvox.service carries 988, 711 and 311, nothing else" \
  "$(q "select count(*) from v_dialplans d join v_domains o using (domain_uuid) where o.domain_name = '$DOMAIN' and dialplan_name = 'photonvox.service' and dialplan_xml like '%(988|711|311)\$%'")" 1
echo "== the emergency routes, read (never called)"
q "select dialplan_name || ' order ' || dialplan_order || ' ' || dialplan_enabled || ' ' || md5(dialplan_xml) from v_dialplans d join v_domains o using (domain_uuid) where o.domain_name = '$DOMAIN' and dialplan_xml ~ '(911|933)' order by dialplan_order" | sed 's/^/   /'
echo "== hand-built routes the protections switched off (kept, never deleted)"
q "select dialplan_name || ' ' || dialplan_enabled from v_dialplans d join v_domains o using (domain_uuid) where o.domain_name = '$DOMAIN' and not dialplan_enabled order by dialplan_order" \
  | sed -E 's/[0-9]{6}([0-9]{4})/…\1/g; s/^/   /'
$SIPP clean
echo "$pass passed, $fail failed (and the takeover's calls: $([ $first = 0 ] && echo passed || echo FAILED))"; [ $fail = 0 ] && [ $first = 0 ]
