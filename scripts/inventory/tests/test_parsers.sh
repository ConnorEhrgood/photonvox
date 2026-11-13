#!/usr/bin/env bash
# The inventory's parsers, fed made-up FreeSWITCH output (documentation addresses, example domains):  scripts/inventory/tests/test_parsers.sh
# Checks what they count, and that nothing identifying (addresses, users, trunk usernames or hosts, phone firmware) reaches the report.
set -euo pipefail
cd "$(dirname "$0")"
INVENTORY_PARSERS_ONLY=1 . ../engine.sh
fail=0
check() { if grep -qxF -- "$2" <<<"$1"; then :; else echo "FAIL: expected line: $2"; fail=1; fi; }
absent() { if grep -qF -- "$2" <<<"$1"; then echo "FAIL: must not appear: $2"; fail=1; fi; }

reg="$(parse_registrations < sample-reg.txt)"
check "$reg" "   registrations: 3"
check "$reg" "   domain acme.sip.example.net: 2"
check "$reg" "   domain other.example.org: 1"
check "$reg" "   agent Grandstream GRP2602G: 1"
check "$reg" "   agent Grandstream GRP2650: 1"
check "$reg" "   agent Zoiper rv2.10: 1"
check "$reg" "   transport UDP: 2"
check "$reg" "   transport TLS: 1"
check "$reg" "   from a private address (behind NAT or on a LAN/overlay): 1; from a public address: 2"
check "$reg" "   ping Reachable: 2"
check "$reg" "   ping Unreachable: 1"
for s in 192.0.2.10 10.168.1.21 198.51.100.7 "Front Desk" Pastor 1.0.13.21 1.0.5.67 aaaa1111; do absent "$reg" "$s"; done

gw="$(parse_gateways "11111111-2222-3333-4444-555555555555 | Local carrier
66666666-7777-8888-9999-000000000000 | Second carrier" < sample-gw.txt)"
check "$gw" "   Local carrier: NOREG"
check "$gw" "   Second carrier: FAIL_WAIT"
[ "$(grep -c . <<<"$gw")" = 2 ] || { echo "FAIL: the header or summary line was parsed as a gateway"; fail=1; }
for s in trunkuser 203.0.113.50 voip.example.com 11111111; do absent "$gw" "$s"; done
unknown="$(parse_gateways "" < sample-gw.txt)"
check "$unknown" "   (unknown gateway): NOREG"

empty="$(parse_registrations < /dev/null)"
check "$empty" "   registrations: 0"

[ $fail = 0 ] && echo "parsers: all checks passed" || exit 1
