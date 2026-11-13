# PhotonVox: build guide

You are building PhotonVox, Photon's phone system (voice, texting, team chat). Read `~/projects/photon-suite/ARCHITECTURE.md` and `OPERATIONS.md`
first (the suite, its rules, PhotonID and organizations, the operations standard), then this repo's [ARCHITECTURE.md](ARCHITECTURE.md) **in full**:
it holds PhotonVox's design and the reasons for it. This guide turns the design into ordered steps. Work through them in order. Stop at every
**GATE** and wait for Connor.

**This guide assumes the recommended answers to the "Decisions for Connor" at the top of ARCHITECTURE.md.** Until Connor has answered them, only
Step 0.1–0.4 (no production contact, no money) may start. If an answer is "no", change ARCHITECTURE.md and this guide together before going on.

## Start here (status as of 2026-11-13)

| Item | State |
|---|---|
| Design | `docs/ARCHITECTURE.md` revision 1; decisions awaiting Connor |
| The live engine | FusionPBX in LXC 600 (`10.10.0.21`) on Proxmox `py`, in HTC's central office. **Production with real customers' phones and 911 on it.** Facts about it are unknown (ARCHITECTURE §22); nothing has been read for this plan |
| PhotonConsole | Monitors the engine today (`photon_pbx` source: read-only Postgres `photon_ro` + the `photon-fpbx-shim`, over mgmtnet). Its code is the reference for every read query (`~/projects/photon/api/app/pbx.py`, `pollers/fusionpbx.py`, `pollers/fpbx_channels.py`, `ops/fusionpbx-shim/`) |
| PhotonID directory | Built, not yet in production (photonid GATE B). `vox` is in its catalog as "coming". Step 0 works against its contract and fake; Step 1 needs it live |
| Repo `~/projects/photonvox` | Git, branch `main`, docs only, **no remote** |
| Staging engine | Does not exist (GATE 0a) |
| Second carrier | No account (GATE 5a) |
| PhotonVox VPS | Does not exist (GATE 1a) |
| Leg B at DC10 | Does not exist (GATE 6a) |

First actions:
1. Read the suite documents, then ARCHITECTURE.md completely, then this guide completely.
2. Do Step 0.1–0.4 (skeleton, API, web, compose). None of it touches production or costs money.
3. Ask Connor for GATE 0a/0b in your first report, and for his answers to the decisions and the questions in ARCHITECTURE §22.

---

## 0. Context

**What it is.** A UCaaS product around a FreeSWITCH + FusionPBX engine (ARCHITECTURE §3). Phones and softphones register to engine legs; the
PhotonVox app (FastAPI + Postgres + React) is the customer and admin experience, drives the engine through one adapter and a small agent on each
leg, and adds what FusionPBX lacks: PhotonID and the directory, roles, numbers and carriers, E911, texting, chat, metering, the Console feed.
Calls never depend on the app.

**The sister products** are next to this repo and are the templates for almost everything (§3): `~/projects/photon` (PhotonConsole, and today's
PBX integration), `~/projects/photonguard` (the newest product built on the directory: copy its shape), `~/projects/photonboard`,
`~/projects/photonid` (the directory, its client and fake), `~/projects/photon-ui`. Read their code before writing the equivalent here.
**Do not modify those repos** unless a step says so and Connor has agreed.

**Decided already (do not re-litigate; ARCHITECTURE "Decisions for Connor" once answered):**
- Cloud in Python (FastAPI, SQLAlchemy, Alembic, Postgres 16, TimescaleDB for `call`); web in React 19 + Vite + TypeScript + `@photon/ui` +
  `oidc-client-ts`.
- The engine stays FreeSWITCH + FusionPBX; one adapter (`app/engine/`) is the only code that knows FusionPBX; `vox-agent` on each leg, event
  socket never off localhost.
- Organizations, sites, people and access from the PhotonID directory (read-only copy, notify then pull, the vendored
  `photonid/directory/client`). PhotonVox's roles: owner, admin, supervisor, user. Fine limits stay here.
- One phone system per organization by default; neutral SIP domain names for new ones.
- Voicemail copies, recordings and MMS in a PhotonVox B2 bucket with `prod/`, `dev/`, `test/` prefixes.
- Desktop and phone are equally first-class: every page reviewed at 1440×900, 820×1180 and 390×844.
- Names and identifiers: ARCHITECTURE §21.

**House rules:** `~/projects/photon-suite/ARCHITECTURE.md` **§2** applies in full: git identity and **no AI or tool attribution anywhere**;
never print secrets; production is Connor's; the home LAN is never routed. For PhotonVox in particular:
- **The live engine is production with 911 on it.** No command on `py`, LXC 600 or any engine leg without Connor's go-ahead **for that
  command**, read-only ones included. Changes happen in a quiet hour he names, one at a time, each with its way back written down first, and
  each followed by test calls (inbound to every affected number, outbound, and a 933 call where the carrier supports it).
- Inside the engine's container, install packages only with `--no-install-recommends`.
- **Never place a real 911 call.** 933 only, or a live test arranged with the local PSAP by Connor.
- Never send or receive real texts to people who did not agree to it; test numbers only.
- American spelling in code, screens and documents.

---

## 1. Environment (the runner)

The runner is described in `~/projects/photon-suite/ARCHITECTURE.md` §2 (persistent home only, **no Docker**, backend suites on LXC 800,
Playwright for screenshots). For PhotonVox:
- Full backend tests via `scripts/remote-test.sh` (copied from photonguard's) into `/root/vox-test` on LXC 800; pure-logic tests locally in
  `~/.venvs/photonvox`.
- **SIPp** (call scenarios) and **baresip** or **pjsua** (a scriptable SIP phone) installed under `~/.local` by `scripts/dev-tools.sh`, pinned,
  recorded in `docs/DEV.md`; on LXC 800 too for tests against the staging engine.
- WebRTC tests in headless Chromium with fake media (`--use-fake-device-for-media-stream --use-fake-ui-for-media-stream`).
- The staging engine (GATE 0a) is the only FreeSWITCH you send calls to. It has no real carrier: a SIPp "carrier" on LXC 800 plays the trunk.

---

## 2. Repo layout (target)

```
photonvox/
  api/          FastAPI app: app/ (config, db, deps, oidc, rls, audit, crypto, directory sync, engine/, carriers/, routes/, models/, worker.py),
                alembic/, tests/, Dockerfile, Dockerfile.test
  agent/        vox-agent (runs on each engine leg; systemd unit; its own tests)
  web/          React app; @photon/ui via file:../../photon-ui; the browser softphone (SIP over WSS)
  contract/     JSON Schemas + samples: vox-agent requests and replies, the Console feed, carrier webhooks we accept
  sipp/         call scenarios (register, inbound, outbound, transfer, voicemail, 911 route check, fraud attempts)
  engine/       staging engine build notes and scripts (install of the pinned FusionPBX/FreeSWITCH, test domains)
  deploy/       caddy/, compose overlays, backup hooks
  scripts/      test-all.sh, remote-test.sh, dev-tools.sh, inventory (read-only SQL for the live engine), backup/restore
  docs/         ARCHITECTURE.md, BUILD-GUIDE.md, BUILD-LOG.md, DEV.md, SPIKES.md, ENGINE.md (versions, adapter coverage), OPERATIONS.md (from Step 1),
                RUNBOOK-FAILOVER.md (Step 6), MIGRATION.md (Step 6)
  docker-compose.yml, docker-compose.test.yml, Makefile, .env.example
```

---

## 3. Copy the house patterns

| Need | Template |
|---|---|
| Everything a new product on the directory needs (settings, OIDC, directory copy, role catalog, RLS, audit, compose, migrate service, readyz, JSON logs) | `photonguard/api/app/` and its `docker-compose.yml` |
| Reading FusionPBX (domains, gateways, CDR, channels; `bytea` text; per-domain scoping; trunk matching) | `photon/api/app/pbx.py`, `photon/api/app/pollers/fusionpbx.py`, `fpbx_channels.py`, `photon/docs/fusionpbx-integration.md` |
| A read-only service on the engine host | `photon/ops/fusionpbx-shim/` (server, systemd sandboxing, token, bind address) |
| Staff-provisioned PBX tenancy and its tests | `photon/api/app/api/routes/pbx.py`, `photon/api/tests/api/test_pbx_api.py` |
| Signed requests between services | suite §4 (`X-Photon<Product>-Signature: t=…,v1=…`) |
| Presigned B2 PUT/GET, our own SigV4, lifecycle rules by prefix | `photonguard/api/app/s3_target.py`, `sigv4.py`, `photonguard/docs/SPIKES.md` Step 0.9 |
| Usage per day for billing | `photonguard` `usage_camera_day` (ARCHITECTURE §8b there) |
| Console feed + the tenant safety check | `photonboard/docs/CONSOLE-INTEGRATION.md`, `photon/api/app/pollers/photonboard.py` |
| Outbound requests to user-supplied URLs | `photon/api/app/webhooks.py` |
| Email | `photonboard/api/app/mail.py`, alerts `alerts.py` |
| Design rules | `photon-ui/DESIGN.md` |
| Operations | `photon-suite/OPERATIONS.md` Part 2 from the first deploy |

---

## 4. Contracts to define before the code that uses them

In `contract/`, JSON Schema with samples, validated by tests on both sides:
1. **vox-agent**: each operation (status, registrations, channels, cache flush, reload, hang up a call, test call, upload report) with its
   request and reply; the signature header; errors.
2. **Engine adapter model**: PhotonVox's own shapes for phone system, extension, device, number, call flow, emergency location, call class,
   independent of FusionPBX's tables. The adapter's tests map each to FusionPBX and back.
3. **Console feed** (`GET /integrations/console/v1/phone-systems`): today's point keys kept (ARCHITECTURE §18), new ones added.
4. **Carrier webhooks** (Step 5 and 8): the payloads we accept from the chosen carrier, with captured real samples (never sent to third-party
   capture sites).

---

## 5. Data model (start small, grow per step)

Every tenant-owned table has `tenant_id` (and `site_id` where it applies) and an RLS policy **from its first migration**. Ids are UUIDs.

- Step 0: the **directory copy** (`tenant`, `site`, `person`, `access`, `sync_state`, as PhotonGuard); `member_limits`; `audit_log`.
- Step 1: `pbx_node` (platform), `phone_system` (tenant, node, `domain_uuid`, domain name), `extension`, `device`, `number`, `trunk`
  (platform), `call` (hypertable: the CDR copy, with trunk, direction, durations, both timestamps), `console_token`.
- Step 2: `call_class_policy`, `spend_policy`, `fraud_event`, `rate_deck`.
- Step 3: `call_flow`, `voicemail`, `recording`, `provisioning_credential` (encrypted), `engine_write` (a log of every write the adapter made).
- Step 5: `emergency_location`, `carrier_order`, `port_request`, `e911_notice_ack`.
- Step 8: `sms_brand`, `sms_campaign`, `opt_out`.
- Step 9: `conversation`, `participant`, `message`, `attachment`, `presence`.
- Step 10: `usage_day`, partner price lists.

---

## 6. Steps

Each step: build, test, write the docs it changes, commit in small, well-described commits, report (§11), then stop at its GATE.

### Step 0: foundations, facts and a staging engine

0.1 **Skeleton.** Layout (§2), `Makefile`, `scripts/test-all.sh`, `.gitignore`, `.env.example`, `docs/DEV.md`, `scripts/dev-tools.sh` (SIPp,
baresip or pjsua, pinned).

0.2 **Inventory script, not run.** `scripts/inventory/` holds the read-only queries that answer ARCHITECTURE §22 questions 1–10 (versions,
domains and counts, gateways without secret columns, destinations, devices by model, provisioning settings, voicemail and recording settings,
registrations and channels through the shim), producing counts and categories only, never names, numbers or passwords. **Connor runs it, or
approves each run.** Results go into `docs/ENGINE.md` with the date.

0.3 **API skeleton.** PhotonGuard's shape: settings, `/healthz`, `/readyz`, PhotonID token checks, the directory copy (vendored client,
`POST /directory/v1/notify`, periodic pull, `resolve` on an unknown `sub`), PhotonVox's role catalog published at start-up, authorization from
the copy (role, site scope, fine limits), audit log, RLS with the app role. Tests: role × scope matrix, partner access, RLS check, isolation on
every route.

0.4 **Web skeleton.** `AppShell`; sign-in (PKCE); sidebar: Calls, Messages, Voicemail, Contacts, and for admins Users, Phones, Numbers, Call
flows; Settings hub (Phone system, Emergency addresses, Recording, Texting, PhotonConsole connection, Audit log); Platform hub (Engines,
Carriers, Fraud, Organizations). Honest empty states. Screenshots at the three sizes, looked at.

0.5 **Compose.** api, worker, migrate, db (Postgres + TimescaleDB), web served by Caddy; the test compose; smoke on LXC 800 with a throwaway
project name.

0.6 **Staging engine** (needs **GATE 0a**: Connor creates an LXC in the colo, isolated from production phones, or names another place). Install
the **same FusionPBX and FreeSWITCH versions as production** (from 0.2), two test domains, a SIPp carrier, `vox-agent`'s first version.
`docs/ENGINE.md` records the install exactly, so it can be rebuilt.

0.7 **Spikes** (findings with numbers in `docs/SPIKES.md`):
- **Write path:** for each object in §4.2, how FusionPBX's own page writes it (tables, cache keys, files); whether the installed version has a
  usable API of its own; a prototype adapter write for an extension, a device and an inbound number, each proven by a SIPp call. Say plainly
  which writes are safe through the database and which are not.
- **Browser softphone:** a call from headless Chromium (SIP over WSS) to an extension on staging, two-way audio checked with fake media; codec
  negotiated; what a TURN service would be needed for.
- **Provisioning:** a Grandstream and a Yealink configuration file served with HTTP authentication over HTTPS; what the redirect services need.
- **Replication:** FusionPBX's Postgres streaming to a second staging container and a promotion; which files must be synced; what breaks.

**Done when:** tests pass (`scripts/test-all.sh` locally, the full suite on LXC 800); the web shell is reviewed at three sizes; the staging
engine is rebuilt once from `docs/ENGINE.md`; SPIKES.md answers the write-path and replication questions with evidence.
**GATE 0:** Connor reviews the spikes and the inventory, and answers the decisions.

### Step 1: adopt the live engine, read-only

Needs **GATE 1a** (the PhotonVox VPS, a `deploy` user, DNS for `vox.` and `api.vox.photonind.com`), **GATE 1b** (the directory live, `vox`
switchable, organizations for the live customers) and **GATE 1c** (a read-only database role for PhotonVox on the live engine, its `pg_hba` line,
its iptables rule and a mgmtnet grant: a production change on LXC 600, done by Connor or with his per-command go-ahead; copy the `photon_ro`
pattern exactly, and grant only the columns needed, never secret ones).

- Import each live domain into a `phone_system` linked to its organization (a platform staff action, audited, refusing a domain already
  linked): extensions, devices, numbers, call flows, recent call history; registration status through the existing shim (read-only).
- Pages with real data: Users and extensions, Phones (registered or not, model), Numbers (what each rings), Call flows (read-only view), Calls
  (history, the user's own or the organization's by role).
- Call ingest: `v_xml_cdr` into `call` every minute (idempotent by the CDR's uuid), trunk matched as PhotonConsole does.
- First production deploy by `scripts/deploy.sh` (suite OPERATIONS §2.2), `docs/OPERATIONS.md` written, the database in the nightly backup
  and the watch manifest.

**Done when:** HUEPC's admin (or Connor as them) sees extensions, phones, numbers and calls that match FusionPBX's own screens for the same
day, checked line by line; nothing was written to the engine (the write role does not exist yet). **GATE 1.**

### Step 2: protect the live engine

Every item here changes production: each needs Connor's go-ahead for that change, in a quiet hour, with the test calls after it.

- **Backups (Stage 1):** the engine's database, configuration, voicemail and greetings in the nightly encrypted backup and B2; a rebuild of the
  engine from that backup onto the staging LXC, timed and written in `docs/OPERATIONS.md`.
- **Fraud defaults** (ARCHITECTURE §17): call classes in the outbound routes (international and premium off, the high-cost NANP codes in their
  own class), voicemail PIN rules and no outdial, forwarding limited by class, unused gateways removed, event guard on. Built and attacked on
  staging first with SIPp scenarios (a stolen login dialing premium numbers; forwarding to an international number; a voicemail outdial).
- **The spend breaker** in vox-worker: rates calls in progress and finished; at the limit blocks outbound for the organization (911 still
  passes, proven on staging) and alerts. Carriers' own limits set (HTC: Connor asks).
- **Exposure:** FusionPBX's screens, the event socket and Postgres reachable only over mgmtnet; MFA for staff screens.
- **Provisioning:** authenticated over HTTPS; the phones' configuration updated to it (phones pick it up at their next check).
- **Phones to names** (ARCHITECTURE §16 step 3): `sip-a.<infra>` pointing at today's address; Connor's own phone first, then the rest.

**Done when:** the rebuild drill is recorded; staging proves each fraud scenario is stopped and 911 is not; the live engine has the defaults
and the test calls after each change passed; every live phone registers by name. **GATE 2.**

### Step 3: self-service changes and voicemail in the app

Needs **GATE 3a** (the write role on the live engine, limited to the tables the spikes proved safe; a production change) and **GATE 3b** (the
PhotonVox B2 bucket and keys per prefix).

- The engine adapter's writes, each proven on staging by a SIPp call: users and extensions (name, voicemail settings, forwarding within the
  call class), phones (add by MAC with an emergency location placeholder, remove, reboot, a new SIP login), ring groups and their members,
  business hours and holidays, simple auto attendants (greeting, digits to destinations). Every write logged in `engine_write` and the audit
  log; a failed write leaves PhotonVox showing the engine's real state, never its own guess.
- `vox-agent` replaces the shim's role for PhotonVox (the shim stays for PhotonConsole until Step 4): status, cache flush after writes,
  voicemail copies to B2 within seconds, recordings uploaded and the local files trimmed.
- Voicemail in the app (play, delete, mark heard, greetings); voicemail to email through Postmark on its own stream (paid tier: Connor).
- Provisioning endpoint in vox-api (if the spike recommended it), zero-touch registration with the vendors' redirect services.

**Done when:** on staging and then on Connor's own domain in production, an admin adds a user, a phone and a ring group in PhotonVox and a real
phone rings for an inbound call to it; a voicemail left on a desk phone plays in the app on a phone and a desktop; a security review of the
adapter, the agent and provisioning has been done. **GATE 3.**

### Step 4: PhotonConsole onto the feed

- `GET /integrations/console/v1/phone-systems` with today's point keys and the new ones (ARCHITECTURE §18); the token in Settings →
  PhotonConsole connection.
- In `~/projects/photon` (a PhotonConsole code change: **Connor's go-ahead**): a `photonvox` poller, and the switch of each `photon_pbx` source to
  it with point keys kept, so rules, dashboards and history continue.

**Done when:** for one week PhotonConsole's points from the feed match the old poller's (run side by side on staging data, then in production),
then the old source is switched over; PhotonConsole no longer needs `photon_ro`. **GATE 4.**

### Step 5: numbers, the second carrier and 911

Needs **GATE 5a** (the carrier chosen, an account opened by Connor, test numbers) and **GATE 5b** (answers to ARCHITECTURE §19 for what
PhotonVox may sell, and HTC's answers in §22).

- Carrier adapter (`app/carriers/`): search, order, release (with the 30-day hold), port requests followed to their date, caller ID name,
  STIR/SHAKEN as the carrier provides it; webhooks verified.
- Outbound routing: HTC first for local and national, the second carrier on failure; international only where switched on.
- **Emergency addresses:** per site, validated with the carrier; each phone's emergency location required; each location tied to a number
  registered at that address; softphone location prompts; the 911 notification to the organization's contacts; the customer notice of VoIP
  911 limits, accepted and recorded.
- 933 test calls from each site (where supported).

**Done when:** a number ordered in PhotonVox rings a desk phone on staging and in Connor's domain; a port request is tracked to completion (a
real one Connor chooses, or the carrier's test path); every live phone has a validated emergency location; a 933 call reads back the right
address; a 911 notification reaches the contacts within seconds on staging (no real 911 call). **GATE 5.**

### Step 6: the new engine pair and the move of the live customers

Needs **GATE 6a** (leg B's host at DC10, mgmtnet peers, HTC's answer on delivering to two addresses) and **GATE 6b** (Connor's approval of
`docs/MIGRATION.md`, written from ARCHITECTURE §16, with dates).

- Build the new leg A (colo) and leg B (DC10) at pinned current versions, from `docs/ENGINE.md`; FusionPBX's database replicated A → B; files
  synced; carriers delivering to both; phones with leg B as secondary.
- `docs/RUNBOOK-FAILOVER.md`: promote B, start it, check registrations and calls, fail back. Drilled on staging, then once in production at a
  time Connor chooses.
- Move the live domains one at a time (§16 steps 5–7): Connor's first; HUEPC after a clean week.

**Done when:** every live domain runs on the new pair with no call lost in any move (CDRs and the customers say so); a production failover to
leg B and back has been drilled and timed; LXC 600 is retired with its backup kept. **GATE 6.**

### Steps 7–10 (outline; each starts with a short plan Connor approves)

| Step | What | Core of it |
|---|---|---|
| 7 | Softphones and presence | The browser softphone in the web app (calls, transfer, hold, park, history); the mobile softphone (white-label choice and its provisioning by QR); presence from registrations and the app |
| 8 | Texting and 10DLC | Brand and campaign registration flow; shared inboxes and personal numbers; opt-outs; MMS to B2; Photon's own notification campaign. Start the first registrations early: vetting takes weeks |
| 9 | Chat and one inbox | Conversations (texts and chat in one list), groups and channels, files, search, web push; retention settings |
| 10 | Metering, billing and partners | `usage_day` for every meter, rating, partner wholesale views, PhotonVox Trunking for customers with their own PBX; Stripe and taxes once Connor chooses (ARCHITECTURE §14, §19) |

Steps 7–9 are app-side and may run alongside Step 6 once Step 5 is through its gate.

---

## 7. Testing rules

- Every change ships with tests; a coverage ratchet. **CRITICAL modules at 100% branch coverage:** auth and roles/scopes; RLS; the engine
  adapter's writes and its tenant scoping (`domain_uuid` on every query); call classes and the spend breaker; 911 routing and emergency location
  assignment; provisioning credentials; vox-agent request signing; carrier webhook verification; texting opt-outs; recording access.
- Every API route has a tenant-isolation test and a site-scope test where scopes apply.
- **Calls are tested with calls:** every adapter write and every routing rule has a SIPp scenario on the staging engine; the fraud scenarios and
  "911 still passes while blocked" are permanent tests.
- Contracts validated on both sides; carrier samples captured from the real carrier.
- Web: Vitest; Playwright screenshots at the three sizes for every page changed, looked at; the softphone tested with fake media.
- **Report honestly:** what was verified on the live engine, what on staging, what only in unit tests. A route that "should work" without a test
  call is unverified.

## 8. Security must-haves (ARCHITECTURE §17, made concrete)

- The event socket never leaves localhost; vox-agent accepts only its fixed operations, signed, over mgmtnet.
- FusionPBX's screens, Postgres and vox-agent are never reachable from the internet.
- SIP passwords random, per device, encrypted at rest, never shown; provisioning authenticated over HTTPS.
- International and premium off by default; the spend breaker on for every organization; 911 never blocked by anything PhotonVox does.
- Caller ID limited to owned numbers.
- Every listen to a recording, read of a shared inbox and routing change audited and visible to the organization's owners.
- Run `/security-review` (or an equivalent careful pass) before GATE 2, GATE 3 and GATE 5.

## 9. What needs Connor

| Gate | Needed | Blocks |
|---|---|---|
| decisions | Answers to "Decisions for Connor" and ARCHITECTURE §22 | Step 0.5 onward |
| 0a | A staging LXC in the colo, isolated from production phones (a Proxmox change) | Step 0.6–0.7 |
| 0b | Running the inventory script on the live engine (or approving each run) | `docs/ENGINE.md`, Step 0.6 versions |
| 0 | Review of the spikes | Step 1 |
| 1a | The PhotonVox VPS, a `deploy` user, DNS records | Step 1 deploy |
| 1b | The directory in production, `vox` switchable, the live customers' organizations | Step 1 |
| 1c | PhotonVox's read-only role on the live engine (production change) | Step 1 import |
| 2 | Each production change of Step 2, in a quiet hour | Step 2 |
| 3a | The write role on the live engine (production change) | Step 3 in production |
| 3b | The PhotonVox B2 bucket and keys; Postmark's paid tier | Step 3 voicemail |
| 4 | The PhotonConsole code change and its deploy | Step 4 |
| 5a | The second carrier's account and test numbers (money) | Step 5 |
| 5b | Regulatory answers (§19) and HTC's answers (§22) | Step 5 production |
| 6a | Leg B's host at DC10, mgmtnet peers, HTC's two-address delivery | Step 6 |
| 6b | Approval of the migration plan and its dates | Step 6 moves |
| any | Changes to PhotonConsole, PhotonID, other repos or any production host; spending money; pushing to GitHub | — |

## 10. Out of scope (until a step says otherwise)

Replacing FusionPBX (ARCHITECTURE §3 says when to look again); active/active engines; on-site survivability; fax; video meetings; outbound
dialers and workforce management; CRM integrations; international numbers; our own native mobile app; partner-branded mobile apps; bulk texting;
chat between organizations; voicemail transcription; billing and charging (metering is in scope at Step 10, charging after Connor decides).

## 11. Reporting back

At each gate, send Connor a short report (he prefers short: the state in a few lines, then only what is needed from him):
1. What was built, and what changed in production (each change with its time and its test calls).
2. Tests: where they ran; the CRITICAL modules' coverage.
3. Verified on the live engine vs on staging vs not verified.
4. What you need from Connor next (the gate table).

Keep `docs/ARCHITECTURE.md` and `README.md` current when a decision or the state changes; add dated notes to `docs/BUILD-LOG.md`.
