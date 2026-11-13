#!/usr/bin/env bash
# PhotonVox: a READ-ONLY inventory of a FusionPBX engine (BUILD-GUIDE Step 0.2; answers ARCHITECTURE §22 question 9).
#
# Run INSIDE the FusionPBX container, as root, only with Connor's go-ahead for that run. From the Proxmox host:
#     pct exec 600 -- bash -s < engine.sh > engine-inventory.txt
# It writes nothing anywhere (no files, no settings, no packages), reads the database in a read-only transaction with a statement timeout, and
# runs only FreeSWITCH status commands. The report holds counts and categories, plus domain names and the names carriers' gateways have in
# FusionPBX. It never prints people's names, phone numbers, MAC addresses, IP addresses, usernames or passwords. Read it before sending it on.
set -uo pipefail
umask 077
export LC_ALL=C

section() { printf '\n== %s\n' "$*"; }
note() { printf '   %s\n' "$*"; }


# ---- parsers of FreeSWITCH's status output (tests/test_parsers.sh feeds them samples) --------------------------------------------------------
# Registrations ("sofia status profile internal reg"): counts by domain, phone model (the first two words of the user agent), transport,
# private or public source address, and reachability. Never the users, addresses or full user agents.
parse_registrations() {
  awk '
    function is_private(ip) { return ip ~ /^10\./ || ip ~ /^192\.168\./ || ip ~ /^172\.(1[6-9]|2[0-9]|3[01])\./ || ip ~ /^127\./ || ip ~ /^100\.(6[4-9]|[7-9][0-9]|1[01][0-9]|12[0-7])\./ }
    /^User:/   { n++; split($2, u, "@"); dom[u[2]]++ }
    /^Agent:/  { $1 = ""; sub(/^ +/, ""); split($0, w, " "); agent[w[1] " " w[2]]++ }
    /^Status:/ { if (match($0, /\((UDP|TCP|TLS|WSS|WS)\)/)) tr[substr($0, RSTART + 1, RLENGTH - 2)]++; else tr["?"]++ }
    /^IP:/     { if (is_private($2)) priv++; else pub++ }
    /^Ping-Status:/ { ping[$2]++ }
    END {
      printf "   registrations: %d\n", n
      for (d in dom) printf "   domain %s: %d\n", d, dom[d]
      for (k in agent) printf "   agent %s: %d\n", k, agent[k]
      for (t in tr) printf "   transport %s: %d\n", t, tr[t]
      printf "   from a private address (behind NAT or on a LAN/overlay): %d; from a public address: %d\n", priv, pub
      for (p in ping) printf "   ping %s: %d\n", p, ping[p]
    }'
}

# Gateways ("sofia status gateway"): FusionPBX names gateways by uuid; $1 maps uuid -> name ("uuid | name" lines). Prints name and state only
# (the data column holds the trunk's username and host).
parse_gateways() {
  GW_MAP="$1" awk '
    BEGIN { n = split(ENVIRON["GW_MAP"], lines, "\n"); for (i = 1; i <= n; i++) { if (split(lines[i], f, / \| /) == 2) name[f[1]] = f[2] } }
    $1 ~ /::/ && $1 !~ /Gateway-Name/ { split($1, p, "::"); g = p[2]; printf "   %s: %s\n", (g in name ? name[g] : "(unknown gateway)"), $3 }'
}

[ "${INVENTORY_PARSERS_ONLY:-}" = 1 ] && return 0 2>/dev/null

[ "$(id -u)" = 0 ] || { echo "run as root inside the FusionPBX container" >&2; exit 2; }
CONF=/etc/fusionpbx/config.conf
[ -r "$CONF" ] || { echo "no $CONF here: is this a FusionPBX 5 container?" >&2; exit 2; }

# ---- the database, read-only ---------------------------------------------------------------------------------------------------------------
conf() { sed -n "s/^[[:space:]]*database\.0\.$1[[:space:]]*=[[:space:]]*//p" "$CONF" | head -1 | tr -d '\r'; }
export PGHOST="$(conf host)" PGPORT="$(conf port)" PGDATABASE="$(conf name)" PGUSER="$(conf username)"
PGPASSWORD="$(conf password)"; export PGPASSWORD                         # never printed
export PGOPTIONS='-c default_transaction_read_only=on -c statement_timeout=20000'
: "${PGHOST:=127.0.0.1}" "${PGPORT:=5432}" "${PGDATABASE:=fusionpbx}" "${PGUSER:=fusionpbx}"

sql() { psql -X -q -A -t -F ' | ' -v ON_ERROR_STOP=1 -c "$1" 2>/dev/null; }
has() { [ "$(sql "select to_regclass('public.$1') is not null")" = t ]; }
col() { [ "$(sql "select count(*) from information_schema.columns where table_name = '$1' and column_name = '$2'")" = 1 ]; }
# Rows of a query, indented; "(not available)" when a table or column of this version is missing.
rows() { local out; if out="$(sql "$1")"; then [ -n "$out" ] && printf '%s\n' "$out" | sed 's/^/   /' || note "(none)"; else note "(not available in this version)"; fi; }

sql "select 1" >/dev/null || { echo "cannot read the FusionPBX database with the credentials in $CONF" >&2; exit 2; }

fs() { command -v fs_cli >/dev/null && fs_cli -x "$1" 2>/dev/null; }

# ---- 1. versions ---------------------------------------------------------------------------------------------------------------------------
section "1. versions"
note "debian: $(cat /etc/debian_version 2>/dev/null || echo unknown)"
# software::version() is in core/software/ on current FusionPBX (5.7 on master, checked 2026-11-13) and in resources/classes/ on older releases.
note "fusionpbx: $(grep -hoE "return '[0-9]+\.[0-9]+\.[0-9]+'" /var/www/fusionpbx/core/software/resources/classes/software.php /var/www/fusionpbx/resources/classes/software.php 2>/dev/null | head -1 | tr -dc '0-9.' || echo unknown)"
[ -d /var/www/fusionpbx/.git ] && note "fusionpbx git: $(git -C /var/www/fusionpbx log -1 --format='%h %cs' 2>/dev/null) on $(git -C /var/www/fusionpbx rev-parse --abbrev-ref HEAD 2>/dev/null)"
note "freeswitch: $(fs version | head -1 | sed 's/^FreeSWITCH Version //')"
note "postgres: $(sql "show server_version")"
note "install method: $(ls -d /usr/src/fusionpbx-install.sh 2>/dev/null >/dev/null && echo 'fusionpbx-install.sh found in /usr/src' || echo 'install script not found in /usr/src')"

# ---- 2. domains and what each holds --------------------------------------------------------------------------------------------------------
section "2. domains (enabled), with counts per table"
rows "select domain_name, domain_enabled from v_domains order by domain_name"
per_domain() {   # table, label, optional extra where
  local t=$1 label=$2 where=${3:-true}
  has "$t" || { note "$label: (no table $t)"; return; }
  note "$label:"
  rows "select d.domain_name, count(x.*) from v_domains d left join $t x on x.domain_uuid = d.domain_uuid and ($where) group by 1 order by 1"
}
per_domain v_extensions "extensions"
per_domain v_extensions "extensions enabled" "x.enabled = 'true'"
per_domain v_devices "devices (provisioned phones)"
per_domain v_destinations "inbound destinations (numbers)" "x.destination_type = 'inbound'"
per_domain v_ring_groups "ring groups"
per_domain v_ivr_menus "IVR menus"
per_domain v_call_center_queues "call center queues"
per_domain v_voicemails "voicemail boxes"
per_domain v_conference_centers "conference centers"
per_domain v_fax "fax servers"

# ---- 3. phones --------------------------------------------------------------------------------------------------------------------------------
section "3. provisioned devices by vendor and template (count, enabled)"
rows "select coalesce(device_vendor, '?'), coalesce(device_template, '?'), count(*), sum(case when device_enabled = 'true' then 1 else 0 end) from v_devices group by 1, 2 order by 3 desc"

section "4. live registrations (internal profile)"
REG="$(fs 'sofia status profile internal reg')"
if [ -n "$REG" ]; then
  printf '%s\n' "$REG" | parse_registrations
else
  note "(fs_cli did not answer)"
fi

# ---- 5. carriers ------------------------------------------------------------------------------------------------------------------------------
section "5. gateways (name, enabled, registers, profile, owning domain) and their live state"
rows "select g.gateway, g.enabled, g.register, g.profile, coalesce(d.domain_name, '(global)') from v_gateways g left join v_domains d on d.domain_uuid = g.domain_uuid order by 1"
if GWS="$(fs 'sofia status gateway')"; then
  MAP="$(sql "select gateway_uuid, gateway from v_gateways")"
  printf '%s\n' "$GWS" | parse_gateways "$MAP"
fi
note "calls through each gateway, last 30 days (outbound by bridge string):"
rows "select g.gateway, count(c.*) from v_gateways g left join v_xml_cdr c on c.last_arg like 'sofia/gateway/' || g.gateway_uuid || '/%' and c.start_stamp > now() - interval '30 days' group by 1 order by 1"

# ---- 6. routing ---------------------------------------------------------------------------------------------------------------------------------
section "6. dial plans by FusionPBX app and context (count, enabled)"
note "app uuids (from FusionPBX's app_config.php, checked 2026-11-13): 8c914ec3… outbound routes, c03b422e… inbound routes, 4b821450… time conditions"
rows "select coalesce(app_uuid::text, '(none)'), dialplan_context, count(*), sum(case when dialplan_enabled = 'true' then 1 else 0 end) from v_dialplans group by 1, 2 order by 3 desc limit 40"
section "7. inbound numbers whose destination has no matching dial plan (calls to them drop)"
rows "select d.domain_name, count(*) from v_destinations x join v_domains d on d.domain_uuid = x.domain_uuid where x.destination_type = 'inbound' and (x.dialplan_uuid is null or not exists (select 1 from v_dialplans p where p.dialplan_uuid = x.dialplan_uuid)) group by 1 order by 1"

# ---- 8. settings that matter (values only where they are not secret) --------------------------------------------------------------------------
section "8. settings (global; values shown only for non-secret settings)"
SAFE="'enabled','http_auth_enabled','dialplan_mode','method','smtp_secure','smtp_auth','smtp_port','record_extension','voicemail_to_email','keep_local'"
rows "select default_setting_category, default_setting_subcategory, default_setting_enabled, case when default_setting_subcategory in ($SAFE) then coalesce(default_setting_value, '') when coalesce(default_setting_value, '') = '' then '(empty)' else '(set)' end from v_default_settings where default_setting_category in ('provision', 'destinations', 'email', 'voicemail', 'recordings') order by 1, 2"
note "domain-level overrides of those categories, per domain:"
rows "select d.domain_name, s.domain_setting_category, count(*) from v_domain_settings s join v_domains d on d.domain_uuid = s.domain_uuid where s.domain_setting_category in ('provision', 'destinations', 'email', 'voicemail', 'recordings') group by 1, 2 order by 1, 2"

# ---- 9. toll-fraud exposure (counts only) -----------------------------------------------------------------------------------------------------
section "9. toll-fraud exposure, per domain"
note "extensions with a SIP password shorter than 16 characters:"
rows "select d.domain_name, count(*) from v_extensions e join v_domains d on d.domain_uuid = e.domain_uuid where length(coalesce(e.password, '')) < 16 group by 1 order by 1"
note "extensions with no toll_allow set (FusionPBX's call class field), and with call forwarding switched on:"
rows "select d.domain_name, sum(case when coalesce(e.toll_allow, '') = '' then 1 else 0 end), sum(case when e.forward_all_enabled = 'true' then 1 else 0 end) from v_extensions e join v_domains d on d.domain_uuid = e.domain_uuid group by 1 order by 1"
note "voicemail boxes whose PIN is the box number, or shorter than 6 digits:"
rows "select d.domain_name, sum(case when v.voicemail_password = v.voicemail_id then 1 else 0 end), sum(case when length(coalesce(v.voicemail_password, '')) < 6 then 1 else 0 end) from v_voicemails v join v_domains d on d.domain_uuid = v.domain_uuid group by 1 order by 1"
note "voicemail boxes that send voicemail by email:"
rows "select d.domain_name, count(*) from v_voicemails v join v_domains d on d.domain_uuid = v.domain_uuid where coalesce(v.voicemail_mail_to, '') <> '' group by 1 order by 1"
note "outbound calls to international numbers (011…), last 90 days:"
rows "select d.domain_name, count(*) from v_xml_cdr c join v_domains d on d.domain_uuid = c.domain_uuid where c.direction = 'outbound' and c.destination_number like '011%' and c.start_stamp > now() - interval '90 days' group by 1 order by 1"

# ---- 10. call volume and recording ------------------------------------------------------------------------------------------------------------
section "10. calls in the last 30 days, per domain and direction (count, answered, answered minutes)"
rows "select d.domain_name, c.direction, count(*), sum(case when c.billsec > 0 then 1 else 0 end), round(sum(c.billsec) / 60.0) from v_xml_cdr c join v_domains d on d.domain_uuid = c.domain_uuid where c.start_stamp > now() - interval '30 days' group by 1, 2 order by 1, 2"
if col v_xml_cdr record_name; then
  note "recorded calls, last 30 days:"
  rows "select d.domain_name, count(*) from v_xml_cdr c join v_domains d on d.domain_uuid = c.domain_uuid where coalesce(c.record_name, '') <> '' and c.start_stamp > now() - interval '30 days' group by 1 order by 1"
fi

# ---- 11. the network edge -----------------------------------------------------------------------------------------------------------------------
section "11. SIP profiles and listening ports"
fs 'sofia status' | awk '$2 == "profile" { printf "   profile %s: %s\n", $1, $NF }'
ss -ltnup 2>/dev/null | awk 'NR > 1 { n = split($5, a, ":"); p = a[n]; split($7, q, "\""); print "   listening " $1 " " p " (" q[2] ")" }' | sort -u
section "12. NAT settings in vars.xml (kind only)"
for v in external_rtp_ip external_sip_ip; do
  val="$(grep -oE "data=\"$v=[^\"]*\"" /etc/freeswitch/vars.xml 2>/dev/null | head -1 | sed "s/.*$v=//; s/\"$//")"
  case "$val" in
    stun:*) kind="STUN" ;; autonat:*) kind="autonat" ;; '$${local_ip_v4}'*) kind="the local address" ;; "") kind="not set" ;; *) kind="an explicit address" ;;
  esac
  note "$v: $kind"
done

# ---- 13. protection and housekeeping --------------------------------------------------------------------------------------------------------
section "13. protection"
for s in fail2ban event_guard nginx; do note "$s: $(systemctl is-active "$s" 2>/dev/null || echo absent)"; done
note "iptables INPUT policy: $(iptables -S INPUT 2>/dev/null | awk '/^-P INPUT/ {print $3}') ; INPUT rules: $(iptables -S INPUT 2>/dev/null | grep -c '^-A' )"
note "nftables rules: $(nft list ruleset 2>/dev/null | grep -c . )"
section "14. storage"
for d in /var/lib/freeswitch/storage /var/lib/freeswitch/recordings /var/backups/fusionpbx; do
  [ -d "$d" ] && note "$d: $(du -sh "$d" 2>/dev/null | cut -f1)"
done
note "root filesystem: $(df -h / | awk 'NR == 2 { print $2 " size, " $5 " used" }')"
section "15. backup jobs inside the container (file names only)"
grep -rlE 'pg_dump|fusionpbx-backup|backup' /etc/cron* /var/spool/cron 2>/dev/null | sed 's/^/   /' || note "(none found)"

printf '\nDone. Nothing was changed. Read the report before sending it on.\n'
