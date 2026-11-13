#!/usr/bin/env bash
# GATE 1c on the live engine: PhotonVox's read-only database role. Runs ON CT 600, from /root/photon-changes (copied there with gate-1c.sql;
# the exact commands, each needing Connor's go-ahead, are in docs/DEPLOY.md).
#   gate-1c.sh check     read-only: what is there now (the photon_ro line it sits beside, the firewall rule, any earlier photonvox_ro)
#   gate-1c.sh apply     the change: the role (gate-1c.sql, password generated here into photonvox_ro.pass, mode 600) and one pg_hba line, reloaded
#   gate-1c.sh verify    read-only: the line loaded without error, the grants are exactly what gate-1c.sql says
#   gate-1c.sh undo      removes the role and the line, reloads
# PhotonVox runs on the Vultr host, which reaches this container over mgmtnet as 10.2.1.5 (no NAT), the address PhotonConsole's photon_ro
# already uses: the iptables rule for 5432 and the mgmtnet grant exist, so neither changes (`check` shows the rule).
# Revised for Step 7 (gate-1c.sql): every non-secret column of the 15 tables the takeover reads, the dial plans included.
set -euo pipefail
cd /root/photon-changes
SRC=10.2.1.5/32
pg() { ( cd / && runuser -u postgres -- psql -d fusionpbx -qtAX -v ON_ERROR_STOP=1 "$@" ); }
HBA=$(pg -c 'show hba_file')
LINE="host    fusionpbx       photonvox_ro    $SRC            scram-sha-256"
NEXT_TO='^[[:space:]]*host[[:space:]]+fusionpbx[[:space:]]+photon_ro[[:space:]]+10\.2\.1\.5/32[[:space:]]'
exists() { pg -c "select count(*) from pg_roles where rolname = 'photonvox_ro'"; }

verify() {
  local bad=0
  ok() { if [ "$2" = "$3" ]; then echo "ok    $1"; else echo "FAIL  $1 (got $2, wanted $3)"; bad=1; fi; }
  ok "the role exists" "$(exists)" 1
  ok "its pg_hba line loaded, without error" "$(pg -c "select count(*) from pg_hba_file_rules where 'photonvox_ro' = any(user_name) and error is null and address = '10.2.1.5'")" 1
  ok "read-only by default" "$(pg -c "select 'default_transaction_read_only=on' = any(rolconfig) from pg_roles where rolname = 'photonvox_ro'")" t
  ok "can read extensions' numbers" "$(pg -c "select has_column_privilege('photonvox_ro', 'v_extensions', 'extension', 'select')")" t
  ok "cannot read SIP passwords" "$(pg -c "select has_column_privilege('photonvox_ro', 'v_extensions', 'password', 'select')")" f
  ok "cannot read voicemail PINs" "$(pg -c "select has_column_privilege('photonvox_ro', 'v_voicemails', 'voicemail_password', 'select')")" f
  ok "cannot read gateway logins" "$(pg -c "select has_column_privilege('photonvox_ro', 'v_gateways', 'password', 'select')")" f
  ok "can read dial plans (Step 7)" "$(pg -c "select has_column_privilege('photonvox_ro', 'v_dialplans', 'dialplan_xml', 'select')")" t
  ok "cannot read FusionPBX users' passwords, salts, API keys or TOTP secrets" "$(pg -c "select bool_or(has_column_privilege('photonvox_ro', 'v_users', c, 'select')) from unnest(array['password','salt','api_key','user_totp_secret']) c")" f
  ok "cannot read menu PINs or recordings' audio" "$(pg -c "select has_column_privilege('photonvox_ro', 'v_ivr_menus', 'ivr_menu_pin_number', 'select') or has_column_privilege('photonvox_ro', 'v_recordings', 'recording_base64', 'select')")" f
  ok "cannot read call records' raw XML/JSON or callers' addresses" "$(pg -c "select has_column_privilege('photonvox_ro', 'v_xml_cdr', 'json', 'select') or has_column_privilege('photonvox_ro', 'v_xml_cdr', 'network_addr', 'select')")" f
  ok "cannot write anything" "$(pg -c "select count(*) from information_schema.role_table_grants where grantee = 'photonvox_ro' and privilege_type <> 'SELECT'")$(pg -c "select count(*) from information_schema.column_privileges where grantee = 'photonvox_ro' and privilege_type <> 'SELECT'")" 00
  ok "reads as the role: extensions, numbers, call history" "$(pg -c "begin read only; set local role photonvox_ro; select (select count(extension) from v_extensions) >= 0 and (select count(destination_number) from v_destinations) >= 0 and (select count(start_stamp) from v_xml_cdr) >= 0; rollback")" t
  ok "  and is refused a SIP password" "$(pg -c "begin read only; set local role photonvox_ro; select password from v_extensions limit 1; rollback" 2>&1 | grep -c 'permission denied')" 1
  ok "tables it can read" "$(pg -c "select count(distinct table_name) from information_schema.column_privileges where grantee = 'photonvox_ro'")" 15
  echo "      columns NOT readable (the secrets):"
  pg -c "select '        ' || c.table_name || '.' || c.column_name from information_schema.columns c where c.table_schema = 'public' and c.table_name in (select distinct table_name from information_schema.column_privileges where grantee = 'photonvox_ro') and not exists (select 1 from information_schema.column_privileges p where p.grantee = 'photonvox_ro' and p.table_name = c.table_name and p.column_name = c.column_name) order by 1"
  [ $bad = 0 ]
}

case "${1:-}" in
  check)
    echo "pg_hba file:          $HBA"
    echo "photon_ro's line:     $(grep -nE "$NEXT_TO" "$HBA" || echo 'NOT FOUND')"
    echo "photonvox_ro lines:   $(grep -c photonvox_ro "$HBA" || true)"
    echo "photonvox_ro role:    $(exists)"
    echo "listen_addresses:     $(pg -c 'show listen_addresses')"
    echo "iptables, 5432 from 10.2.1.5: $(iptables -S INPUT | grep -cE -- '-s 10\.2\.1\.5(/32)? .*--dport 5432 .*-j ACCEPT' || true)"
    echo "FusionPBX tables:     $(pg -c "select count(*) from pg_tables where schemaname = 'public' and tablename in ('v_domains','v_extensions','v_extension_users','v_voicemails','v_destinations','v_ivr_menus','v_ivr_menu_options','v_ring_groups','v_ring_group_destinations','v_dialplans','v_dialplan_details','v_gateways','v_recordings','v_users','v_xml_cdr')") of 15"
    ;;
  apply)
    grep -qE "$NEXT_TO" "$HBA" || { echo "photon_ro's pg_hba line for $SRC is not there: nothing changed" >&2; exit 1; }
    ! grep -q photonvox_ro "$HBA" && [ "$(exists)" = 0 ] || { echo "photonvox_ro is already there (gate-1c.sh undo first): nothing changed" >&2; exit 1; }
    trap 'echo "stopped part way: run gate-1c.sh undo" >&2' ERR
    # The line first (a line for a role that does not exist yet matches nobody), placed right under photon_ro's; loaded by the reload below.
    cp -p "$HBA" "$HBA.before-gate-1c"
    sed -i -E "\\%$NEXT_TO%a $LINE" "$HBA"
    [ "$(grep -c photonvox_ro "$HBA")" = 1 ]
    (umask 077; [ -s photonvox_ro.pass ] || openssl rand -hex 24 > photonvox_ro.pass)
    # The password reaches psql on its standard input, never a command line.
    { printf "\\set pw '%s'\n" "$(cat photonvox_ro.pass)"; cat gate-1c.sql; } | ( cd / && runuser -u postgres -- psql -d fusionpbx -qX -v ON_ERROR_STOP=1 )
    pg -c 'select pg_reload_conf()' > /dev/null
    sleep 1
    verify
    echo "The password is in /root/photon-changes/photonvox_ro.pass (mode 600): enter it in PhotonVox (Platform → Instances), then delete the file."
    ;;
  verify) verify ;;
  undo)
    [ "$(exists)" = 0 ] || pg -c 'drop owned by photonvox_ro' -c 'drop role photonvox_ro'
    if grep -q photonvox_ro "$HBA"; then cp -p "$HBA" "$HBA.before-gate-1c-undo"; sed -i '/photonvox_ro/d' "$HBA"; pg -c 'select pg_reload_conf()' > /dev/null; fi
    rm -f photonvox_ro.pass
    echo "removed: role $(exists), pg_hba lines $(grep -c photonvox_ro "$HBA" || true)"
    ;;
  *) echo "usage: gate-1c.sh check|apply|verify|undo" >&2; exit 2 ;;
esac
