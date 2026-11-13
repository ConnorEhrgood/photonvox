#!/usr/bin/env bash
# Boot the whole stack (docker-compose.yml) on LXC 800 in a throwaway Compose project, check it from outside, and take everything away again:
# containers, the database volume, the network and the image it built. Never prunes Docker globally (LXC 800 is shared and short of disk).
#   scripts/smoke-stack.sh
# Passwords are made on LXC 800 for this run only and never printed. The stack runs as "development" (no directory to connect to yet).
set -euo pipefail
cd "$(dirname "$0")/.."
HOST=${VOX_TEST_SSH:-lxc800}
DIR=/root/vox-test-smoke
PROJECT=photonvox-smoke
PORT=18113
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
tar --exclude='__pycache__' --exclude='.pytest_cache' --exclude='.env' -czf "$TMP/smoke.tgz" api docker-compose.yml .env.example
scp -q "$TMP/smoke.tgz" "$HOST":/tmp/$PROJECT.tgz
ssh "$HOST" bash -s <<REMOTE
set -euo pipefail
rm -rf $DIR && mkdir -p $DIR && tar -xzf /tmp/$PROJECT.tgz -C $DIR && rm -f /tmp/$PROJECT.tgz && cd $DIR
umask 077
{ grep -v '^\(POSTGRES_PASSWORD\|APP_DB_PASSWORD\|SYSTEM_DB_PASSWORD\|OIDC_AUDIENCE\)=' .env.example
  echo "POSTGRES_PASSWORD=\$(openssl rand -hex 24)"; echo "APP_DB_PASSWORD=\$(openssl rand -hex 24)"; echo "SYSTEM_DB_PASSWORD=\$(openssl rand -hex 24)"
  echo "OIDC_AUDIENCE=smoke"; echo "ENVIRONMENT=development"; echo "API_PORT=$PORT"; echo "DIRECTORY_URL="; echo "DB_HOST=$PROJECT-db-1"; } > .env
cleanup() { docker compose -p $PROJECT down -v --remove-orphans >/dev/null 2>&1 || true; docker image rm photonvox-api:dev >/dev/null 2>&1 || true; rm -rf $DIR; }
trap cleanup EXIT
docker compose -p $PROJECT up -d --build --quiet-pull >build.log 2>&1 || { tail -30 build.log; exit 1; }
ok=0
for i in \$(seq 1 60); do
  if curl -fsS http://127.0.0.1:$PORT/healthz >/dev/null 2>&1 && curl -fsS http://127.0.0.1:$PORT/readyz >/dev/null 2>&1; then ok=1; break; fi
  sleep 2
done
echo "healthz: \$(curl -sS http://127.0.0.1:$PORT/healthz)"
echo "readyz:  \$(curl -sS http://127.0.0.1:$PORT/readyz)"
echo "me without a token: \$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:$PORT/me)"
echo "migration: \$(docker compose -p $PROJECT ps -a --format '{{.Service}} {{.State}} {{.ExitCode}}' | grep '^migrate')"
sleep 35
docker compose -p $PROJECT ps --format '{{.Service}} {{.State}} {{.Health}}'
echo "api user: \$(docker compose -p $PROJECT exec -T api id -u)  read-only root: \$(docker compose -p $PROJECT exec -T api sh -c 'touch /app/x 2>&1 || true' | grep -c 'Read-only')"
[ \$ok = 1 ] || { docker compose -p $PROJECT logs --tail 40 api; exit 1; }
REMOTE
