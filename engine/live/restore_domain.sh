#!/usr/bin/env bash
# Put one domain's rows back exactly as they were in a pg_dump (the takeover's rollback, ARCHITECTURE §17.6). Runs ON the engine, as root.
#   restore_domain.sh checksum <domain name>                one fingerprint per table of the domain's rows (compare before and after)
#   restore_domain.sh restore  <dump file> <domain name>   the domain's rows in the tables PhotonVox may write, back to the dump, in ONE transaction
# Only the tables PhotonVox's write role can change are touched (extensions, voicemail boxes, numbers, menus and their options, ring groups and
# their members, dial plans and their details); only the domain's rows in them (dial plan details: those of the domain's dial plans, or marked
# with the domain). Every other domain, and everything else of this one, is left alone. The dump is restored into a scratch database first
# (fusionpbx_restore, dropped afterwards); FusionPBX's cache of the domain is cleared after the commit, so FreeSWITCH reads the rows back.
set -euo pipefail
TABLES="v_extensions v_voicemails v_destinations v_ivr_menus v_ivr_menu_options v_ring_groups v_ring_group_destinations v_dialplans v_dialplan_details"
pg() { ( cd / && runuser -u postgres -- psql -qtAX -v ON_ERROR_STOP=1 "$@" ); }
domain_uuid() { pg -d "$1" -c "select domain_uuid from v_domains where domain_name = '$2'"; }
where() {   # the domain's rows of a table
  if [ "$1" = v_dialplan_details ]; then
    echo "dialplan_uuid in (select dialplan_uuid from v_dialplans where domain_uuid = '$2') or domain_uuid = '$2'"
  else
    echo "domain_uuid = '$2'"
  fi
}
checksum() {   # <database> <domain uuid>
  for t in $TABLES; do
    echo "$t $(pg -d "$1" -c "select count(*) || ' ' || coalesce(md5(string_agg(md5(r::text), '' order by md5(r::text))), '-') from $t r where $(where $t "$2")")"
  done
}
case "${1:-}" in
  checksum)
    D=$(domain_uuid fusionpbx "$2"); [ -n "$D" ] || { echo "no domain $2" >&2; exit 1; }
    checksum fusionpbx "$D" ;;
  restore)
    DUMP=$2; NAME=$3
    D=$(domain_uuid fusionpbx "$NAME"); [ -n "$D" ] || { echo "no domain $NAME" >&2; exit 1; }
    # The rows travel through files postgres writes and reads: a private folder outside /root (which postgres cannot enter), removed at the end.
    WORK=$(mktemp -d /var/tmp/photonvox-restore.XXXXXX); chmod 700 "$WORK"; chown postgres "$WORK"
    trap 'rm -rf "$WORK"; pg -d postgres -c "drop database if exists fusionpbx_restore" > /dev/null' EXIT
    pg -d postgres -c "drop database if exists fusionpbx_restore" -c "create database fusionpbx_restore" > /dev/null
    # The dump is root's (mode 600): root reads it and hands it to pg_restore on standard input.
    ( cd / && runuser -u postgres -- pg_restore --no-owner --no-privileges -d fusionpbx_restore ) < "$DUMP" 2> "$WORK/pg_restore.err" || true
    [ "$(domain_uuid fusionpbx_restore "$NAME")" = "$D" ] || { echo "the dump has no domain $NAME (see $WORK/pg_restore.err)" >&2; exit 1; }
    echo "the dump's rows of the domain:"; checksum fusionpbx_restore "$D"
    { echo "begin;"
      for t in $(echo $TABLES | tr ' ' '\n' | tac); do echo "delete from $t where $(where $t "$D");"; done
      for t in $TABLES; do
        ( cd / && runuser -u postgres -- psql -qtAX -d fusionpbx_restore -c "\\copy (select * from $t where $(where $t "$D")) to '$WORK/$t.copy'" )
        echo "\\copy $t from '$WORK/$t.copy'"
      done
      echo "commit;"; } > "$WORK/restore.sql"
    chown postgres "$WORK/restore.sql"
    pg -d fusionpbx -f "$WORK/restore.sql"
    rm -f /var/cache/fusionpbx/dialplan.* "/var/cache/fusionpbx/directory."*"@$NAME" /var/cache/fusionpbx/configuration.ivr.conf.*
    echo "the engine's rows of the domain now:"; checksum fusionpbx "$D" ;;
  *) echo "usage: restore_domain.sh checksum <domain> | restore <dump> <domain>" >&2; exit 2 ;;
esac
