#!/usr/bin/env bash
# PhotonVox: the READ-ONLY part of the inventory that only the Proxmox host can answer (ARCHITECTURE §22 question 9: backups of the engine's
# container, what the stopped `kamailio` container was). Run on the Proxmox host as root, only with Connor's go-ahead for that run:
#     bash host.sh 600 601 > host-inventory.txt
# Reads configuration and lists backup files; changes nothing. Prints no addresses or passwords.
set -uo pipefail
export LC_ALL=C
ENGINE=${1:-600}
OTHER=${2:-601}
section() { printf '\n== %s\n' "$*"; }
note() { printf '   %s\n' "$*"; }
[ "$(id -u)" = 0 ] && command -v pct >/dev/null || { echo "run as root on the Proxmox host" >&2; exit 2; }

section "1. Proxmox"
note "version: $(pveversion 2>/dev/null | head -1)"
note "cluster nodes: $(pvecm nodes 2>/dev/null | awk 'NR > 4 && NF { n++ } END { print n + 0 }')"

section "2. the engine container ($ENGINE)"
note "status: $(pct status "$ENGINE" 2>/dev/null | awk '{print $2}')"
pct config "$ENGINE" 2>/dev/null | awk -F': ' '$1 ~ /^(hostname|ostype|cores|memory|swap|onboot|unprivileged|protection)$/ { printf "   %s: %s\n", $1, $2 }'
pct config "$ENGINE" 2>/dev/null | awk -F': ' '$1 ~ /^(rootfs|mp[0-9]+)$/ { n = split($2, a, ","); size = ""; for (i = 1; i <= n; i++) if (a[i] ~ /^size=/) size = a[i]; split(a[1], st, ":"); printf "   %s: storage %s %s\n", $1, st[1], size }'
pct config "$ENGINE" 2>/dev/null | awk -F': ' '$1 ~ /^net[0-9]+$/ { n = split($2, a, ","); out = ""; for (i = 1; i <= n; i++) if (a[i] ~ /^(bridge|firewall|tag)=/) out = out " " a[i]; printf "   %s:%s\n", $1, out }'
note "Proxmox firewall service: $(pve-firewall status 2>/dev/null | head -1)"

section "3. backup jobs that include the engine"
if [ -r /etc/pve/jobs.cfg ]; then
  awk -v id="$ENGINE" '
    /^vzdump:/ { if (job != "") flush(); job = $2; inc = 0; all = 0; sched = ""; store = ""; keep = ""; mode = ""; next }
    /^[[:space:]]+vmid / { n = split($2, v, ","); for (i = 1; i <= n; i++) if (v[i] == id) inc = 1 }
    /^[[:space:]]+all 1/ { all = 1 }
    /^[[:space:]]+schedule / { $1 = ""; sched = $0 }
    /^[[:space:]]+storage / { store = $2 }
    /^[[:space:]]+prune-backups / { keep = $2 }
    /^[[:space:]]+mode / { mode = $2 }
    /^[[:space:]]+enabled 0/ { disabled = 1 }
    function flush() { if (inc || all) printf "   job %s: schedule%s, storage %s, mode %s, keep %s%s\n", job, sched, store, mode, keep, (disabled ? " (DISABLED)" : ""); disabled = 0 }
    END { if (job != "") flush() }' /etc/pve/jobs.cfg
else
  note "(no /etc/pve/jobs.cfg)"
fi
grep -lE "vzdump.*\b$ENGINE\b" /etc/cron.d/* 2>/dev/null | sed 's/^/   cron file: /'
section "4. the newest backups of the engine (name and size; each storage that holds backups)"
for st in $(pvesm status --content backup 2>/dev/null | awk 'NR > 1 { print $1 }'); do
  pvesm list "$st" --vmid "$ENGINE" 2>/dev/null | awk -v st="$st" 'NR > 1 { printf "   %s: %s %.1f GB\n", st, $1, $4 / 1e9 }' | tail -3
done

section "5. the other container ($OTHER)"
note "status: $(pct status "$OTHER" 2>/dev/null | awk '{print $2}')"
pct config "$OTHER" 2>/dev/null | awk -F': ' '$1 ~ /^(hostname|ostype|onboot)$/ { printf "   %s: %s\n", $1, $2 }'
pct config "$OTHER" 2>/dev/null | grep -q '^description:' && note "description: (present; Connor reads it: it may say what the container was for)"

printf '\nDone. Nothing was changed. Read the report before sending it on.\n'
