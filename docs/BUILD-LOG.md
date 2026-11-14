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

## 2026-11-13: the PhotonVox app (design; phase A)

- Connor's direction: a custom, branded PhotonVox softphone app as its own phase (Teams Phone falls short for mobile-first and softphone-first
  clients; desk-phone customers should get a branded companion). ARCHITECTURE §18a and decisions 20–28; BUILD-GUIDE phase A (A0–A5) with gates.
- The main choice, **WebRTC with PhotonVox's own signaling through a gateway beside FreeSWITCH, instead of a native SIP stack**: it shares one
  engine with the browser softphone, avoids PJSIP's and liblinphone's GPL-or-commercial licenses (GPL is impractical through the App Store), and
  keeps SIP passwords off devices (the gateway registers each device to its extension). It also makes the gateway the natural push sender,
  so RFC 8599 through Kamailio is not needed.
- Checked on the web (2026-11-13): Apple's guideline 4.2.6 (template apps only when submitted by the content's provider) and 4.3, from secondary
  sources (Apple's own page was not reached); Xcode Cloud's 25 included hours a month (Apple's announcement); Google Play's 14-day,
  12-tester closed test for new personal accounts (Google's help page; the organization-account exemption only from third-party guides, marked
  "to confirm" in §18a).
- Replaced: revision 1's "white-label softphone first", R2's separate browser softphone and R3's mobile softphone. Six new questions for
  Connor (§22, 13–18).

## 2026-11-13: decisions answered; decision 23 revised

- Connor approved decisions 1–28 as recommended ("Everything else looks quite good"), except 23. ARCHITECTURE's decision table is now marked
  decided; the BUILD-GUIDE no longer waits on them, only on its resource gates.
- Decision 23 as decided: on any device with cellular service, 911 dialed in the app is always handed to the phone's own dialer (Connor prefers
  the native handoff: the cellular network locates the handset). Devices without cellular (desktops, Wi-Fi-only tablets, phones with no
  service) place 911 over PhotonVox with an automatic location (site match by Wi-Fi access point, network, public IP or geofence; else OS
  location through a 911 provider; ask only when that fails, once per place; an ECRC last). "We cannot constantly ask the user where they are."
- Designed but not verified (spike A0, real devices): iOS's confirmation for `tel:911` from an app, an iPhone's behavior in airplane mode, the
  call-time location read from the background, what the call observer reports. Android's `ACTION_DIAL` for emergency numbers is from Android's
  documentation. 911 provider candidates (Bandwidth, Intrado, RedSky, Comtech) are named for research, not checked.

## 2026-11-13: Step 0.2 (inventory scripts) and the app's 911 test plan

- **Step 0.2:** `scripts/inventory/engine.sh` (inside the FusionPBX container) and `host.sh` (on the Proxmox host), read-only, counts and
  categories only; written and tested here, **not run** (Connor runs them or approves each run). Every table, column and app uuid in the SQL was
  checked against FusionPBX's own schema definitions (`app_config.php`, master, 5.7), which also confirmed the three dial-plan app uuids the
  design had marked "to confirm" and showed that `software::version()` moved to `core/software/` in newer releases. The FreeSWITCH output
  parsers are tested against sample output under `mawk`, which is Debian's default awk and refused one variable name gawk would accept. The SQL
  itself has not run against a real FusionPBX.
- **The app's 911 test plan** (Connor): ARCHITECTURE §18a part 4 (six layers: the `route()` decision function at 100% branch coverage; a test
  emergency number in test builds only, proven by the caller ID that arrives and kept out of release builds by a build check; 933 per carrier;
  a real-device matrix split between a device farm and Photon's own phones; a yearly live 911 test arranged with the PSAP, with its runbook;
  production events for every emergency dial, with no location or content). BUILD-GUIDE A3, A4 and A5 and gates A4b and A5b follow.
- One change of design it brought: **933 now follows 911's path** (handed to the cellular dialer on phones), so a carrier's 933 read-back can be
  tested through the app. Earlier the same day 933 was never handed off.
- Stopped here: the next BUILD-GUIDE item, Step 0.6 (the staging instance), needs GATE 0a (a staging container in the colo), and the spikes after
  it need the GDMS key and phones (GATES 0c, 0d). Running the inventory needs Connor (GATE 0b).

## 2026-11-13: the inventory, read

- Connor approved the run; the operator reviewed both scripts and ran them read-only, with no errors. Findings (counts only) in ARCHITECTURE
  §17a and `docs/ENGINE.md`; the reports stay out of git. The most serious: **no Proxmox backup of the engine** (only an in-container backup on
  the same disk); 1 of 5 numbers drops its calls (no dial plan); 10 of 10 extensions without a call class and 6 short voicemail PINs (no
  international calls in 90 days, so the defaults cost the customer nothing); both carrier gateways live in the test domain. The fixes are being
  raised with Connor by the operator; none are written here.
- Small faults in my own scripts, shown by the real run and fixed: the FusionPBX version had "unknown" appended (a `grep` over two paths, one
  missing, failed under `pipefail`); the git line printed empty; two registrations' transport was not recognized (`UDP-NAT` style); the SIP
  profiles printed their call count, not their state; the provisioning settings printed hundreds of model-specific lines (now only the ones that
  matter). Added for a second run: a rough classification of what the enabled outbound routes' patterns allow (international, premium, North
  American), without printing the patterns.
- Connor's rule for staging, written into Step 0.6, the house rules and §16: no carrier gateways, never the HTC trunk, outbound SIP blocked.

## 2026-11-13: Step 3's pure core, ahead of order (the document, validation, the compiler)

- Built while the staging container waits for Connor's approval, because it needs no resources: `app/document/model.py` (the phone-system
  document of ARCHITECTURE §8 as strict models; `contract/phone-system/schema.json` generated from it, with a small-office sample),
  `app/document/validate.py` (every problem by path: dangling references, 911 prerequisites (a validated emergency location and a held emergency
  number per site), caller ID and direct numbers only from held numbers, reserved and prefix-colliding extensions, loops of automatic forwards),
  and `app/compiler/` (the document to an **engine plan**: extensions with caller IDs, emergency caller IDs and call classes; voicemail, ring
  groups, menus, time conditions, inbound numbers; outbound routes per class in the instance's upstream order; the locked emergency route first).
- **The compiler stops at an engine plan, not FusionPBX rows**: how each object is written to FusionPBX is the write-path spike's question
  (Step 0.7, on staging). The adapter will map the plan to rows.
- Choices made here (say if any is wrong): 911 and 933 match with or without any site's outside-line prefix (over-matching 911 is the safe side);
  988, 711, 211, 311, 511 and 811 are always allowed and 411 is not (it costs money); premium 900 and 976 match no route at all; the high-cost
  North American area codes are off unless an owner switches one on like a country ("1876"); a 911 call shows the site's emergency number even
  for a user who shows a direct line; shared voicemail boxes are separate from users' own; every user gets a voicemail box.
- Tests: 275 on LXC 800, 100% line and branch coverage, with `validate.py`, `compile.py` and `classes.py` added to the critical modules. The
  golden plan for the sample was read line by line before it was frozen.

## 2026-11-13: the second inventory run (outbound routes)

- Run by the operator, read-only, no errors (report outside git). The customer has 2 enabled outbound routes: at least one allows international
  (011 or +), North American numbers are covered, none names 900 or 976. With no call class on any extension, **international dialing is open
  from every extension** on the live system. Recorded in ARCHITECTURE §17a. The operator is raising the fix with Connor; nothing is written here.
- Limit of the classification, recorded with it: it only notices patterns that name 900 or 976. A broad North American pattern would also let
  premium 900 numbers and the high-cost Caribbean area codes through, so whether those are open is unknown until someone reads the two patterns.

## 2026-11-13: the staging container, first build (not usable yet)

- Connor created `vox-staging` (Proxmox CT 610, 10.10.0.60, Debian 12, 2 cores, 2 GB, 10 GB) with his nftables guard (`inet vox_guard`: nothing
  to the HTC trunk's network, no new SIP to public addresses). Rules: no carrier gateways, no public port forward, no production gateway or trunk
  credentials, `--no-install-recommends`.
- `engine/staging/build.sh`: the FusionPBX install script at the revision in use when production was installed (`1d4100b`), with production's
  versions pinned (FusionPBX at its last 5.5.12 commit, FreeSWITCH tag v1.11.1, sofia-sip 1.13.17, libks, spandsp and FusionPBX's optional apps as
  of 2026-07-31), no recommended packages, the install script's own later fix for unprivileged containers, and the admin password kept out of
  the log. Recorded in `docs/ENGINE.md`.
- First build (12 minutes): versions as planned (FreeSWITCH's build string is production's exactly); guard unchanged; no gateways. **Not usable:**
  my script set a private umask around the whole install instead of only the password file, so 18,540 files the install created are readable by
  their owner only, and FreeSWITCH cannot read FusionPBX's config (no SIP profiles load). Fixed in the script; it now also refuses to run on a
  container that already has an install, and restarts fail2ban at the end (it failed on a missing `auth.log`). **Needs Connor: reset CT 610 to
  fresh Debian 12** (a snapshot of the fresh container first would make the "rebuilt once" check in Step 0's done-when a rollback away).
- `scripts/staging-check.sh` (Step 0.6's check, run from the runner): the guard's rules are present, no gateway exists in FusionPBX or
  FreeSWITCH but the SIPp upstream, an INVITE from FreeSWITCH to a public documentation address is dropped by the guard (its counter moves), and
  a packet to the HTC trunk's network is dropped before leaving the container. Not run yet: it needs FreeSWITCH's profiles.
- Live engine, from the operator (done on production today, not by me): the number whose calls dropped was removed; the VoIP.ms gateway and its
  disabled route were removed; a nightly Proxmox backup of CT 600 now runs (02:15, local storage, keep 3). **Every production outbound route is
  North American only**: the second run's "international" was the inventory script counting the `\+1` of a North American pattern. Fixed: a
  route counts as international only for `011` or a literal `+` not followed by `1`. Connor keeps voicemail PINs at 4 digits: §15 and the
  inventory's PIN check now use 4. ARCHITECTURE §17a updated; whether the North American patterns exclude 900 and the high-cost Caribbean area
  codes is still open (§22).

## 2026-11-13: staging is up (second build)

- Connor reset CT 610 to fresh Debian 12 (same address, key and guard) and saved the fresh state as a vzdump on `py`'s local storage, restorable
  on request (the directory storage has no snapshots).
- The fixed `build.sh` ran in 8 minutes, no errors: FreeSWITCH reports production's exact build, FusionPBX 5.5.12, PHP 8.2, PostgreSQL 18.7;
  every service running, fail2ban included; the internal and external SIP profiles up; no gateway; the guard unchanged. Details in
  `docs/ENGINE.md`.
- `scripts/staging-check.sh` passes all 7 checks (after one fix: FreeSWITCH's gateway table header had been read as a gateway). The INVITE to a
  public address and the packet to the HTC trunk's network were both counted by the guard's drop rules.
- Live engine: the CT 600 backups are now copied nightly to the NAS (01:30 Pacific, 30 days, zstd-checked), so they leave the node; ARCHITECTURE
  §17a updated. What remains of §16's Stage 1 is the restore drill onto staging (Step 2).

## 2026-11-13: Step 0.7, the engine write path (SPIKES §1)

- **SIPp upstream** on LXC 800: `sipp/` (image `photonvox-sipp:3.6.1`, SIPp 3.6.1 from Debian 12; scenarios for the upstream, a registering
  phone, an answering phone, a call, a call that presses a key by SIP INFO) and `scripts/sipp.sh` (named, labeled containers removed on exit,
  logs in `/root/vox-test/sipp`; no global prune). A gateway `sipp-upstream` (10.10.0.80) on staging; `staging-check.sh` now matches
  FreeSWITCH's uuid-named gateways and was proven to fail on a stray one.
- **Every object written by FusionPBX's own pages** (driven in headless Chromium, `engine/spike/page.mjs`) and diffed table by table
  (`engine/spike/snapshot.py`), each proven by a SIPp call: domain, gateway, the upstream's address in the providers list, extensions with
  voicemail, outbound routes (national and 911), inbound numbers, ring group, IVR menu, time condition.
- **The same phone system written straight into the database** (`engine/spike/direct.py`), the domain seeded by FusionPBX's own
  `upgrade.php --defaults`, the cache cleared key by key: `engine/spike/prove.sh` passes 20 of 20 (calls out with the outbound and the emergency
  caller ID, a call refused by its call class, numbers in, ring group, menu with a key press, closed hours). Decision taken by the spike: the
  adapter writes the database directly; FusionPBX 5.5.12 has no write API.
- Traps recorded in SPIKES §1b–§1c: unanchored call-class matching (`national` matches `international-44`), FreeSWITCH reads only
  `dialplan_xml`, file cache entries never expire, inbound numbers need a destination row and dial plan describing the same number, the
  providers list also applies to the internal profile, the domain page leaves 72 empty dial plan rows, eavesdrop and intercept enabled by
  default, caller ID in `Remote-Party-ID` (HTC: which header?).
- A FusionPBX source study (outside git, in the scratchpad) supports the findings.
- LXC 800: no containers or logs left; the image stays (121 MB, about 30 MB unique) for the engine tests; 12.9 GB free.
- From Connor: the live engine's new block route (premium, NXX 976, 21 high-cost Caribbean area codes) recorded in ARCHITECTURE §17a; the
  **Call blocking** design added as ARCHITECTURE §15a with **proposed decision 29**, and in BUILD-GUIDE Steps 2 and 3 and the R2 table.

## 2026-11-13: Step 3, the adapter (and decision 29 decided)

- Decision 29 (call blocking) marked decided by Connor, 2026-11-13.
- **The compiler:** the document gains `calling.blocking` (categories let through, numbers and prefixes to block, North American numbers let
  through) and `features` (eavesdrop, intercept: off by default). Photon's default list is `app/compiler/blocking.py` (version 2026-11-13); the
  plan's second route, right after 911, is the locked block route (premium, high-cost North American codes, satellite, international not
  switched on, and the organization's own list). High-cost codes moved out of the national pattern into the block route, so a number can be
  let through; premium stays out of national as a second line and can only be let through by Photon staff. The contract schema was
  regenerated; the golden plan reviewed and refrozen.
- **The adapter** (`app/engine/`): `fusionpbx.py` builds every row and dial plan (critical module, 100% branch coverage), `writer.py` upserts
  and removes in one transaction, scoped to the domain, `upstreams.py` writes the instance's gateways and providers entries, `publish.py` puts
  the steps in order, `agent.py` is what vox-agent will offer. Spike fixes in it: **call classes matched anchored**, **eavesdrop and intercept
  switched off** in each domain, one `call_direction-outbound` per domain, the emergency route showing the emergency caller ID.
- **Proven:** the writer against a FusionPBX-shaped database on LXC 800 (11 tests: first publish, republish keeping secrets and what phone
  users set, removal, scoping, features, upstreams); on staging, `engine/staging/prove-publish.sh` passes 55 checks with SIPp: national calls
  with the direct number, the outside-line prefix, 911/9911/933 with the site's emergency number, 988; premium, high-cost, listed,
  international and satellite numbers refused with nothing reaching the upstream, a let-through number allowed; the main number in all three
  carrier forms, the menu and its key, the group, open and closed hours in the site's time zone, unreachable users hung up or sent to voicemail;
  an unchanged republish writes nothing new and keeps passwords; a reduced publish removes what left; the spike's domain untouched.
- Staging: the adapter's database role created (GATE 3a's staging part); the spike's direct-write domain removed. The full suite: 337 API tests
  at 100% coverage, the critical-module check including the new modules, web and parsers green.
- `scripts/remote-test.sh` now uses `/root/vox-test/suite`, so it no longer deletes the SIPp files beside it.
- Found (SPIKES §1f): FusionPBX's database is SQL_ASCII (the adapter connects with a UTF-8 client encoding); no text-to-speech module, so menus
  stay silent until recordings (a Step 3 decision); FreeSWITCH follows the `timezone` variable for hours, as proven.

## 2026-11-13: Step 3, publishing for real (check, versions, undo, hand edits, records) and Connor's answers

- **Decisions 30 and 31** recorded from Connor's answers: text-to-speech greetings generated at publish and stored, recorded greetings
  overriding (provider comparison in ARCHITECTURE §8a: Google Chirp 3 HD recommended, Azure Neural runner-up, Telnyx if one vendor matters
  more; a listening test decides); 911 addresses held per number with carrier requests to Hickory, numbers unconfirmed until Hickory confirms
  (§11a). Postmark: already on the paid tier.
- **PhotonVox's records** (migration 0002): `pbx_instance`, `phone_system` (one per organization, its draft), `phone_system_version`,
  `engine_object` (what the running version wrote), `engine_secret` (sealed SIP passwords and PINs; no policy for the API's role),
  `emergency_location` (validated by Photon staff in R1), `emergency_number` and `carrier_request` (decision 31). `SECRETS_KEY` (Fernet).
- **Publishing** (`app/engine/service.py`, run by the worker): compile, write, record, then the **post-publish check**: a synthetic loopback
  call per inbound number (stopped by a PhotonVox dial plan at its first stop in the domain, so no phone rings) and through the route
  selection of 911 and 933 with and without the outside prefix, plus a premium number that must be blocked. A route's bridges sit behind a
  condition every real call passes; a synthetic call logs the route, its gateways and the number it would send instead. A failed write or
  check fails the version and publishes the previous ready version again (or removes what a first publish wrote).
- **Versions and undo** (restore is a new version with an earlier document), **hand edits** (the engine compared with the running version:
  changed columns, missing rows, switched-on features, objects added by hand listed and left alone; the next publish puts PhotonVox's back).
- **The API:** the phone system and its draft (saved with problems, published only without), publish, versions, restore, **templates**
  (small office, front-desk menu; Connor names Photon's first ones), **bulk import** (pasted rows, header or not, each row's problems in
  words, into a ring group), sites' emergency addresses; Platform: instances (logins sealed), the address queue, carrier requests (emailed by
  the worker through Postmark when Hickory's address is set; staff record ticket numbers and Hickory's answer).
- **A serious bug caught on staging, before anything left it:** moving the bridges into the synthetic gate's own condition made FreeSWITCH
  send a literal `$1` (a capture belongs to the condition it sits in), for every outbound call, 911 included. The 911 call proofs had checked
  the caller ID but not the dialed number. Fixed (the number to send is set in the matching condition), and both the call proofs and the
  post-publish check now verify the number sent.
- Proven: 66 checks on staging (`engine/staging/prove-publish.sh`: calls, the check passing, a number broken by hand making its check fail and
  a republish repairing it, hand edits found and put back); the API suite on LXC 800 at 100% line and branch coverage with `emergency.py`
  added to the critical modules.
- **The web app:** the Overview shows the phone system's state, its problems, hand edits, the numbers' 911 state with the carrier, and its
  versions with each check's result (failed test calls in words) and "go back to version N"; the setup wizard (site and 911 address, main
  number and template, people pasted and reviewed row by row); Users with bulk import into a ring group; Platform → 911 for staff (addresses
  to check, requests to carriers with the email text, "sent by hand" with a ticket number, the carrier's answer). 121 web tests; screenshots
  of the new pages at the three sizes, no sideways scrolling.

## 2026-11-13: Step 3, vox-agent (the SSH stand-in replaced)

- `agent/vox_agent.py`: the engine's agent, Python 3 standard library only. Signed requests (HMAC-SHA256 over time, method, path and body;
  five minutes' skew; a signature is never accepted twice), fixed operations (status, cache deletes, rescans with killing removed gateways,
  ACL reloads, seeding a domain with FusionPBX's `upgrade.php --defaults`, the synthetic calls of the post-publish check), every value checked
  against a fixed pattern, nothing through a shell; FreeSWITCH reached through its event socket on localhost. 18 tests at 100% (a fake event
  socket; PhotonVox's own client against the real agent).
- Installed on staging as a hardened systemd service (www-data). Found while installing: FusionPBX's `--defaults` writes FreeSWITCH's
  scripts, configuration and storage directories, so those are writable to the service (www-data owns them anyway); everything else is not.
- The API's side is `HttpAgent` (instances are registered with the agent's URL and secret, sealed); the SSH stand-in is gone. The staging
  proofs (66 checks) pass with everything going through vox-agent.

## 2026-11-13: Step 3, the screens, clone, voicemail to email

- **Numbers** (what each number rings, by its hours, per site), **Call flows** (ring groups, menus with keys 0–9 and the no-key outcome,
  shared mailboxes, office hours and each site's hours). Every change saves the draft whole; renaming a group, menu, mailbox or hours updates
  every reference; names are typed freely and stored in their short form. 135 web tests, coverage above the ratchet, screenshots at three sizes.
- **Clone:** another customer's call flows, hours, calling policy and features into this draft (the integrator must see both); this
  customer's sites, numbers and people stay; people matched by extension; what does not match is left for the problems list.
- **Voicemail to email:** FusionPBX's email queue sends voicemail with the recording attached; PhotonVox keeps each instance's outgoing mail
  (Platform → the instance's mail, the password sealed) and writes it to FusionPBX's `email` settings with Apply (also the upstreams), and each
  mailbox's address from the document. Proven on staging with Mailpit on LXC 800 as the SMTP sink: a SIPp caller who speaks (a looped tone,
  `call-speak.xml`) leaves a message for an unregistered user and the email arrives with the recording. Found on the way: a message of silence
  is discarded by FusionPBX (3 seconds of silence end the recording), and the greeting takes about 10 seconds before recording starts.
- For production: a Postmark server for voicemail (its token) and the sender domain's DNS (DKIM, Return-Path): Connor.
- Fixed on the way: a test fixture set its dependency override on a freshly reloaded app object instead of the one serving (another test
  reloads `app.main`).

## 2026-11-13: Step 3, the build test, a vox-agent fix, text-to-speech (decision 30 decided)

- **Sites:** a site is set up for phones from the Sites page (its 911 address, the numbers its 911 calls and other calls show, its hours):
  the gap the build test's second site found.
- **The build test** (`engine/staging/build-test.sh`): the API and worker, in the test suite's container on LXC 800, build a phone system
  through the same requests as the screens (the wizard with 30 pasted people across two sites, the second site, four numbers, a ring group per
  site; staff validate both addresses), publish it to staging through vox-agent with the post-publish check, then find a hand edit and put it
  back; SIPp then calls it (each number by its schedule, both groups, a direct line; calls out with each site's number and a user's direct
  line; 911 from each site with that site's number; international and premium refused, toll-free allowed). 31 checks, passing repeatedly.
  15 requests; the API's part 0.5 s, publishing and the check under 2 s. The "10 minutes of a tester's time" needs a person with the web app.
  Staging's database and agent are now reachable from LXC 800 only (ENGINE.md).
- **A vox-agent bug the build test caught:** two identical requests in the same second (a publish's cache deletes and its republish's) carried
  the same signature and the second was refused as a replay, failing the publish and its restore. Signatures now carry a random nonce; replay
  protection keys on it.
- **Decision 30 decided by Connor: Google Cloud Text-to-Speech, Chirp 3 HD.** Built: `app/speech` (a provider interface; Google over REST with
  an API key; four voices proposed: Kore, Charon, Aoede in US English, Kore in US Spanish), audio cached by voice and text (`speech_audio`,
  the system's own), vox-agent's `sound` operation writing the file into the domain's recordings, menus naming it, the voice chosen on Call
  flows. Proven on staging with a stand-in provider (a tone): the menu played the file (69 checks). Waiting: Connor's Google Cloud project, the
  API key and budget (ARCHITECTURE §8a lists exactly what), then the listening test (`scripts/tts-samples.py`).

## 2026-11-13: Step 3, the security review and its fixes

A review of the document, compiler, adapter, vox-agent and the routes (an adversarial read, findings checked against the code). Fixed:
- **C1, names reaching dial plans:** every key the document uses (users, groups, menus, mailboxes, hours, locations) is a constrained name and
  every site a directory UUID; the adapter also checks each generated dial plan against an allowlist of applications and variables before writing.
- **C2, numbers nobody holds:** Photon assigns numbers to organizations (`held_number`, Platform → Number stock); a draft can only use the
  organization's own numbers, and the writer refuses a number another domain holds on the engine. The wizard and Numbers pick from the list.
- **H1, who may widen calling:** `app/document/policy.py`: a technician cannot widen calling policy (international, premium, a class's reach)
  or change a site's 911 settings; those need the permission for it, checked on the draft's difference, not on the screen.
- **M1** international by an allowlist of country codes; **M2** emergency addresses cleaned before they are stored or emailed;
  **L1/L2** vox-agent: a body-size limit, stricter domain names, a negative length refused, a handler timeout; **L4** engine errors shown to
  integrators in plain words, the details kept for staff; **L6** names and emails refuse `%`, `<`, `>` and control characters (they reach
  FusionPBX's voicemail email); **L7** clone does not copy mailbox emails.
- Noted, not fixed: **L3** vox-agent's seen nonces are in memory (a replay inside the time window after a restart) and it speaks plain HTTP
  (mgmtnet carries it in production); **L5** a failed cache clear after a committed write leaves that version's rows until the next publish or
  undo; **L8** 4-digit PINs (Connor's choice, kept); **L9** no limits yet on text-to-speech spend; the Info items (the synthetic-check
  variable's carry-through, `upgrade.php --defaults` across domains, the agent secret readable by www-data).
- Tests: the API suite and critical modules at 100% (policy, emergency, the adapter), web 140, vox-agent 29; the staging proofs (69) and the
  build test (31) pass with the fixes.

## 2026-11-13: hosting on the shared Photon host (decision 18 replaced), the first deploy prepared (not run)

- **Connor's decision:** PhotonVox's cloud runs on the Vultr host beside PhotonID, the directory, PhotonConsole and PhotonBoard, its own
  compose project, database and memory ceilings, behind the shared Caddy; its own VPS with paying customers or when the host gets tight.
  ARCHITECTURE decision 18 and §16, BUILD-GUIDE GATE 1a updated.
- **Prepared:** `docker-compose.prod.yml` (no host ports, `vox-edge` with the aliases `vox-api` and `vox-web`, ceilings 704 MB in all), the
  web image (unprivileged nginx with its CSP, as the directory's), `deploy/caddy/vox.caddy` (hostnames spelled out for a graceful reload),
  `scripts/deploy.sh`, docs/DEPLOY.md (the exact first-deploy commands and what needs Connor), and `deploy/proposals-photonboard.patch` for
  PhotonBoard (the proxy overlay that keeps `vox-edge` when the proxy is recreated, the deploy and restore scripts including it, the nightly
  backup's `vox-db.dump.enc` and `vox/.env`, the watcher's containers). Read-only on the host to prepare it: its containers, networks, memory,
  the Caddy files, the backup and watcher scripts.
- **Rehearsed on LXC 800** (`scripts/rehearse-deploy.sh`, 20 checks, everything removed afterwards): the proxy stand-in joined `vox-edge` and
  reloaded without a restart while another site kept answering. Idle use about 190 MB.
- **Found on the way:** the web app linked `@photon/ui` from a sibling folder, which an image built from `web/` cannot see: the stylesheets
  and logo are now vendored (photon-ui's `sync-vendored.mjs --css --base`), as the directory does. The API now trusts `X-Forwarded-For` from
  private addresses (`--proxy-headers`), or every request behind the proxy would share one sign-in throttle.
- **GATE 1c** written as `engine/live/gate-1c.sh` and `gate-1c.sql` (check, apply, verify, undo; a column-limited read-only role, one
  `pg_hba` line beside PhotonConsole's; no iptables or mgmtnet change, since the host's overlay address is already allowed). Rehearsed on
  staging with a stand-in for photon_ro's line (13 checks; staging's `pg_hba` restored byte for byte afterwards). Not run on the live engine.

## 2026-11-13: the first production deploy (GATE 1a)

- With Connor's go-ahead, as one phase: b1 put PhotonBoard's side on the host (the proxy overlay, and the deploy, restore, backup and
  watch scripts; photonboard fea8028 and 2ee8ad3), id1 registered PhotonVox in PhotonID and connected it to the directory (its values piped
  into the host's `.env`), then PhotonVox was deployed (commit ba15639): `scripts/deploy.sh`, the proxy joined `vox-edge` with
  `docker network connect`, the site added, validated and reloaded gracefully. The proxy was not restarted and the directory answered
  throughout. Both certificates were issued first time.
- Checked: every container healthy; the worker synced with the directory and published its role catalog; the API's health, the web app
  and CORS through the proxy; PhotonID, the directory, Console and Board still answer; a manual backup holds `vox-db.dump.enc`; the watcher
  checks the four containers. About 210 MB in use; 1.7 GB still available on the host.
- The watcher mailed Connor once (22:00) because `.env` existed before the containers did, and sent the recovery at 22:15. Next time,
  create `.env` just before the stack starts (DEPLOY.md, "Learned").
- Open: nobody can sign in until an organization has `vox` switched on (Connor is choosing; Photon's own is the suggestion); the
  directory's `platform_admin` field is not mapped yet; GATE 1c is not run, and nothing touched the live engine.

## 2026-11-13: sign-in on the suite's shared module (ph-auth)

Connor found PhotonVox still showed its own sign-in page. It now follows the suite's sign-in contract through `@photon/ui/auth`
(vendored into `web/src/ph-auth` with `sync-vendored.mjs --auth`; the PhotonID directory app is the reference):
- No sign-in page: a signed-out visitor goes straight to PhotonID with the deep link kept (path, query and hash); `pages/Login.tsx` is gone and
  `/login` is an old address for home (a development build keeps a paste-a-token page there). Silent SSO; renewal by refresh token only, no iframe.
- Loop guards: a 401 just after signing in is the "We couldn't sign you in" page, never another redirect; a 401 later goes to PhotonID again.
  A 403 is always a page (No access to PhotonVox, with Sign out); "access being set up" is the shared page and checks again by itself.
- Sign-out ends the PhotonID session and comes back to `/auth/signed-out`, which goes on to PhotonID's sign-in form (`prompt=login`).
  Tokens in sessionStorage only.
- Tests: 194 web tests (the contract's unit tests in `src/auth/signin.test.tsx`, the reference token-source tests, the module's own), coverage
  above the ratchet; the API's contract test (401 JSON with `WWW-Authenticate: Bearer` and no `Location`, 403 JSON with a `code`);
  `web/scripts/signin-contract.mjs` against the dev PhotonID (id1's dev app "PhotonVox web (dev)"), 11 checks: signed out at 1440 and 390
  straight to PhotonID, the deep link back after a real sign-in, sessionStorage only, silent SSO in a new tab without a page or an iframe,
  the 401 and 403 pages without a loop, sign-out through `/auth/signed-out` with `prompt=login`, no silent sign-in afterwards, `/login`.

## 2026-11-13: Photon staff from the directory (not deployed: waiting for the go-ahead)

As PhotonConsole did (photon 16a5902): the directory's person documents now carry `platform_admin` and `partners: [{partner_id, slug, role}]`.
- Re-vendored the directory client from photonid b3e8c7f (`projection.py`'s contract text, `FakeDirectory.person(platform_admin=, partners=)`).
- `directory/projection.py` `staff_flags(doc)`: platform admin is `platform_admin is True`; **Photon staff is a platform admin or any member, in any
  role, of partner Photon** (slug `photon`). A document without the fields, or a malformed one, gives neither. Every person document sets
  `person.is_staff` and `person.is_platform_admin`; a change is audited as `directory.staff_flags` (actor "directory", no organization);
  a person removed from the directory loses both.
- The staff gate (the platform routes, and seeing across organizations) is `is_staff`, or the sub in `PLATFORM_ADMIN_SUBS`: **a fallback for
  one release**, then removed. `/me` says `is_staff` and `is_platform_admin`; the web app shows Platform to staff.
- **Photon staff with no organization of their own** (Connor today) get the shell with Platform and go there from `/`; before, they got
  "No access to PhotonVox yet".
- Migration **0006**: `person.is_staff`, and the sync cursor back to 0 so the first pull after the deploy re-reads every person document.
- Tests: the flags from eight kinds of document; a Photon member with no access, a platform admin, another partner's owner (not staff);
  leaving partner Photon (the own grant stays), becoming platform admin, removal, exactly four audit events and none for a rename; a document
  from before the fields; the fallback; the app role cannot set `is_staff`; staff see only platform-level audit rows. API 500 passed (40
  staging-only skipped), 100% coverage, critical modules 100%; web 197.

**The deploy** (when approved): `scripts/deploy.sh` (migration 0006 runs in `migrate`); the worker's next pull (within its interval) is the
full re-read. Check `/platform/directory` (cursor back up, no error) and Connor's `person` row (`is_staff`, `is_platform_admin` true, from
the directory). Rollback: the previous commit; 0006's downgrade drops the column.
- **Deployed 2026-11-13, about 22:36 UTC** (Connor approved, with 0006), after a backup (`backups-manual/pre-vox-staff-…/vox-db.dump`, read
  back). id1 then switched PhotonVox on for the organization PhotonConsole uses; the next pull brought in Connor as staff and platform
  administrator (from the directory) and owner there, with one audit event and no sync error. Signed-out deep links still go straight to
  PhotonID (desktop and phone). DEPLOY.md has the details.

## 2026-11-13: the takeover of live customers, redesigned (design only)

Connor: Hickory Church (the directory organization, PhotonVox switched on) is HUEPC on instance A, to be migrated "seamlessly". ARCHITECTURE §17
is now the plan of record: monitored, imported and compared (row level and a call matrix, with a report of what could not be expressed),
rehearsed on a staging copy (no gateways), **taken over in place** (rows keep their ids, so phones, passwords, voicemail, PINs and call history
do not notice; HTC and the numbers unchanged; one behavior-identical publish with no lost calls; a week of instant "back to hand-built"), then
the protections as a later version. §17a records the mapping. Proposed decision 32 (in place, in R1 as Step 7) and BUILD-GUIDE Step 7 and
GATE 7a for Connor; questions 19–23 in §22. Nothing changed in production.

## 2026-11-13/14: Step 7, the in-place takeover of HUEPC (decision 32), on the live engine

Connor approved it as a phase: the window runs to Saturday 2026-11-14 22:00 Eastern (Hickory Church is empty until Sunday). By then HUEPC is
either managed by PhotonVox with no behavior change and test calls passing, or fully back as it was. Each production step: exact commands in
`~/vox-takeover/stepN.sh` (outside git, mode 600, no secrets), reviewed, then "go". Never 911 or 933. Protections are not part of it.

- **Step 0, backups (22:52–22:55 UTC):** vzdump of CT 600 to `local` in snapshot mode, 31 s, 2.50 GB, zstd-checked, **protected** from the
  nightly keep-3 pruning (`vzdump-lxc-600-2026_11_13-17_52_33.tar.zst`); `pg_dump -Fc` of `fusionpbx` inside CT 600 to
  `/root/photon-changes/fusionpbx-pre-takeover-20261113.dump` (3.96 MB, 119 tables with data, sha256 234ca6fd…), copied to the NAS
  (`~/backups/ct600/` on the runner's SSDs pool, mode 600; same sha256; py's temporary copy removed).
- **Step 1, GATE 1c (about 23:10 UTC):** `gate-1c.sh` revised for Step 7 (every non-secret column of 15 tables, the dial plans included;
  20 secret columns unreadable), rehearsed on staging, then on CT 600: check clean (photon_ro's line, the iptables rule for 10.2.1.5),
  apply with all checks ok, the password moved to the runner (`~/.config/photonvox/live-ro.pass`, mode 600) and deleted on CT 600; from the
  Vultr host, port 5432 reachable over mgmtnet and a real login from PhotonVox's API container (2 domains, 10 extensions, read-only session,
  a SIP password refused). No iptables or mgmtnet change was needed. Undo: `gate-1c.sh undo` on CT 600.
- **Step 2, the export (about 23:15 UTC):** one read-only export of HUEPC through photonvox_ro from the Vultr host: 10 extensions, 10 voicemail
  boxes, 4 numbers, 1 menu (5 keys), 0 ring groups, 2 recordings, 1 FusionPBX user, 66 dial plans (domain, public, global), 1 gateway; no secret
  column. Kept on the runner (`~/vox-takeover/data`, mode 600, outside git).
- **Offline, the import and the compare-until-identical (no production access):** the importer, the builder's adoption, the compare and the
  writer that writes only differing rows (commit a6ced4b). Result on HUEPC: **the first publish is identical to the live rows** (15 objects, 47
  rows; 59 hand-built rows untouched and watched). The understanding check (each object regenerated from the document, compared by what it
  does): every number, menu key, voicemail box and extension the same, except **extension 701 (the elevator)**, whose outside and 911 calls show
  the second number; the document cannot say that yet, so it is kept exactly as it is and listed to decide. Fixed in the importer on the way:
  voicemail switched off on 3 extensions (a `voicemail` flag per user), a menu that ends the call (timeout optional), greetings that are their
  own recordings (`recording:<file>`), and 911 caller ID read as FusionPBX sends it (the emergency one, else the outbound one).
- **Staging rehearsal, before the takeover:** HUEPC copied onto CT 610 (`engine/staging/load_copy.py`: same domain and row ids, random secrets,
  the gateway a SIPp stand-in with the live gateway's id, never a carrier); the call matrix (`engine/staging/takeover-calls.sh`) passes 22 of 22:
  internal calls, the menu, a key, each of the 4 numbers, a call out.
- **Found: HUEPC's phones have no 911 route on the engine.** None of the 52 enabled dial plans a call from its extensions passes through (the
  domain's and the global ones) matches 911, 933, 9911 or 1911; the outbound routes all need 10 or 11 digits. A 911 call through FusionPBX
  would end with no route. Whether the phones reach 911 another way (a second account, the HT801's line) is for Connor. Read from the export,
  never dialed. Not changed by the takeover (its first publish is a no-op); raised with the operator at once.
- **Staging rehearsal, through PhotonVox (offline, about 23:20–23:55 UTC):** the copy adopted and published through the API and the worker
  exactly as on the live engine (no vox-agent; the instance's own gateway): 15 objects, 47 rows, **every row of the domain identical after the
  publish, to the last date**; the drift check ready. **The 22 calls after the takeover: identical to the run before.** The rollback
  (`engine/live/restore_domain.sh`: the domain's rows in the nine writable tables back from the pre-takeover dump, in one transaction, through a
  scratch database) rehearsed: a renamed extension, a deleted number, a stray dial plan and an edited hand-built detail all put back exactly
  (fingerprints identical) in 2.5 s; the calls identical again; nothing left behind. Fixed on the way: the scratch folder (postgres cannot
  enter /root) and reading the root-only dump.
- **The write role (`engine/live/gate-rw.sh`/`.sql`) rehearsed on staging:** a member of photonvox_ro, insert/update/delete on the nine
  tables PhotonVox writes and nothing else, no secrets readable; the takeover run as that role, including a hand edit put back through
  staging's vox-agent (a real write). Found on the way: the writer's upsert read `xmax` (RETURNING), which needs table-wide SELECT; it now
  writes an existing row with an UPDATE and a new one with an INSERT (it already knew which exist), so the role stays column-limited.
  Staging's roles undone and its pg_hba restored byte for byte afterwards; a clean copy reloaded.
- **Operator commands** (`python -m app.manage`: add-instance, adopt, publish, drift, show) so the production steps run from reviewed files,
  each audited with the operator's name.
- **Step 3 (about 23:47–23:55 UTC):** 3A: PhotonVox's database backed up (`backups-manual/pre-vox-takeover-code-…`, read back), the takeover
  code deployed (6524735, migration 0007), every container healthy, every Photon site 200. 3B: the write role on CT 600 (`gate-rw.sh`):
  check clean, apply with its 8 checks ok, the password moved to the runner (`~/.config/photonvox/live-rw.pass`) and deleted on CT 600, a
  real login from the Vultr host (reads, may update extensions, may not update domains, refused a SIP password). No vox-agent: not needed
  for a no-op publish. Undo: `gate-rw.sh undo` on CT 600. (Writing step 3, one read-only command ran on the Vultr host before its go: a
  look for a deploy marker; it changed nothing. Said so to the operator.)
- **Steps 4 and 5 written for review** (`~/vox-takeover/step4.sh`, `step5.sh`): 4 = the export again (the operator added an "Emergency-911"
  route by hand, Connor's approval; the takeover leaves it as a hand-built extra) and the compare again, then the live engine registered in
  PhotonVox (its own HTC gateway, no vox-agent, the write role) and HUEPC adopted through `app.manage` (reads only, proves the no-op). 5 = a
  fresh dump (also to the NAS), the domain's fingerprints, the first publish, the fingerprints compared and the drift check, the test calls
  placed by FreeSWITCH (`engine/live/test_calls.sh`: extension to extension, the menu, one carrier loop to the main number; never 911, 933 or
  9911, refused by the script), the 911 route read; the rollback (R0 PhotonVox only, R1 the domain's rows from the dump, R2 the vzdump with
  Connor) written in the file before anything runs.
- **Step 4 (about 00:05 UTC 2026-11-14):** 4.0 the export again (the operator's Emergency-911 route in it: order 5, enabled, 12 details) and the
  offline compare again: IDENTICAL, 15 objects, 47 rows, 72 hand-built rows (59 + the 911 route and its details), only extension 701 differs
  if regenerated. 4.1 Hickory Church (organization 1fe5a7d9…) has one site, "Hickory Church" (dca2b67a…): id1 not needed. 4.2 the live engine
  registered in PhotonVox as `live-a` (its own HTC gateway by id, no vox-agent, the write role's login sealed). 4.3 HUEPC adopted for Hickory
  Church through `app.manage adopt`, which read the engine as photonvox_rw and proved the no-op: objects 15, rows 47, extras 72, one item to
  decide (extension 701). PhotonVox shows it as new, adopted, no version yet. Nothing was written to the engine.
- **Step 5, the first publish (2026-11-14, 23:59–00:02 UTC; Hickory Church empty until Sunday):** 5.0 the test-call and restore scripts on
  CT 600 (checksums equal); a fresh dump (`/root/photon-changes/fusionpbx-pre-publish.dump`, 4.2 MB, also on the NAS, sha256 equal); the
  domain's fingerprints (9 tables); 7 registrations, no channels, PhotonConsole's shim active. 5.1 **version 1 published: ready, no check
  gates (adopted), nothing written.** 5.2 **the fingerprints after: IDENTICAL (empty diff); drift: 0 changed, 0 missing, 0 extra, 0
  hand-built changed.** 5.3 test calls placed by FreeSWITCH: 101 → 100 bridged to the registered phone (rang, hung up after 4 s); the menu
  answered; **the carrier loop**: 101 → the main number out through the HTC gateway on HTC's profile, back in from HTC to the main number and
  into the menu; every leg hung up, the four call records NORMAL_CLEARING. Never 911, 933 or 9911. 5.4 the Emergency-911 route read, never
  called: order 5, enabled, md5 7d2d09fa…d2d1 before and after; 7 registrations again, no channel left, the shim active; PhotonVox shows HUEPC
  ready, version 1, adopted; the rows still identical after the calls.
- **HUEPC is managed by PhotonVox**, behavior unchanged. Rollback stays ready for the week (step5.sh R0/R1/R2; the dumps kept on CT 600 and the
  NAS). Hand edits are found by the drift check (on PhotonVox's rows and the 72 hand-built ones) and nothing locks Hickory Church out of
  FusionPBX's screens; putting a hand edit back needs vox-agent on CT 600 (a later step: until then such a publish is refused before it commits).
  Next, with Connor: extension 701's caller ID, the protections version, vox-agent on CT 600 (port 8781).

## 2026-11-14: after the takeover

- **Connor:** the GitHub repository ConnorEhrgood/photonvox exists (origin). Before the first push the history was checked: no `.env`, dump,
  export, inventory report or `~/vox-takeover` data was ever tracked; no private key; none of the real passwords or secrets appears in any
  commit; no HUEPC phone number. The HUEPC domain name appears only in ARCHITECTURE (a design fact since the first revision; also in
  PhotonConsole's docs). The push itself is the operator's (this session's permissions do not allow it).
- **Connor:** HUEPC's 911 addresses for …4424 and …2300 are confirmed on file with HTC; extension 701 (the elevator) is as intended ("dials the
  number it needs"): the importer's one "decide" item is closed. Both in §17a.
- **The protections version, rehearsed on staging's copy of HUEPC (export 2) and prepared for Connor (`~/vox-takeover/protections.sh`, not
  run).** The first rehearsal failed one check (the premium route: nothing found): the hand-built `Block-premium-and-Caribbean` still ran
  ahead of PhotonVox's block, because the retire list never arrived. `scripts/remote-test.sh` wrote the staging settings unquoted and the
  test container sourced them, so `a|b|c` became a shell pipe (a password with `$` or a space would have broken the same way); each value is
  now shell-quoted. Then: **published with 7 of 7 checks** (four inbound numbers, the premium block, 911 and 933 read, never called), drift
  empty, the five retired routes switched off and kept. **46 calls** (`engine/staging/protect-calls.sh`): the takeover's 22 again, then
  national numbers dialed as +1, 1 or ten digits reached the carrier as ten digits, toll-free, 988 and 711 went out, 1900/900 premium and
  1876/809 Caribbean refused with nothing sent to the carrier. (The takeover script leaves LXC 800 in FreeSWITCH's loaded providers ACL; the
  new script resets it first, or the phones' calls land in the public context.) **The undo** (`app.manage republish <org> 1`, new): all 559
  rows of the domain equal the takeover's (FusionPBX's bookkeeping columns aside), and the takeover's 22 calls pass.
- For the live engine: vox-agent gains `VOX_AGENT_OPERATIONS` (CT 600: status, cache/delete and check only; seeding a domain, rescans, ACL
  reloads and greetings answer "no such operation") and a systemd drop-in that lets it write only FusionPBX's cache; `app.manage set-agent`
  keeps an agent's secret only after a signed status call succeeds (`set-agent … off` removes it). `test_calls.sh` never dials 988 or an N11
  code, its carrier loop carries the calling extension's toll_allow (PhotonVox's routes check it; tried on the protected copy), and it reads
  each extension's classes and 911 number. Retiring the two specific HTC routes changes no call (same carrier, same ten digits; one only
  matches caller 400, which no extension has). The emergency caller ID stays what Emergency-911 sends today (…4424; 701 …2300).
- `protections.sh` (for Connor's go, part by part): P deploy main (home briefs, migration 0008; backup first; two `.env` values), A vox-agent
  on CT 600 port 8781 (the mgmtnet grant gains tcp/8781: the mgmtnet repo's change, for Connor), B ten-digit format and readopt, C the 911
  address (Connor), D the dry run (read), E dump and fingerprints, F protect-apply and publish, G drift, fingerprints, test calls. Rollback
  written first: U0 `republish 1` (rehearsed), R1 the domain's rows from E's dump, R2 the vzdump with Connor; the agent's removal.

## 2026-11-14: PhotonEntry's door stations (a1's contract, approved by the operator within Connor's plan; built, not deployed)

- **Review sent to a1 first;** a1 agreed all seven points and updated photonaccess (7f9c397, 32839f9): server = the phone system's SIP domain,
  username = the extension, station ids = door keys, the call UUID as the call's id, ended_at may lag, published doors only, 400s; and a1's
  question led to `sip.outbound_proxy` (optional, null unless an engine's `sip_access` sets it; customer SIP domains resolve publicly through
  a wildcard, checked for the live engine). No "dial" field: PhotonEntry sets the call button to "0" (anything a door dials rings its flow).
- **Built:** `doors` in the document (validation, site-scoped policy, compiler, adapter), migration 0009 (integration tokens, hashed;
  `pbx_instance.sip_access`), capability `vox.entry.manage` (admin, owner; sensitive), the two read-only endpoints, vox-agent's read-only
  `door-calls`, `check_xml` allowing exactly one engine-run command (the door's answer log line), the web app's Doors section and Settings →
  PhotonEntry connection. API 564 passed, critical modules 100%; agent 31; web 226; answers validated against PhotonEntry's own schemas.
- **Proved on staging's engine (engine/staging/build-test.sh, 42 of 42):** a door calling rings a desk phone and a ring group; the
  answerer's "#" (RFC 2833 from the SIPp phone) is received by FreeSWITCH and sent on to the door as RFC 2833; a door dialing an outside
  number rings its flow and nothing reaches the carrier stand-in; the door's log lines name who answered (100; 120 through the group).
  Findings on the way: FreeSWITCH refuses an exported `${…}` value on the answering leg, and FusionPBX replaces a hangup hook set before the
  transfer, so the door's own leg logs at answer (`callee_id_number`, escaped twice); FusionPBX's call record puts the answering extension,
  not the door, in `extension_uuid`, so ended calls are found by the logged call id or the caller's number. vox-agent on staging was
  updated (bind 10.10.0.60:8780 as documented).
- **Not expressible yet:** an outside number (a mobile) as a door's outcome; when it comes, the trunk leg needs the same "#" proof.
  **For the live engine, later:** its vox-agent allows status, cache/delete and check only (protections.sh); doors there need `door-calls`
  added to `VOX_AGENT_OPERATIONS`, and the read role must read `v_xml_cdr.caller_id_number` (call history columns; to verify then).

## 2026-11-14: a dev PhotonVox for PhotonEntry's integration tests (Connor's go; not production)

- LXC 800, `/root/vox-dev`, compose project `photonvox-dev` (`docker-compose.dev-lxc.yml`, `scripts/dev-stack.sh up|seed|status|down`):
  database, migration and API only, containers labeled `com.photonvox.owner=photonvox-dev`, API on 10.10.0.80:8113. Dev PhotonID (the dev
  Zitadel) as issuer; no directory sync, no worker, no web app; `.env` made there (secrets never printed). Nothing global pruned.
- Seeded (`api/scripts/dev_entry_seed.py`): organization e0e0e0e0-…-a1 "PhotonEntry test (dev)", two doors (150 → Front desk, 151 → a
  group) on the staging engine (CT 610) in domain `entry.vox.test`, published with 4 of 4 checks; the instance's `sip_access` names the
  outbound proxy 10.10.0.60:5060 (the test domain does not resolve). A token went to a1 directly; the seed output is in
  `~/keys/photonvox-dev-entry-seed.json` (mode 600).
- Found: staging's adapter could not read `v_xml_cdr`; it now reads six columns of it (ENGINE.md), and door-calls logs why when the engine
  does not answer. Checked: door-stations and a real door call's door-calls (answered by 100, "#" pressed), both valid against PhotonEntry's
  schemas; 401 without a token.
