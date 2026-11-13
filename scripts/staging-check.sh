#!/usr/bin/env bash
# Staging never reaches a carrier (Connor, 2026-11-13; BUILD-GUIDE Step 0.6). Run from the runner; read-only apart from two test packets that
# the staging guard drops on the way out. Fails if:
#   - Connor's guard (nftables table inet vox_guard) is missing a rule;
#   - FusionPBX or FreeSWITCH has any gateway other than the SIPp upstream on LXC 800 (named sipp-upstream, proxy 10.10.0.80);
#   - a SIP INVITE from FreeSWITCH to a public address, or a packet to the HTC trunk's network, is not dropped by the guard.
set -euo pipefail
STAGING="${STAGING:-root@10.10.0.60}"
KEY="${KEY:-$HOME/.ssh/vox_staging}"
on() { ssh -i "$KEY" -o ConnectTimeout=10 "$STAGING" "$@"; }
fail=0
ok()  { echo "ok    $*"; }
bad() { echo "FAIL  $*"; fail=1; }

guard="$(on 'nft list table inet vox_guard' 2>/dev/null || true)"
for c in "HTC trunk: never from staging" "no SIP to public addresses" "no SIP over IPv6 to public addresses"; do
  grep -qF "\"$c\"" <<<"$guard" && ok "guard rule: $c" || bad "guard rule missing: $c"
done

# Gateways, in FusionPBX's table and in FreeSWITCH itself. The only one allowed is the SIPp upstream.
db="$(on "sudo -u postgres psql -d fusionpbx -qtAX -F'|' -c \"select gateway, proxy, enabled from v_gateways\"")"
others="$(awk -F'|' 'NF && !($1 == "sipp-upstream" && $2 ~ /^10\.10\.0\.80(:[0-9]+)?$/)' <<<"$db")"
[ -z "$others" ] && ok "FusionPBX gateways: $(grep -c . <<<"$db" || true) (only the SIPp upstream allowed)" || bad "FusionPBX has a gateway other than the SIPp upstream: $(cut -d'|' -f1 <<<"$others" | paste -sd, -)"
fsgw="$(on "fs_cli -x 'sofia status gateway'" | awk 'NF >= 2 && $1 ~ /::/ && $1 != "Profile::Gateway-Name" { print $1 }' | grep -v '::sipp-upstream$' || true)"
[ -z "$fsgw" ] && ok "FreeSWITCH gateways: none but the SIPp upstream" || bad "FreeSWITCH has gateways: $(paste -sd, - <<<"$fsgw")"

# The blocked INVITE. 198.51.100.10 is a documentation address (RFC 5737): public as far as the guard is concerned, routed nowhere.
count() { on "nft list table inet vox_guard" | grep -F "\"$1\"" | grep -oE 'packets [0-9]+' | awk '{print $2}'; }
before="$(count 'no SIP to public addresses')"
on "fs_cli -x 'originate {originate_timeout=3,ignore_early_media=true}sofia/external/staging-check@198.51.100.10:5060 &park()'" > /dev/null 2>&1 || true
after="$(count 'no SIP to public addresses')"
[ "$after" -gt "$before" ] && ok "INVITE to a public address dropped by the guard ($((after - before)) packets)" || bad "INVITE to a public address was not dropped by the guard"

before="$(count 'HTC trunk: never from staging')"
on "timeout 2 bash -c 'echo > /dev/udp/172.30.254.1/5060' 2>/dev/null; true"
after="$(count 'HTC trunk: never from staging')"
[ "$after" -gt "$before" ] && ok "packet to the HTC trunk's network dropped by the guard" || bad "packet to the HTC trunk's network was not dropped"

exit $fail
