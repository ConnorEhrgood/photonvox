#!/usr/bin/env bash
# The takeover's test calls (ARCHITECTURE §17.6), placed by FreeSWITCH itself on the engine (no phones needed). Runs ON the engine, as root.
#   test_calls.sh internal <domain> <from extension> <to extension>   an extension calls another: where the call goes (the phone, or voicemail)
#   test_calls.sh menu     <domain> <menu extension>                   the menu answers
#   test_calls.sh loop     <domain> <from extension> <10-digit number> <caller ID number>
#        a call out through the domain's own outbound route to one of its own numbers, which the carrier sends back in: both legs are shown
# Each call is placed with `originate` over a loopback channel (as if the extension dialed it), watched for a few seconds, then hung up.
# NEVER 911, 933, 9911 or anything that could reach an emergency service: refused below, whatever is asked.
set -euo pipefail
fs() { fs_cli -x "$1"; }
refuse() { case "$1" in *911*|*933*|1911|9911) echo "refused: $1 is never dialed in a test" >&2; exit 2;; esac; }
legs() {   # the channels now: name, state, application, destination (one per line)
  fs "show channels as delim |" | awk -F'|' 'NR==1 { for (i = 1; i <= NF; i++) h[$i] = i; next } NF > 5 && $1 != "" {
    print "   " $h["name"] " | " $h["callstate"] " | " $h["application"] " " $h["application_data"] " | dest " $h["dest"] }' \
    | sed -E 's/[0-9a-f]{8}-[0-9a-f-]{27}/<id>/g'
}
place() {   # <uuid> <channel variables> <loopback target>: one variable block (FreeSWITCH takes one)
  fs "bgapi originate {origination_uuid=$1,photonvox_test=true,originate_timeout=20,hangup_after_bridge=true,$2}$3 &park()" > /dev/null
}
finish() { fs "uuid_kill $1" > /dev/null || true; sleep 2; echo "   after hanging up: $(fs 'show channels count' | grep -o '[0-9]* total')"; }
before=$(fs 'show channels count' | grep -o '[0-9]* total')
case "${1:-}" in internal|menu|loop) echo "   channels before: $before" ;; esac

case "${1:-}" in
  internal)
    D=$2 FROM=$3 TO=$4; refuse "$TO"; U=$(cat /proc/sys/kernel/random/uuid)
    echo "== $FROM calls $TO (registered: $(fs "sofia_contact */$TO@$D" | grep -q error && echo no || echo yes))"
    place "$U" "origination_caller_id_number=$FROM,origination_caller_id_name='PhotonVox test'" "loopback/$TO/$D"
    sleep 4; legs; finish "$U" ;;
  menu)
    D=$2 MENU=$3; refuse "$MENU"; U=$(cat /proc/sys/kernel/random/uuid)
    echo "== the menu $MENU"
    place "$U" "origination_caller_id_number=PhotonVox,origination_caller_id_name='PhotonVox test'" "loopback/$MENU/$D"
    sleep 4; legs; finish "$U" ;;
  loop)
    D=$2 FROM=$3 NUM=$4 CID=$5; refuse "$NUM"
    [[ "$NUM" =~ ^[2-9][0-9]{2}[2-9][0-9]{6}$ ]] || { echo "refused: $NUM is not a 10-digit North American number" >&2; exit 2; }
    U=$(cat /proc/sys/kernel/random/uuid)
    echo "== $FROM calls …${NUM: -4} out through the carrier, and it comes back in"
    place "$U" "origination_caller_id_number=$FROM,origination_caller_id_name='PhotonVox test',outbound_caller_id_number=$CID,outbound_caller_id_name='PhotonVox test'" "loopback/$NUM/$D"
    sleep 8; legs | sed -E "s/$NUM/…${NUM: -4}/g; s/$CID/…${CID: -4}/g"; finish "$U" ;;
  state)      # read-only: registrations of the domain, channels, PhotonConsole's status shim
    echo "   registrations of the domain: $(fs 'show registrations' | grep -c "$2" || true); channels: $before; shim: $(systemctl is-active photon-fpbx-shim 2>/dev/null || true)" ;;
  records)    # read-only: the domain's call records of the last 10 minutes (numbers shortened to their last four digits)
    ( cd / && runuser -u postgres -- psql -d fusionpbx -tA -F ' | ' -c "select start_stamp::time(0), direction, right(coalesce(caller_id_number, ''), 4), right(coalesce(destination_number, ''), 4), hangup_cause from v_xml_cdr where domain_name = '$2' and start_stamp > now() - interval '10 minutes' order by start_stamp" ) | sed 's/^/   /' ;;
  route911)   # read-only: the domain's dial plans that mention 911 (never called), with a fingerprint of each
    ( cd / && runuser -u postgres -- psql -d fusionpbx -tA -F ' | ' -c "select dialplan_name, dialplan_order, dialplan_enabled, md5(dialplan_xml) from v_dialplans p join v_domains d using (domain_uuid) where d.domain_name = '$2' and dialplan_xml ~ '911' order by dialplan_order" ) | sed 's/^/   /' ;;
  *) echo "usage: test_calls.sh internal <domain> <from> <to> | menu <domain> <menu> | loop <domain> <from> <10-digit number> <caller ID> | state|records|route911 <domain>" >&2; exit 2 ;;
esac
