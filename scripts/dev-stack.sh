#!/usr/bin/env bash
# The dev PhotonVox on LXC 800 (docker-compose.dev-lxc.yml): for other products' integration tests, never production.
#   scripts/dev-stack.sh up       ship this commit (git archive) to /root/vox-dev, make its .env once (secrets made there, never printed), start
#   scripts/dev-stack.sh seed     the test organization, a phone system with a door on the staging engine, published; prints a new PhotonEntry
#                                 token once (staging's adapter login and agent secret go on standard input, never a command line)
#   scripts/dev-stack.sh status | down    (down removes only this project's containers, volume and image; nothing global is pruned)
set -euo pipefail
cd "$(dirname "$0")/.."
HOST=lxc800 DIR=/root/vox-dev
C="cd $DIR && docker compose -f docker-compose.yml -f docker-compose.dev-lxc.yml"
case "${1:-}" in
  up)
    git archive --format=tar HEAD api docker-compose.yml docker-compose.dev-lxc.yml | ssh $HOST "mkdir -p $DIR && cd $DIR && rm -rf api && tar -xf -"
    ssh $HOST "cd $DIR && [ -f .env ] || (umask 077; {
      echo POSTGRES_PASSWORD=\$(openssl rand -hex 24); echo APP_DB_PASSWORD=\$(openssl rand -hex 24); echo SYSTEM_DB_PASSWORD=\$(openssl rand -hex 24)
      echo SECRETS_KEY=\$(python3 -c 'import base64,os; print(base64.urlsafe_b64encode(os.urandom(32)).decode())')
      echo ENVIRONMENT=development; echo DB_HOST=photonvox-dev-db-1
      echo OIDC_ISSUER=http://10.10.0.80:8085; echo OIDC_AUDIENCE=399486252065226755; echo OIDC_WEB_CLIENT_ID=399486252400836611
      echo CORS_ORIGINS=http://localhost:5183; } > .env)"
    ssh $HOST "$C up -d --build db migrate api" 2>&1 | grep -vE "^ *(#|=>)" | tail -5
    ssh $HOST "curl -s -m 5 http://10.10.0.80:8113/healthz; echo" ;;
  seed)
    { sed -e '1s|^|postgresql+psycopg://photonvox_adapter:|' -e '1s|$|@10.10.0.60:5432/fusionpbx|' ~/.config/photonvox/staging-adapter.pass
      cat ~/.config/photonvox/agent-10.10.0.60.secret; cat api/scripts/dev_entry_seed.py; } \
      | ssh $HOST "$C exec -T api python -c 'import sys; url = sys.stdin.readline().strip(); secret = sys.stdin.readline().strip(); exec(sys.stdin.read(), {\"__name__\": \"seed\", \"URL\": url, \"SECRET\": secret})'" ;;
  status) ssh $HOST "$C ps --format '{{.Name}} {{.Status}}'; docker ps --filter label=com.photonvox.owner=photonvox-dev --format '{{.Names}} {{.Label \"com.photonvox.owner\"}}'" ;;
  down) ssh $HOST "$C down -v --remove-orphans && docker rmi photonvox-api:devstack >/dev/null 2>&1; rm -rf $DIR" ;;
  *) echo "usage: scripts/dev-stack.sh up | seed | status | down" >&2; exit 2 ;;
esac
