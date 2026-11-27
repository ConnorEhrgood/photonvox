#!/usr/bin/env bash
# The demo's live simulator (docs/DEMO.md §2; sim/): the demo's phones registered on the staging engine (CT 610) and a business's calls placed
# among them in real time, from LXC 800. The compose project vox-demo-sim in /root/vox-demo-sim there (half a CPU and 256 MB in all, everything
# labeled com.photonvox.owner=vox-demo-sim; nothing global is ever pruned). Only ever the demo's domain on the staging engine: no customer, no
# live engine, no carrier, no emergency number. The demo must be seeded first (`manage demo seed`, scripts/dev-stack.sh).
#   scripts/demo-sim.sh up       ship sim/, build the image, write the phones' credentials (from the engine straight to a mode-600 file on
#                                LXC 800, never printed), install the engine's route to the phones' network and its voicemail tidy timer, start
#   scripts/demo-sim.sh reset    the demo's history made again: 35 days back-filled (sim/backfill.py) and its voicemail boxes emptied
#   scripts/demo-sim.sh status | logs [carrier|phones]
#   scripts/demo-sim.sh down     stop it (the project's containers and network; the image and the engine's route and timer stay)
#   scripts/demo-sim.sh remove   down, and the image, the directory, and the route and timer on the engine: nothing of it left
set -euo pipefail
cd "$(dirname "$0")/.."
HOST=lxc800 DIR=/root/vox-demo-sim DOMAIN=demo.vox.test ENGINE=10.10.0.60 NET=172.31.61.0/29
C="cd $DIR && docker compose"
PY="${PHOTONVOX_VENV:-$HOME/.venvs/photonvox}/bin/python"
S() { ssh -i ~/.ssh/vox_staging root@$ENGINE "$@"; }
PSQL="cd /tmp && runuser -u postgres -- psql -d fusionpbx -qtAX -v ON_ERROR_STOP=1"
UNITS="vox-demo-sim-route.service vox-demo-voicemail-tidy.service vox-demo-voicemail-tidy.timer"

case "${1:-}" in
  up)
    [ "$(S "$PSQL -c \"select count(*) from v_domains where domain_name = '$DOMAIN'\"")" = 1 ] || { echo "the demo is not on the engine: seed it first" >&2; exit 1; }
    ssh $HOST "mkdir -p -m 700 $DIR/config && cd $DIR && rm -f *.py Dockerfile docker-compose.yml"
    { tar -C sim -cf - Dockerfile .dockerignore docker-compose.yml scheduler.py scenarios.py traffic.py; } | ssh $HOST "tar -C $DIR -xf -"
    scp -q sipp/scenarios/tone-ulaw.wav $HOST:$DIR/tone-ulaw.wav
    echo "{\"engine\": \"$ENGINE\", \"domain\": \"$DOMAIN\", \"address\": \"10.10.0.80\", \"answer_port\": 5200, \"carrier_port\": 5071}" \
      | ssh $HOST "cat > $DIR/config/sim.json"
    # Every phone but the conference room's (110 stays offline: a real system always has one). A line a phone, as SIPp reads it.
    S "$PSQL -c \"select e.extension || ';[authentication username=' || e.extension || ' password=' || e.password || ']' from v_extensions e
         join v_domains d using (domain_uuid) where d.domain_name = '$DOMAIN' and e.extension <> '110' order by 1\"" \
      | ssh $HOST "umask 077; { echo SEQUENTIAL; cat; } > $DIR/config/phones.csv
          echo \"phones: \$(grep -c ';' $DIR/config/phones.csv), lines SIPp could not read: \$(grep -c -v -E '^(SEQUENTIAL|[0-9]+;\[authentication username=[0-9]+ password=[^] ;]+\])\$' $DIR/config/phones.csv)\""
    tar -C engine/staging/demo -cf - . | S "tar -C /tmp -xf - --no-same-owner && install -m 755 /tmp/vox-demo-voicemail-tidy /usr/local/sbin/ \
      && for u in $UNITS; do install -m 644 /tmp/\$u /etc/systemd/system/; done; cd /tmp && rm -f vox-demo-voicemail-tidy $UNITS \
      && systemctl daemon-reload && systemctl enable -q --now vox-demo-sim-route.service vox-demo-voicemail-tidy.timer && ip route show $NET"
    ssh $HOST "$C up -d --build --remove-orphans" 2>&1 | grep -vE "^ *(#|=>)" | tail -6
    ssh $HOST "$C ps --format '{{.Name}} {{.Status}}'" ;;
  reset)
    "$PY" sim/backfill.py --days "${2:-35}" | S "$PSQL"
    S "/usr/local/sbin/vox-demo-voicemail-tidy clear" ;;
  status)
    ssh $HOST "$C ps --format '{{.Name}} {{.Status}}'; docker stats --no-stream --format '{{.Name}} {{.CPUPerc}} {{.MemUsage}}' \$(docker ps -q --filter label=com.photonvox.owner=vox-demo-sim)"
    S "echo \"route: \$(ip route show $NET)\"; echo \"tidy timer: \$(systemctl is-active vox-demo-voicemail-tidy.timer)\"
       echo \"phones registered: \$(fs_cli -x 'show registrations' | grep -c ',$DOMAIN,')\"; echo \"calls now: \$(fs_cli -x 'show calls count')\"
       $PSQL -c \"select 'voicemails: ' || count(*) || ' (' || count(*) filter (where coalesce(m.message_status, '') <> 'saved') || ' unheard)' from v_voicemail_messages m join v_domains d using (domain_uuid) where d.domain_name = '$DOMAIN'\"
       $PSQL -c \"select 'call records: ' || count(*) || ', ' || count(*) filter (where accountcode is distinct from 'photonvox-sim') || ' of them live calls' from v_xml_cdr where domain_name = '$DOMAIN'\"" ;;
  logs) ssh $HOST "$C logs --tail ${3:-40} ${2:-}" ;;
  down) ssh $HOST "[ ! -f $DIR/docker-compose.yml ] || ($C down --remove-orphans)" ;;
  remove)
    ssh $HOST "[ ! -f $DIR/docker-compose.yml ] || ($C down --remove-orphans); docker rmi photonvox-demo-sim:1 >/dev/null 2>&1 || true; rm -rf $DIR"
    S "systemctl disable -q --now vox-demo-voicemail-tidy.timer vox-demo-sim-route.service 2>/dev/null || true
       cd /etc/systemd/system && rm -f $UNITS /usr/local/sbin/vox-demo-voicemail-tidy && systemctl daemon-reload" ;;
  *) sed -n 2,13p "$0"; exit 2 ;;
esac
