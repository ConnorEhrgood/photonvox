# PhotonVox: build log

Dated notes, kept for their reasoning. They describe what was true and decided on their date, not necessarily what is true now
(ARCHITECTURE.md is the current design).

## 2026-11-13: planning pass (design only)

- Repo created with `docs/ARCHITECTURE.md` (revision 1), `docs/BUILD-GUIDE.md` and this log. Nothing built, nothing deployed.
- Sources read: `photon-suite/ARCHITECTURE.md` and `OPERATIONS.md`; `photon/docs/fusionpbx-integration.md` and PhotonConsole's PBX code
  (`api/app/pbx.py`, `pollers/fusionpbx.py`, `api/routes/pbx.py`, `ops/fusionpbx-shim/`, the provisioning and resale sections of its
  ARCHITECTURE.md); `photonguard/docs/ARCHITECTURE.md` and `BUILD-GUIDE.md` (as the model for this plan's shape); `photonid/docs/DIRECTORY.md`
  and the directory's `app/catalogue.py` (which already lists `vox` as "coming", with the notice address `https://api.vox.photonind.com/directory/v1/notify`);
  `photonedge/docs/ARCHITECTURE.md` §1–6.
- **The live engine was not read.** No SSH to `py`, LXC 600 or any production host, by instruction. Every fact about it here comes from the
  documents above (dated September and October 2026); everything else is a question in ARCHITECTURE §22.
- Main recommendation: keep FreeSWITCH + FusionPBX as the engine and build PhotonVox as the product layer around it (ARCHITECTURE §3), with one
  adapter as the only code that knows FusionPBX, so replacing it later stays possible.
- Things noticed while reading that matter later:
  - PhotonConsole matches calls to trunks by the bridge string and the carrier's source address because the CDR has no gateway column; the
    same will be needed for rating.
  - Both configured gateways live in the default domain, not the customer's; VoIP.ms was failing in September and may be unused.
  - FusionPBX returns text as `bytea` through psycopg; PhotonConsole decodes every value (`_text`). The adapter must too.
  - An inbound number needs a `v_destinations` row consistent with its dial plan; a mismatch silently drops calls (found live 2026-09-15).
  - LXC 601 (`kamailio`, stopped) and a `kamailio_ro` database role from `10.10.0.22` exist; their purpose is unknown.
- Decisions and questions are waiting for Connor (top of ARCHITECTURE.md and §22). Proposed edits to the suite documents are in ARCHITECTURE §23
  and were not applied.

## 2026-11-13: revision 2 (Connor's product direction)

- Connor's direction, twice the same day: PhotonVox is a UI for integrators to deploy phone systems extremely fast, tightly integrated with
  Photon's FusionPBX instance(s) and Grandstream GDMS, with one monitoring pane and barcode enrollment; routing, trunks and caller ID are
  abstracted away; Photon (through HTC and later upstreams) is the primary trunking provider and partners may bring their own trunks.
- ARCHITECTURE.md rewritten as revision 2 and BUILD-GUIDE.md rebuilt around a first release (R1): the builder (document of outcomes, compiler,
  templates, bulk import), several instances, Photon trunking with locked 911, GDMS, barcode enrollment, the monitoring pane and the
  PhotonConsole feed, toll-fraud defaults. Texting, chat and the mobile softphone moved to R3; partner trunks, the takeover of live customers,
  the DC10 standby, the browser softphone, B2 storage and metering to R2. Telnyx is no longer recommended: HTC stays primary, other upstreams
  only for known gaps (questions in §22).
- **GDMS API, how it was read:** the knowledge-base article (updated 2024-03-15) covers only tokens, organization and site lists, device add
  and tasks. The full reference at `doc.grandstream.dev/GDMS-API/EN/` is an apiDoc site that renders with JavaScript; its data file
  (`api_data.js`, about 1 MB) was downloaded into the session scratchpad and parsed (never executed) to list every endpoint with its
  parameters and responses. Versions: v1.0.0 (2019-10-18), v1.1.0 (2020-12-05). Findings in ARCHITECTURE §12. Two that shaped decisions:
  **organizations cannot be created through the API** (decision 11: one organization per environment, sites nested by the API), and **push
  callbacks show no signature** (treated as notices and confirmed by a pull). Nothing was called: there is no API account.
- No Step 0 code had been written when the direction arrived (the session was still reading PhotonGuard's templates), so the pause point is
  the plan commit itself.

## 2026-11-13: Step 0.1, 0.3, 0.4, 0.5 (the parts that hold under any answer)

- **API** (`api/`): PhotonGuard's shape, adapted. The directory copy (organizations, sites, people, access) kept by notify-then-pull with the
  reference client vendored from photonid at `bae1afd` (the client files are unchanged since `585bf6d`; checksums pinned by a test). The role
  catalog is ARCHITECTURE §7 (owner, admin, user) in one table (`app/roles.py`): decision 15 is not answered yet, and if Connor changes the roles
  only that table and its tests change. Authorization by role and site scope with the directory's "strongest entry at a site" rule; row-level
  security with the owner / `vox_app` / `vox_system` split from the first migration; audit log; `/me`, an organization's sites and members
  (partner staff shown as "Partner support"), platform views of organizations and the directory copy; the worker (pull, publish roles,
  heartbeat). `/healthz` has no dependencies and `/readyz` checks the database (suite OPERATIONS §2.5).
- **Tests:** 204 on LXC 800 (`scripts/remote-test.sh`, project `photonvox-test`), 100% line and branch coverage, every critical module at
  100%. The directory's World has an integrator (partner technician, admin of two customers through the partner grant) from the start.
  Found while doing it: FastAPI 0.143 nests included routers in `app.routes`, so the "every tenant route is isolated" test lists routes from the
  OpenAPI schema instead.
- **Web** (`web/`, dev port 5183): the photon-ui shell vendored by its own sync script; PhotonID sign-in (copied from PhotonGuard); the
  integrator's navigation (Customers first when someone works on several customers or through a partner; Overview, Users, Phones, Numbers, Call
  flows, Sites, Monitor; "My phone" for a user); Settings (Team, Templates, Alerts, PhotonConsole connection, Audit log) and Platform
  (Organizations, Instances, Upstreams, GDMS, Number stock) hubs. Pages not built say so and name their step. 109 tests; coverage above
  PhotonGuard's ratchet. Every page screenshotted at the three sizes and looked at; one fix from that review (a person invited without a name
  showed a blank title on the Team page). photon-ui has no phone icon: Phones uses the "screens" icon until one is added there.
- **Compose and smoke** (`docker-compose.yml`, `scripts/smoke-stack.sh`): db, one-shot migrate, api (read-only root, all capabilities dropped,
  unprivileged), worker. Smoke on LXC 800 as project `photonvox-smoke`: migration exited 0, all services healthy, `/me` without a token 401.
  The first run failed because the database is addressed by container name and the smoke project's name differs; `DB_HOST` now sets it.
  Everything the smoke run makes is removed by it.
- **LXC 800 left clean:** no PhotonVox containers, volumes, networks or folders; the test image was removed at the end of the session (the next
  `remote-test.sh` rebuilds it, a few minutes).
- **Next, and what blocks it:** 0.2 (the inventory script) can be written without anyone; 0.6 (the staging instance) needs GATE 0a, and the GDMS,
  zero-touch and barcode spikes need GATES 0c and 0d (BUILD-GUIDE §9). Everything after Step 0 waits for Connor's answers to the decisions.
