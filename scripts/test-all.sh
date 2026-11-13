#!/usr/bin/env bash
# Every suite, in order, stopping at the first failure:  scripts/test-all.sh [--no-api] [--smoke]
#   the API's pure-logic tests here, the web (types, tests with the coverage ratchet), then the full API suite on LXC 800 with coverage and the
#   critical-module check (scripts/remote-test.sh).
#   --no-api   skip the API suite (it needs LXC 800)
#   --smoke    also boot the whole stack there and check it from outside (scripts/smoke-stack.sh, a few minutes)
set -euo pipefail
cd "$(dirname "$0")/.."
step() { printf '\n\033[1m== %s\033[0m\n' "$*"; }
API=1; SMOKE=0
for a in "$@"; do case "$a" in --no-api) API=0;; --smoke) SMOKE=1;; *) echo "unknown option $a" >&2; exit 2;; esac; done
PY=${PHOTONVOX_VENV:-$HOME/.venvs/photonvox}/bin/python

step "api: pure-logic tests (no database)"; (cd api && "$PY" -m pytest tests/unit -p no:warnings -p no:cacheprovider -q 2>&1 | tail -3)
step "web: types"; (cd web && npx tsc --noEmit -p tsconfig.app.json)
step "web: tests, with the coverage ratchet"; (cd web && npx vitest run --coverage 2>&1 | grep -E "Tests |All files|ERROR" )
if [ "$API" = 1 ]; then step "api: full suite on LXC 800, with coverage"; COVERAGE=1 ./scripts/remote-test.sh 2>&1 | tail -4; fi
if [ "$SMOKE" = 1 ]; then step "the whole stack: smoke test on LXC 800"; ./scripts/smoke-stack.sh 2>&1 | grep -v "^ Container\|^ Network\|^ Volume\|^#" | tail -12; fi
printf '\n\033[1mall green\033[0m\n'
