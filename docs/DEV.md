# PhotonVox: development

## Where things run

| What | Where | How |
|---|---|---|
| API pure-logic tests | the runner | `~/.venvs/photonvox` (`python3 -m venv ~/.venvs/photonvox && ~/.venvs/photonvox/bin/pip install -r api/requirements-dev.txt`), then `cd api && ~/.venvs/photonvox/bin/python -m pytest tests/unit` |
| API full suite (needs Postgres) | LXC 800 | `scripts/remote-test.sh [pytest args]`; `COVERAGE=1` adds branch coverage and the critical-module check. Folder `/root/vox-test`, Compose project `photonvox-test`, taken down after each run |
| The whole stack | LXC 800 | `scripts/smoke-stack.sh`: builds and boots `docker-compose.yml` as project `photonvox-smoke`, checks it, removes everything it made |
| Web | the runner | `cd web && npm install`, `npx vitest run`, `npx tsc --noEmit -p tsconfig.app.json`, `npm run dev` (port **5183**) |
| Screenshots | the runner | `cd web && node scripts/screenshots.mjs [name]`: every page at 1440×900, 820×1180 and 390×844 into `web/screenshots/` (git-ignored), then look at them |
| Everything | | `scripts/test-all.sh [--no-api] [--smoke]` |

Dev ports: web **5183**, API **8113** (taken by nobody else: 5175, 5180–5182 and 8110–8112 are other agents').

## LXC 800 is shared

Its disk is small and d2 and d3 use it too. Never `docker system prune` or prune images globally. The test image `photonvox-test-tests` (about
630 MB) is kept between runs to make them quick; remove it when you stop for a while: `ssh lxc800 docker image rm photonvox-test-tests` and
`rm -rf /root/vox-test`. The smoke script removes its own image every time.

## The shell and the directory client are vendored

- `web/src/shell/` comes from photon-ui: `node ~/projects/photon-ui/scripts/sync-vendored.mjs web/src` (never edit it here).
- `api/photonid_directory_client/` comes from `photonid/directory/client` (see its `VENDORED.md`); `tests/unit/test_vendored.py` fails if it was edited.

## Running the web app against a local API

There is no local Postgres on the runner, so the API runs on LXC 800 (the smoke stack, or a compose project of your own). In development the
web app can take a pasted token (`VITE_DEV_TOKEN_LOGIN=1`), never in a production build.
