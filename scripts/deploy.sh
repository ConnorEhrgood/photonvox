#!/usr/bin/env bash
# Ships the current commit to the Photon host and rebuilds PhotonVox there (docs/DEPLOY.md: the first deploy has one-time steps before this).
#   scripts/deploy.sh
# The host gets exactly a commit (git archive), never this folder's local files; its .env exists only there and is never overwritten or deleted.
# The shared proxy is not touched: PhotonVox's containers are recreated on vox-edge, where the proxy already is. Migrations run in the stack's
# one-shot `migrate` service before the API and worker start.
set -euo pipefail
cd "$(dirname "$0")/.."
HOST=${VOX_HOST:-prod}; DEST=/opt/photon/vox
C="docker compose -f docker-compose.yml -f docker-compose.prod.yml"
[ -z "$(git status --porcelain)" ] || { echo "commit first: the host gets exactly a commit" >&2; exit 1; }
SHA=$(git rev-parse --short HEAD)
ssh "$HOST" "[ -f $DEST/.env ] && docker network inspect vox-edge > /dev/null" \
  || { echo "the host is not set up yet ($DEST/.env, the vox-edge network): docs/DEPLOY.md, the first deploy" >&2; exit 1; }
TMP=$(mktemp -d); trap 'rm -rf "$TMP"' EXIT
git archive HEAD api web docker-compose.yml docker-compose.prod.yml deploy | tar -x -C "$TMP"
# --delete removes files the commit no longer has; .env is excluded, so it is never deleted (and --delete-excluded is never used).
rsync -az --delete --exclude .env "$TMP/" "$HOST:$DEST/"
# Build first, then wait until no version is being published before the worker is recreated (audit VOX-B-6): a publish cut off half-way
# leaves the phone system to be published again. An older image without `manage busy` cannot say: then the deploy goes ahead (as before).
ssh "$HOST" "cd $DEST && BUILD_SHA=$SHA $C build 2>&1 | tail -3"
for i in $(seq 1 60); do
  n=$(ssh "$HOST" "cd $DEST && $C exec -T worker python -m app.manage busy" 2>/dev/null) || { echo "the running worker cannot say whether it is publishing: going ahead"; break; }
  [ "$n" = 0 ] && break
  echo "waiting: $n version(s) queued or being published"; sleep 5
done
ssh "$HOST" "cd $DEST && BUILD_SHA=$SHA $C up -d --build --remove-orphans 2>&1 | tail -8 && $C ps --format '{{.Service}} {{.State}} {{.Health}}'"
for i in $(seq 1 20); do curl -fsS -o /dev/null https://api.vox.photonind.com/healthz && break; sleep 3; done
curl -s -o /dev/null -w "api %{http_code}\n" https://api.vox.photonind.com/healthz
curl -s -o /dev/null -w "web %{http_code}\n" https://vox.photonind.com/
# The proxy serves every Photon product: they must still answer.
for u in https://board.photonind.com/ https://account.photonind.com/ https://console.photonind.com/; do curl -s -o /dev/null -w "$u %{http_code}\n" "$u"; done
echo "deployed $SHA"
