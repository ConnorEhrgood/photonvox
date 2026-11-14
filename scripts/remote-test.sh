#!/usr/bin/env bash
# Run the backend suite on LXC 800 (Docker lives there, not on the runner).
#   scripts/remote-test.sh [pytest args]            e.g. scripts/remote-test.sh tests/api/test_rls.py -x
#   COVERAGE=1 scripts/remote-test.sh               with a branch-coverage report and the critical-module check
# Uses its own folder (/root/vox-test/suite) and its own Compose project (photonvox-test), and takes everything down afterwards (containers, the
# throwaway database, the network). LXC 800 is shared and short of disk: this never prunes Docker globally; the test image is kept so the next
# run is quick (remove it with `docker image rm photonvox-test-tests` when done for a while).
set -euo pipefail
cd "$(dirname "$0")/.."
HOST=${VOX_TEST_SSH:-lxc800}
DIR=${VOX_TEST_DIR:-/root/vox-test/suite}     # its own subfolder: /root/vox-test/sipp (scripts/sipp.sh) lives beside it
PROJECT=photonvox-test
ARGS="$(printf '%q ' "$@")"       # keeps quoting intact (-k "a or b") through the remote shell
if [ "${COVERAGE:-}" = 1 ]; then PYTEST="sh -c 'pytest --cov=app --cov-branch --cov-report=term-missing:skip-covered --cov-report=json:/tmp/cov.json $ARGS && python tests/check_critical.py /tmp/cov.json'"; else PYTEST="pytest $ARGS"; fi

TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
tar --exclude='.venv' --exclude='__pycache__' --exclude='.pytest_cache' --exclude='.coverage' --exclude='.env' -czf "$TMP/vox-test.tgz" api contract docker-compose.test.yml
# The staging build test's connection details travel in a file only root can read, removed after the run (never on a command line).
if [ "${VOX_STAGING_E2E:-}" = 1 ]; then
  # Shell-quoted (%q): the file is sourced over there, and a value may hold "|", "$" or spaces (the retire list does).
  (umask 077; for v in VOX_STAGING_E2E VOX_STAGING_DB_URL VOX_STAGING_AGENT_URL VOX_STAGING_AGENT_SECRET VOX_STAGING_TAKEOVER VOX_STAGING_DOMAIN \
                       VOX_STAGING_GATEWAY VOX_STAGING_RW_URL VOX_STAGING_PROTECT VOX_STAGING_RETIRE VOX_STAGING_UNDO; do
     printf '%s=%q\n' "$v" "${!v:-}"; done > "$TMP/staging.env")
fi
cat > "$TMP/run.sh" <<RUN
#!/bin/bash
cd $DIR
rm -f run.done run.out
if [ -f staging.env ]; then set -a; . ./staging.env; set +a; rm -f staging.env; fi
if docker compose -p $PROJECT -f docker-compose.test.yml build --quiet tests > build.out 2>&1; then
  docker compose -p $PROJECT -f docker-compose.test.yml run --rm tests $PYTEST > run.out 2>&1
else
  cp build.out run.out; false
fi
echo \$? > run.done
docker compose -p $PROJECT -f docker-compose.test.yml down -v --remove-orphans > /dev/null 2>&1
RUN
scp -q "$TMP/vox-test.tgz" "$HOST":/tmp/$PROJECT.tgz
scp -q "$TMP/run.sh" "$HOST":/tmp/$PROJECT-run.sh
[ -f "$TMP/staging.env" ] && scp -q -p "$TMP/staging.env" "$HOST":/tmp/$PROJECT-staging.env
ssh "$HOST" "rm -rf $DIR && mkdir -p $DIR && tar -xzf /tmp/$PROJECT.tgz -C $DIR && rm -f /tmp/$PROJECT.tgz && mv /tmp/$PROJECT-run.sh $DIR/run.sh && { [ ! -f /tmp/$PROJECT-staging.env ] || mv /tmp/$PROJECT-staging.env $DIR/staging.env; } && systemd-run --unit=$PROJECT-\$(date +%s) --collect bash $DIR/run.sh" > /dev/null
for _ in $(seq 1 240); do
  sleep 5
  if ssh "$HOST" test -f $DIR/run.done 2>/dev/null; then
    ssh "$HOST" cat $DIR/run.out
    exit "$(ssh "$HOST" cat $DIR/run.done)"
  fi
done
echo "timed out waiting for tests" >&2
exit 1
