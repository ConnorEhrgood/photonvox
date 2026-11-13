#!/usr/bin/env bash
# Replace staging's copy of a live domain with a fresh one from its export (the takeover rehearsal, ARCHITECTURE §17.5): every row of the domain
# removed, then engine/staging/load_copy.py again (new random secrets; the gateway stand-in again), the caches cleared and the gateway rescanned.
#   engine/staging/reload_copy.sh <export.json>
set -euo pipefail
cd "$(dirname "$0")/../.."
EXPORT=${1:?usage: reload_copy.sh <export.json>}
S() { ssh -i ~/.ssh/vox_staging root@10.10.0.60 "$@"; }
read -r DOM GW < <(python3 -c "import json,sys; d=json.load(open(sys.argv[1])); print(d['domain']['domain_name'], d['tables']['v_gateways'][0]['gateway_uuid'])" "$EXPORT")
OWNER=$(S "sudo -u postgres psql -d fusionpbx -tAc \"select domain_uuid from v_domains where domain_name = '10.10.0.60'\"")
S "D=\$(sudo -u postgres psql -d fusionpbx -tAc \"select domain_uuid from v_domains where domain_name = '$DOM'\"); [ -z \"\$D\" ] || sudo -u postgres psql -d fusionpbx -q -v ON_ERROR_STOP=1 -c \"begin; delete from v_dialplan_details where dialplan_uuid in (select dialplan_uuid from v_dialplans where domain_uuid = '\$D') or domain_uuid = '\$D'; delete from v_dialplans where domain_uuid = '\$D'; delete from v_destinations where domain_uuid = '\$D'; delete from v_ivr_menu_options where domain_uuid = '\$D'; delete from v_ivr_menus where domain_uuid = '\$D'; delete from v_voicemails where domain_uuid = '\$D'; delete from v_extensions where domain_uuid = '\$D'; delete from v_recordings where domain_uuid = '\$D'; delete from v_gateways where gateway_uuid = '$GW'; delete from v_domains where domain_uuid = '\$D'; commit;\""
python3 engine/staging/load_copy.py "$EXPORT" "$OWNER" | S 'cd / && sudo -u postgres psql -d fusionpbx -q -v ON_ERROR_STOP=1'
S "rm -f /var/cache/fusionpbx/*; fs_cli -x 'sofia profile external killgw $GW' > /dev/null; fs_cli -x 'sofia profile external rescan' > /dev/null"
echo "staging's copy reloaded: $(S "sudo -u postgres psql -d fusionpbx -tAc \"select count(*) from v_extensions e join v_domains d using (domain_uuid) where d.domain_name = '$DOM'\"") extensions"
