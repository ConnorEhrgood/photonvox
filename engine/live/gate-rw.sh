#!/usr/bin/env bash
# PhotonVox's write role on the live engine (CT 600), Step 7 (decision 32). Runs ON CT 600, from /root/photon-changes, after GATE 1c (it is a
# member of photonvox_ro, and its pg_hba line goes right under photonvox_ro's). The exact commands are in the takeover's step file.
#   gate-rw.sh check     read-only: photonvox_ro's line (the anchor), no photonvox_rw yet
#   gate-rw.sh apply     the role (gate-rw.sql, password generated into photonvox_rw.pass, mode 600) and one pg_hba line, reloaded, verified
#   gate-rw.sh verify    read-only: what it may and may not do
#   gate-rw.sh undo      removes the role and the line, reloads
# SRC: the address it logs in from (default the Vultr host over mgmtnet, 10.2.1.5; the staging rehearsal sets LXC 800's).
set -euo pipefail
cd /root/photon-changes
SRC=${SRC:-10.2.1.5/32}
pg() { ( cd / && runuser -u postgres -- psql -d fusionpbx -qtAX -v ON_ERROR_STOP=1 "$@" ); }
HBA=$(pg -c 'show hba_file')
LINE="host    fusionpbx       photonvox_rw    $SRC            scram-sha-256"
NEXT_TO='^[[:space:]]*host[[:space:]]+fusionpbx[[:space:]]+photonvox_ro[[:space:]]'
exists() { pg -c "select count(*) from pg_roles where rolname = 'photonvox_rw'"; }
WRITES="v_extensions v_voicemails v_destinations v_ivr_menus v_ivr_menu_options v_ring_groups v_ring_group_destinations v_dialplans v_dialplan_details"

verify() {
  local bad=0
  ok() { if [ "$2" = "$3" ]; then echo "ok    $1"; else echo "FAIL  $1 (got $2, wanted $3)"; bad=1; fi; }
  ok "the role exists, a member of photonvox_ro" "$(exists)$(pg -c "select pg_has_role('photonvox_rw', 'photonvox_ro', 'member')")" 1t
  ok "its pg_hba line loaded, without error" "$(pg -c "select count(*) from pg_hba_file_rules where 'photonvox_rw' = any(user_name) and error is null")" 1
  ok "may write the nine tables" "$(for t in $WRITES; do pg -c "select has_table_privilege('photonvox_rw', '$t', 'insert') and has_table_privilege('photonvox_rw', '$t', 'update') and has_table_privilege('photonvox_rw', '$t', 'delete')"; done | sort -u)" t
  ok "may not write anything else" "$(pg -c "select count(*) from information_schema.role_table_grants where grantee = 'photonvox_rw' and privilege_type in ('INSERT','UPDATE','DELETE','TRUNCATE') and table_name not in ($(echo $WRITES | sed "s/[a-z_]*/'&'/g; s/ /,/g"))")" 0
  ok "may not write the domains, gateways, users or settings" "$(pg -c "select bool_or(has_table_privilege('photonvox_rw', t, 'insert,update,delete')) from unnest(array['v_domains','v_gateways','v_users','v_default_settings','v_domain_settings','v_xml_cdr']) t")" f
  ok "cannot read SIP passwords or voicemail PINs" "$(pg -c "select has_column_privilege('photonvox_rw', 'v_extensions', 'password', 'select') or has_column_privilege('photonvox_rw', 'v_voicemails', 'voicemail_password', 'select')")" f
  ok "not read-only by default (it writes)" "$(pg -c "select coalesce(bool_or(c = 'default_transaction_read_only=on'), false) from pg_roles, unnest(rolconfig) c where rolname = 'photonvox_rw'")" f
  ok "no superuser, no role or database creation" "$(pg -c "select rolsuper or rolcreaterole or rolcreatedb from pg_roles where rolname = 'photonvox_rw'")" f
  [ $bad = 0 ]
}

case "${1:-}" in
  check)
    echo "pg_hba file:           $HBA"
    echo "photonvox_ro's line:   $(grep -nE "$NEXT_TO" "$HBA" || echo 'NOT FOUND')"
    echo "photonvox_rw lines:    $(grep -c photonvox_rw "$HBA" || true)"
    echo "photonvox_rw role:     $(exists)"
    echo "photonvox_ro role:     $(pg -c "select count(*) from pg_roles where rolname = 'photonvox_ro'")"
    ;;
  apply)
    grep -qE "$NEXT_TO" "$HBA" || { echo "photonvox_ro's pg_hba line is not there (GATE 1c first): nothing changed" >&2; exit 1; }
    ! grep -q photonvox_rw "$HBA" && [ "$(exists)" = 0 ] || { echo "photonvox_rw is already there (gate-rw.sh undo first): nothing changed" >&2; exit 1; }
    trap 'echo "stopped part way: run gate-rw.sh undo" >&2' ERR
    cp -p "$HBA" "$HBA.before-gate-rw"
    sed -i -E "\\%$NEXT_TO%a $LINE" "$HBA"
    [ "$(grep -c photonvox_rw "$HBA")" = 1 ]
    (umask 077; [ -s photonvox_rw.pass ] || openssl rand -hex 24 > photonvox_rw.pass)
    { printf "\\set pw '%s'\n" "$(cat photonvox_rw.pass)"; cat gate-rw.sql; } | ( cd / && runuser -u postgres -- psql -d fusionpbx -qX -v ON_ERROR_STOP=1 )
    pg -c 'select pg_reload_conf()' > /dev/null
    sleep 1
    verify
    echo "The password is in /root/photon-changes/photonvox_rw.pass (mode 600): it goes to PhotonVox (sealed), then the file is deleted."
    ;;
  verify) verify ;;
  undo)
    if [ "$(exists)" != 0 ]; then
      pg -c "select pg_terminate_backend(pid) from pg_stat_activity where usename = 'photonvox_rw'" > /dev/null
      pg -c 'drop owned by photonvox_rw' -c 'drop role photonvox_rw'
    fi
    if grep -q photonvox_rw "$HBA"; then cp -p "$HBA" "$HBA.before-gate-rw-undo"; sed -i '/photonvox_rw/d' "$HBA"; pg -c 'select pg_reload_conf()' > /dev/null; fi
    rm -f photonvox_rw.pass
    echo "removed: role $(exists), pg_hba lines $(grep -c photonvox_rw "$HBA" || true)"
    ;;
  *) echo "usage: gate-rw.sh check|apply|verify|undo" >&2; exit 2 ;;
esac
