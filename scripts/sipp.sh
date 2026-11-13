#!/usr/bin/env bash
# SIPp on LXC 800, for the engine tests against staging (BUILD-GUIDE Steps 0.6–0.7). Everything lives in /root/vox-test/sipp there; every
# container is named vox-sipp-<name> (Call-IDs carry the name and the time: SIPp is always process 1 in its container), labeled com.photonvox.owner=photonvox-tests, and removed when it exits. Never prunes anything globally.
#   scripts/sipp.sh build                     sync sipp/ and build the image photonvox-sipp:3.6.1
#   scripts/sipp.sh start <name> <sipp args>  run in the background (the upstream, an answering phone)
#   scripts/sipp.sh run <name> <sipp args>    run to the end and return SIPp's exit code (0 = every call succeeded)
#   scripts/sipp.sh log <name>                its message trace (-trace_msg writes to /logs/<name>.log)
#   scripts/sipp.sh stop <name> | clean       stop one | stop all of ours and remove the logs (clean --image also removes the image)
set -euo pipefail
HOST="${SIPP_HOST:-lxc800}"
DIR=/root/vox-test/sipp
IMAGE=photonvox-sipp:3.6.1
LABEL=com.photonvox.owner=photonvox-tests
cd "$(dirname "$0")/.."

docker_run() {  # <name> <detach flag> <sipp args...>
  local name="$1" detach="$2"; shift 2
  ssh "$HOST" "mkdir -p $DIR/logs && docker run $detach --rm --name vox-sipp-$name --label $LABEL --network host \
    -v $DIR/logs:/logs $IMAGE -nostdin -trace_msg -message_file /logs/$name.log -trace_err -error_file /logs/$name.err -cid_str %u-$name-\$(date +%s%N)@%s $(printf '%q ' "$@")"
}

case "${1:-}" in
  build) ssh "$HOST" "mkdir -p $DIR" && tar -C sipp -cf - . | ssh "$HOST" "tar -C $DIR -xf -" \
           && ssh "$HOST" "docker build -q -t $IMAGE --label $LABEL $DIR" ;;
  start) name="$2"; shift 2; ssh "$HOST" "rm -f $DIR/logs/$name.log $DIR/logs/$name.err"; docker_run "$name" -d "$@" > /dev/null ;;
  run)   name="$2"; shift 2; ssh "$HOST" "rm -f $DIR/logs/$name.log $DIR/logs/$name.err"; docker_run "$name" "" "$@" > /dev/null ;;
  log)   ssh "$HOST" "cat $DIR/logs/$2.log 2>/dev/null; cat $DIR/logs/$2.err 2>/dev/null" ;;
  stop)  ssh "$HOST" "docker stop vox-sipp-$2 >/dev/null 2>&1 || true" ;;
  clean) ssh "$HOST" "ids=\$(docker ps -aq --filter label=$LABEL --filter name=vox-sipp-); [ -z \"\$ids\" ] || docker rm -f \$ids >/dev/null; rm -rf $DIR/logs"
         [ "${2:-}" = --image ] && ssh "$HOST" "docker rmi $IMAGE >/dev/null 2>&1 || true; rm -rf $DIR" || true ;;
  *) sed -n 2,9p "$0"; exit 2 ;;
esac
