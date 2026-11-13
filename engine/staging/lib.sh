# Shared by the staging call proofs (prove-publish.sh, build-test.sh): source it after setting DOMAIN, PHONES ("<extension>:<port> ..."), and a
# function pw <extension> that prints that extension's SIP password. Calls come from SIPp on LXC 800 (scripts/sipp.sh); the upstream answers
# on 10.10.0.80:5071.
SIPP=scripts/sipp.sh
PY="${PHOTONVOX_VENV:-$HOME/.venvs/photonvox}/bin/python"
S() { ssh -i ~/.ssh/vox_staging root@10.10.0.60 "$@"; }
q() { S "sudo -u postgres psql -d fusionpbx -qtAX -c \"$1\""; }
invites() { $SIPP log "$1" | grep -c '^INVITE '; }
pass=0; fail=0
check() { if [ "$2" = "$3" ]; then echo "ok    $1"; pass=$((pass+1)); else echo "FAIL  $1 (got $2, wanted $3)"; fail=$((fail+1)); fi; }

fresh() {   # restart the answering phones and the upstream, so each check counts only its own INVITEs
  local p
  for p in $PHONES; do $SIPP stop ph${p%:*}; done
  $SIPP stop up
  for p in $PHONES; do $SIPP start ph${p%:*} -sf /scenarios/phone-answer.xml -i 10.10.0.80 -p ${p#*:} -mi 10.10.0.80; done
  $SIPP start up -sf /scenarios/upstream-uas.xml -i 10.10.0.80 -p 5071 -mi 10.10.0.80
  sleep 1
}
out() {     # <name> <extension> <digits>: SIPp's exit code (0 = answered)
  $SIPP run "$1" -sf /scenarios/call.xml -s "$3" -set from "$2" -set domain $DOMAIN -au "$2" -ap "$(pw $2)" -i 10.10.0.80 -p 5094 \
    -m 1 -d 1000 -timeout 15s 10.10.0.60:5060 > /dev/null 2>&1; local rc=$?; sleep 1; echo $rc     # SIPp's message log is buffered
}
inbound() { # <name> <number as sent> <scenario> [args]
  local name=${1//+/p} num=$2 sf=$3; shift 3
  $SIPP run "$name" -sf /scenarios/$sf -s "$num" -set from 3105550199 -set domain 10.10.0.60 -i 10.10.0.80 -p 5096 -m 1 -timeout 25s "$@" \
    10.10.0.60:5080 > /dev/null 2>&1; local rc=$?; sleep 1; echo $rc
}
register() { $SIPP stop ph$1; $SIPP run reg$1 -sf /scenarios/phone-register.xml -s $1 -au $1 -ap "$(pw $1)" -set domain $DOMAIN -i 10.10.0.80 -p $2 \
    -m 1 -timeout 10s 10.10.0.60:5060 > /dev/null 2>&1; echo $?; }
acl_off() { # phones and the upstream share LXC 800's address; FusionPBX applies the providers list on the internal profile too (SPIKES §1c)
  q "delete from v_access_control_nodes where node_cidr = '10.10.0.80/32'" > /dev/null
  S "rm -f /var/cache/fusionpbx/configuration.acl.conf; fs_cli -x reloadacl > /dev/null; fs_cli -x 'acl 10.10.0.80 providers'"
}
