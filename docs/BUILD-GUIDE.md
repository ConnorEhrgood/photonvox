# PhotonVox: build guide

You are building PhotonVox: a tool for integrators to deploy phone systems extremely fast on Photon's FusionPBX instances, with Grandstream phones
provisioned through GDMS and enrolled by a barcode scan, and one monitoring pane. Read `~/projects/photon-suite/ARCHITECTURE.md` and
`OPERATIONS.md` first, then this repo's [ARCHITECTURE.md](ARCHITECTURE.md) **in full** (revision 2). This guide turns the first release (R1) into
ordered steps. Work through them in order. Stop at every **GATE** and wait for Connor.

**Connor decided the "Decisions" at the top of ARCHITECTURE.md on 2026-11-13: all as recommended, except decision 23 (the app's 911
location is automatic; ARCHITECTURE §18a).** This guide follows them. Steps still stop at their gates for the resources only Connor can give.

## Start here (status as of 2026-11-13)

| Item | State |
|---|---|
| Design | `docs/ARCHITECTURE.md` revision 2 with §18a (the app); **decisions 1–28 decided 2026-11-13** (23 as Connor revised it) |
| The live engine | FusionPBX in LXC 600 (`10.10.0.21`) on Proxmox `py`, in HTC's central office. **Production with real customers' phones and 911 on it.** Inventoried read-only 2026-11-13 (ARCHITECTURE §17a): one customer, 10 extensions, 7 phones, 5 numbers; **no backup off the node**; fixes being raised with Connor, not written here |
| PhotonConsole | Polls the engine today (`photon_pbx`: read-only Postgres `photon_ro` + `photon-fpbx-shim`, over mgmtnet). Its code is the reference for every read query |
| PhotonID directory | Built, not yet in production (photonid GATE B). `vox` is in its catalog as "coming". Steps 0–3 work against its contract and fake |
| GDMS | API reference read (ARCHITECTURE §12); **no API account** (GATE 0c) |
| Repo `~/projects/photonvox` | Git, branch `main`, **no remote**: commit locally. **Step 0.1–0.5 done 2026-11-13** (skeleton; inventory scripts, run once by the operator; API on the directory fake; web shell; compose and smoke). **Ahead of order, because it needs no resources: Step 3's document, its validation and the compiler to an engine plan** (no FusionPBX writes: those wait for the write-path spike) |
| Staging instance, PhotonVox VPS | Staging: CT 610 given 2026-11-13 (GATE 0a); first build not usable, needs a fresh container (docs/ENGINE.md). VPS: does not exist (GATE 1a) |

**Dev ports** (they collide with no other agent): web **5183**, API **8113**.

First actions:
1. Read the suite documents, then ARCHITECTURE.md completely, then this guide completely.
2. Do Step 0.1–0.5. None of it touches production or costs money.
3. Ask Connor for GATE 0a–0d in your first report, and for his answers to the decisions and ARCHITECTURE §22.

---

## 0. Context

**What it is.** The integrator is the primary user. They build a customer's phone system from a template in minutes, paste in users, scan
phones on site. PhotonVox compiles the phone system's document of outcomes into FusionPBX objects on one of Photon's instances (routing, caller
ID, trunks and 911 are generated, never edited), and writes each phone, its SIP account and its template to GDMS so the phone sets itself up on
power-up. One pane shows engines, trunks, registrations and GDMS phone status; PhotonConsole gets a feed. Calls never depend on the app or on
GDMS.

**The sister products** are next to this repo and are the templates for almost everything (§3): `~/projects/photonguard` (the newest product on
the directory: copy its shape), `~/projects/photon` (PhotonConsole and today's PBX integration), `~/projects/photonboard`, `~/projects/photonid`
(the directory, its client and fake), `~/projects/photon-ui`. **Do not modify those repos** unless a step says so and Connor has agreed.

**Decided (do not re-litigate; ARCHITECTURE "Decisions for Connor" once answered):**
- Cloud in Python (FastAPI, SQLAlchemy, Alembic, Postgres 16; TimescaleDB only if call history needs it); web in React 19 + Vite + TypeScript +
  `@photon/ui` + `oidc-client-ts`.
- FusionPBX + FreeSWITCH is the engine, several instances, all Photon's. `app/engine/` is the only code that knows FusionPBX; `app/gdms/` the
  only code that knows GDMS; `vox-agent` on each instance, the event socket never off localhost.
- The phone system is a **document of outcomes**; the compiler generates every FusionPBX route, gateway, caller-ID rule and destination; 911 is
  generated per site and locked.
- Organizations, sites, people and access from the directory (read-only copy, the vendored `photonid/directory/client`). Roles: owner, admin,
  user. Phone users are PhotonVox's own records.
- Desktop and phone equally first-class: every page reviewed at 1440×900, 820×1180 and 390×844; the scanner on a real phone.
- Names and identifiers: ARCHITECTURE §21.

**House rules:** `~/projects/photon-suite/ARCHITECTURE.md` **§2** applies in full: git identity and **no AI or tool attribution anywhere**;
never print secrets; production is Connor's. For PhotonVox in particular:
- **The live engine is production with 911 on it.** No command on `py`, LXC 600 or any instance without Connor's go-ahead **for that
  command**, read-only ones included. Changes in a quiet hour he names, one at a time, each with its way back written first and test calls
  after (inbound to each affected number, outbound, 933 where supported).
- **GDMS holds real customers' phones** (if Photon's account already has them): until Connor says otherwise, the API touches only the staging
  GDMS organization.
- Inside an engine's container, packages only with `--no-install-recommends`. **Never place a real 911 call**, except the scheduled live
  test of phase A5, arranged with the PSAP and run by its runbook.
- **Staging never reaches a carrier** (Connor, 2026-11-13): no carrier gateways on it, outbound SIP to the internet blocked (Step 0.6).
- On LXC 800: your own directory `/root/vox-test` and your own compose project; its disk is low and shared: **never prune Docker globally**,
  clean up after yourself.
- American spelling everywhere.

---

## 1. Environment (the runner)

As in suite §2 (persistent home only, **no Docker on the runner**, backend suites on LXC 800, Playwright for screenshots). For PhotonVox:
- Backend tests via `scripts/remote-test.sh` into `/root/vox-test` on LXC 800 (own compose project name, cleaned after); pure-logic tests
  locally in `~/.venvs/photonvox`.
- **SIPp** and a scriptable SIP phone (baresip or pjsua) under `~/.local` by `scripts/dev-tools.sh`, pinned, recorded in `docs/DEV.md`; also on
  LXC 800 for tests against the staging instance.
- The scanner is tested in headless Chromium with a fake camera fed a recorded video of labels (`--use-file-for-fake-video-capture`), and on
  real phones by Connor.

---

## 2. Repo layout (target)

```
photonvox/
  api/          FastAPI app: app/ (config, db, deps, oidc, rls, audit, crypto, directory sync, roles, access,
                document/ (the phone-system document, validation, templates), compiler/, engine/ (FusionPBX adapter), gdms/,
                monitor/, routes/, models.py, worker.py), alembic/, tests/, photonid_directory_client/ (vendored)
  agent/        vox-agent (systemd service on each instance; its own tests)
  web/          React app (port 5183 in dev); the scanner
  contract/     JSON Schemas + samples: the phone-system document, vox-agent requests and replies, the Console feed, GDMS payloads we use
  sipp/         call scenarios (register, inbound per outcome, outbound per class, 911 route selection, fraud attempts)
  engine/       staging instance build notes and scripts
  deploy/       caddy/, compose overlays, backup hooks
  scripts/      test-all.sh, remote-test.sh, dev-tools.sh, inventory/ (read-only SQL for the live engine)
  docs/         ARCHITECTURE.md, BUILD-GUIDE.md, BUILD-LOG.md, DEV.md, SPIKES.md, ENGINE.md, GDMS.md, OPERATIONS.md (from Step 1)
  (phase A)     packages/calling/, gateway/, apps/mobile/, apps/desktop/, contract/calling/
  docker-compose.yml, docker-compose.test.yml, Makefile, .env.example
```

---

## 3. Copy the house patterns

| Need | Template |
|---|---|
| A product on the directory (settings, OIDC, directory copy, role catalog, RLS, audit, compose, migrate service, readyz) | `photonguard/api/app/` and its compose files |
| Reading FusionPBX (domains, gateways, CDR, channels; `bytea` text; per-domain scoping; trunk matching) | `photon/api/app/pbx.py`, `photon/api/app/pollers/fusionpbx.py`, `fpbx_channels.py`, `photon/docs/fusionpbx-integration.md` |
| A read-only service on the engine host | `photon/ops/fusionpbx-shim/` |
| Signed requests between services | suite §4 |
| Notify-then-pull from an outside system | PhotonGuard's `box_sync.py` (the PhotonEdge hub), the directory client |
| Console feed + the tenant safety check | `photonboard/docs/CONSOLE-INTEGRATION.md`, `photon/api/app/pollers/photonboard.py` |
| Email | `photonboard/api/app/mail.py`, `alerts.py` |
| Design rules | `photon-ui/DESIGN.md` |
| Operations | `photon-suite/OPERATIONS.md` Part 2 from the first deploy |

---

## 4. Contracts to define before the code that uses them

In `contract/`, JSON Schema with samples, validated by tests:
1. **The phone-system document** (ARCHITECTURE §8): sites, hours, numbers and their outcomes, menus, groups, users, calling. Templates are
   documents with blanks.
2. **vox-agent**: status, registrations, channels, gateway states, cache flush, reload, synthetic call, hang up.
3. **GDMS**: the requests and replies PhotonVox uses (device add/list/edit/delete, SIP server and account, line assignment, XML config,
   template push, tasks, push callbacks), with samples captured from the real API in Step 0 (never sent to third-party capture sites).
4. **Console feed** (`GET /integrations/console/v1/phone-systems`): today's point keys kept (ARCHITECTURE §14).

---

## 5. Data model (start small, grow per step)

Every tenant-owned table has `tenant_id` (and `site_id` where it applies) and an RLS policy **from its first migration**. Ids are UUIDs.

- Step 0: the directory copy (`tenant`, `site`, `person`, `access`, `sync_state`, as PhotonGuard); `audit_log`.
- Step 1: `pbx_instance` (platform), `phone_system` (tenant, instance, `domain_uuid`, domain name, managed or monitored-only), `extension`,
  `phone_user`, `number`, `call` (CDR copy).
- Step 2: `call_class_policy`, `spend_policy`, `fraud_event`, `rate_table`.
- Step 3: `phone_system_version` (the document, who, when), `engine_object` (what was written, its hash), `template` (partner or Photon),
  `emergency_location`, `upstream` (platform), `number_stock`, `port_request`.
- Step 4: `gdms_connection` (platform; per partner later), `gdms_site`, `gdms_sip_server`, `phone` (MAC, serial, model, site, user, GDMS state),
  `enrollment` (the steps done, for retries), `phone_model`.
- Step 5: `phone_status` (current and history), `alert`, `console_token`.

---

## 6. Steps

Each step: build, test, write the docs it changes, commit in small, well-described commits (locally: no remote), report (§11), stop at its GATE.

### Step 0: foundations and spikes

0.1 **Skeleton.** Layout (§2), `Makefile`, `scripts/test-all.sh`, `.gitignore`, `.env.example`, `docs/DEV.md`, `scripts/dev-tools.sh`.

0.2 **Inventory script, not run.** `scripts/inventory/`: read-only queries that answer ARCHITECTURE §22 question 9, giving counts and
categories only (never names, numbers or passwords). **Connor runs it, or approves each run.** Results to `docs/ENGINE.md`, dated.

0.3 **API skeleton** (PhotonGuard's shape): settings, `/healthz`, `/readyz`, PhotonID token checks, the directory copy (vendored client,
`POST /directory/v1/notify`, periodic pull, `resolve` on an unknown `sub`), the role catalog (owner, admin, user) published at start-up,
authorization from the copy (role, site scope), audit log, RLS with the app role. Tests: role × scope matrix, partner access, RLS check,
isolation on every route, sync from the fake directory.

0.4 **Web skeleton** on port 5183: `AppShell`; sign-in (PKCE); sidebar for integrators: **Customers**, **Phones**, **Numbers**, **Monitor**;
inside a customer: Overview, Users, Phones, Numbers, Call flows, Sites, Activity; Settings hub (Templates, Alerts, PhotonConsole connection,
Audit log); Platform hub (Instances, Upstreams, GDMS, Number stock, Organizations). Honest empty states. Screenshots at the three sizes,
looked at.

0.5 **Compose.** api, worker, migrate, db, web served by Caddy; the test compose; a smoke run on LXC 800 under `/root/vox-test` with its own
project name, cleaned up after.

0.6 **Staging instance** (needs **GATE 0a**: an LXC in the colo, isolated from production phones). The **same FusionPBX and FreeSWITCH versions
as production** (FusionPBX 5.5.12, FreeSWITCH 1.11.1, PostgreSQL 18, Debian 12: ARCHITECTURE §17a), a SIPp "upstream" on LXC 800, vox-agent's
first version. `docs/ENGINE.md` records the install so it can be rebuilt. **Connor's rule: staging never uses or reaches the HTC trunk. It has no
carrier gateways at all (no HTC, no VoIP.ms, nothing copied from production), and its firewall blocks outbound SIP (5060, 5061 and the RTP
range) to anything but LXC 800's SIPp upstream.** A check in `scripts/` lists staging's gateways and fails if any exists that is not the SIPp
upstream, and a test from staging proves an INVITE to a public address is blocked.

0.7 **Spikes** (findings with numbers in `docs/SPIKES.md`):
- **Engine write path:** for each object the compiler writes (extension and voicemail, ring group, IVR, time condition, destination and its
  dial plan, outbound route, gateway, caller ID, the 911 route), how FusionPBX's own page writes it; whether the installed version has a usable
  API of its own; a prototype write of each, proven by a SIPp call.
- **GDMS** (needs **GATE 0c**: an API Developer key and API user on a staging GDMS organization): token and signature, which host; site tree
  create; SIP server and account; device add with a real phone's MAC and serial; line assignment; model template push; XML config; the push
  callback (what it carries, whether it is signed); `device/list` status; rate limits by measurement; error codes met. Record everything in
  `docs/GDMS.md`.
- **Zero-touch** (needs **GATE 0d**: two boxed Grandstream phones of the models Photon will stock): a factory-new phone, added through the API,
  plugged in on a test network: how long until it registers to the staging instance, and through what path it found GDMS.
- **Barcode:** which barcodes the boxes and labels carry; the scanner (browser `BarcodeDetector` and a bundled decoder) on Connor's phone and a
  tablet, iOS and Android, in poor light; time from opening the scanner to a recognized MAC and serial.

**Done when:** tests pass (`scripts/test-all.sh` locally, the full suite on LXC 800); the web shell is reviewed at three sizes; the staging
instance is rebuilt once from `docs/ENGINE.md`; SPIKES.md and GDMS.md answer the spikes with evidence. **GATE 0:** Connor reviews them and has
answered the decisions.

### Step 1: instances and the live engine, read-only

Needs **GATE 1a** (the PhotonVox VPS, a `deploy` user, DNS for `vox.` and `api.vox.photonind.com`), **GATE 1b** (the directory in production,
`vox` switchable, organizations for the live customers) and **GATE 1c** (a read-only database role for PhotonVox on the live engine, its
`pg_hba` line, iptables rule and mgmtnet grant: a production change, copying the `photon_ro` pattern, columns limited to non-secret ones).

- `pbx_instance` registry (Platform → Instances): the staging instance and the live one, with health from vox-agent (staging) or the shim
  (live, until vox-agent is installed there in Step 2).
- Adopt each live domain as a **monitored-only** phone system linked to its organization: extensions, numbers, registrations, call history.
- First production deploy by `scripts/deploy.sh`; `docs/OPERATIONS.md`; the database in the nightly backup and the watch manifest.

**Done when:** the live domains appear with data matching FusionPBX's own screens, checked line by line; nothing was written to the engine.
**GATE 1.**

### Step 2: protect the live engine

Production changes, each with Connor's go-ahead, in a quiet hour, with test calls after:
- Backups of the engine (database, configuration, voicemail, greetings) in the nightly encrypted backup; a rebuild onto the staging LXC,
  timed, in `docs/OPERATIONS.md`.
- Toll-fraud defaults (ARCHITECTURE §15): call classes, voicemail PIN rules and no outdial, forwarding by class, unused gateways removed, event
  guard; built and attacked on staging first with SIPp.
- The spend breaker in vox-worker (911 still passes, proven on staging); upstreams' own limits (HTC: Connor asks).
- FusionPBX's screens, the event socket and Postgres only over mgmtnet; MFA on staff screens.
- vox-agent installed on the live engine beside the shim.

**Done when:** the rebuild drill is recorded; staging proves each fraud scenario is stopped and 911 is not; the live engine has the defaults.
**GATE 2.**

### Step 3: the builder: document, compiler, publish

Needs **GATE 3a** (the adapter's write role on the staging instance; a new production instance or a managed domain on the live one only at
Step 6) and **GATE 3b** (how emergency addresses are validated and registered with HTC, from ARCHITECTURE §22 question 6; if by hand, a staff
queue in PhotonVox with HTC's turnaround is the R1 path).

- The phone-system document, its validation (ARCHITECTURE §8) and versions; templates (Photon's first ones as Connor names them) and clone;
  the new-customer wizard; users one at a time and **bulk import** with its review screen; sites and **emergency addresses** (validation, then
  the per-site emergency number); hours and holidays; numbers from **stock** and port requests (tracked by hand in R1).
- The **compiler** and the **adapter**: every object of ARCHITECTURE §8 generated and written to the staging instance; publish with the
  synthetic check; undo; drift detection.
- **Photon trunking:** upstream gateways per instance generated from `upstream`; outbound routes per call class in Photon's order; caller ID
  only from held numbers; the **locked 911 route** per site.
- Voicemail to email through Postmark (its own stream; paid tier: Connor).

**Done when:** on staging, a phone system built from a template with 30 pasted users, two sites and four numbers is published in under 10
minutes of the tester's time; SIPp proves every outcome (each number by schedule, menus, groups, unreachable forwarding), caller ID per site and
per user, each call class allowed or refused, 911 selecting the site's route and number; a hand edit in FusionPBX is detected and replaced by
the next publish; a security review of the compiler, adapter and agent is done. **GATE 3.**

### Step 4: GDMS and barcode enrollment

Needs **GATE 4a** (the production GDMS organization and API user; Connor says whether Photon's existing account may be used) and the phones of
GATE 0d.

- `app/gdms/`: token refresh, signing, retries with backoff, the site tree, SIP server per phone system, SIP account per extension, device
  add/edit/delete, line assignment, model template and XML pushes, tasks (reboot, factory reset), the push receiver (a notice, confirmed by
  `device/list`), the periodic full list.
- **Enrollment** as ARCHITECTURE §13: the scanner, assign or create a user, the idempotent steps with retry, the live card (added → online →
  registered), plain errors for GDMS's refusals; scan many, assign later; enrollment by typed or pasted MAC and serial.
- Phone removal and moving a phone to another user, with the extension password rotated and other phones re-provisioned.
- The phone-model table (lines, BLF keys, template id, TLS).

**Done when:** on the staging instance, Connor scans a boxed phone with his own phone, picks a user, plugs the phone in, and it registers and
calls without anything else being touched; the time from scan to "Ready" and from power to "registered" is measured; removal and reassignment
work; a security review of the GDMS module and the push receiver is done. **GATE 4.**

### Step 5: the monitoring pane and PhotonConsole

- Status collection (engines through vox-agent; GDMS through pushes and lists), the "two sources agree" logic and the site-wide outage rule;
  the pane at its four levels (ARCHITECTURE §14); phone actions; the built-in alerts by email.
- The Console feed with today's point keys and the new phone points; the token in Settings.
- In `~/projects/photon` (**a PhotonConsole code change: Connor's go-ahead**): a `photonvox` poller replacing `photon_pbx`, point keys kept; run
  side by side for a week, then switch, and retire `photon_ro` and the shim.

**Done when:** pulling a phone's network cable, then a whole test site's uplink, shows the right single problem on the pane within a minute and
sends the alert; PhotonConsole's points from the feed match the old poller's for a week. **GATE 5.**

### Step 6: pilot (the first release)

Needs **GATE 6a**: Connor names the first real customer (or rebuilds his own domain as a managed one) and the instance it goes on, and approves
the write role on that production instance.

- Build it with PhotonVox end to end in production: template, users, numbers, emergency addresses, phones by barcode; timed.
- Watch it for two weeks; fix what the integrator found slow.

**Done when:** a real phone system was deployed by an integrator in the times ARCHITECTURE §1 promises, works, and is watched on the pane and in
PhotonConsole. **GATE 6: R1 done.**

### R2 and R3 (outline; each starts with a short plan Connor approves)

| Release | Step | Core |
|---|---|---|
| R2 | Partner trunks | ARCHITECTURE §9: per-domain gateways, numbers on partner trunks, "the trunk that holds the caller ID", failover to Photon trunking, 911 never on them |
| R2 | Take over live customers | ARCHITECTURE §17: import, compile, compare, move with an inter-instance trunk, GDMS for their phones; retire LXC 600 |
| R2 | Standby at DC10 | Replica, file sync, runbook, drill; GDMS SIP servers list both |
| R2 | Numbers by API | Ordering, porting and E911 records through an upstream with APIs (if HTC has none, the upstream Connor chooses) |
| R2 | **The PhotonVox app** (browser, desktop, mobile): phase A below | ARCHITECTURE §18a |
| R2 | Voicemail and recordings in the app (B2); metering; queues and supervisors; Yealink | ARCHITECTURE §18 |
| R3 | Texting and 10DLC; team chat (in the web app and the PhotonVox app); billing | ARCHITECTURE §18 |

### Phase A: the PhotonVox app (R2; ARCHITECTURE §18a)

One app on iOS, Android, macOS and Windows, and the browser softphone, on one calling engine. Decisions 20–28 are decided (2026-11-13; 23 revised). A0 may run during R1's Steps 3–5; A1 starts after GATE 6 (R1 done). Each step ends at its gate. Rough lengths are in ARCHITECTURE §18a
(about 4–5 months in all).

Repo additions: `packages/calling/` (the TypeScript engine), `gateway/` (vox-gateway, Go), `apps/mobile/` (React Native), `apps/desktop/`
(Electron), `contract/calling/` (the signaling messages, validated from TypeScript and Go).

**A0: spikes** (needs **GATE A0a**: test devices (an iPhone, an Android phone) and, for iOS, Connor's Mac or an Xcode Cloud workflow; **GATE
A0b**: the staging instance from Step 0.6). Findings with numbers in `docs/SPIKES.md`:
- FreeSWITCH's WebRTC profile on the staging instance: a browser call with Opus to a desk-phone extension and to a SIPp "PSTN" leg with G.711;
  transcoding CPU per call measured.
- A gateway prototype in Go: register one device's contact to an extension, receive an INVITE, pass SDP through to a browser; the desk phone
  and the browser ring together; whoever answers first wins and the other stops.
- Push on real devices: an iPhone woken by an APNs VoIP push (development environment) showing CallKit's incoming-call screen with the app
  killed and the phone locked; an Android phone woken by an FCM high-priority message showing the Telecom incoming-call screen; time from the
  INVITE to the ringing screen measured, 20 tries each.
- `react-native-webrtc` with CallKit's audio session on iOS (the known hard part): two-way audio after answering from the lock screen.
- TURN: a call from a network that blocks UDP, through coturn on 443.
- 911 on real devices (decision 23): the handoff on an iPhone (`tel:911` and the system's confirmation) and an Android phone (`ACTION_DIAL`),
  **stopped before the call is placed** (never a real 911 call); a PhotonVox call in progress when the handoff happens; dual SIM; whether an
  iPhone in airplane mode with Wi-Fi turns its radio on for an emergency call (Android's dialer does); how the app tells "has cellular service"
  on each OS; what iOS's call observer reports after a handoff. For devices without cellular: a fresh location at call time from the app's
  dialer and from the system's Recents list (possibly in the background with "while using" permission); the Wi-Fi BSSID and network name
  (iOS needs Apple's Wi-Fi information entitlement); what "approximate location" gives.

**Done when:** each spike works on real devices or says plainly why not, with measurements. **GATE A0:** Connor reviews them and confirms
decisions 21–22 (or picks the native SIP stack instead).

**A1: gateway, engine and browser softphone** (needs **GATE A1a**: the gateway's public names and ports on each instance, coturn, and its
mgmtnet grants: production changes when they reach the live instance).
- `contract/calling/`: connect (device-signed), call offer/answer/candidates, ring, answer, hang up, hold, DTMF, transfer (blind,
  attended), park and pick up, presence; validated on both sides.
- `vox-gateway`: device registry (pushed from vox-api; works when vox-api is down), per-device registration to FreeSWITCH with the extension's
  credential (encrypted at rest), SIP over TLS to FreeSWITCH, SDP pass-through, TURN credentials per call, transfer and park by SIP, presence
  from vox-agent, rate limits, metrics; the push sender (used from A3).
- `@photonvox/calling`: the call state machine and the signaling client, unit-tested without a browser; the browser softphone in the web app
  (dialer, incoming call, active call, transfer, park, history from the CDR copy, voicemail from R2's voicemail work).
- Device enrollment in vox-api: device keys, the device list, sign-out, the QR pairing for phone users without a PhotonID account.
- "Where calls ring" (everywhere / app only / desk only) in the document and the compiler.

**Done when:** on staging, a browser call to and from a desk phone, an outside number (SIPp upstream) and another browser, with blind and
attended transfer, park and pick up, and the desk phone and the browser ringing together; a signed-out device is refused within seconds; vox-api
stopped, calls still work; security review of the gateway and the device enrollment done. **GATE A1.**

**A2: desktop** (needs **GATE A2a**: macOS Developer ID through Xcode Cloud or Connor's Mac; a Windows signing service if Windows is in the first
release (question 16)).
- Electron app around the web app's softphone pages: starts at login, tray or menu bar, system notifications for calls, OS keychain for tokens
  and the device key, signed auto-updates; macOS notarized, Windows signed.

**Done when:** the desktop app on macOS (and Windows, if in scope) installs from a signed build, updates itself, and makes and receives calls
on staging. **GATE A2.**

**A3: mobile, with push** (needs **GATE A3a**: the Apple Developer Program and Google Play Console organization accounts (question 13), the APNs
key and the FCM project, the GitHub remote for Xcode Cloud (question 17)).
- React Native app: sign-in (PhotonID, PKCE, universal link / app link) and QR pairing; calls through `@photonvox/calling` and
  `react-native-webrtc`; CallKit with PushKit on iOS, Telecom (self-managed ConnectionService) with FCM on Android; voicemail, history,
  directory and phone contacts, favorites, presence, do not disturb; the partner's branding after sign-in; sign-out and data wipe.
- The gateway's push path: APNs VoIP and FCM high priority, ringing held until the device connects, cancel when another device answers.
- Android builds on the runner; iOS on Xcode Cloud; internal TestFlight and Play internal testing.
- **The release-build check** (ARCHITECTURE §18a part 4, layer 2): the test emergency number exists only in debug and internal-test builds;
  every release pipeline (Xcode Cloud's release workflow, the Gradle release task, the desktop release) fails if the number or its setting's
  name appears anywhere in the built bundle; a unit test asserts the release configuration has none. Proven by building a release with the
  number deliberately left in and watching the check fail.

**Done when:** on real devices, with the app killed and the phone locked, an incoming call rings within 3 seconds of the INVITE in 19 of 20
tries on each platform, together with the user's desk phone; answering from the lock screen gives two-way audio; a call survives switching
between Wi-Fi and cellular (the app reconnects and ICE restarts) or fails clearly; battery use with the app idle for 24 hours is measured and
negligible; removing the user wipes the app. **GATE A3.**

**A4: 911 in the app** (the handoff needs nothing from Connor beyond **GATE A4b**: the test emergency number, question 14b; part 2 needs **GATE
A4a**: HTC's answer, or a contracted 911 provider, on per-call location and an ECRC, question 14).
- **The handoff (primary, ARCHITECTURE §18a part 1):** the decision function `route()` (layer 1) in `@photonvox/calling`; the dial intent on each
  OS; the same check for calls started from the system's Recents list, contacts or Siri; a PhotonVox call in progress held or ended; "has
  cellular service" per OS read into `route()`'s inputs; the Kari's Law notification and the layer 6 event sent as the app hands off, queued
  when offline, never delaying it. No location permission needed on phones for this.
- **Devices without cellular (part 2):** site matching by Wi-Fi access point, network name, public IP and geofence, with the integrator's tool
  for mapping a site's access points to its emergency locations; the best OS location elsewhere, sent in the form the 911 provider accepts;
  asking the user only when automatic location fails or is too coarse, once per new place; the ECRC as the last fallback; location read only at
  sign-in, on network change and at call time; only the current emergency location kept on the server.
- **The test layers (§18a part 4):** layer 1's table of cases and generated test; layer 2's test number on real phones; layer 3's 933 on each
  carrier that supports it; layer 4's device matrix, split between a device farm and Photon's own phones; layer 6's events in production with
  an alert to Photon staff when a dialer did not open. `docs/911-TESTS.md` holds the matrix, each run's results and the live tests.

**Done when:**
- `route()` is at 100% branch coverage with the table of cases (911, 112, 933, `9-911` and the other prefixed forms, `*911`; cellular in
  service, emergency-only, out of service, radio off, airplane mode; SIM absent, locked, ready; iOS, Android, desktop, browser), and the
  generated test shows no input ever refuses or delays an emergency number;
- on real phones (an iPhone and an Android phone on each major carrier), dialing the **test emergency number** in the app opens the system
  dialer and the call arrives at the test menu **with the phone's own mobile number as caller ID**, from the app's dialer and from the system's
  Recents, with a PhotonVox call in progress, with the phone locked, and under Do Not Disturb; the test notification and the layer 6 event
  arrive each time;
- 933 through the app reads back on every carrier that supports it on wireless (the list and the result per carrier in `docs/911-TESTS.md`),
  and on a desktop and a Wi-Fi-only tablet at a site and at a confirmed place (or the provider's limit is documented);
- the layer 4 matrix has been run once in full, farm and own phones, on the oldest supported and the current iOS and Android;
- on a desktop and a Wi-Fi-only tablet, a user moving between two mapped areas of a site gets the right emergency location without being
  asked, and a user at a new place is asked once and not again there;
- the release-build check has failed a release built with the test number in it, and passes a clean one. **GATE A4.**

**A5: release** (needs **GATE A5a**: Connor's approval of the store listings, privacy labels and the demo organization for Apple's review;
the trademark answer, question 18).
- Partner beta (TestFlight external, Play closed testing) with Photon's own staff and one partner; store submission; desktop release channel.
- **The first live 911 test** (ARCHITECTURE §18a, the runbook; needs **GATE A5b**: the PSAP's agreement, question 14c), before the store
  release: a desk phone, the desktop app at a site and off site, and a phone's handoff; results in `docs/911-TESTS.md`. Then about once a year,
  and before any release that changes 911 routing.
- The layer 4 device matrix run again on the release candidate; the release-build check passing.
- `docs/APP-RELEASE.md`: how a release is built, signed, tested and shipped; who holds which key.

**Done when:** the live 911 test has been done and recorded with no open finding, the app is live in both stores and the desktop app is
downloadable, the pilot customer's users run it beside their desk phones
for two weeks, and the release runbook has been followed once by someone other than its author (or by Connor). **GATE A5: phase A done.**

R3 adds texting and chat to the app (one conversation model with the web app).

---

## 7. Testing rules

- Every change ships with tests; a coverage ratchet. **CRITICAL modules at 100% branch coverage:** auth, roles and scopes; RLS; the document's
  validation; the compiler (every outcome, every call class, 911); the adapter's tenant scoping (`domain_uuid` on every query and write); the
  fraud breaker; GDMS signing and the push receiver; enrollment's steps and their retry; caller-ID choice; vox-agent request signing;
  in phase A, device enrollment and sign-out, the gateway's device authentication, the app's emergency `route()` function and its 911
  location rules.
- Every API route has a tenant-isolation test and a site-scope test where scopes apply.
- **Calls are tested with calls:** each outcome and each routing rule has a SIPp scenario on the staging instance; "911 still passes while
  blocked" and the fraud scenarios are permanent tests.
- **The compiler has golden tests:** a document in, the exact FusionPBX objects out, reviewed when they change.
- GDMS is tested against a fake built from the samples captured in Step 0, and against the staging GDMS organization before each gate.
- Web: Vitest; Playwright screenshots at three sizes for every page changed; the scanner with a fake camera.
- Phase A: `@photonvox/calling` unit-tested without a browser; the gateway with Go's race detector and SIPp; push and CallKit/Telecom only on
  real devices, reported with their numbers.
- **Report honestly:** what was verified on the live engine, on staging, with real phones, or only in unit tests.

## 8. Security must-haves

- The event socket never leaves localhost; vox-agent accepts only its fixed operations, signed, over mgmtnet.
- FusionPBX's screens, Postgres and vox-agent never reachable from the internet.
- SIP passwords random, never shown, rotatable; GDMS credentials encrypted, never logged.
- International and premium off by default; the spend breaker on for every organization; **nothing PhotonVox does can block or misroute 911**.
- Caller ID only from held numbers; partner trunks (R2) only in their own customer's domain.
- Every change to a phone system, every phone action and every staff view in the audit log.
- Phase A: no SIP credentials on any device; device keys never leave the device; a signed-out device is refused by the gateway within seconds;
  push payloads carry only what the incoming-call screen shows.
- `/security-review` (or an equivalent careful pass) before GATES 2, 3 and 4.

## 9. What needs Connor

| Gate | Needed | Blocks |
|---|---|---|
| decisions | Answers to "Decisions for Connor" and ARCHITECTURE §22 | Step 0.6 onward |
| 0a | A staging LXC in the colo, isolated from production phones | Step 0.6–0.7 engine |
| 0b | ~~Running the inventory script~~ done 2026-11-13 (ARCHITECTURE §17a); a second run for the outbound-route classification | the route question |
| 0c | A GDMS API Developer key, an API user, a staging GDMS organization | GDMS spike |
| 0d | Two boxed Grandstream phones of the models Photon will stock | zero-touch and barcode spikes |
| 1a | The PhotonVox VPS, a `deploy` user, DNS | first deploy |
| 1b | The directory in production, `vox` switchable, the live customers' organizations | Step 1 |
| 1c | PhotonVox's read-only role on the live engine | Step 1 adoption |
| 2 | Each production change of Step 2 | Step 2 |
| 3a | The adapter's write role on the staging instance | Step 3 |
| 3b | How HTC validates and registers emergency addresses; the first templates; Postmark's paid tier | Step 3 |
| 4a | The production GDMS organization and API user | Step 4 in production |
| 5 | The PhotonConsole code change and its deploy | Step 5 |
| 6a | The pilot customer, its instance, the production write role | Step 6 |
| A0a | Test devices (iPhone, Android); Connor's Mac or an Xcode Cloud workflow | phase A spikes |
| A1a | The gateway's names, ports, coturn and mgmtnet grants on each instance | phase A1 in production |
| A2a | macOS Developer ID; a Windows signing service if Windows is in scope | desktop releases |
| A3a | Apple and Google organization accounts (D-U-N-S), APNs key, FCM project, the GitHub remote | mobile builds and push |
| A4a | Whether HTC handles 911 with a per-call location and an ECRC, or which 911 provider to contract (question 14) | app 911 on devices without cellular |
| A4b | A test emergency number (a DID Photon owns) for test builds; phones on the carriers to test (questions 14a, 14b) | the handoff tests |
| A5a | Store listings, privacy labels, the review demo organization, the trademark answer | store release |
| A5b | The PSAP's agreement to a scheduled live 911 test (question 14c), and Connor's go-ahead for that day | the first live test, before the store release |
| any | Changes to other repos or any production host; spending money; pushing to GitHub | — |

## 10. Out of scope for R1

Everything in the R2 and R3 rows of §6, phase A included; replacing FusionPBX; active/active; on-site survivability; fax; video meetings; CRM integrations;
international numbers; partner-run FusionPBX instances; partners' own GDMS accounts; billing and charging.

## 11. Reporting back

At each gate, a short report (Connor prefers short: the state in a few lines, then only what is needed from him):
1. What was built, and what changed in production (each change with its time and its test calls).
2. Tests: where they ran; the CRITICAL modules' coverage.
3. Verified on the live engine, on staging, with real phones, or not at all.
4. What you need from Connor next (the gate table).

Keep `docs/ARCHITECTURE.md` and `README.md` current when a decision or the state changes; dated notes in `docs/BUILD-LOG.md`.
