.PHONY: test test-unit test-web test-api smoke screenshots
test: ; scripts/test-all.sh
test-unit: ; cd api && $(HOME)/.venvs/photonvox/bin/python -m pytest tests/unit -q
test-web: ; cd web && npx tsc --noEmit -p tsconfig.app.json && npx vitest run
test-api: ; COVERAGE=1 scripts/remote-test.sh
smoke: ; scripts/smoke-stack.sh
screenshots: ; cd web && node scripts/screenshots.mjs
