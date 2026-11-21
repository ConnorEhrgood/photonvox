#!/usr/bin/env bash
# A rehearsal of the first production deploy (docs/DEPLOY.md) on LXC 800, with nothing of production: the stack with docker-compose.prod.yml, a
# stand-in for the shared proxy (Caddy with the same `secure` snippet, `import sites/*.caddy`, a site of another product, and local certificates),
# the proxy joined to vox-edge with `docker network connect` and reloaded gracefully, then the checks, the backup's dump line, and everything removed.
#   scripts/rehearse-deploy.sh            (KEEP=1 leaves it running for a look; run it again without KEEP to remove it)
# LXC 800 is shared: its own folder, names and labels; no global prune; the images it built are removed at the end.
set -uo pipefail
cd "$(dirname "$0")/.."
HOST=${VOX_TEST_SSH:-lxc800}
DIR=/root/vox-test/rehearsal
# Never production (audit VOX-B-15): this removes a compose project and its volumes on the host it is given.
case "$HOST" in prod|*144.202.2.169*) echo "refused: $HOST is production" >&2; exit 1;; esac
ssh "$HOST" 'test ! -e /opt/photon' || { echo "refused: $HOST has /opt/photon (a production host), or did not answer" >&2; exit 1; }
TMP=$(mktemp -d); trap 'rm -rf "$TMP"' EXIT
tar --exclude=node_modules --exclude=coverage --exclude=screenshots --exclude=dist --exclude='.env' --exclude=__pycache__ --exclude=tests \
    -czf "$TMP/r.tgz" api web docker-compose.yml docker-compose.prod.yml deploy
ssh "$HOST" "rm -rf $DIR && mkdir -p $DIR" && scp -q "$TMP/r.tgz" "$HOST:$DIR/" || exit 1

ssh "$HOST" "KEEP=${KEEP:-} bash -s" <<'REMOTE'
set -uo pipefail
cd /root/vox-test/rehearsal && tar -xzf r.tgz && rm r.tgz
pass=0; fail=0
check() { if [ "$2" = "$3" ]; then echo "ok    $1"; pass=$((pass+1)); else echo "FAIL  $1 (got $2, wanted $3)"; fail=$((fail+1)); fi; }
# Its own project name, never production's (`photonvox`): a mistaken host still cannot take that stack down.
C="docker compose -p photonvox-rehearsal -f docker-compose.yml -f docker-compose.prod.yml"
P=vox-rehearsal-proxy
leftovers() {
  docker compose -p photonvox-rehearsal down -v --remove-orphans > /dev/null 2>&1     # by project label: works before .env exists
  docker rm -f $P > /dev/null 2>&1; docker network rm vox-edge vox-rehearsal-other > /dev/null 2>&1
}
cleanup() {
  leftovers
  docker image rm photonvox-api:dev photonvox-web:dev > /dev/null 2>&1
  cd / && rm -rf /root/vox-test/rehearsal
}
leftovers          # a run kept with KEEP=1
# Throwaway values: none of these reach anything real.
rnd() { openssl rand -hex 24; }
cat > .env <<ENV
POSTGRES_PASSWORD=$(rnd)
APP_DB_PASSWORD=$(rnd)
SYSTEM_DB_PASSWORD=$(rnd)
OIDC_ISSUER=https://id.rehearsal.test
OIDC_AUDIENCE=rehearsal
CORS_ORIGINS=https://vox.photonind.com
DIRECTORY_URL=https://api.account.rehearsal.test
DIRECTORY_CLIENT_ID=rehearsal
DIRECTORY_CLIENT_SECRET=$(rnd)
DIRECTORY_NOTICE_SECRET=$(rnd)
SECRETS_KEY=$(openssl rand 32 | base64 | tr '+/' '-_')
VITE_API_URL=https://api.vox.photonind.com
VITE_OIDC_ISSUER=https://id.photonind.com
VITE_OIDC_CLIENT_ID=rehearsal
VITE_OIDC_AUDIENCE_PROJECT=rehearsal
VITE_DIRECTORY_APP_URL=https://account.photonind.com
ENV
chmod 600 .env

echo "== the shared proxy's stand-in, already serving another product"
docker network create --label photon.rehearsal=vox vox-rehearsal-other > /dev/null
mkdir -p proxy/sites
cat > proxy/Caddyfile <<'CF'
{
	local_certs
}
(secure) {
	header {
		Strict-Transport-Security "max-age=31536000"
		X-Content-Type-Options nosniff
		Referrer-Policy no-referrer
		-Server
	}
}
import /etc/caddy/sites/*.caddy
CF
printf 'other.rehearsal.test {\n\trespond "other product" 200\n}\n' > proxy/sites/other.caddy
docker run -d --name $P --label photon.rehearsal=vox --network vox-rehearsal-other -p 127.0.0.1:18443:443 \
  -v "$PWD/proxy/Caddyfile:/etc/caddy/Caddyfile:ro" -v "$PWD/proxy/sites:/etc/caddy/sites:ro" caddy:2.11.7-alpine > /dev/null
sleep 2
get() { curl -sk -o /dev/null -w '%{http_code}' --resolve "$1:18443:127.0.0.1" "https://$1:18443$2"; }
check "the other product answers" "$(get other.rehearsal.test /)" 200
STARTED=$(docker inspect -f '{{.State.StartedAt}}' $P)

echo "== PhotonVox's stack (docker-compose.prod.yml)"
docker network create --label photon.product=vox vox-edge > /dev/null
if ! $C up -d --build --quiet-pull > up.out 2>&1; then tail -30 up.out; cleanup; exit 1; fi
for i in $(seq 1 30); do [ "$($C ps --format '{{.Health}}' api)" = healthy ] && [ "$($C ps --format '{{.Health}}' web)" = healthy ] && break; sleep 3; done
check "api healthy" "$($C ps --format '{{.Health}}' api)" healthy
check "web healthy" "$($C ps --format '{{.Health}}' web)" healthy
check "worker running" "$($C ps --format '{{.State}}' worker)" running
check "migrations ran" "$($C ps -a --format '{{.State}} {{.ExitCode}}' migrate)" "exited 0"
check "no host ports published" "$(docker ps --filter label=com.docker.compose.project=photonvox-rehearsal --format '{{.Ports}}' | grep -c '0.0.0.0\|127.0.0.1')" 0
check "vox-api and vox-web on vox-edge" "$(docker network inspect vox-edge -f '{{range .Containers}}{{.Name}} {{end}}' | tr ' ' '\n' | grep -c 'photonvox-rehearsal-\(api\|web\)-1')" 2

echo "== the proxy joins vox-edge and reloads (never recreated)"
docker network connect vox-edge $P
cp deploy/caddy/vox.caddy proxy/sites/vox.caddy
check "caddy validate" "$(docker exec $P caddy validate --config /etc/caddy/Caddyfile > validate.out 2>&1; echo $?)" 0
( for i in $(seq 1 20); do get other.rehearsal.test /; echo; sleep 0.25; done > during.out ) &
check "caddy reload" "$(docker exec $P caddy reload --config /etc/caddy/Caddyfile > reload.out 2>&1; echo $?)" 0
wait
check "the other product answered throughout the reload" "$(grep -vc '^200$' during.out)" 0
check "the proxy was not restarted" "$(docker inspect -f '{{.State.StartedAt}}' $P)" "$STARTED"
check "the proxy kept its other network" "$(docker inspect -f '{{range $k, $v := .NetworkSettings.Networks}}{{$k}} {{end}}' $P)" "vox-edge vox-rehearsal-other "
sleep 2
check "vox.photonind.com serves the web app" "$(get vox.photonind.com /)" 200
check "  with its Content-Security-Policy" "$(curl -skI --resolve vox.photonind.com:18443:127.0.0.1 https://vox.photonind.com:18443/ | grep -ci '^content-security-policy:.*connect-src .self. https://api.vox.photonind.com https://id.photonind.com')" 1
check "  a deep link goes to the app" "$(get vox.photonind.com /platform/instances)" 200
check "api.vox.photonind.com/healthz" "$(get api.vox.photonind.com /healthz)" 200
# (FastAPI reads a route's body before checking who is asking, so the proxy's limit is what stops it.)
check "  a 3 MB body is refused by the proxy" "$(head -c 3000000 /dev/zero | curl -sk -o /dev/null -w '%{http_code}' --resolve api.vox.photonind.com:18443:127.0.0.1 -X PUT -H 'Content-Type: application/json' --data-binary @- https://api.vox.photonind.com:18443/tenants/00000000-0000-4000-8000-000000000000/phone-system/draft)" 413
check "  the page may call the directory's API (the app switcher)" "$(curl -skI --resolve vox.photonind.com:18443:127.0.0.1 https://vox.photonind.com:18443/ | grep -ci '^content-security-policy:.*https://api.account.photonind.com')" 1
check "  the summary answers the dashboard's preflight" "$(curl -sk -o /dev/null -w '%{http_code}' --resolve api.vox.photonind.com:18443:127.0.0.1 -X OPTIONS -H 'Origin: https://account.photonind.com' -H 'Access-Control-Request-Method: GET' https://api.vox.photonind.com:18443/v1/summary)" 204
check "  the summary without a token is 401" "$(curl -sk -o /dev/null -w '%{http_code}' --resolve api.vox.photonind.com:18443:127.0.0.1 https://api.vox.photonind.com:18443/v1/summary)" 401
check "  migrations at 0008" "$($C exec -T db psql -U photonvox -d photonvox -tAc 'select version_num from alembic_version' < /dev/null)" 0008
check "  CORS for the web app's origin" "$(curl -skI --resolve api.vox.photonind.com:18443:127.0.0.1 -X OPTIONS -H 'Origin: https://vox.photonind.com' -H 'Access-Control-Request-Method: GET' https://api.vox.photonind.com:18443/healthz | grep -ci '^access-control-allow-origin: https://vox.photonind.com')" 1

echo "== the nightly backup's lines (proposed for backup-host.sh)"
DUMP=$($C exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --format=custom --no-owner' < /dev/null 2> dump.err | wc -c)
check "the dump is larger than 4096 bytes (the script's sanity check)" "$([ "$DUMP" -gt 4096 ] && echo yes)" yes
echo "   dump: $DUMP bytes"

echo "== memory"
docker stats --no-stream --format '   {{.Name}} {{.MemUsage}}' $(docker ps -q --filter label=com.docker.compose.project=photonvox-rehearsal)
if [ -n "${KEEP:-}" ]; then echo "(kept running: run the script again without KEEP to remove it)"; else cleanup; fi
check "cleaned up" "$( [ -n "${KEEP:-}" ] || { docker ps -aq --filter label=com.docker.compose.project=photonvox-rehearsal; docker ps -aq --filter name=$P; docker network ls -q --filter name=vox-edge; } | wc -l)" 0
echo "$pass passed, $fail failed"; [ $fail = 0 ]
REMOTE
