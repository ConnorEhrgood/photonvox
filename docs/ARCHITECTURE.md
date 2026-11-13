# PhotonVox — architecture

**Status:** design, revision 2, 2026-11-13, with §18a (the PhotonVox app, phase A) added the same day. Nothing of the product is built
(BUILD-GUIDE Step 0's skeleton is). Revision 2 follows Connor's product direction of the same day (below), which takes priority over revision 1
wherever they differ. The live phone system (FusionPBX in LXC 600, `10.10.0.21`) was **not read or touched**:
facts about it come from `photon/docs/fusionpbx-integration.md`, PhotonConsole's code and the suite documents; whatever they do not say is a
question in §22. The build is driven by [BUILD-GUIDE.md](BUILD-GUIDE.md).

Suite-wide topics (PhotonID and organizations, the rules for working on Photon, conventions, hosting, networks, the ASN plan) are in
`~/projects/photon-suite/ARCHITECTURE.md` and `OPERATIONS.md`; read them first.

**Connor's direction (2026-11-13), in his words:**
> "PhotonVox will be a UI to make the deployment of phone systems extremely fast for integrators leveraging the platform. It will integrate
> tightly with our FusionPBX instance(s) as well as Grandstream GDMS, giving us both a single pane of glass for monitoring and seamless phone
> enrollment with a single scan of a barcode, allowing a phone to be instantly assigned to a user built in the platform."
>
> "Our UI will handle all of the basic little things that happen with every phone system, like managing what calls go out of what trunks via
> what phone numbers and things like that. Pretty much all of that will be abstracted away. Partners will have the ability to set up their own
> VoIP trunks, but we will act as the primary trunking provider through Hickory Telephone and any other upstreams we end up getting."

---

## Decisions (decided by Connor, 2026-11-13)

**Decisions 1–28 approved as recommended ("Everything else looks quite good"), except decision 23, which Connor changed (the native handoff
on cellular devices, automatic location elsewhere);
the row below is the decided version. Decisions 29 (call blocking), 30 (text-to-speech) and 31 (911 addresses per number) were added the same day from Connor's answers.** The BUILD-GUIDE follows them. Changing one means changing it here first, with Connor.

| # | Decision | Why | § |
|---|---|---|---|
| 1 | **The first release (R1) is: fast deployment (wizard, templates, bulk import), several FusionPBX instances, routing abstracted, Photon trunking with locked 911, GDMS, barcode enrollment, the monitoring pane and the PhotonConsole feed, toll-fraud defaults.** R2: partner trunks, taking over today's hand-built customers, the standby engine at DC10, number automation, the PhotonVox app (phase A: browser, desktop and mobile softphone, §18a), voicemail and recordings in the app, metering. R3: texting and chat | It is Connor's product, and the smallest release that delivers it | 1 |
| 2 | **Keep FreeSWITCH + FusionPBX as the engine, driven entirely by PhotonVox.** Integrators never use FusionPBX's screens; Photon staff keep them for emergencies, off the internet | Live customers run on it; it already has the call features; PhotonVox adds the speed and the abstraction | 5 |
| 3 | **Several FusionPBX instances, all Photon's**, each with an optional standby. PhotonVox places each new phone system on an instance; integrators never choose or see one | Room to grow and to move customers; one engine per partner would multiply what Photon must secure | 5 |
| 4 | **One phone system per organization**, covering all its sites, on a neutral SIP domain name (`<id>.sip.photoninfra.xyz`); existing domains keep their names | Internal dialing across sites; names change, domains in phone configurations should not | 6 |
| 5 | **Routing is abstracted.** Integrators choose outcomes ("this number rings this menu", "this site's calls show this number"); PhotonVox generates and owns every FusionPBX route, gateway, caller-ID rule and inbound destination. A hand edit in FusionPBX is detected, reported, and replaced at the next publish | What Connor asked for; it also makes every phone system built the same way, which is what makes it supportable | 8 |
| 6 | **911 is generated and locked**: always through Photon's trunking, from the site's validated emergency address and that site's emergency number. A site gets no phones until its address is validated. Nobody can edit it, and partner trunks never carry 911 | It can never be misconfigured by a user, as Connor asked; Photon can only vouch for 911 on trunks it runs | 11 |
| 7 | **Photon trunking is the default: Hickory Telephone (HTC) first, further upstreams only when HTC cannot provide something needed** (which gaps exist is a question for Connor, §22). Failover and the least-cost order between upstreams are Photon's and invisible to partners | Replaces revision 1's "add Telnyx": HTC stays primary, and an upstream is chosen for a known gap | 9 |
| 8 | **"Photon SIP Trunking" becomes "PhotonVox Trunking"**, the label each customer sees configurable per partner | One product name for all voice (suite question §13.2) | 9 |
| 9 | **Partner trunks (bring your own carrier) in R2**: a call goes out the trunk that holds the number it shows; when a partner trunk fails, local and national calls fall back to Photon trunking (an organization can turn that off); 911 never uses it; the same fraud limits apply | Simple to explain, keeps caller ID honest with carriers, keeps 911 on one known path | 9 |
| 10 | **GDMS is how Grandstream phones are provisioned.** PhotonVox writes the device, its SIP account and its template to GDMS through the API; FusionPBX's own phone provisioning is not used for them. Accepted: GDMS holds those phones' SIP passwords. **Yealink later** | GDMS's API covers adding by MAC and serial, SIP accounts, line assignment, templates and status pushes (§12); phones fetch their settings from it on power-up with no site visit | 12 |
| 11 | **One GDMS account (Photon's), one GDMS organization per environment, GDMS sites nested partner → customer → site**, all created by the API. Partners' own GDMS accounts later | The API cannot create GDMS organizations (it lists them only), so one organization per customer would need a manual step on every deployment | 12 |
| 12 | **Barcode enrollment in the PhotonVox web app** on a phone or tablet: scan the box or label (MAC and serial), pick or create the user, done. The browser's barcode reader where it exists, a bundled reader elsewhere (iOS) | Works on the integrator's own phone with no app to install | 13 |
| 13 | **One SIP login per extension** (FusionPBX's model), with a random password PhotonVox rotates automatically when a phone is removed (GDMS re-provisions the others) | Replaces revision 1's "a login per phone", which FusionPBX does not model; rotation through GDMS makes it cheap | 13 |
| 14 | **Monitoring: collect once, in PhotonVox.** PhotonVox's pane is the integrators' tool (engines, trunks, registrations, GDMS phone status, per organization and site) with a small fixed set of phone alerts. PhotonConsole receives PhotonVox's feed for custom rules and dashboards beside the rest of the building, and stops polling FusionPBX itself | Nothing collected twice, no second rule engine; integrators get phone alerts without needing PhotonConsole | 14 |
| 15 | **Phone users are PhotonVox's own records** (name, extension, site, email), linked to a PhotonID person only if they will sign in. Roles for people who sign in: owner, admin, user (supervisor arrives with call queues) | Building a phone system for 30 people must not mean 30 PhotonID invitations | 6, 7 |
| 16 | **Today's live customers stay as they are in R1** (monitored, not managed by PhotonVox) and are taken over in R2 with no downtime | R1 builds new phone systems; nothing risks the live ones until the builder is proven | 17 |
| 17 | **Toll-fraud defaults on every organization, applied to the live engine first**: international and premium off, a daily spend limit that stops outbound calls (never 911), no outside dialing from voicemail | The largest financial risk in a phone system | 15 |
| 18 | **PhotonVox's cloud (API, web app, worker) on its own small VPS** (Misaka, Ashburn, 2 vCPU / 4 GB). *Costs money* | Calls never depend on the app; it should not share a failure with PhotonID or PhotonGuard | 16 |
| 19 | **Redundancy: a warm standby instance at Equinix DC10 in R2**, promoted by a drilled runbook (target 15 minutes). Phones point at names from day one (GDMS holds the server names, so a move is one edit and a push) | Matches the suite's Stage 3; names keep every later move invisible | 16 |
| 20 | **Build our own branded PhotonVox app** (replaces "white-label softphone first"): one app on iOS, Android, macOS and Windows plus the browser, all on one TypeScript calling engine (React Native on mobile, Electron on desktop). Calls, voicemail, history, contacts, presence, transfer and park now; texting and chat with R3. It rings together with the user's desk phone (same extension) | Connor's direction; one engine means one set of calling bugs, not three | 18a |
| 21 | **WebRTC with PhotonVox's own signaling**, through a small **calling gateway (`vox-gateway`, Go) beside each FreeSWITCH instance**; FreeSWITCH terminates the media (Opus to the app, G.711 to the PSTN); coturn on each instance for UDP-blocked networks; no separate SBC. Not a native SIP stack (PJSIP or liblinphone) | Same engine as the browser; no GPL or commercial SIP license; no SIP password on any device; encryption and NAT traversal always on | 18a |
| 22 | **Incoming calls wake the app through the gateway**: APNs VoIP push + CallKit on iOS, FCM high-priority + Telecom (ConnectionService) on Android; the gateway rings the caller back at once and holds the call until the device connects. Not RFC 8599 through Kamailio. Devices keep no standing connection in the background | The app is not a SIP client, and the gateway already stands where Kamailio would; near-zero battery at rest | 18a |
| 23 | **911 in the app** (decided by Connor): **on any device with cellular service, 911 dialed in the app is always handed to the phone's own dialer and the cellular network**, which locates the handset; no location work there. Devices without cellular (desktops, Wi-Fi-only tablets, phones with no service) place 911 over PhotonVox with an **automatic** location: the matched site's validated address (Wi-Fi access point or network, public IP, geofence), else the OS location sent through a 911 provider that accepts it, the user asked only when that fails (once per new place), a national emergency call relay center (ECRC) last. Location read only at sign-in, on network change and at call time, never tracked. Kari's Law notification also when the app hands off. 933 follows 911's path. Tested in six layers, real 911 only in a yearly test arranged with the PSAP (§18a part 4) | "We cannot constantly ask the user where they are", and the cellular network locates a phone best (Connor); RAY BAUM'S Act for non-fixed devices; the locked 911 design (§11) | 18a |
| 24 | **One app in the stores ("PhotonVox"), the partner's branding inside after sign-in**; per-partner store listings later as a paid option, published from the partner's own developer accounts | Apple's 4.2.6/4.3 make per-partner apps a partner-account job; one listing is one build and one review per release | 18a |
| 25 | **Sign in with PhotonID, or pair by a one-time QR code** an admin shows, for phone users without a PhotonID account | Keeps "a 30-person office in minutes" true; still revocable per device | 18a |
| 26 | **A key per device in the Secure Enclave or Keystore, no SIP credentials on devices**; signing out a device or removing the user cuts it off at the gateway at once and wipes the app's data on its next run | A stolen phone carries nothing that works elsewhere | 18a |
| 27 | **Builds: Android and Windows on the runner, iOS and macOS on Xcode Cloud** (25 hours a month included; needs the photonvox repo on GitHub), Connor's Mac as the fallback. **Apple Developer Program and Google Play Console as organization accounts, Connor the Account Holder**; Play App Signing with our upload key in `~/keys`; APNs and FCM keys on the gateway hosts and in Bitwarden. *Costs money (Apple $99 a year, Google $25 once, Windows signing a small monthly fee)* | No Mac to buy or keep running; keys held the way PhotonBoard's are | 18a |
| 28 | **Phase A sits in R2**, first after R1, with its spikes during R1; about **4–5 months** to the stores | It needs R1's instances, numbers and locked 911; nothing in R1 waits for it | 18a |
| 29 | **Call blocking per organization** (decided 2026-11-13, as Connor asked; §15a): Photon's default list (international until switched on, premium, high-cost Caribbean and other non-US North American codes, satellite and other high-cost ranges) blocked by default; the partner or an admin allows a category or adds and removes numbers and prefixes; compiled as one locked block route right after the emergency routes; 911 and 933 never blocked; Photon keeps the list current suite-wide. The block route, the default list and the page in R1; per-extension overrides and blocked-call alerts with it if small, else R2; inbound blocking (callers, anonymous) in R2, spam scoring later | The riskiest destinations closed for everyone without depending on each extension's call class; the live engine already needed a hand-built version (§17a) | 15a |
| 30 | **Text-to-speech greetings** (Connor, 2026-11-13: a key feature): menus and messages are spoken from their text, **generated when the phone system is published and stored as files** on the engine (no dependency on the provider when a call comes in); a recorded greeting always overrides. *Provider, recommended pending a listening test on real phones:* **Google Cloud TTS, Chirp 3 HD** (8 kHz mu-law and 16 kHz output directly, an IVR audio profile, US English and Spanish voices, SSML and custom pronunciations, first 1M characters a month free then $30 per million, no logging of the text); runner-up **Azure Neural** ($15 per million, the most phone-ready formats; its code of conduct asks that a synthetic voice be disclosed); **Telnyx** if one vendor matters more (a REST TTS API exists; its Polly and Azure voices cost more than direct). ElevenLabs: most natural, 2–5 times the price, weak SSML on its newest models, OEM terms for resale to check | §8a |
| 31 | **911 addresses are held per number in PhotonVox and confirmed with the carrier** (Connor, 2026-11-13: Hickory tracks by hand which address each DID is at): every number the organization holds is registered at its site's validated address; a change makes a **carrier request** (for Hickory a clear email, or a ticket number staff record) tracked until Hickory confirms; until then the number shows **unconfirmed** (to the integrator, the customer's admins and Photon staff). A carrier with an API later submits and polls through the same request. *Recommended:* publishing is not held back while a number is unconfirmed (911 still routes, with the address the carrier last confirmed), but staff are alerted daily until it is | §11a |

Dropped from revision 1 (no longer decisions now): Telnyx as the second carrier (replaced by 7), a login per phone (replaced by 13), and the
R3 items (texting, chat, B2 bucket for recordings), which keep their design in §18 and come back as decisions before their release. Revision 1's
"white-label mobile softphone first" is replaced by the PhotonVox app (decisions 20–28).

---

## Terms (what the integrator sees, and what the code calls it)

| User-facing | Internal | Meaning |
|---|---|---|
| **phone system** | `phone_system`; a FusionPBX **domain** on one instance | One organization's PBX |
| **user** | `phone_user` | A person who has a phone or an extension. Not necessarily someone who signs in |
| **extension** | `extension`; FusionPBX `v_extensions` | A dialable internal number with voicemail |
| **phone** | `phone`; a GDMS device | A desk phone, cordless base or adapter, known by MAC and serial |
| **number** | `number` (E.164) | A public telephone number |
| **call flow** | `flow`: menus, ring groups, schedules | What happens when a number is called |
| **emergency address** | `emergency_location` | The validated address sent with a 911 call |
| **PhotonVox Trunking** | `upstream` (HTC, later others) | Photon's own trunks |
| **partner trunk** | `partner_trunk` | A partner's own carrier (R2) |
| (never shown) | `pbx_instance`, gateways, dial plans, outbound routes, destinations | What PhotonVox generates in FusionPBX |

---

## 1. What PhotonVox is

**A tool for integrators to deploy phone systems extremely fast**, on Photon's FusionPBX instances, with Grandstream phones that set
themselves up from GDMS. The integrator is the primary user: a partner's technician, or Photon staff acting as one. Their customer's admin
and users come second, and in R1 see only a small portal.

What an integrator does with it (R1):

| Task | How long it should take |
|---|---|
| A new customer's phone system: organization (from the directory), template, sites with validated emergency addresses, numbers, business hours, main menu, ring groups | **under 10 minutes** for a typical small office, most of it answering a few questions |
| 30 users with extensions and voicemail | **one paste** (a spreadsheet's rows) and a review screen |
| Each phone | **one scan and one tap** on site; the phone works on power-up |
| Change who a number rings, open hours, a holiday | one screen, published in seconds |
| See whether anything is wrong, for one customer or all of them | one page |

What the customer gets is a normal business phone system: extensions, Grandstream desk phones, voicemail with email delivery, auto attendants,
business hours and holidays, ring groups, music on hold, direct numbers, caller ID per site or per user, 911 that is always right, and
monitoring. Call queues, conferences, paging and call park are in FusionPBX and come as outcomes in R1 or R2 as integrators need them.

### Releases

| Release | Contents |
|---|---|
| **R1** | The builder (wizard, templates, bulk import, outcomes); several FusionPBX instances; generated routing with Photon trunking (HTC) and locked 911; GDMS; barcode enrollment; the monitoring pane; the PhotonConsole feed; toll-fraud defaults; voicemail to email |
| **R2** | Partner trunks; taking over today's live customers; the standby instance at DC10; number ordering, porting and E911 records through upstream APIs (where they exist); **the PhotonVox app (phase A, §18a): browser, desktop and mobile softphone**; voicemail and recordings in the app (B2); metering for billing; call queues with supervisor views; Yealink |
| **R3** | Texting and 10DLC; team chat (both in the app too); billing itself |

---

## 2. Principles carried over from the suite

| Rule | What it means here |
|---|---|
| Tenancy in every table, RLS on | `tenant_id` (the directory organization id) everywhere; the engine's tenancy is the FusionPBX domain, one per phone system |
| PhotonID says who; products decide what | Read-only copy of the directory (notify, then pull); PhotonVox publishes its own roles; phone users are PhotonVox's |
| No public sign-up | Organizations come from the directory, created by partners or Photon |
| Staff act visibly | Partner and Photon staff show as "Partner support"; every change to a phone system is in its audit log |
| Devices talk only outbound | Phones dial out to GDMS (settings) and to the engine (calls); nothing at a site listens on the internet |
| Two timestamps | Calls and device events keep the source's time and PhotonVox's ingest time |
| **Site autonomy** | **Voice is the exception.** A cloud PBX cannot ring a site's phones with its uplink down; calls to unreachable phones go to voicemail or a mobile number automatically, and survivability on site is a later paid option (§18) |
| Never dark over billing | A restricted account keeps inbound calls, its numbers and **911 always** |
| Monitored by PhotonConsole through a read-only feed | `GET /integrations/console/v1/phone-systems` (§14) |
| Declarative configuration | A phone system is a JSON document of outcomes; FusionPBX is generated from it (§8). This is also what makes templates and cloning trivial |

---

## 3. The integrator's flows

### A new customer

1. **Organization.** The partner creates it in the directory (or already has it) and switches PhotonVox on. In PhotonVox it appears under
   "Customers" with "Set up phone system".
2. **Template.** "Small office", "Medical office", "Church", "Retail", "Blank" (Photon edits the list; data, not code). A template is a
   phone-system document with blanks: business hours, a main menu or not, an "Everyone" ring group, extension range, voicemail to email,
   music on hold. Partners can save their own templates, and can **clone** an existing customer's setup.
3. **Sites.** The directory's sites are listed; each needs an emergency address. PhotonVox fills it from the site's address and validates it
   (§11); the integrator fixes it if the validation suggests a correction. A site with no validated address cannot get phones.
4. **Numbers.** Pick from Photon's stock in the right area code (instant), or request a port (tracked, §10). Each number gets an outcome:
   "rings the main menu", "rings Front desk", "rings Pastor (direct line)".
5. **Hours.** Open hours per site and a holiday calendar (US federal holidays offered as a default).
6. **Publish.** PhotonVox compiles the document (§8), writes FusionPBX through the adapter, checks it with a test call on the engine itself (a
   synthetic call through the new routes that never leaves the engine), and shows "Ready".

### Users

- **Bulk import:** paste rows from a spreadsheet or upload a CSV: name, email (for voicemail), optional extension (else the next free one),
  site, optional direct number, optional phone MAC. A review screen shows what will be made and every problem before anything is created.
- **One at a time:** name and site; everything else defaulted.
- A user is PhotonVox's own record (decision 15). "Invite to sign in" links them to a PhotonID person later (through the directory's
  invitation, once the directory lets products invite: suite §5 phase 2; until then the partner invites in the directory).

### Phones

- **On site, by barcode** (§13): scan, choose the user, done. Or scan a pile of boxes first and assign them from a list.
- **In the office:** type or paste MACs and serials, assign users; phones set themselves up wherever they are plugged in.

### Day to day

Change an outcome, hours, a holiday, a user's direct number, move a phone to another user (the old user's password is rotated, the phone
re-provisions), reboot or factory-reset a phone (GDMS tasks), see status. Every change goes through the same compile and publish, so it is
the same quality every time.

---

## 4. The big picture

```
 SITE                              PHOTONVOX CLOUD                                   ENGINE INSTANCES (Photon's)
                                                                                     
 integrator's phone ──HTTPS──▶  vox-web ─▶ vox-api ── compile + adapter ──mgmtnet──▶ instance A: HTC central office (FusionPBX + FreeSWITCH + vox-agent)
  (camera: barcode)                 │         │                                      instance B: … (more as needed; DC10 standby in R2)
                                    │         ├── GDMS API (device, SIP account, template, tasks) ◀── GDMS status pushes
 Grandstream phone ──HTTPS──▶ GDMS (settings on power-up)                                 │
 Grandstream phone ──SIP/TLS + SRTP──────────────────────────────────────────────────────▶ the instance of its phone system
                                    │         ├── upstreams' APIs where they exist (HTC: §22)
                                    │         └── PhotonConsole feed, PhotonID directory sync
                                  vox-worker: status collection, fraud breaker, drift checks, upstream jobs
                                                                             instances ◀──SIP──▶ HTC (and later upstreams); partner trunks (R2)
```

| Piece | What it does | Stack |
|---|---|---|
| **vox-api** | Directory copy and authorization; customers, phone systems, users, phones, numbers, flows, emergency addresses; the compiler and the engine adapter; GDMS calls; the GDMS push receiver; the Console feed | FastAPI + Postgres 16 |
| **vox-worker** | Status collection (engines, GDMS), drift checks, the fraud breaker, retries of half-finished enrollments, upstream jobs | same image |
| **vox-web** | The integrator's app (desktop and phone equally first-class, suite §6) with the barcode scanner; the customer admin's small portal | React 19 + Vite + `@photon/ui` |
| **vox-agent** | On each instance: status, cache flush and reload after a publish, the synthetic test call, the fraud breaker's hang-up | systemd service; successor to `photon-fpbx-shim` |
| **engine instance** | FusionPBX + FreeSWITCH: calls, voicemail, menus, ring groups | Debian, in an LXC (colo) or a VPS |
| **vox-gateway** (phase A) | Beside each instance: the PhotonVox app's signaling and push, registering each app device to its extension; coturn beside it (§18a) | Go |

**Calls never depend on the PhotonVox app or on GDMS.** With vox-api down, phones keep calling; with GDMS down, phones keep the settings
they have and keep calling; only changes wait.

---

## 5. The engine: FusionPBX, several instances

### Keep FusionPBX (decision 2)

Weighed in revision 1 and unchanged: replacing it (FreeSWITCH alone configured by PhotonVox, a Kamailio-based platform, or a licensed UCaaS
platform) would cost years or per-seat fees and move live customers, while FusionPBX already has multi-tenant domains, voicemail, menus,
ring groups, schedules, queues and conferences under an open-source license (MPL 1.1, to confirm for the installed versions). What changes in
revision 2 is that **PhotonVox now writes nearly all of FusionPBX's configuration**, not a few settings, which makes the adapter the heart of
R1. Look again at replacing FusionPBX if the adapter has to reproduce too much of FusionPBX's page logic, if upgrades keep breaking it, or when
active/active is needed (§16).

### The adapter and the agent

- **`app/engine/` is the only code that knows FusionPBX.** It takes the compiled phone system (§8) and writes it as FusionPBX objects:
  domain, extensions and voicemail boxes, ring groups, menus (IVR), time conditions, inbound destinations with their dial plans, outbound
  routes, gateways, caller-ID settings, the 911 route. Every object it writes is recorded in PhotonVox (`engine_object`: kind, FusionPBX uuid,
  the hash of what was written), which is how drift is found and how a phone system is removed cleanly.
- **Writes go to FusionPBX's database** with a role limited to the tables the adapter writes, in one transaction per publish, followed by
  vox-agent deleting exactly the cache entries the publish touched (FusionPBX 5.5.12 has no write API: SPIKES §1d). Built and proven on
  staging in Step 3 (`app/engine/`): a pure builder makes every row and dial plan from the plan, each in the phone system's domain with ids
  derived from the phone system's id; the writer **upserts** PhotonVox's columns only (what phone users set, such as call forwarding, survives),
  removes what the previous publish wrote and this one does not, generates a SIP password or PIN only for a new row, and returns the manifest
  that becomes `engine_object`. A new domain is seeded by FusionPBX's own `upgrade.php --defaults` through vox-agent. The connection uses a
  UTF-8 client encoding (FusionPBX's database is SQL_ASCII).
- **Each object is written exactly as FusionPBX's own page would** (the known trap: an inbound number needs a destination row consistent with its
  dial plan, or calls drop silently). Every kind of write has a test on a staging instance of the same version, ending in a real SIP call.
- **Publish is checked**: after writing, vox-agent places a synthetic call through each new inbound route and the 911 route's selection
  (stopping before the call leaves the engine), and PhotonVox shows "Ready" only when they pass. A failed publish restores the previous
  version of the phone system (PhotonVox keeps every published version).
- **Drift:** the worker compares what FusionPBX holds with `engine_object` hashes every few minutes. A difference (someone edited FusionPBX by
  hand) is shown on the phone system ("changed outside PhotonVox") and replaced by the next publish (decision 5). Objects PhotonVox did not
  write are left alone and listed.
- **vox-agent** (one per instance) offers fixed operations only, signed (`X-PhotonVox-Signature: t=…,v1=…`, five minutes' skew, no replays)
  and over mgmtnet: status (version, profiles, gateway states, registrations), cache deletes, gateway rescans, ACL reloads, seeding a new
  domain, the post-publish check's synthetic calls; channels and hanging up a call arrive with monitoring (Step 5). The event socket never
  leaves localhost. Built in Step 3 (`agent/`): Python 3's standard library only, run by systemd as `www-data` with the system read-only
  except FusionPBX's cache and FreeSWITCH's own directories, no capabilities.

### Several instances (decision 3)

- **`pbx_instance`**: name, where it is (site, region), its role (`active`, `standby`, `draining`), management address over mgmtnet, the
  adapter's database credentials and the agent's secret (encrypted), its public SIP names, its upstream connections, capacity figures
  (phone systems, registrations, concurrent calls), FusionPBX and FreeSWITCH versions, and its standby (R2).
- **Placement:** a new phone system goes to an active instance in its organization's `home_region` with room (the integrator never chooses;
  platform staff can). Moving a phone system to another instance is a planned operation (the same steps as §17's takeover: build on the
  target, move phones by editing the GDMS SIP server, move numbers at the upstream).
- **Each instance has its upstream gateways** (Photon trunking), generated by PhotonVox in the instance's default domain, as today's HTC
  gateway is; phone systems' routes refer to them.
- **Photon staff** see instances on the Platform page: health, load, versions, drift, and which phone systems each holds.
- **Partners do not run instances** (decision 3); partner-run FusionPBX servers can be monitored by PhotonConsole as they are today.

---

## 6. Tenancy: organizations, sites, phone systems, users

```
directory organization ──1:1── phone_system ── on one pbx_instance; one FusionPBX domain
        │                         ├── extension ── phone_user (optional) ── phones
        └── site ◀────────────────┼── phone ── site, emergency location, GDMS site
                                  ├── number ── site (for caller ID and 911)
                                  └── flows (menus, ring groups, schedules)
```

- **One phone system per organization** (decision 4), spanning its sites; a second one only on request (franchises). A FusionPBX domain belongs to
  exactly one organization (unique per instance).
- **Domain names:** new ones `<short random id>.sip.photoninfra.xyz`; existing ones keep theirs (`huepc.pbx-pa.photoninfra.xyz`).
- **Phone users** (decision 15): `phone_user` holds name, email, site, extension, optional `person_id` (a directory person who can sign in).
  A user can have several phones (a desk phone and a cordless handset) on one extension.
- **`home_region`** from the directory is kept and used for placement (§5).

---

## 7. Roles and partners

- **Integrators are partner staff** (or Photon staff as partner "Photon") acting through **partner grants**: suite §5. Their role in PhotonVox
  comes from the partner grant, applies to every customer of the partner, and shows to the customer as "Partner support".
- **PhotonVox roles** (decision 15), published to the directory:

| Role | Site-limitable | Can |
|---|---|---|
| `owner` | no | Everything for the organization, including numbers and emergency addresses |
| `admin` | yes | Build and change the phone system: users, phones, flows, hours, numbers' outcomes, enrollment; for their sites when limited |
| `user` | yes | Their own voicemail settings and greetings, forwarding within the allowed class, their phones' status |

  A partner technician typically holds `admin` through the partner grant; a partner owner or admin holds `owner`. A customer's office
  manager is a direct `admin`. `supervisor` arrives with call queues (R2).
- **Sensitive capabilities** (suite §5): `vox.number.port`, `vox.number.release`, `vox.e911.edit`, `vox.forwarding.external`, later
  `vox.recording.listen` and `vox.call.monitor`.
- **Templates belong to partners** (and Photon's to everyone); clone works only within a partner's own customers.
- **White-label:** nothing customers see names the carrier, the engine or GDMS; phone screens show the partner's or Photon's name through the
  suite's `branding` lookup (pushed as a GDMS template setting).

---

## 8. Routing, abstracted: outcomes and the compiler

**Integrators never see dial plans, outbound routes, gateways, caller-ID rules or inbound destinations** (decision 5). They see outcomes; the
compiler turns them into FusionPBX.

### The phone-system document (what the integrator edits)

```json
{
  "sites": {"<site id>": {"emergency_location": "<id>", "caller_id": "+17245550100", "hours": "office", "unreachable": "voicemail"}},
  "hours": {"office": {"mon-fri": ["08:00-17:00"], "holidays": "us-federal"}},
  "numbers": {
    "+17245550100": {"site": "<site id>", "open": {"menu": "main"}, "closed": {"voicemail": "general"}},
    "+17245550123": {"site": "<site id>", "always": {"user": "<pastor>"}}
  },
  "menus": {"main": {"greeting": "<file>", "options": {"1": {"group": "office"}, "2": {"user": "<pastor>"}, "0": {"group": "everyone"}}, "timeout": {"group": "office"}}},
  "groups": {"office": {"members": ["<user>", "<user>"], "strategy": "simultaneous", "then": {"voicemail": "general"}}},
  "users": {"<pastor>": {"extension": "102", "direct_number": "+17245550123", "show": "direct"}},
  "calling": {"class": "national", "spend_limit_usd": 50}
}
```

Integrators set these through screens, never as JSON; the document is what PhotonVox stores, versions, compiles, clones and templates.

### What the compiler generates (and nobody edits)

| Outcome | FusionPBX objects |
|---|---|
| a number rings something, by schedule | an inbound destination, its dial plan, a time condition, the target |
| a menu, a group, a voicemail box | IVR menu, ring group, voicemail, with the outcome's options |
| "this site's calls show this number"; "this user shows their direct line" | outbound caller ID per extension (effective and outbound caller-ID name and number), from the site default and user overrides; **only numbers the organization holds** |
| which trunk a call uses | outbound routes per call class (§15) with the instance's upstream gateways in Photon's order (§9); in R2, partner trunks for numbers they hold |
| 911 | one locked emergency route per site (§11) |
| blocked destinations | **one locked block route right after the emergency routes** (§15a): Photon's default list less what the organization allows, plus its own numbers and prefixes |
| unreachable phones | each extension's "not registered" forwarding to the site's choice |
| internal dialing | extension range, feature codes (voicemail `*97`, etc.), consistent in every phone system |

- **Deterministic:** the same document compiles to the same objects; a template applied twice gives the same phone system.
- **Validated before writing:** every number has an outcome; every site with phones has a validated emergency address and an emergency number;
  caller ID only from held numbers; no loops (a group whose "then" points back at itself); extension ranges do not collide with feature codes
  or 911/933/988/311-style service codes.
- **Versioned:** each publish is a version with who and when; "undo" publishes the previous one.

### 8a. Greetings: text-to-speech at publish (decision 30)

A menu's greeting (and any message the plan speaks) is text in the document. At publish, PhotonVox has it spoken once by the text-to-speech
provider, at the engine's rates (8 kHz mu-law for G.711, 16 kHz for wideband), stores the files with the version and writes them to the engine
with the rest; the engine plays files and never calls the provider. The audio is keyed by the text, voice and provider, so a republish reuses
it, and a recorded greeting (uploaded or recorded by phone) overrides it. The staging engine has no speech module, so until this is built a
menu answers silently (SPIKES §1f). Provider comparison (2026-11-13, list prices; a listening test on real phones decides):

| Provider (voice tier) | Phone formats | Per million characters | Notes |
|---|---|---|---|
| Google Cloud TTS, Chirp 3 HD | 8 kHz mu-law, 16 kHz PCM; IVR audio profile | $30 (first 1M a month free); Neural2 $16, Standard $4 | SSML (say-as, phoneme), custom pronunciations; does not log the text; **recommended** |
| Azure AI Speech, Neural | 8 kHz mu-law/PCM, 16 kHz PCM, G.722 | $15 (HD $22; 0.5M a month free) | mature SSML; code of conduct asks that synthetic voices be disclosed; **runner-up** |
| Amazon Polly, Neural / Generative | 8 kHz mu-law, 16 kHz PCM | $16 / $30 | full SSML and lexicons; caching and replay allowed |
| Telnyx TTS (own, Ultra, or Polly/Azure through it) | depends on the voice: Polly and Azure voices at 8/16 kHz | $3 (own) to $48; Polly Neural $24 | one vendor with other Telnyx services; Ultra's formats and output terms not documented |
| ElevenLabs, Flash / Multilingual | 8 kHz mu-law, 16 kHz PCM | $40 / $80 (credit plans) | most natural; weak SSML on newest models; OEM terms for resale; free plan non-commercial |
| Deepgram Aura-2; Cartesia Sonic | 8/16 kHz mu-law and PCM | about $30; $38–65 | no SSML documented (Deepgram); not compared further |
| OpenAI TTS; PlayHT | — | — | OpenAI's speech models close 2027-01-06; PlayHT closed: not candidates |

---

## 9. Trunking

### PhotonVox Trunking (Photon's, the default)

- **Upstreams:** Hickory Telephone (HTC) first, IP-authenticated, on-net from the colo instance (decision 7). Further upstreams are added only when
  HTC cannot provide something needed; what R1 needs that HTC might not provide is a question (§22): numbers outside HTC's area, toll-free,
  ordering and porting by API (or a fast manual process), E911 record updates, CNAM, and (R3) texting.
- **Failover and least cost, by Photon:** for each call class, the compiler orders the instance's upstream gateways by Photon's rate table and
  health (the cheapest healthy upstream first, the others after it as failover). The order is a platform setting, the same for every phone
  system on the instance, invisible to partners. Rebuilt on every publish and whenever platform staff change an upstream.
- **Inbound:** each upstream delivers its numbers to the instance that holds the phone system (and in R2 to its standby on failure).
- **The customer sees "PhotonVox Trunking"** (decision 8), or the partner's label.

### Partner trunks (R2; decision 9)

A partner may add its own VoIP trunk (credentials or IP authentication) and make it available to some of its customers.

| Question | Answer |
|---|---|
| Where it lives | A gateway generated in that customer's FusionPBX domain (not the instance's default domain), so no other customer can route over it |
| Which numbers | Numbers the partner adds as "on partner trunk X". Photon neither orders, ports nor files E911 records for them |
| Which calls use it | **A call goes out the trunk that holds the number it shows as caller ID.** A site whose caller ID is a partner-trunk number sends its calls over that trunk; a user who shows a Photon number uses Photon trunking. Carriers check caller ID against the numbers they hold, so this is also what keeps calls from being blocked |
| Failover | If the partner trunk does not answer, local and national calls retry over Photon trunking (on by default, per organization switch; caller ID attestation may be lower). International never fails over |
| 911 | **Never on a partner trunk.** Each site has a Photon emergency number with an E911 record at its validated address, even if all its other numbers are on partner trunks; 911 calls show that number and leave by Photon trunking. The PSAP's call back rings the site's chosen outcome |
| Fraud limits | The same call classes and spend breaker as Photon trunking (the partner pays the carrier, but a compromised extension is still a compromise); the partner sets the limit, Photon sets the ceiling |
| Monitoring | The trunk's registration or reachability and its calls appear on the pane like Photon's, attributed to the partner |
| Billing | Minutes on partner trunks are metered for visibility, not charged as Photon minutes; the platform fee applies |

---

## 10. Numbers

- **`number`**: E.164, organization, site, holder (`upstream:htc`, later others, or `partner_trunk:<id>`), state (in stock, assigned, porting
  in, releasing), outcome, caller-ID name, emergency use.
- **Photon keeps a stock of numbers** per area code on its upstreams, so assigning one during a deployment is instant even where ordering is a
  manual process with HTC; platform staff refill the stock (and the stock level is watched).
- **Porting in:** a tracked request (numbers, losing carrier, account and PIN, authorized name, signed authorization, wanted date), done with
  HTC or another upstream, with test calls on the day. In R1 the tracking is in PhotonVox and the work is by hand; API ports come with an
  upstream that has one (R2).
- **Releasing:** a 30-day hold, then back to stock or to the upstream.
- **Caller ID:** an extension may show only numbers its organization holds; STIR/SHAKEN signing is the upstream's.

---

## 11. Emergency calling (911), locked

**911 must work from every phone, during a billing restriction, during a fraud block and during a failover, and no user can break it**
(decision 6).

- **Generated, per site:** the compiler writes each site's emergency route; it is not an outcome anyone edits. Dialing **911** works without a
  prefix, and **9-911** too (Kari's Law); **933** (address read-back) is allowed where the upstream supports it.
- **Address:** each site has one or more emergency locations (building, floor, room) validated against the 911 database through the upstream
  (MSAG). Validation is part of the new-customer flow; a site has no phones until it passes.
- **Number:** each site has an **emergency number** held on Photon trunking, registered with the upstream at that address. A 911 call from
  any phone at the site shows that number and leaves through Photon trunking (HTC for numbers in its area: native 911 routing to the local
  PSAP). Which phone is at which site comes from the phone's enrollment (its site), never from free text.
- **Notification (Kari's Law):** every 911 call notifies the organization's designated contacts at once (email, and on screen in PhotonVox),
  with the phone, user and location; it never delays the call. Photon staff are told too (a record that one happened).
- **Moved phones:** a phone that registers from a public address that is not its site's known address is flagged on the pane ("this phone may
  have moved: its 911 address may be wrong"). The PhotonVox app hands 911 to the cellular network on phones, and locates devices without cellular automatically (§18a).
- **Customer notice of VoIP 911 limits**, accepted and recorded when a phone system is created (§19).
- **Never place a real 911 test call** without the PSAP's agreement; 933 and the engine's synthetic check are the tests.
- With HTC: how emergency records are created and changed (by hand, with what turnaround) and how 911 will be routed after HTC's softswitch
  moves to Ashburn are questions (§22).

### 11a. Numbers' 911 addresses with the carrier (decision 31)

Hickory keeps, by hand, which address each number is at. PhotonVox therefore holds the truth and keeps Hickory in step:
- **Per number:** `emergency_number` holds each number's address (its site's validated emergency location), the address the carrier last
  confirmed, and a state: **unconfirmed** (changed, not yet asked), **requested** (asked, waiting), **confirmed**.
- **After each publish** PhotonVox compares the numbers the organization holds with what is registered: a new number, a number moved to another
  site or address, a number given up. Any difference becomes one **carrier request** listing each number with its action (add, change, remove)
  and the full address; an earlier request not yet sent is folded into it.
- **For Hickory:** the request is sent as a plain email to Hickory's 911 contact (Postmark, from Photon's address, the request id in the
  subject, one line per number with the address as Hickory needs it), or staff note a ticket number if Hickory prefers its portal. Photon staff
  see open requests on the Platform page, record Hickory's answer (**confirmed** or **rejected** with a note) and the numbers follow. A request
  open longer than Hickory's usual turnaround is flagged.
- **Shown:** the number is marked unconfirmed wherever it appears (numbers list, the site, the phone system's overview) until confirmed, and
  Photon staff get a daily summary. 911 keeps routing meanwhile (decision 31's recommendation), with the address the carrier last confirmed.
- **Carriers with an API later:** the same request record is submitted and polled by the carrier's adapter (`app/carriers/`), so only the
  sending and the confirmation change.

---

## 12. Grandstream GDMS

### What the GDMS API allows (read 2026-11-13)

Source: Grandstream's API reference at `https://doc.grandstream.dev/GDMS-API/EN/` (an apiDoc site; its data file was read directly, since
the page itself needs JavaScript): **API v1.0.0 released 2019-10-18, v1.1.0 released 2020-12-05**; and the knowledge-base article "GDMS API
Guide" (updated 2024-03-15). Nothing was called; there is no GDMS API account yet. What follows is what the documents say; Step 0 proves it.

| Area | What the API offers | Notes |
|---|---|---|
| **Access** | Enable "API Developer" in the GDMS web app (Others → API developer) to get a client id and secret. Token by OAuth2 *password* grant (`/oauth/token`, with a GDMS user's name and a hash of its password), refreshed hourly | US host `www.gdms.cloud`, EU `eu.gdms.cloud`; the reference also shows `api.gdms.cloud` (Step 0 checks which). Every call carries `access_token`, a millisecond `timestamp` and a `signature`: SHA-256 over `&access_token=…&client_id=…&client_secret=…&timestamp=…&` (plus the SHA-256 of the JSON body for calls with one). Only requests inside a time window are accepted |
| **Organizations** | List only | **No create**: organizations are made in the GDMS web app (decision 11) |
| **Sites** | List, details, **add** (with a parent site: sites nest), edit, delete | PhotonVox makes partner → customer → site trees |
| **Devices** | **Add by MAC + serial number** (both required; batches up to 100; a site is required), list (with status), details, edit (rename, move to another site), delete (batches up to 100) | List returns per device: model, firmware, public and private IP, **status (online / offline / abnormal)**, **account status (none / abnormal / normal)**, DND, last configuration time, site, whether its configuration is synchronized and why not. Add refuses a device that **exists in another GDMS account** (error 30011), a bad serial (30010), an unsupported model (30012) |
| **SIP servers** | Add (name, server address, outbound proxies, DNS mode A/SRV/NAPTR, transport UDP/TCP/TLS, NAT traversal, voicemail access number, failover/secondary servers), edit, list, delete | One per phone system: the SIP domain, with the instance's names as proxies |
| **SIP accounts** | Add (batches up to 100: user id, authentication id and password, display name, voicemail number, under one or more SIP servers), edit, list, details, delete | |
| **Line assignment** | `device/account/configuration`: put SIP account X on account index N of a phone (variants for general phones, DP cordless bases with handset mapping, HT adapters' ports); `device/account/status`: per line, registered or not and call state | |
| **Configuration** | **Model templates** and **group templates** (made in the web app; the API lists them and pushes one to listed MACs); **per-device or per-site XML configuration** (P-value settings), applied immediately or merged | Photon's defaults (time zone, NTP, codecs, branding, security settings) as model templates; per-phone details as XML |
| **Tasks** | Reboot, factory reset, firmware upgrade (now or scheduled); list, delete | Recurring tasks not supported |
| **Push** | A callback URL plus subscriptions: device status (online, offline, abnormal), SIP account status per line, alerts (registration failure, factory reset, reboot, task failure, back online, offline) | The documents show no signature on the callbacks, so PhotonVox treats a callback as a notice and confirms by asking GDMS (notify, then pull) |
| **Channel management** | Distributor functions: list devices held by a channel, assign devices to sub-channels or to a customer's organization, reclaim, return | Relevant if Photon buys phones as a GDMS channel (§22) |
| Not documented | Rate limits; webhook signing; the zero-touch path itself (how a factory-new phone finds GDMS) | Step 0 measures and asks Grandstream; Grandstream phones are documented elsewhere to contact Grandstream's provisioning service at first boot, which hands GDMS-registered devices their settings: proven with a real phone in Step 0 |

### How PhotonVox uses it (decision 10)

- **Photon's GDMS account**, with a dedicated API user; **one GDMS organization per environment** ("PhotonVox", "PhotonVox staging"), made once by
  hand. Under it PhotonVox makes **sites** `partner / customer / site` (decision 11). Partners and customers never log into GDMS.
- **Per phone system: one GDMS SIP server** (server = the SIP domain; outbound proxies = the instance's SIP names; DNS SRV; TLS where the model
  supports it).
- **Per extension: one GDMS SIP account** (user id and authentication id = the extension, the password from FusionPBX, display name = the
  user's name), under that SIP server.
- **Per phone:** add the device (MAC, serial, the site's GDMS site), put the user's SIP account on line 1 (more lines for shared lines later),
  push the model template, and push the per-phone XML (BLF keys for the user's group, the phone's label).
- **Photon's model templates** per supported model (security: admin password set, web interface limited, SIP TLS where supported; time zone
  from the site; branding), kept in GDMS by platform staff and referenced by id in PhotonVox.
- **Status:** the GDMS push subscription (device status, line status, alerts) wakes the worker, which confirms with `device/list` for those MACs;
  a full `device/list` every few minutes is the backstop. Stored as phone status and shown on the pane (§14).
- **Removal:** delete the device in GDMS, rotate the extension's password (FusionPBX and the GDMS SIP account; other phones of that user
  re-provision), optionally a factory-reset task first.
- **Credentials:** the GDMS client secret, API user and its password hash are secrets (encrypted at rest, never logged); the API user is used for
  nothing else. **GDMS holds the SIP passwords of the phones it provisions**: accepted (decision 10), mitigated by one password per extension
  that PhotonVox can rotate at any time, registration limits, and the fraud breaker (§15).
- **Supported models:** the Grandstream models Photon stocks (question §22); PhotonVox keeps a model table (lines, BLF keys, template id,
  whether TLS works), so an unsupported model is refused at scan time, not at power-up.

---

## 13. Barcode enrollment

**One scan and one tap, then the phone works when it is plugged in** (decision 12).

1. The integrator opens PhotonVox on a phone or tablet, chooses the customer and site (remembered), and taps **Add phones**.
2. **Scan:** the camera reads every barcode in view continuously; PhotonVox picks out the **MAC** (12 hex digits; a Grandstream prefix) and
   the **serial** (Grandstream's format) from the box label or the phone's own label, in one pass. Model comes from GDMS once added, or from
   the label's model code if present. A beep and a card: "GRP2602 · MAC …:16:CF · SN 20EY…".
3. **Assign:** pick a user (search as you type), or **New user** (name; extension filled in), or **Unassigned** (a lobby phone on a new
   extension, or assign later). One tap: **Add**.
4. PhotonVox does, in order, each step idempotent by MAC and recorded so a retry continues where it stopped:
   - make sure the user's extension exists in FusionPBX (create and publish if new);
   - make sure the GDMS site and SIP server exist; make or update the user's GDMS SIP account;
   - add the device in GDMS (MAC, serial, site); assign the account to line 1; push the model template and the phone's XML;
   - record the phone in PhotonVox (site, user, emergency location = the site's).
   The card turns **Ready** in a few seconds. Errors are said plainly, with what to do: "This phone belongs to another GDMS account: ask the
   seller to release it" (30011); "Serial does not match this MAC" (30010); "This model is not supported yet".
5. **Power-up:** the phone fetches its settings and registers. The pane shows it live: *added → online in GDMS → registered on the phone
   system*, typically a minute or two after power is connected. If it stays offline, the card says what is missing (no network, wrong VLAN, or
   not yet powered).

- **Scan many, assign later:** a pile of boxes scanned in a row becomes a list of unassigned phones; assign by dragging users onto them, or
  from the bulk import's MAC column.
- **In the browser:** the camera needs HTTPS and permission; the browser's `BarcodeDetector` where it exists (Chrome on Android), a bundled
  decoder elsewhere (Safari on iOS has no `BarcodeDetector`; a WebAssembly or JavaScript decoder such as ZXing). Tested on Connor's phones and
  a tablet in Step 0 with real Grandstream boxes and labels (which barcodes they carry is a question until then).
- **The rule that cannot be skipped:** the site must have a validated emergency address before its first phone is added (§11). The scan
  screen says so at the start, not after the scan.

---

## 14. Monitoring: one pane, and PhotonConsole

### Collect once, in PhotonVox (decision 14)

PhotonVox is the only thing that talks to the engines (through vox-agent and the database) and to GDMS. PhotonConsole stops polling FusionPBX
directly and reads PhotonVox's feed instead. Nothing is collected twice.

### The pane (the integrator's tool)

| Level | What it shows |
|---|---|
| **All my customers** (partner) | One line per customer: phone system state, phones offline / total, trunks, open problems, last change. Problems first |
| **A customer** | Per site: phones (GDMS status, line registration, model, firmware, IP, user), numbers and their last inbound call, emergency address state, calls in progress, drift ("changed outside PhotonVox"), the last publishes |
| **A phone** | GDMS status and its history, each line's registration from GDMS **and** from the engine, last configuration, public address, actions: reboot, re-provision, factory reset, move to another user |
| **Platform** (Photon staff) | Instances (role, health, load, versions, standby lag in R2), upstream gateways' state per instance, GDMS API health, the fraud breaker's state per organization, stock of numbers |

**Two sources agree or the pane says why not:** GDMS online + engine registered = working; GDMS online + engine not registered = a
configuration or credential problem (PhotonVox offers "re-provision"); GDMS offline + not registered = the phone or the site's network or power;
**every phone at a site offline together = the site's internet** (said as one problem, not twenty: the camwatch rule, "whose problem it is").

**Built-in alerts** (a fixed small set, not a rule engine): a site's phones all offline; an instance or an upstream down; the fraud breaker
tripped; a 911 call; an emergency address invalid; a phone offline more than a set time (per site, off by default). Sent to the partner's
contacts for the customer by email (Postmark) and shown on the pane.

### PhotonConsole

- PhotonVox publishes the suite's read-only feed, `GET /integrations/console/v1/phone-systems` (per-organization token, scope `vox:read`,
  naming the organization's directory id; PhotonConsole refuses a document naming another organization). It carries today's point keys
  (`ext_<n>_registered`, `active_call_count`, `cdr_count_7d`, `enabled_extension_count`, `concurrent_calls_peak_month`, per trunk
  `trunk_<key>_minutes_today` / `_month` / `_month_inbound` / `_month_outbound` / `_channels_in_use` / `_channels_peak_month`) so existing
  rules and dashboards continue, plus per phone `phone_<id>_online` and `phone_<id>_registered` (from GDMS and the engine).
- **Who does what:** PhotonVox shows phone systems and sends the fixed phone alerts above; PhotonConsole shows phone data beside the building's
  other systems and runs any custom rules a customer wants ("if the lobby phone is offline after hours, page the on-call tech"). PhotonConsole
  never polls FusionPBX or GDMS; PhotonVox never grows a rule engine.
- **PhotonConsole's change** (a `photonvox` poller replacing `photon_pbx`, point keys kept): a PhotonConsole code change, with Connor's go-ahead
  (BUILD-GUIDE Step 5). Its `photon_ro` database access and the shim are retired after it.
- Photon's own platform health goes to Photon's own PhotonConsole organization through the same feed.

---

## 15. Security and toll fraud

Defaults for every organization, applied to the live engine first (decision 17):

| Defense | How |
|---|---|
| **Call classes** | `local`, `national` (NANP excluding the high-cost Caribbean and other NANP area codes billed as international, the one-ring-scam targets), `toll_free`, `international` (off; on per country by an owner, audited), `premium` (900/976 and premium international ranges: always off). Enforced in the generated outbound routes, not only in the app |
| **Spend breaker** | vox-worker prices calls in progress (from vox-agent every 10 s) and finished ones; at an organization's daily limit, outbound calls stop (911 never), costly calls in progress are hung up, Photon staff and the partner are alerted. Upstreams' own limits as a second line |
| **SIP passwords** | Random, 24+ characters, one per extension, never shown to anyone, rotated by PhotonVox on demand and when a phone is removed |
| **Registration limits** | Where a site's public address is known, its phones' extensions may register only from it (FusionPBX per-extension address limits), generated by the compiler; the engine's event guard blocks repeated failures; SIP scanners are dropped at the firewall |
| **Voicemail** | PINs of 4 digits (Connor, 2026-11-13), random at creation, emailed to the user; no outdial or callback; lockout after repeated wrong PINs |
| **Forwarding** | Outside forwarding obeys the call class; changes audited and emailed to the user |
| **No DISA** | No dial-in-then-dial-out features are generated |
| **Engine exposure** | Only SIP, RTP (and WSS in R2) are public. FusionPBX's screens, Postgres and vox-agent only over mgmtnet; staff screens need MFA. FusionPBX's own phone provisioning is switched off for GDMS-provisioned phones |
| **GDMS** | The API user and secret encrypted; the GDMS web login for staff with MFA; phones' admin passwords set by Photon's template; the phones' web interface limited |
| **Caller ID** | Only held numbers; signed by the upstream |

### 15a. Call blocking (decision 29, 2026-11-13)

A **Call blocking** page in each organization's settings, for the partner (all its organizations) and the organization's admins.
- **Blocked by default**, from **Photon's default list**: international (until switched on per country, §15), premium (900, NXX 976, premium
  international ranges), the high-cost Caribbean and other non-US North American area codes, satellite and other high-cost ranges. Photon
  keeps the list current suite-wide (a versioned list on the Platform page; a change reaches every organization at its next publish, and
  PhotonVox republishes all of them when the list changes).
- **The partner or an admin can allow a category** (audited, and premium stays blocked unless Photon staff allow it), and **add or remove
  specific numbers and prefixes** (a number to block, or one to let through inside a blocked category).
- **Optional:** per-extension overrides (an extension allowed one category, or held to a stricter list); a **"call blocked" record** in the
  audit with an alert to the partner (repeated attempts from one extension are a fraud sign); **911 and 933 are never blocked**: the emergency
  routes come first, and the page refuses an entry that would match an emergency or service code.
- **The compiler emits it as one locked block route right after the emergency routes**: hang up with `CALL_REJECTED`, log a warning, and
  vox-agent reports the attempt (as the live engine's hand-built `Block-premium-and-Caribbean` route does today, §17a). It sits beside the
  call classes: classes decide what an extension may dial, the block route removes the riskiest destinations for everyone.
- **Inbound blocking** on the same page, later: block a caller's number, block anonymous callers (to a message or voicemail), and spam scoring
  (from the upstream's attestation and a reputation feed) after that.

Also: SIP over TLS and SRTP where the model supports it; secrets at rest with Fernet (`SECRETS_KEY`); CPNI rules for call records; a written
procedure for lawful requests; RLS, tenant-isolation tests on every route, critical modules at 100% branch coverage (BUILD-GUIDE §7).

---

## 16. Hosting, redundancy and the ASN plan

| What | Where |
|---|---|
| **Instance A** (today's engine, then a rebuilt one) | The colo in HTC's central office (Proxmox `py`), on-net with HTC |
| **More instances** | Added as needed: in the colo, or at Equinix DC10 (Misaka) |
| **Standby for instance A** (R2) | DC10: FusionPBX's Postgres a streaming replica, files synced, promoted by a runbook (target 15 minutes), drilled quarterly |
| **PhotonVox app** | Its own small VPS, Misaka Ashburn (decision 18), standalone Caddy like PhotonGuard; reaches instances over mgmtnet |
| **Staging instance** | A staging LXC in the colo, same versions as production, isolated from production phones. **Connor's rule (2026-11-13): it never uses or reaches the HTC trunk, has no carrier gateways at all, and its outbound SIP to the internet is blocked**; a SIPp "upstream" on LXC 800 stands in for every carrier |

- **Stages** (the suite's): Stage 1 now (backups of each instance's database, configuration and voicemail; a rebuild drilled on staging;
  phones on names); Stage 2 in R2 (warm standby at DC10); Stage 3 (active/active with Kamailio in front of live instances) only when a
  contract needs it.
- **Before the standby exists, a colo outage stops calls** for phone systems on instance A. The only mitigation before then is at the
  upstream: per-number failover destinations, if HTC offers them (§22). The colo's own single points (one cable, one router, one HTC switch;
  suite OPERATIONS §5.5) make the standby PhotonVox's most important R2 item.
- **Phones point at names:** the GDMS SIP server for each phone system lists the instance's names (`sip-a.<infra>`, `sip-b.<infra>`, DNS SRV
  where the model supports it). Moving a phone system or failing over changes DNS or one GDMS SIP server entry, and GDMS pushes it.
- **ASN plan** (suite OPERATIONS §5.6, pending ARIN): SIP and RTP stay unicast per instance with SIP's own failover; Photon's own addresses
  would make upstream allowlists and customers' firewall rules permanent and allow peering with HTC and Prizm; the /24 cannot be split between
  sites, so per-site IPv4 waits for the network design. PhotonVox depends on none of it.

---

## 17. Today's live customers

- **R1: monitored, not managed** (decision 16). PhotonVox adopts each live domain read-only (users, phones, numbers, call history, status),
  so it appears on the pane, and changes nothing in it. Toll-fraud defaults and backups are applied to the live engine (production changes,
  each with Connor's go-ahead).
- **R2: take over without downtime.** For each live domain: import its FusionPBX configuration into a phone-system document (what maps to
  outcomes; what does not is listed for a decision); compile it and **compare** with what is live, until the compiled version is equivalent; build
  it on the new instance; join an inter-instance trunk so calls for the domain reach whichever instance has its phones; add its phones to GDMS
  (if they are not already) and point them at the new instance; move its numbers at HTC; test; remove the old copy a week later. Connor's own
  domain first, HUEPC after a clean week. Each step has its way back; none takes a phone offline for longer than its re-registration.
- **LXC 600 retires** when no domain is left on it (backup kept 60 days).

---

## 17a. What the live engine holds (inventory, 2026-11-13)

Read with Connor's go-ahead by `scripts/inventory/engine.sh` and `host.sh` (read-only; run by the operator, reviewed beforehand, no errors).
The reports stay out of git (they name domains); these are the findings as counts.

| Area | Finding |
|---|---|
| Versions | FusionPBX 5.5.12 (installed with the FusionPBX install script), FreeSWITCH 1.11.1, PostgreSQL 18, Debian 12; Proxmox VE 9.1 (two nodes) |
| Container | 4 cores, 4 GB memory, 32 GB disk on the node's local LVM (16% used), unprivileged; Proxmox's firewall service is disabled cluster-wide (the container's own iptables, policy DROP, is what protects it) |
| Domains | 2: the one customer (HUEPC) and Photon's own test domain (empty: no extensions) |
| The customer | 10 extensions (all enabled), 10 voicemail boxes, 5 inbound numbers, 1 IVR menu, 0 ring groups, 0 queues, 0 conferences, 0 fax |
| Phones | 7 registered, all Grandstream (5 GRP2602G, 1 GRP2650, 1 HT801V2 analog adapter), **all from public addresses** (over the internet, not across HTC's network or a VPN), mostly UDP; **0 devices in FusionPBX**: the phones are not provisioned by FusionPBX (how they are, GDMS or by hand, is open: question 1) |
| Numbers | 1 of the 5 inbound numbers had no matching dial plan (calls to it dropped); **removed on 2026-11-13**, leaving 4, each with its dial plan |
| Call volume (30 days) | 123 inbound (122 answered, about 225 minutes), 41 outbound (40 answered, about 170 minutes), 27 internal; no recorded calls |
| Carriers | 2 gateways, **both owned by the test domain**, not the customer's and not global (the customer's outbound calls use them across domains): Hickory Telephone (IP-authenticated, its own `htc` SIP profile; carried all 41 outbound calls) and VoIP.ms (registering, failing, 0 calls: unused). **VoIP.ms and its disabled route were removed on 2026-11-13**; HTC is the only gateway |
| Dial plans | the customer: 3 outbound routes (2 enabled; the disabled VoIP.ms one since removed), inbound routes for its numbers, the IVR; also 9 dial plans left in an old context named after the server's own address (from the install, before the domains existed) |
| Toll-fraud exposure | **all 10 extensions have no call class (`toll_allow`) set**; voicemail PINs are 4 digits (Connor's choice: kept); SIP passwords are all 16+ characters; call forwarding off everywhere; no international calls in 90 days. **Outbound routes: 2 enabled, both North American only** (the operator read them, 2026-11-13; the second run's "international" was the inventory script counting the `\+1` of a North American pattern, since fixed), so **international dialing is not possible today**, call class or not. **Since 2026-11-13 a block route `Block-premium-and-Caribbean` (order 45, before the HTC routes)** hangs up with `CALL_REJECTED` and logs a warning for 900 numbers, NXX 976 and 21 high-cost Caribbean area codes (242 246 264 268 284 345 441 473 649 658 664 721 758 767 784 809 829 849 868 869 876); US territories (340, 787 and others), toll-free and ordinary North American numbers still pass. Tested with FreeSWITCH's regex; the regenerated dial plan holds it (SQL kept on CT 600 in `/root/photon-changes`). It is the hand-built form of §15a's block route |
| Provisioning, email, recording | FusionPBX provisioning not in use; voicemail to email not in use, and the mail settings have no SMTP host; call recording not in use |
| Protection | fail2ban and FusionPBX's event guard running; iptables policy DROP with 35 rules; NAT by FreeSWITCH's autonat. Listening: SIP on 5060 (internal), 5080 (external), 5082 (`htc`), web 80/443, and also PostgreSQL, SNMP, mail, the event socket and the status shim (whether only on private addresses, and what the firewall lets through, is not in the report) |
| **Backups** | At the inventory, Proxmox had no backup job for the container, and the only backup was FusionPBX's own daily job on the same disk (21 MB). **Since 2026-11-13 a Proxmox backup of CT 600 runs nightly** (02:15, keep 3) to the node's local storage, and **is copied nightly to the NAS** (01:30 Pacific, kept 30 days, each copy checked with zstd), so the backups are off the node. Not yet drilled: a restore onto staging (BUILD-GUIDE Step 2) |
| Container 601 ("kamailio") | stopped; unused |

**What it changes in this plan:**
- **§17 (takeover in R2) is small:** one customer, 10 extensions, 5 numbers, 1 IVR, 7 phones. The phones are not FusionPBX-provisioned, so moving
  them means adding them to GDMS (their MACs and serials, from the phones or GDMS if they are already there) and pointing them at the new
  instance's names. The broken number is fixed in the takeover if not before.
- **§15 on the live engine:** the routes are North American only, so international is closed, and the block route (2026-11-13) stops premium
  and high-cost Caribbean numbers. What remains for Step 2: call classes with `toll_allow` on every extension, and the block route generated
  by PhotonVox (§15a) in place of the hand-built one. The unused VoIP.ms gateway is gone (2026-11-13).
- **§16 Stage 1:** the nightly backup now leaves the node (to the NAS); what remains is the rebuild drill (BUILD-GUIDE Step 2), restoring it
  onto staging.
- **§9 and §5:** upstream gateways belong in the instance's global scope, generated by PhotonVox, never inside a customer's or the test domain.

The fixes on the live engine are being raised with Connor separately; nothing here changes it.

---

## 18. Later releases (designed, not in R1)

| Item | Release | Design notes kept from revision 1 |
|---|---|---|
| **The PhotonVox app** (browser, desktop, mobile softphone) | R2, phase A | §18a: one app and one calling engine; replaces the separate browser and mobile softphone items |
| **Voicemail and recordings in the app** | R2 | A PhotonVox B2 bucket (`prod/`, `dev/`, `test/`), vox-agent copies voicemail and uploads recordings; recording off by default, with a consent notice where law requires (Pennsylvania needs all parties' consent); every listen audited |
| **Metering** | R2 | `usage_day` per organization and meter (seats, phones, numbers, minutes by class and trunk, recordings); CDR rating against Photon's rate table; wholesale to partners; telecom taxes and fees decided before any invoice (§19) |
| **Call queues and supervisors** | R2 | FusionPBX call center as an outcome; the `supervisor` role |
| **Yealink** | R2 | Yealink's redirect service (RPS) or management cloud in place of GDMS, behind the same "phone" model |
| **Partners' own GDMS accounts** | R2+ | GDMS connection per partner; the same device flow |
| **Texting (SMS/MMS) and 10DLC** | R3 | Needs an upstream with messaging (§22). Brands and campaigns per organization through the upstream; shared inboxes and personal numbers; STOP/HELP enforced; MMS media in B2; Photon's own campaign for suite notifications; in the PhotonVox app too |
| **Team chat** | R3 | Built in, one conversation model with texting; presence from registrations; in the PhotonVox app too |
| **PhotonEdge service** | later | Optional call-quality probes and phone discovery on sites that have a PhotonEdge; survivability only if a customer pays |

---

## 18a. The PhotonVox app (phase A)

**Connor (2026-11-13):** a custom, branded PhotonVox softphone app, as its own phase. Teams Phone is not a good enough experience for clients
who are mobile-first or softphone-first, and customers on traditional desk phones should have a nice, integrated, branded companion. This
replaces revision 1's "white-label softphone first" and moves the mobile softphone out of R3. Design only: nothing is built.

### What it is

**One PhotonVox app** on iOS, Android, macOS and Windows, and the same calling in the browser (the web app's softphone). They share one
**calling engine**, so a fix or a feature lands everywhere at once.

| Now (phase A) | When R3 lands |
|---|---|
| Make and receive calls (one number or several lines), hold, mute, speaker and Bluetooth, DTMF; blind and attended transfer; park and pick up; call waiting | Texting from the user's numbers and shared inboxes |
| Voicemail (play, delete, greetings), call history, the company directory and the phone's own contacts, favorites | Team chat |
| Presence (on a call, available, do not disturb) for the user and colleagues | |
| Do not disturb, forwarding within the call class, "ring my desk phone only" | |
| 911 with a confirmed location (below) | |

**Companion to a desk phone.** A user's desk phone and their apps are registrations of the **same extension** (decision 13: one SIP login per
extension, held by the server, never by the app). FreeSWITCH rings every registration of an extension at once, so the desk phone and the app
ring together; whichever answers first takes the call. A user with no desk phone has only the app. The user chooses where calls ring
(everywhere, app only, desk only) and the compiler (§8) writes it.

### Signaling and media: WebRTC, with PhotonVox's own signaling (decision 21)

| | **WebRTC + PhotonVox signaling (recommended)** | Native SIP stack on the device |
|---|---|---|
| Engine | libwebrtc on every platform: the browser's own, Electron's (Chromium), and `react-native-webrtc` on iOS and Android | PJSIP (GPLv2, or a commercial license from Teluu) or liblinphone (GPLv3, or a commercial license from Belledonne) |
| Licenses | BSD (libwebrtc), MIT (`react-native-webrtc`) | **GPL code cannot practically ship through the App Store** (Apple's terms add restrictions the GPL forbids), so in practice a **commercial license** per stack; liblinphone's is a yearly fee |
| One engine with the browser | **Yes**: the browser softphone must be WebRTC anyway | No: two calling stacks to build and keep working |
| SIP password on the device | **None**: the device has a device key; the gateway (below) holds the extension's credential | Yes, in the device's keychain (or a per-device credential FusionPBX does not model) |
| Media security and NAT | DTLS-SRTP and ICE built in, always | SRTP and ICE optional, often misconfigured |
| Wake for incoming calls | Push from PhotonVox's call gateway (below) | RFC 8599 push through a SIP proxy (Kamailio) that holds the INVITE, pushes, and waits for the device to re-register |
| Works with any SIP server | No (PhotonVox's gateway is required) | Yes (not needed: PhotonVox only talks to its own engines) |

**Recommended: WebRTC with PhotonVox's own signaling**: one engine across browser, desktop and mobile; no GPL or commercial SIP license; no SIP
passwords on devices; encryption and NAT traversal always on.

**The pieces:**
- **`@photonvox/calling`**: a TypeScript package (in this repo) holding the call state machine and the signaling client. The web app,
  the desktop app and the mobile app all use it unchanged; `react-native-webrtc` gives the same `RTCPeerConnection` interface as the browser.
- **`vox-gateway`** (the calling gateway): a small service on each engine instance, beside FreeSWITCH, with a public WSS address
  (`gw-a.<infra>`). Towards devices it speaks PhotonVox's signaling (JSON over a WebSocket, authenticated by the device key); towards FreeSWITCH
  it is a SIP user agent: it **registers each enrolled device** to the extension's account (over SIP/TLS, using the extension's credential, which
  stays on the gateway, encrypted), receives the INVITEs, and passes the SDP through. It handles push (below) and keeps working when vox-api is
  down (it holds a copy of the device registry, pushed to it by vox-api). Written in **Go** (the suite's language for long-running network
  services; a maintained SIP library such as `sipgo`, BSD-licensed, to confirm in the spike). Calls never depend on vox-api, as before.
- **FreeSWITCH terminates the WebRTC media itself** (its WebRTC-capable SIP profile: ICE, DTLS-SRTP, Opus). No media goes through the gateway.
  FreeSWITCH already anchors media and transcodes, so the app speaks **Opus** (wideband, loss-tolerant, low bit rate) and the PSTN and desk
  phones keep G.711 or G.722; FreeSWITCH converts. Transcoding costs CPU on the instance, counted in its capacity (§5).
- **NAT and TURN:** FreeSWITCH has a public address, so ICE succeeds directly from almost every network. For networks that block UDP, a
  **coturn** server on each instance offers TURN over TCP and TLS on 443, with short-lived credentials the gateway makes per call. **No separate
  SBC:** the gateway and FreeSWITCH's WebRTC profile are the edge for apps; desk phones keep their direct SIP/TLS path.
- **Transfer, park, conference:** the app asks the gateway; the gateway does it with SIP (REFER, REFER with Replaces for attended transfer,
  FusionPBX's park codes). Presence comes from FreeSWITCH's events through vox-agent and from the apps themselves.

### Calls that ring when the app is closed (decision 22)

| Platform | How |
|---|---|
| **iOS** | A **PushKit VoIP push** wakes the app, which must report the call to **CallKit** at once (iOS ends apps that receive a VoIP push and do not); the system's incoming-call screen shows it, on the lock screen too; audio uses CallKit's audio session; calls appear in the phone's Recents |
| **Android** | An **FCM high-priority data message** wakes the app, which shows the call through the **Telecom framework** (a self-managed `ConnectionService`) with a full-screen incoming-call screen; Android 14+ needs the full-screen-intent permission for that (the app asks and explains) |
| **Desktop** | The app keeps its WebSocket open while it runs (it starts at login, in the tray or menu bar); system notifications for calls; no push needed |
| **Browser** | The open tab only (a browser cannot be woken for a call) |

**The server side: the gateway itself, not RFC 8599 through Kamailio.** RFC 8599 is the standard for SIP clients; the app is not a SIP client,
and the gateway already stands where Kamailio would. When FreeSWITCH sends an INVITE to a device's registration, the gateway:
1. answers FreeSWITCH with `180 Ringing` at once (the caller hears ringing; the desk phone rings in parallel);
2. sends the push (APNs VoIP for iOS, FCM high priority for Android) with a short call id, and nothing else (no caller details leave in the
   push beyond the caller name and number the incoming-call screen needs);
3. waits for the device to connect and claim the call (target under 3 seconds; it gives up after the extension's ring time);
4. passes the offer and answer, and answers FreeSWITCH (`200 OK`) when the user picks up. If another registration answers first, the gateway
   cancels the app's call (the push already shown is ended through CallKit or Telecom).

**Registration model and battery:** the device holds **no standing connection** when the app is in the background: no SIP keep-alives, no
open socket. The gateway keeps the device's registration to FreeSWITCH alive for it. The phone wakes only for a push, so the battery cost of
the app at rest is close to nothing. A device that has not been seen for 30 days is unregistered at FreeSWITCH (so it is not rung) until it
opens the app again. Push credentials (the APNs key, the FCM service account) live only on the gateway hosts.

### 911 from the app (decision 23, as Connor decided it on 2026-11-13)

**Connor:** "The remote softphone location resolution will likely need to be GPS based. We cannot constantly ask the user where they are."
And: he prefers the native handoff. **On any device with cellular service, 911 dialed in the app is always handed to the phone's own dialer and
the cellular network, which carries the handset's location. It never goes over VoIP, so no location work happens on those devices.**

The rules (§11, §19): Kari's Law (911 without a prefix, and notification) applies to every PhotonVox extension. RAY BAUM'S Act needs a
dispatchable location with each 911 call placed over PhotonVox; for **non-fixed devices** it asks for an automated dispatchable location where
technically feasible, and otherwise allows the user's registered location, alternative location information (such as coordinates with their
accuracy), or routing to a national emergency call relay center (to be confirmed with counsel, §19). A call handed to the cellular network is a
cellular 911 call, located by the carrier, not by PhotonVox.

#### 1. Primary: hand 911 to the phone's own dialer

**Which numbers.** The app treats a dialed number as an emergency number before anything else happens: **911** always, plus the numbers the
phone itself knows as emergency numbers (Android's `TelephonyManager.isEmergencyNumber`, which reads the SIM's and the network's lists; on iOS,
which has no such interface, a list kept in the app: 911, 112 and the other common ones). **933** (the address read-back test) follows
the same path as 911: on a handoff device it goes to the phone's dialer, so the carrier reads back what it would send (where it supports 933 on
wireless); elsewhere it goes through PhotonVox to the 911 provider. 933 sends no Kari's Law notification.

**How the handoff is done:**

| | iOS | Android |
|---|---|---|
| The handoff | Open `tel:911` (`UIApplication.open`); the system's phone app takes over. iOS shows its own "Call 911?" confirmation for numbers opened from apps, so it is one more tap | Start `Intent.ACTION_DIAL` with `tel:911`: the system dialer opens with the number filled in, one tap to call. (`ACTION_CALL` cannot place emergency calls; Android's documentation says to use `ACTION_DIAL`) |
| Calls started outside the app's dialer | A call from the iOS Recents list, a contact or Siri that belongs to PhotonVox arrives as a start-call request (`INStartCallIntent`); the app checks the number first and hands an emergency number off the same way, never through CallKit as VoIP | The same check for calls started from contacts or the call log through Telecom |
| A PhotonVox call already in progress | The cellular emergency call takes priority; the app puts its call on hold or ends it when the system starts the emergency call | Telecom holds or disconnects self-managed calls when an emergency call starts |
| Dual SIM | The system chooses the line; emergency calls may use any available network, even another carrier's. The app does not pick a SIM | The same: the dialer and Telecom choose |
| Airplane mode, Wi-Fi only | To verify in spike A0. If the phone turns its radio on for an emergency call (Android's dialer does so as standard behavior), the handoff stays; if it cannot, the device counts as "no cellular service" (part 2) | Android's dialer turns the radio back on for emergency calls: handoff |

**"Has cellular service"** means: the device has a phone radio (an iPhone or an Android phone; iPads and Android tablets cannot place
cellular voice calls) **and** it is registered on some network right now (iOS: a current radio access technology; Android: the service
state), or it is an Android phone in airplane mode (above). A phone with no SIM can still reach 911 on any network where one is in range, so
"no SIM" alone does not stop the handoff. Only a phone with no network at all goes to part 2.

**No location permission is needed for this.** On phones the app asks for location only as an optional permission at sign-in, explained as
"used only if you call 911 when your phone has no mobile service" (part 2); declining it changes nothing for normal 911 calls.

#### 2. Devices without cellular service: desktops, Wi-Fi-only tablets, phones with no service

These place 911 over PhotonVox, with the best location available, **automatically**:

1. **At a known site: the site's validated dispatchable address.** The device is matched to one of its organization's sites by, strongest
   first: the **Wi-Fi access point** (BSSID), which an admin can map to a building, floor or room where a site has several emergency
   locations; the **Wi-Fi network name** or the **public IP address** of the site's network; or a **geofence** (the OS location inside the
   site's radius with an accuracy better than that radius). A match uses that site's emergency location and emergency number, exactly as a desk
   phone at the site does (§11).
2. **Elsewhere: the best location the device has**: the OS location services (Wi-Fi positioning, GPS where the device has it; on desktops the
   OS location where it has one, else only the network match) give coordinates and their accuracy. They go with the call **in the form the 911
   provider accepts**: coordinates with their uncertainty in a location object carried with the call, or a civic address reverse-geocoded from
   them, through a provider that routes calls by such a location to the right PSAP.
3. **Ask the user only when automatic location fails or is too coarse** (no permission, "approximate" only, worse than about 100 m, no fix),
   and then **once per new place**; the confirmed place is validated and remembered, and used without asking whenever the device is there again.
   Never on every network change.
4. **Last fallback: a national emergency call relay center (ECRC)**, where a trained operator asks the caller where they are and passes the
   call to the right PSAP. Used when there is no usable location at all. **911 is never blocked.**

**Who carries these calls.** Desk phones keep HTC's native 911 (§11). Part 2 needs a 911 provider that takes a location with each call and
offers an ECRC. **Candidates, as research to confirm** (none verified for this plan; prices, contracts and interfaces unknown): Bandwidth (its
911 services for VoIP providers), Intrado (911 services for carriers and VoIP providers), RedSky (enterprise E911 for nomadic users), and
others the research turns up (for example Comtech's 911 services). The first question is whether **HTC handles any of it** (§22, question 14).

**When location is read, and what is kept** (part 2 devices only; privacy and battery): at sign-in, when the app sees a network change (while
it runs, or when it starts or returns to the foreground on another network), and at the moment a 911 call is placed. Never continuously: no
background tracking, no OS geofence monitoring; a few reads a day. Kept: on the device, the last location and the user's confirmed places; on
the server, only the device's current emergency location (a site, a confirmed place, or the last coordinates with their accuracy), overwritten
each time; and the location sent with a 911 call, with that call's record (retention to confirm, §19). No history of where anyone has been;
users can see and delete their confirmed places. Permissions: "while using the app" only, never "always", with the purpose text saying it is for
911; reading the Wi-Fi network on iOS needs location permission and Apple's Wi-Fi information entitlement, on Android location permission.
**The call-time read** (to verify in spike A0): a call from the app's own dialer starts in the foreground, where "while using" allows a fresh
read; a call started from the system's Recents list may start the app in the background, where it might not. The call never waits for a fix
(about 2 seconds, then the best known location goes).

#### 3. Notification (Kari's Law) in every case

- **Over PhotonVox (part 2):** PhotonVox sees the call, so the organization's contacts are notified as for a desk phone (§11).
- **Handed to the cellular network (part 1):** the app knows the user dialed 911 in it, records the handoff (part 4, layer 6) and sends the
  notification **as it hands off**
  ("911 dialed from the PhotonVox app on Ada's phone at 14:03; the call went to the mobile network, which locates the phone"), queued if the
  device is offline, never delaying the handoff. Whether the call then connected the app cannot know reliably: iOS's call observer
  (`CXCallObserver`) reports that a call started on the device but not its number, and only while the app runs; Android would need phone-state
  and call-log permissions the app should not ask for. So the notification says "dialed", not "connected". A 911 call the user places from the
  phone's own dialer, outside the app, is invisible to PhotonVox and is not notified.
- Kari's Law strictly covers calls placed through the phone system; a cellular call is arguably outside it. The notification is sent anyway
  (Connor's wish), and counsel confirms the wording (§19).

#### 4. Testing 911 in the app

**Real 911 is never dialed, except in the scheduled test of layer 5, arranged beforehand with the PSAP.** Six layers, from cheapest to rarest:

**Layer 1: the decision as a pure function, fully tested.** One function in `@photonvox/calling` decides what a dialed number does:
`route(dialed, device, config) -> { action, reason }`, where `action` is `handoff` (to the phone's dialer), `voip911` (over PhotonVox with a
location), `voip` (an ordinary call) or `refuse` (never for an emergency number). Its inputs are plain data, so it has no OS calls in it:
- `dialed`: the digits as typed, normalized (spaces and punctuation removed; the site's outside-line prefix stripped, so `9-911` and `9911` are
  911 where 9 is the prefix; the compiler (§8) supplies the prefix per site);
- `device`: platform (iOS, Android, desktop, browser), whether it has a phone radio, the cellular service state (in service, emergency calls
  only, out of service, radio off), airplane mode, the SIM state (absent, locked, ready, network-locked) and, on Android, the system's own
  verdict (`isEmergencyNumber`);
- `config`: the emergency list (911 always, 112 and the other common ones), 933, and in test builds only the test emergency number (layer 2).

Rules it encodes: an emergency number on a device with cellular service (in service, or emergency-only, or an Android phone in airplane mode)
is `handoff`; no SIM or a locked SIM does not stop a handoff where the network allows emergency calls; elsewhere it is `voip911`; **933 follows
the same path as 911** (handed off on a cellular device, so the carrier reads back what it would send; through PhotonVox elsewhere, so the 911
provider reads back the dispatchable address); feature codes such as `*911` are not emergency numbers; nothing returns `refuse` for an
emergency number. Tested by a table of cases (every number form x every device state x every platform) at **100% branch coverage** (a CRITICAL
module), plus a generated test that no input combination ever refuses or delays 911. The mobile app reads the OS state and calls the function;
the desktop and browser always get `voip911`.

**Layer 2: a test emergency number, in test builds only.** One number Photon owns (a DID that rings a test menu on the staging instance,
which answers, reads the caller's number aloud and records it in the CDR) is treated by the function **exactly like 911**: same handoff, same
notification (marked as a test). On real phones, the proof that a handoff really leaves over the cellular network is the **caller ID that
arrives at the test number: the phone's own mobile number, never a PhotonVox number.**
- **It cannot ship in a release build.** The number exists only in a build setting read in debug and internal-test builds; release builds
  compile it out. The release pipeline (Xcode Cloud's release workflow, the Gradle release task, the desktop release) runs a **check that fails
  the build** if the test number, or the setting's name, appears anywhere in the built bundle (the JavaScript bundle and the native binaries),
  and a unit test asserts the release configuration has no test number. Even if one slipped through, dialing it reaches only a test menu.

**Layer 3: 933 through the app on real phones, per carrier.** 933 dialed in the app on a cellular phone is handed off; where the carrier
supports 933 on wireless, it reads back the location and callback number it would send to a PSAP. Run on each carrier Photon's customers use
(AT&T, Verizon, T-Mobile, and the regional carriers around Photon's sites); **which carriers support 933 for wireless is research to confirm**
(§22): where a carrier does not, layer 2 stands in for it. On desktops and Wi-Fi-only tablets, 933 goes through PhotonVox to the 911 provider,
which reads back the dispatchable address (the site's, or the confirmed place's).

**Layer 4: a real-device matrix, every release.**

| Condition | What is checked | Device farm? |
|---|---|---|
| Normal: in service, SIM ready | handoff opens the system dialer with the number; layer 2 caller ID | farm for "dialer opens with 911 filled"; own phones for the call |
| No SIM | handoff still offered where the OS allows emergency calls without a SIM | farm (devices without SIMs) for the decision; own phone for a layer 2 call is impossible without a SIM, so the dialer opening is the check |
| Airplane mode with Wi-Fi | Android: handoff (the dialer turns the radio on); iOS: as spike A0 found | own phones (farms rarely let a test toggle airplane mode) |
| Dual SIM (eSIM + physical), one without service | the system picks a line; the app does not | own phones |
| Locked screen | a handoff started while the phone is locked (Siri, or the app's call screen over the lock screen during a call) | own phones |
| During an active PhotonVox call | the app's call is held or ended; the handoff goes through | own phones (needs a live call) |
| Do Not Disturb / Focus | the handoff is unaffected; the notification still goes out | own phones |
| Roaming (another network, abroad) | handoff to the dialer; the local network maps 911 or 112 | own phones (rarely: a travel test) |
| Android work profile | the app in a work profile still opens the system dialer | farm if it offers managed profiles, else own phone |
| iOS and Android, the oldest supported version and the current one | all of the above where the OS differs | farm for versions and models; own phones for the calls |

**Device farms** (AWS Device Farm, Firebase Test Lab, BrowserStack and the like) cover breadth: many models and OS versions running layer 1
on real OS state readings, the dial intent opening the system dialer with the number filled in (stopped there), the CallKit and Telecom
handling of calls started from the system. **They cannot place calls** (and must never be asked to dial 911), so anything that makes a call,
needs a specific SIM, carrier, network condition or a second live call runs on **Photon's own phones**: one iPhone and one Android phone per
major carrier at least.

**Layer 5: a scheduled live 911 test call, about once a year and before any release that changes 911 routing** (runbook below). It is the only
time anyone dials 911.

**Layer 6: in production, every emergency dial is recorded as an event.** The app sends an event for each emergency-number dial: the device,
its organization, the platform and app version, the time, the route taken (`handoff` or `voip911`) and whether the system dialer opened (for a
handoff) or the call was placed (over PhotonVox). **No location and no call content.** It is queued if the device is offline. The events show
that handoffs happen and work (Photon staff are alerted when a dialer did not open), they drive the Kari's Law notification (§18a part 3), and
they are kept with the organization's audit log (retention as for 911 records, §19).

#### The live 911 test runbook (layer 5)

1. **When:** once a year, and before a release that changes how 911 is routed or located. Never during a known busy period for the PSAP.
2. **Arrange it:** call the PSAP that serves the test location on its **non-emergency (administrative) line**, two weeks ahead; agree the date,
   a short time window, how many calls, from which numbers, and who answers on their side; ask whether they want written notice. If the PSAP
   says no, or asks to postpone, the test does not happen.
3. **Before:** the organization's Kari's Law contacts (Photon's own test organization) are told; the devices are ready: a desk phone at the
   site (HTC's native 911), the desktop app at the site and at a confirmed off-site place (through the 911 provider), and a phone with the app
   (the handoff; a cellular 911 call, located by the carrier).
4. **Each call:** the caller says at once: *"This is a scheduled test call from Photon, arranged with your center. There is no emergency."*
   Then confirms with the call-taker: the callback number they see, the location they see (the site's dispatchable address, the off-site place,
   or the carrier's location), and that it reached the right PSAP. A call-taker who is busy ends the test: call back on the administrative line.
5. **Check on our side:** the Kari's Law notification arrived for each call, the layer 6 events are there, the CDR shows the route.
6. **Abort:** any real emergency at the PSAP, any confusion about whether a call is a test, or a call reaching the wrong PSAP stops the test
   (the last is a finding to fix before anything else).
7. **Record:** date, PSAP, call-taker's first name if given, each call's callback number and location as seen, the notifications, problems found,
   in `docs/911-TESTS.md`; problems become fixes before the next release.

### Branding (decision 24)

| | **One app, partner branding at sign-in (recommended)** | Per-partner store listings |
|---|---|---|
| What the user sees | "PhotonVox" in the store and on the home screen; after sign-in, the partner's logo, colors and support contact inside the app (the suite's `branding` lookup) | The partner's own app name and icon everywhere |
| Store rules | One app published by Photon, the provider of the service: fine | Apple's guideline 4.2.6 rejects template apps unless **submitted by the provider of the content**, and 4.3 rejects near-identical apps: in practice each partner's app must be published **from the partner's own developer account**. Google Play also restricts duplicate apps |
| Cost | One build, one review per release, one set of push keys | Per partner: a developer account (Apple $99 a year, organization enrollment with a D-U-N-S number; Google $25 once), its own bundle id, signing and APNs keys, a build and a review for every release, store screenshots and listings. Each one multiplies release work |
| What cannot change | The incoming-call screen (CallKit, Telecom) shows the app's name, "PhotonVox" | Nothing |

**Recommended: one app**, with per-partner store listings later as a paid option for large partners, under their own developer accounts.

### Sign-in, devices and security (decisions 25, 26)

- **Sign-in with PhotonID** (OIDC with PKCE through the system browser, returning to the app by a universal link / app link). Refresh tokens in
  the iOS Keychain or Android Keystore-backed storage; on desktop, the OS keychain (macOS Keychain, Windows Credential Manager).
- **Pairing by QR code** for phone users who have no PhotonID account (decision 15 keeps phone users PhotonVox's own): an admin shows a
  one-time QR code in PhotonVox (valid 15 minutes, for one user); scanning it enrolls the device for that user's extension. That keeps "deploy
  in minutes" true for a 30-person office.
- **Each device has its own key**, made on the device (Secure Enclave on iOS, StrongBox or TEE-backed Keystore on Android, the OS keychain on
  desktop), never exported. Enrollment registers the public key, the push token, the platform, model and app version with vox-api, which
  pushes it to the gateways. The device signs its connection to the gateway with that key.
- **No SIP credentials on any device.** The gateway holds the extension's credential; a stolen phone carries nothing that works elsewhere.
- **Device list:** users see their devices in the app and the web app; admins see every device of their organization. **Sign out a device**
  (user or admin) or **remove the user** (the directory says so, or the phone user is deleted): the gateway drops the device at once, its
  registration at FreeSWITCH and its push token are removed, and the next time the app runs it is told it was signed out and **wipes its local
  data** (cached history, voicemail, contacts, tokens). This is app-level wipe, not device management; an MDM's managed configuration
  (AppConfig) is a later option for customers who use one.
- **Calls placed from the app** obey the extension's call class and the spend breaker (§15) like any phone; the gateway refuses a device that
  has been signed out within seconds.
- **Local data** is encrypted by the OS (iOS data protection, readable after first unlock so a locked phone can still show an incoming call).

### The app's technology

| Part | Choice | Why |
|---|---|---|
| Calling engine | `@photonvox/calling` (TypeScript) | One engine for every platform |
| Mobile | **React Native** with `react-native-webrtc` and native modules for PushKit/CallKit and Telecom/ConnectionService (an existing open-source CallKit/ConnectionService bridge, or our own small module) | Same language and much of the same React as the web app; the native parts are small and well known |
| Desktop | **Electron** wrapping the web app's softphone pages | Chromium's WebRTC; the web app's own React, so the desktop app is mostly packaging |
| Browser | The PhotonVox web app's softphone | The engine as is |

Flutter was considered (one UI codebase for all four platforms) and set aside: its calling engine would be Dart, not shared with the browser
softphone, and the web app is React.

### Build and release (decision 27)

- **Android** builds on the runner (Android SDK and JDK 17 are there; React Native's Gradle build needs nothing else).
- **iOS and macOS** need macOS. Recommended: **Xcode Cloud** (25 compute hours a month are included in the Apple Developer Program; Apple
  manages the distribution signing; TestFlight is built in). It needs the repo on GitHub (photonvox has no remote yet: Connor's call). **Connor's
  Mac** stays the fallback for debugging on a tethered iPhone. A hosted macOS runner (GitHub Actions) is the alternative if Xcode Cloud falls
  short (paid by the minute).
- **Windows** builds on the runner (Electron). Its code-signing certificate must live in a hardware or cloud key store under current CA rules:
  a cloud signing service (for example Azure Trusted Signing, a small monthly fee) works from Linux CI. Unsigned Windows apps are blocked or
  warned about by SmartScreen.
- **Accounts:** an **Apple Developer Program** membership and a **Google Play Console** account, both as **organizations** (Photon's legal
  entity, a D-U-N-S number). Google requires new **personal** accounts to run a 14-day closed test with at least 12 testers before
  production; organization accounts avoid that (to confirm when opening it). Connor is the Account Holder of both; agents never hold his
  Apple ID or Google password.
- **Keys and who holds them** (the suite's release-key rules, as for PhotonBoard's):
  - Google **Play App Signing** holds the app signing key; Photon holds the **upload key** in `~/keys` on the runner (mode 600, never
    printed), in Bitwarden, and in one other place.
  - Apple distribution signing is Xcode Cloud's (cloud-managed certificates); an **App Store Connect API key** for uploads is a secret in CI
    and Bitwarden.
  - The **APNs auth key** (`.p8`) and the **FCM service account** are secrets on the gateway hosts and in Bitwarden, rotated yearly.
  - The Windows signing identity in the cloud signing service; macOS Developer ID through Xcode Cloud (or Connor's Mac) with notarization.
- **Store review:** a demo organization with working extensions for Apple's reviewers; the VoIP background mode justified by CallKit; no account
  creation in the app (accounts come by invitation), so no in-app account deletion is needed (to confirm against the current guidelines).
- **Channels:** internal (TestFlight internal testers, Play internal testing) → partners' beta (TestFlight external, Play closed testing) →
  stores. Desktop: an auto-update channel (Electron's updater, signed).

### Where it sits, and how long (decision 28)

**Phase A runs in R2**, as its first major item after R1 (the app needs R1's instances, numbers and locked 911). It **replaces** R2's
"browser softphone" and R3's "mobile softphone". The spikes (A0) can run during R1's Steps 3–5 because they need only the staging instance
and test devices. Chat and texting join the app when R3 lands.

Rough length, for planning only: A0 spikes 2–3 weeks; A1 gateway, engine and browser softphone 5–6 weeks; A2 desktop 2 weeks; A3 mobile
with push 6–8 weeks; A4 softphone 911 2–3 weeks (overlapping A3); A5 store release 2–4 weeks (reviews, beta). **About 4–5 months** from A0
to the stores, depending on how fast the gates (accounts, devices, HTC's 911 answers) are passed.

---

## 19. Regulatory obligations to confirm

Selling phone service makes Photon an **interconnected VoIP provider** unless it sells as HTC's agent. Each item needs a telecom attorney's or
accountant's confirmation before customers are added beyond today's (not legal advice; some may be covered by the arrangement with HTC):
FCC registration and Universal Service reporting (Form 499); the Robocall Mitigation Database and STIR/SHAKEN through the upstream; 911 rules
for interconnected VoIP, Kari's Law and RAY BAUM'S Act (§11); CPNI protection and annual certification; CALEA; telecom taxes and 911 fees per
line; state registrations; call-recording consent (R2); 10DLC and TCPA for texting (R3); for the app (§18a): the RAY BAUM'S Act options for
non-fixed devices (automated location, coordinates, ECRC), whether Kari's Law notification applies to a 911 call handed to the cellular
network, and how long a 911 call's location is kept.

---

## 20. Links with the other products

| From → to | What | When |
|---|---|---|
| PhotonID → PhotonVox | organizations, sites, people, access | R1 |
| PhotonVox → PhotonConsole | the per-organization feed; Photon's platform health | R1 |
| PhotonConsole → PhotonVox | "call and play a message" / "send a text" as alert channels | R3 |
| PhotonGuard ↔ PhotonVox | alarm call-outs to keyholders; a SIP door station rings desk phones beside its camera | later |
| PhotonEdge ↔ PhotonVox | the optional site service (§18) | later |

---

## 21. Names and identifiers

Product **PhotonVox**; directory key `vox` (in the directory's catalog as "coming"). `vox.photonind.com` (app), `api.vox.photonind.com` (API;
directory notices to `https://api.vox.photonind.com/directory/v1/notify`, as the catalog assumes). SIP names under the neutral
infrastructure domain, the app's gateways too (`gw-a.<infra>`). The app: store name "PhotonVox", package `@photonvox/calling` for the engine, bundle
and application ids under Photon's reverse domain (`com.photonind.vox`). Repo `photonvox`; database owner `photonvox`, roles `vox_app` and `vox_system`; scope `vox:read`; header
`X-PhotonVox-Signature`. PhotonConsole's `photon_pbx`, `pbx_instance` and the shim keep their names until retired.

---

## 22. Open questions (only Connor can answer)

**GDMS and phones**
1. Does Photon have a GDMS account already (PhotonConsole's notes mention Grandstream endpoints "via GDMS")? Are HUEPC's phones in it? May
   PhotonVox use it, with an API Developer key and a dedicated API user?
2. Which Grandstream models will Photon stock for R1? A couple of boxed units of each for the barcode and provisioning tests.
3. Does Photon buy phones as a GDMS channel (distributor features) or ordinarily?

**HTC** (what R1 needs; what HTC cannot do decides whether another upstream is needed now)
4. Numbers: can Photon hold a stock of HTC numbers? How are numbers ordered (API or by hand, how fast)? Numbers outside HTC's area, and
   toll-free?
5. Porting in to HTC: process and timing.
6. E911: answered in part (decision 31: Hickory keeps each number's address by hand; PhotonVox sends a request per change). Still open: the
   address (email or portal) Hickory wants requests sent to, its usual turnaround, whether it can check an address against the 911 database
   before use (MSAG), 933 support, and how 911 will be routed after HTC's softswitch moves to Ashburn.
7. CNAM (caller-ID name) updates; per-number failover destinations; delivering to two addresses (an instance and its standby).
8. Texting (R3): does HTC offer SMS/MMS and 10DLC registration?

**The live system**: question 9 is **answered by the inventory of 2026-11-13 (§17a)**. Still open from it: how the phones are provisioned (by
hand, or GDMS: question 1); whether anyone outside Photon uses FusionPBX's screens. (Premium and high-cost Caribbean numbers: answered, blocked
since 2026-11-13, §17a.)

**The business**
10. Photon's regulatory standing for selling voice (§19): what it holds, what HTC covers, and who to ask.
11. The first templates to build (which kinds of customers come first), and how many phone systems are expected in year one.
12. Budget: the PhotonVox VPS; any upstream beyond HTC; the text-to-speech provider (decision 30). (Postmark: already on the paid tier.)

**The PhotonVox app** (phase A, §18a)
13. Photon's legal entity name and its **D-U-N-S number** (both stores' organization accounts need them; getting one can take weeks). Does Photon
    already have an Apple Developer or Google Play account?
14. **911 from devices without cellular** (decision 23, part 2): does **HTC** handle any of it: 911 calls carrying a per-call location (coordinates
    with uncertainty, or a civic address), numbers registered at users' home addresses, or routing to a national emergency call relay center
    (ECRC)? If not, may Photon contract a 911 provider for these calls (Bandwidth, Intrado, RedSky or another, after research), and is there one
    Photon already deals with?
14a. **Which carriers support 933 on wireless** (research to confirm; layer 3 of §18a's 911 tests), and which carriers Photon's customers use
    most (the phones Photon keeps for testing follow them).
14b. **A test emergency number** for the app's test builds: a number Photon owns, ringing a test menu on the staging instance (layer 2).
14c. **The PSAP for the yearly live test** (layer 5): which center, and who at Photon makes the arrangement.
15. **Test devices:** an iPhone and an Android phone for development, and Connor's Mac with Xcode for tethered debugging when needed.
16. **Windows** in the first app release, or iOS, Android and macOS first? (Windows needs a code-signing service, a small monthly fee.)
17. A **GitHub remote for photonvox** (Xcode Cloud builds from it).
18. The store name **"PhotonVox"**: a trademark search before the first listing (the suite already suggests one for PhotonGuard).

---

## 23. Proposed changes to the suite documents (not applied)

- **`photon-suite/ARCHITECTURE.md` §1:** PhotonVox row: repo `photonvox`, hostnames, state "planned (design rev 2, 2026-11-13); engine live",
  "a tool for integrators to deploy phone systems on Photon's FusionPBX instances and Grandstream GDMS".
- **§5 role table:** PhotonVox: owner, admin, user (supervisor later); site-limitable all but owner.
- **§7:** PhotonVox → PhotonConsole feed, replacing "FusionPBX over mgmtnet" once PhotonConsole moves to it; PhotonVox ↔ GDMS (outbound API
  and push callbacks).
- **§10:** the PhotonVox VPS; instances in the colo and later DC10.
- **§11 roadmap:** phase **V1** = PhotonVox R1 (BUILD-GUIDE Steps 0–6), after D1; phase **VA** = the PhotonVox app (BUILD-GUIDE phase A), in R2.
- **§2 / release keys:** the PhotonVox app's Play upload key, App Store Connect API key, APNs key and FCM service account join the list of
  release keys kept in `~/keys`, Bitwarden and one other place.
- **§13:** question 2 answered by decisions 7 and 8 here once Connor agrees.
- **`photonid`:** make `vox` available in `app/catalogue.py` once PhotonVox publishes its roles (its own session).
