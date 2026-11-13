# PhotonVox — architecture

**Status:** design, revision 1, 2026-11-13. Nothing is built. The live phone system (FusionPBX in LXC 600, `10.10.0.21`) was **not read or touched**
for this document: everything about it comes from `photon/docs/fusionpbx-integration.md`, PhotonConsole's code and the suite documents, and
whatever those do not say is listed as a question in §22, not guessed. The build is driven by [BUILD-GUIDE.md](BUILD-GUIDE.md).

Suite-wide topics (PhotonID and organizations, the rules for working on Photon, shared conventions, hosting, networks, the ASN plan) are in
`~/projects/photon-suite/ARCHITECTURE.md` and `OPERATIONS.md`; read them first. This document holds PhotonVox's own design and the reasons for it.

---

## Decisions for Connor

Each line is a yes/no. The recommendation is **yes** for every line; the reason is one sentence. Where a line costs money it says so.
BUILD-GUIDE.md assumes these answers; a "no" changes the section named.

| # | Decision | Why yes | § |
|---|---|---|---|
| 1 | **Keep FreeSWITCH + FusionPBX as the call engine.** PhotonVox is a product layer around it (its own app, API, roles, numbers, texting, chat); customers never see FusionPBX's screens; Photon staff keep them, off the public internet | Live customers already run on it; rebuilding voicemail, IVRs, queues and phone provisioning is years of work for one person; FreeSWITCH is the engine either way | 3 |
| 2 | **One phone system (FusionPBX domain) per organization**, covering all its sites; each extension, phone and number records its site. A second phone system for one organization only when it asks | Internal dialing and one auto attendant across sites is what customers expect; the site is still known for 911 and for site-limited admins | 5 |
| 3 | **New SIP domains get neutral infrastructure names** (no customer name, no Photon brand: `<id>.sip.photoninfra.xyz`); existing domains keep theirs | Domain names live in every phone's configuration; customer names change and partners resell | 5 |
| 4 | **PhotonVox roles: owner, admin, supervisor, user** (site-limitable except owner). An extension can exist without a person (a lobby phone) | Matches how phone systems are run; "user" is anyone who has a phone, voicemail or texting | 6 |
| 5 | **Partners resell Photon's PhotonVox only**; no partner-run FusionPBX servers (PhotonConsole's `pbx_instance` seam stays unused) | One engine to secure and upgrade; partner-run PBXes can still be monitored by PhotonConsole | 6 |
| 6 | **Add a second carrier with a full API** (numbers anywhere, porting, E911 addresses, SMS/MMS and 10DLC, outbound failover). Recommend **Telnyx**; HTC stays the primary for local voice and 911. *Costs money: an account and numbers* | HTC gives on-net local service but texting, national numbers and API-driven E911 need a CPaaS-grade carrier | 7 |
| 7 | **"Photon SIP Trunking" becomes "PhotonVox Trunking"** (SIP trunks for customers who keep their own PBX); the label each customer sees stays configurable per partner | Answers suite question §13.2; one product name for all voice | 7 |
| 8 | **Desk phones: Grandstream (today's) and Yealink only**, zero-touch through the vendors' redirect services, provisioning over HTTPS with a per-phone login, never plain or unauthenticated | Two vendors are testable; unauthenticated provisioning leaks SIP passwords and is a top toll-fraud path | 11 |
| 9 | **Softphones: a browser softphone inside the PhotonVox web app (WebRTC) from the start; on mobile, a white-labeled softphone first (Acrobits Cloud Softphone or similar) beside the PhotonVox web app for texting, chat and voicemail; our own native app later.** *The white-label app costs per user* | Incoming calls on iOS need VoIP push through a push service; buying that first gets mobile calling working in weeks, not months | 11 |
| 10 | **Team chat is built into PhotonVox** (one conversation model for texting and chat), not Matrix or Mattermost | Same identity, tenancy, presence and app as calls and texts; an outside chat server would need its own tenancy and sign-in glue | 10 |
| 11 | **PhotonEdge is not needed for voice.** Later, an optional PhotonVox service on it for call-quality probes and phone discovery; on-site survivability (local calling and 911 with the internet down) only if a customer asks and pays | Phones already dial out to the cloud; most voice sites will have no PhotonEdge | 12 |
| 12 | **Voicemail and recordings go to Backblaze B2, in a bucket of PhotonVox's own** (`prod/`, `dev/`, `test/` prefixes as PhotonGuard does). **Call recording is off by default**, and plays a notice where consent law needs it (Pennsylvania needs all parties' consent) | Keeps the PBX hosts small and rebuildable; recordings are sensitive and get their own keys and lifecycle | 13 |
| 13 | **The PhotonVox app gets its own small VPS** (Misaka, Ashburn, 2 vCPU / 4 GB), not `photon-infra-a` (full) or the PhotonGuard VPS (transit-capped). *Costs money* | Calls never depend on the app, but texting, chat and admin do; it should not share a failure with PhotonID or PhotonGuard | 15 |
| 14 | **Redundancy: a second engine leg at Equinix DC10 as a warm standby**, promoted by a drilled runbook (target 15 minutes); active/active (Kamailio in front of two live FreeSWITCH legs) only when a contract needs it. **Phones move to DNS names now**, so no later step has to touch them | Matches the suite's Stage 3 (manual failover across sites); a name on every phone is the cheap step that makes every later move invisible to customers | 15 |
| 15 | **Toll-fraud defaults on every organization, applied to the live PBX first**: international and premium destinations off, a daily spend limit that stops outbound calls (never 911), voicemail and forwarding never dial out internationally | A single compromised extension can run up thousands of dollars in a night; this is the largest financial risk in the product | 17 |
| 16 | **PhotonConsole keeps its direct FusionPBX poller until PhotonVox publishes a Console feed, then switches to the feed with the same point keys** (before any engine node moves) | Console's rules and dashboards survive; Console stops holding a credential that reads every customer's call records | 18 |
| 17 | **Meter from day one; Photon bills partners wholesale, partners bill customers** (the suite's proposal), with telecom taxes and regulatory fees handled by a tax service or an accountant Connor picks (§19) | Voice billing without taxes and fees is not legal to send; metering is needed before any price can be set | 14 |

---

## Terms (what the customer sees, and what the code calls it)

| User-facing | Internal | Meaning |
|---|---|---|
| **phone system** | `phone_system`; a FusionPBX **domain** | One organization's PBX: its extensions, call flows, numbers. Usually one per organization (§5) |
| **user** | a person with a `vox` grant; `extension.person_id` | Someone who uses PhotonVox. Not every extension has one |
| **extension** | `extension`; FusionPBX `v_extensions` | A dialable internal number with voicemail, forwarding and a SIP login |
| **phone** | `device`; FusionPBX `v_devices` | A desk phone, conference phone or adapter, provisioned by its MAC address |
| **number** | `number` (E.164) | A public telephone number the organization holds |
| **call flow** | IVR menus, ring groups, time conditions, queues | What happens when a number is called |
| **emergency address** | `emergency_location` | The validated street address (plus building, floor, room) sent with a 911 call |
| **PhotonVox Trunking** | `trunk`; FusionPBX gateway | SIP trunks: Photon's carriers for Photon's PBX, or sold to a customer's own PBX |
| **engine** / **leg** | `pbx_node` | A FreeSWITCH + FusionPBX server. Customers never see these words |

---

## 1. What PhotonVox is, and what customers get

PhotonVox is Photon's phone system, growing into a **UCaaS platform: voice, texting and team chat in one app**, sold directly and through partners,
signed in with PhotonID, monitored by PhotonConsole. Today it is one FusionPBX server in the colo (HTC's central office) with live customers
(HUEPC and Connor's own domain are the known ones), monitored by PhotonConsole over mgmtnet.

What a customer gets (★ = exists today through FusionPBX, offered to customers through staff; everything else is new):

| Area | What |
|---|---|
| **Phone system** | Extensions ★, desk phones provisioned for them ★, voicemail ★ with email delivery and (later) transcription, auto attendants (IVR) ★, business hours and holidays ★, ring groups ★, call queues with supervisor views, call park, paging, conference bridges, music on hold ★, company directory, call recording (opt-in) |
| **Numbers** | Local and toll-free numbers, porting in from the old carrier, caller ID name, a validated emergency address per site and per phone |
| **Apps** | The PhotonVox web app (desktop and phone equally first-class, suite §6): calls with a browser softphone, call history, voicemail, texts, chat, contacts, presence. A mobile softphone (§11) |
| **Texting** | SMS and MMS from the organization's numbers, shared inboxes ("Front desk") and personal numbers, with the 10DLC registration done for them |
| **Team chat** | One-to-one, groups and channels inside the organization, files, presence from the phones and the app |
| **Admin** | Users and phones, numbers, call flows, hours, queues, emergency addresses, reports (calls, queues, usage), the audit log, all from PhotonVox; people and sites from the directory ("Manage organization") |
| **Monitoring** | Phones offline, trunks, call volume and queue health as PhotonConsole points and alerts, beside the rest of their building |
| **PhotonVox Trunking** | SIP trunks and numbers for a customer who keeps their own PBX |

**Not in the first releases:** fax (T.38 over SIP is unreliable; an email-to-fax service later if a customer needs it), video meetings,
contact-center features beyond queues (no outbound dialer, no workforce management), CRM integrations, international numbers.

---

## 2. Principles carried over from the suite

The suite principles (`photon-suite/ARCHITECTURE.md` §3), applied to voice:

| Rule | What it means here |
|---|---|
| Tenancy in every table from the first migration, RLS on | `tenant_id` (the directory organization id) on every PhotonVox table; the engine's own tenancy is the FusionPBX domain, mapped one way (§5) |
| PhotonID says who; products decide what | PhotonVox keeps a read-only copy of the directory (notify then pull), publishes its own roles, keeps fine limits (which extension is yours, which inboxes you see) |
| No public sign-up | Organizations and people come from the directory; phones and numbers are added by admins |
| Staff act visibly, and are audited | Photon and partner staff appear as "Partner support"; every listen to a recording, read of a shared inbox and change to call routing is in the audit log |
| Devices talk only to their own platform, outbound | Phones and softphones register outbound to PhotonVox's SIP servers; nothing at a site listens on the internet; no port forwarding for phones |
| Device credentials are their own namespace | Each phone gets its own SIP and provisioning logins, random, stored encrypted, rotated when the phone is removed |
| Two timestamps on everything from the field | Calls carry the engine's start/answer/end times and PhotonVox's ingest time |
| **Site autonomy** | **Voice is the exception, and the design says so.** A cloud PBX cannot ring a site's phones with its uplink down. Mitigations: calls to unreachable phones go to voicemail or a mobile number automatically (§12), sites get the suite's cellular failover radio with voice prioritized, and survivability on a PhotonEdge is a later paid option |
| Never dark over billing | A restricted account keeps receiving calls, keeps its numbers and **always reaches 911**; restriction stops new numbers, international calling and new texting campaigns |
| Monitored by PhotonConsole through a read-only per-organization feed | `GET /integrations/console/v1/phone-systems` (§18) |
| Declarative configuration | Call flows and policies are JSON in PhotonVox and pushed to the engine by one adapter (§3), so the engine can change under them |

---

## 3. The engine: keep FusionPBX (recommended)

### What was weighed

| Option | What it means | Verdict |
|---|---|---|
| **A. Keep FreeSWITCH + FusionPBX; build PhotonVox around it** | FusionPBX stays the engine's configuration store and Photon staff's console; PhotonVox owns the customer experience and writes to the engine through one narrow adapter | **Recommended now** |
| B. FreeSWITCH alone, configured by PhotonVox | FreeSWITCH asks PhotonVox for users and dial plans (`mod_xml_curl`); PhotonVox rebuilds voicemail settings, IVRs, queues, ring groups, provisioning templates | The right end state if FusionPBX ever holds us back; too much to build before customers see anything |
| C. Kamailio + FreeSWITCH as a carrier-style platform | Kamailio as registrar and proxy (replicated registrations), FreeSWITCH pools for media and features | The shape for active/active and large scale (§15 stage 3); it does not replace the feature layer, so it comes on top of A or B |
| D. Buy a hosted or licensed UCaaS platform (NetSapiens, Kazoo/2600Hz, a CPaaS-built stack) and white-label it | Fastest to a full feature list | Per-seat license fees, another vendor's tenancy and sign-in to glue to PhotonID, and Photon's live customers would have to move. Not recommended unless Photon wants to sell voice without building it |

**Why A:** the live customers already run on it (no migration of the engine to start); FreeSWITCH is the engine in A, B and C anyway; FusionPBX
already has multi-tenant domains, voicemail, IVRs, ring groups, time conditions, queues (`mod_callcenter`), conferences and phone provisioning
templates for Grandstream and Yealink; it is open source (FusionPBX and FreeSWITCH are under the Mozilla Public License 1.1, to confirm for the
installed versions), so nothing is per seat. **What A costs:** FusionPBX's database is its own (and odd: text read back as `bytea`, found by
PhotonConsole), its write paths are designed for its own PHP pages, its screens are not brandable, and upgrades must be tested. Those costs are
contained by the adapter below.

**When to look again (any one):** the adapter needs to reproduce more than about a dozen FusionPBX screens' logic; a FusionPBX upgrade breaks
the adapter twice; active/active is needed (§15), which is when B and C come together; or FusionPBX's maintenance stops.

### How PhotonVox drives the engine

```
 PhotonVox app (API, worker)                         engine leg (FusionPBX + FreeSWITCH)
   engine adapter ── reads: Postgres, a read-only role ──────▶  FusionPBX database
        │       └── writes: one write role, a fixed list of tables ──▶  (same database)
        └────── HTTPS over mgmtnet, signed ──▶ vox-agent ── local only ──▶ FreeSWITCH event socket (status, cache flush, reload)
                                                  └── uploads voicemail and recordings to B2 (§13)
```

- **One adapter module** (`app/engine/`) is the only code that knows FusionPBX. Everything above it speaks PhotonVox's own model (phone system,
  extension, phone, number, call flow). The adapter has one implementation today (`fusionpbx`) and is shaped so a `freeswitch` one (option B)
  could replace it.
- **Reads** use a read-only database role, as PhotonConsole's `photon_ro` does (and every query is scoped by `domain_uuid`).
- **Writes** use a second role granted `INSERT/UPDATE/DELETE` only on the tables the adapter writes, and each write is followed by the
  engine's cache flush through `vox-agent`. Every write path is tested against a **staging engine of the exact production version**: the
  adapter's test writes, then FusionPBX's own page reads it back correctly, then a scripted test call (SIPp) proves it routes. Step 0 also
  checks whether the installed FusionPBX has a usable API of its own for some writes (versions differ; not assumed here).
- **Known trap** (from the memory of live work, 2026-09-15): an inbound number needs both a `v_destinations` row and its dial plan, consistent
  with each other; hand-made rows that disagree silently drop calls. The adapter creates numbers exactly as FusionPBX's Destinations page does,
  and a test places a call to prove it.
- **`vox-agent`** runs on each engine leg (the successor to PhotonConsole's `photon-fpbx-shim`, same principle: the event socket never leaves
  localhost). It offers a fixed list of operations (status, registrations, channels, cache flush, reload, a hang-up for the fraud breaker, a
  test call), each authenticated with a signed request (`X-PhotonVox-Signature: t=…,v1=…`, suite §4) from PhotonVox only, over mgmtnet. It never
  accepts free-form commands.
- **FusionPBX's own screens** stay for Photon staff (features PhotonVox has not built yet, and troubleshooting), reachable only over mgmtnet with
  MFA, never from the internet. Customers' admins who log into FusionPBX today (question §22) move to PhotonVox.
- **Pinned versions.** The engine's FusionPBX, FreeSWITCH and Debian versions are recorded, upgraded as planned changes on staging first
  (suite OPERATIONS §2.9). FreeSWITCH's Debian packages have needed a free SignalWire access token since 2023 (to verify at Step 0).

---

## 4. The big picture

```
  SITES                                  │  ENGINE LEGS (SIP + media)                       │  PHOTONVOX CLOUD (control)
                                         │                                                   │
  desk phones ─SIP/TLS + SRTP, outbound─▶│  leg A: HTC central office (colo, primary)        │  vox-api ── Postgres (+TimescaleDB for calls)
  (voice VLAN 10.168/13)                 │    FreeSWITCH + FusionPBX + vox-agent ◀──mgmtnet──┼── vox-worker (CDR, fraud, metering, carriers)
  browser softphone ─WSS + DTLS-SRTP────▶│  leg B: Equinix DC10, Ashburn (standby, later)    │  vox-web (React)
  mobile softphone ─SIP/TLS (push)──────▶│                                                   │       ▲ HTTPS
                                         │  carriers: HTC (local, 911 on-net) ◀─SIP─▶ legs   │  browsers, apps
  PhotonEdge (optional, §12)             │            Telnyx (numbers, SMS, E911, failover)  │◀── carrier webhooks (SMS in, number events)
                                         │                                                   │──▶ Backblaze B2 (voicemail, recordings, MMS)
                                         │                                                   │──▶ PhotonConsole feed, PhotonID directory sync
```

| Piece | What it does | Stack |
|---|---|---|
| **vox-api** | Directory copy and authorization; phone systems, users, extensions, phones, numbers, call flows, emergency addresses; call history; voicemail and recordings (presigned B2 links); texting and chat (WebSocket for live updates); the provisioning endpoint phones fetch; the Console feed; carrier webhooks | FastAPI + Postgres 16 (+TimescaleDB for `call`) |
| **vox-worker** | CDR ingest and rating, the fraud breaker, metering, carrier jobs (number orders, ports, E911 address checks, 10DLC status), recording housekeeping | same image, `python -m app.worker` |
| **vox-web** | The customer and admin app, with the browser softphone (SIP over WebSocket to the engine) | React 19 + Vite + `@photon/ui`, the shared `AppShell` |
| **vox-agent** | On each engine leg: status, controlled actions, uploads to B2 | Python or Go (Step 0 decides; Python matches the shim it replaces), systemd |
| **engine leg** | Calls, voicemail, IVRs, queues, conferences, phone registrations, carrier trunks | FreeSWITCH + FusionPBX, Debian, in an LXC (colo) or a VPS (DC10) |

**The key property: calls never depend on the PhotonVox app.** If vox-api is down, phones keep registering and calling, voicemail keeps
working, 911 works. What waits: admin changes, texting, chat, the web softphone's sign-in, call history.

---

## 5. Organizations, sites and phone systems (tenancy)

PhotonVox serves organizations with `vox` switched on in the PhotonID directory (the directory's catalog already lists `vox` as "coming";
making it available is a directory change, §23). It keeps the usual read-only copy: organizations, their sites, people with a PhotonVox grant,
their effective access.

```
directory organization ──1:n── phone_system ──1:1── FusionPBX domain (on one engine, replicated to its standby)
        │                        ├── extension ── site (for 911 and site-limited admins), person (optional)
        └── site ◀───────────────┼── device (phone) ── site, emergency location
                                 ├── number ── site, emergency address, carrier, campaign
                                 └── call flow (IVR, ring group, hours, queue)
```

- **One phone system per organization by default** (decision 2). It spans all the organization's sites: extensions dial each other, one auto
  attendant can serve every site. The site still matters: every extension, phone and number names its site, which gives 911 its address
  (§8) and lets a site-limited admin manage only their site's people and phones.
- **A second phone system** for one organization only on request (a franchise whose locations want separate numbering). `phone_system` has the
  organization id and may list the sites it covers.
- **A FusionPBX domain belongs to exactly one organization** (PhotonConsole already enforces one tenant per domain per PBX instance; PhotonVox
  enforces it with a unique key on `domain_uuid` per engine).
- **Domain names** (decision 3): new ones are neutral, `<short id>.sip.photoninfra.xyz` (a random short id, not the organization's name).
  Existing ones (`huepc.pbx-pa.photoninfra.xyz`, `pbx-pa.photoninfra.xyz`) keep their names: renaming a domain means reconfiguring every phone
  on it, for nothing the customer sees. The domain is the SIP realm phones register to; customers see "your phone system", never it.
  (Whether `photoninfra.xyz` is meant to stay Photon's neutral infrastructure domain: question §22.)
- **Moving an organization to another partner** changes nothing in PhotonVox (numbers and phones stay with the organization).
- **The directory's `home_region`** is kept on each copy of an organization and stored in `phone_system`; with one region (`us-east`) it
  routes nothing yet. A second region later means a second pair of engine legs and a second PhotonVox cell (suite OPERATIONS §5.2).

---

## 6. Roles, fine limits and partner resale

### PhotonVox's roles (its own, published to the directory)

| Role | Site-limitable | Can |
|---|---|---|
| `owner` | no | Everything: numbers (order, port, release), emergency addresses, recording policy, texting registration, trunks, billing contacts |
| `admin` | yes | Users, extensions, phones, call flows, hours, queues and ring groups for their sites; emergency locations of their sites' phones; reports |
| `supervisor` | yes | Queue and ring-group membership, live queue views, listen/whisper/barge on queue calls (sensitive), recordings of their queues (sensitive), reports |
| `user` | yes | Their own extension(s): voicemail, forwarding, greetings, call history, the softphone; texting from inboxes they are given; chat |

Capabilities marked **sensitive** (suite §5, for the privacy controls to come): `vox.recording.listen`, `vox.call.monitor`,
`vox.inbox.read_shared`, `vox.number.port`, `vox.number.release`, `vox.e911.edit`, `vox.forwarding.external`.

### Fine limits stay in PhotonVox

Keyed by (person, organization), they only narrow: **which extensions are theirs** (usually one), **which shared inboxes** they may read and
send from, **which queues** they supervise, **whether they may forward calls outside** the organization, their **call class** (local, national,
international) within what the organization allows.

**An extension does not need a person.** Lobby phones, conference rooms and door stations are extensions with no user. A person with the
`user` role and no extension can still text and chat.

### Partners

- Partner staff act through partner grants ("Partner support (partner)", suite §5), audited. Partner owners and admins create organizations,
  switch PhotonVox on, order numbers and set up phone systems for their customers.
- **Partners resell Photon's PhotonVox only** (decision 5). PhotonConsole's `pbx_instance` seam (a partner's own FusionPBX) is not used by
  PhotonVox; a partner's own PBX can still be monitored by PhotonConsole, and can buy PhotonVox Trunking.
- **White-labeling:** nothing a customer sees names the carrier (PhotonConsole's rule today: "the carrier's name never reaches the customer");
  SIP domains, provisioning names and the mobile softphone are neutral or partner-branded through the suite's `branding` lookup; partner
  sign-in branding comes from PhotonID. A partner-branded mobile app is a later, paid item (decision 9).
- **Wholesale:** partners see their customers' usage (seats, numbers, minutes, texts) to bill them (§14).

---

## 7. Numbers and carriers

### Carriers

| Carrier | Role | Why |
|---|---|---|
| **Hickory Telephone (HTC)** | **Primary for local voice** in its area, and the route for 911 for numbers it serves; already HUEPC's trunk (IP-authenticated) | The engine sits in HTC's central office: on-net, one hop, and 911 goes to the PSAP the way the local carrier sends it |
| **Second carrier, recommended Telnyx** (decision 6; Bandwidth is the alternative at higher volume) | Numbers anywhere in the US and toll-free; porting by API; E911 address validation and registration by API; SMS/MMS and 10DLC; outbound failover when HTC is down; leg B's carrier | API-first, no minimums, signs STIR/SHAKEN; terms and prices to be checked before any account is opened |

- VoIP.ms is configured on the default domain and was in `FAIL_WAIT` in September 2026 (`fusionpbx-integration.md`); whether it carries
  anything is a question (§22). Recommend removing unused gateways (a gateway with credentials is a fraud path).
- **Outbound routing per call class** (§17): local and national go to HTC first, the second carrier on failure; toll-free to whichever is
  cheaper; international only if the organization has it switched on, through the second carrier; **911 always through the carrier that holds
  that number's emergency record** (§8).
- **Inbound:** each carrier delivers to both legs (primary first, standby on failure) once leg B exists; until then to leg A.
- Trunks today are **gateways in FusionPBX's default domain**, and the CDR has no gateway column (PhotonConsole matches calls to trunks by the
  bridge string and the carrier's source address). PhotonVox's call ingest uses the same matching and stores the trunk on each call.

### Numbers

- **`number`**: E.164, organization, site, carrier, kind (local, toll-free), what it rings (a call flow, extension, queue), caller ID name, its
  emergency address, texting state (off, pending registration, on, and its campaign), port state. The organization holds the number; partners
  and Photon staff act on it.
- **Ordering** through the carrier's API by area code or rate center; **releasing** has a 30-day cooling-off in PhotonVox (a number released by
  mistake can be taken back) and needs `vox.number.release`.
- **Porting in:** a tracked request (numbers, the losing carrier's account number and PIN, the authorized name, a signed letter of
  authorization, the requested date), submitted through the carrier's API, followed to its firm order commitment date, with test calls on the
  day. Numbers in HTC's own area may port to HTC instead (question §22).
- **Caller ID:** an extension may present only numbers its organization holds (no spoofing); outbound calls are signed for STIR/SHAKEN by the
  carrier, which needs the carrier to know the number is ours; caller ID name (CNAM) registered per number.

---

## 8. Emergency calling (911)

This is the part of PhotonVox with life-safety consequences. **911 must work from every phone, every softphone, during a billing restriction,
during a fraud block and during a failover.**

- **Direct dialing (Kari's Law):** 911 works without any prefix, and `9-911` also works where a site uses 9 for an outside line. Built into
  every phone system's dial plan by PhotonVox; an admin cannot remove it.
- **Notification (Kari's Law):** when anyone dials 911, PhotonVox notifies the organization's designated contacts at once (on-screen in the
  app, SMS, email, and optionally a ring on a front-desk phone) with who called, from which phone and which emergency location. The
  notification never delays the call.
- **Dispatchable location (RAY BAUM'S Act):** every emergency call carries a validated street address plus building, floor and room where
  needed.
  - **Emergency addresses** are per site, validated with the carrier (MSAG validation) before they can be used; a site may have several
    (buildings).
  - **Desk phones** (fixed): each phone has an emergency location; adding a phone requires one (defaulting to its site's main address).
  - **Softphones and mobile** (non-fixed): the app asks the user to confirm or enter where they are when it signs in and when its network
    changes, warns that 911 from the app sends the address they gave, and offers "dial 911 from your mobile's own dialer" on phones. Dynamic
    per-call locations through the carrier's API (Step 5 checks what Telnyx offers).
  - **How the location reaches the PSAP:** each emergency location is tied to a number registered with the carrier at that address; a 911
    call goes out with that number as caller ID through that carrier. For HTC-served numbers, the address is in HTC's own 911 records (how
    HUEPC's are registered today: question §22).
- **Notices to customers:** interconnected VoIP providers must tell customers the limits of VoIP 911 (power and internet outages, moved
  phones) and keep the acknowledgment. PhotonVox shows it when a phone system is created and records who accepted it (§19).
- **Testing:** each new site gets a test call to 933 (where the carrier supports it, it reads back the address) and, with the local PSAP's
  agreement, a scheduled live test. No live 911 test call without arranging it first.
- **Failover:** 911 must leave from whichever leg is active. HTC's 911 route after its softswitch moves to Ashburn must be settled with HTC
  (suite OPERATIONS §5.6) before leg B carries production.

---

## 9. Texting (SMS and MMS) and 10DLC

- **Business texting from the organization's own numbers**, two ways: **shared inboxes** (a number such as the main line, read by the people
  given access, with assignment and "done") and **personal numbers** (a user's direct line).
- **10DLC is mandatory** for texting from US local numbers to consumers. Photon registers, through the carrier (acting as Photon's campaign
  service provider with The Campaign Registry): each organization as a **brand** (legal name, EIN, address, contact; sole proprietors have their
  own path), then a **campaign** per use (customer care, account notices, mixed), with sample messages and how people opt in. Vetting takes days
  to weeks and carries one-time and monthly fees that pass through (§14). **A number cannot send a text until its campaign is approved**; the
  app says so in words. **Toll-free texting** has its own verification and is the alternative for some organizations.
- **Opt-out:** STOP, UNSUBSCRIBE and similar end texting to that person from that brand, recorded and enforced by PhotonVox before the
  carrier ever sees a message; HELP answers with the organization's contact text. Opt-outs are kept forever.
- **Messages in, messages out:** the carrier posts inbound messages and delivery reports to PhotonVox's webhook (signature checked, replayed
  messages refused); outbound goes through the carrier's API from vox-worker with per-number rate limits. MMS media is stored in B2 (§13) and
  shown through presigned links.
- **Content rules:** marketing texts need consent the customer collected (TCPA); PhotonVox's terms say so and the campaign records it. No bulk
  "blast" tool in the first releases.
- **The suite's own texts:** Photon registers one campaign of its own for platform notifications (PhotonConsole alerts, PhotonGuard alarm
  notices, sign-in codes if PhotonID ever wants them), so PhotonVox becomes the suite's SMS sender (§20).

---

## 10. Team chat, and one conversation model

- **Built into PhotonVox** (decision 10). One model for every thread: a `conversation` has a kind (`sms`, `chat_direct`, `chat_group`,
  `channel`), participants (people, or outside phone numbers for texting), and messages with attachments. The app shows them in one list,
  which is what makes it UCaaS rather than three tools.
- **Chat:** one-to-one, groups and channels inside one organization; files (to B2); mentions; read state; editing and deleting own messages
  for a while; search. **No chat between organizations** in the first releases (partner staff chat with customers is a later question).
- **Presence:** from phone registrations and calls in progress (vox-agent), the app's own activity, and a status the user sets.
- **Live updates** over a WebSocket from vox-api; **push** to browsers (web push) and later to the native app.
- **Retention:** chat and texts are kept until deleted, with an organization setting for automatic deletion after N days; exports for
  legal holds are an owner's action, audited.
- **Why not Matrix (Synapse) or Mattermost:** both are full servers with their own accounts, tenancy and operations, which would need
  PhotonID and directory glue, a second database and a second app; none of their federation or end-to-end encryption is needed here.

---

## 11. Phones: desk phones, provisioning, softphones, mobile

### Desk phones

- **Supported:** Grandstream (GRP26xx today at HUEPC) and Yealink (decision 8). Others only as "bring your own", unsupported.
- **Zero-touch:** a new phone, at first boot, asks its vendor's redirect service (Grandstream GDMS, Yealink RPS) where to get its settings;
  PhotonVox registers the MAC there pointing at PhotonVox's provisioning address. An admin adds a phone by its MAC (or scans its box label on a
  phone) and picks the extension and emergency location; the phone sets itself up when plugged in.
- **Provisioning is authenticated**: HTTPS only, a per-phone username and password delivered through the redirect service, and the files
  generated per request (never left on disk). Today's settings must be checked (question §22): unauthenticated provisioning by MAC is a known
  way to steal SIP passwords. The provisioning endpoint can stay FusionPBX's own (with its HTTP authentication and address limits on) or move
  into vox-api (recommended at Step 3: one place to log and rate-limit it).
- **Phones register to a name, not an address** (decision 14): `sip-a.<infra>` and `sip-b.<infra>` as primary and secondary (or DNS SRV where
  the model supports it). SIP over TLS with SRTP where the model supports it; UDP otherwise, on the voice VLAN (`10.168.0.0/13`).
- **Site gateways:** SIP ALG off (MikroTik sites); voice VLAN with QoS marking honored; the PhotonEdge or the gateway checks it (§12).

### Softphones

- **Browser softphone inside the PhotonVox web app** (decision 9): SIP over secure WebSocket to the engine (FreeSWITCH's WSS listener),
  media DTLS-SRTP, Opus or G.711. Works on desktop browsers; on phones the web app is for texting, chat and voicemail (mobile browsers cannot
  receive calls in the background). Media goes to the engine leg directly; a TURN service (TCP/443) only for networks that block UDP, sized
  and priced when needed.
- **Mobile calling, first:** a white-labeled softphone (Acrobits Cloud Softphone is the reference: its push service wakes the app for incoming
  calls on iOS and Android; others to compare at Step 7), provisioned by QR code from the PhotonVox app with its own SIP login per device.
  Per-user fees: to price before deciding.
- **Mobile, later: our own app**, wrapping the PhotonVox web app (Capacitor, as PhotonGuard plans) with native call handling (CallKit,
  Android's ConnectionService) and our own VoIP push. One app for calls, texts, chat and voicemail. A real project: planned after the rest
  works.
- **Each softphone and each desk phone has its own SIP login** under the extension (FusionPBX supports several registrations per extension, as
  HUEPC's extension 100 already shows), so a lost phone is one revocation.

---

## 12. PhotonEdge on site

Phones need nothing on site: they dial out to the engine. So **PhotonVox does not require a PhotonEdge** (decision 11); most voice-only sites
will not have one. Where a PhotonEdge exists (PhotonGuard or PhotonBoard sites), PhotonVox may later ask the hub for a small service,
`vox-sitekit`, under the usual rules (requested by PhotonVox, configured over its own connection, outranked by recording and safety services):

| What `vox-sitekit` would do | Why |
|---|---|
| Call-quality probes: SIP OPTIONS and a short RTP test to each engine leg every few minutes, from the voice VLAN | Says "the site's uplink is losing packets" before customers say "calls are choppy"; whose problem it is (the camwatch rule) |
| Find phones on the LAN (LLDP, DHCP options, ARP plus vendor MAC prefixes) | An installer sees which phones are plugged in and not yet provisioned |
| Check SIP ALG and NAT behavior | The most common cause of one-way audio |
| **Later, only if a customer pays for it: survivability** | A local registrar that takes over when the uplink drops: internal calls and 911 through a cellular or analog gateway. A large project; not planned |

**What happens when a site loses its internet** (no PhotonEdge needed): the engine notices the phones' registrations expire and sends their
calls to each extension's "unreachable" destination: voicemail, a mobile number, or another site's ring group (FusionPBX's forward when not
registered). The admin sets a site-wide default. Sites with a cellular failover radio (suite §8) keep calling on it if voice traffic is
prioritized.

---

## 13. Voicemail and recordings (Backblaze B2)

- **A PhotonVox bucket** (decision 12), separate from PhotonGuard's (different lifecycle, different keys, smaller blast radius), with the
  suite's prefixes: `prod/`, `dev/`, `test/`, and lifecycle rules per retention prefix, as PhotonGuard learned on B2 (expired versions and delete
  markers need their own rules).

```
{env}/vm/{tenant}/{extension}/{yyyy}/{mm}/{id}.{ext}         voicemail copies (lifecycle: kept while the message exists, then removed by the worker)
{env}/r{days}/{tenant}/{yyyy}/{mm}/{dd}/{call id}.{ext}       call recordings, by retention (r30, r90, r365, r2555)
{env}/hold/{tenant}/...                                       recordings on legal hold (no lifecycle)
{env}/mms/{tenant}/{yyyy}/{mm}/{id}                            MMS and chat files
{env}/greet/{tenant}/...                                      greetings and music on hold (sources; the engine keeps a local copy)
```

- **Voicemail stays on the engine too.** FreeSWITCH plays voicemail to the phone from its local storage, so the engine keeps it (and its
  standby a replica, §15); `vox-agent` copies each new message to B2 within seconds, and the app and email links play the B2 copy. Deleting in
  either place deletes both. The engine's copy is the working one; B2 is the copy for apps and the backup.
- **Recordings leave the engine.** When recording is on, the engine writes the file; `vox-agent` uploads it (compressed: mono MP3 or Opus at
  16–32 kbit/s, about 7–14 MB an hour), checks the upload, then deletes the local file after a few days' buffer. The engine's disk never holds
  months of recordings.
- **Size:** voice is small. A 32 kbit/s recording is about 14 MB an hour; 1,000 recorded hours a month is about 14 GB, under $0.10 at B2's
  $6.95/TB-month (PhotonGuard's figure, 2026-11-07). Storage is not a cost driver; per-organization retention is a policy and a price, not a
  capacity problem.
- **Consent:** recording is off by default (decision 12). When on, inbound calls hear a notice before they reach anyone, and recording of
  calls to or from all-party-consent states (Pennsylvania among them) is never silent. The organization chooses which calls are recorded
  (everything, queues only, on demand by a user).
- **Access:** playback and download through short presigned links, authorized at the moment of asking; every listen and download in the audit
  log; recordings encrypted by B2 at rest, with per-organization envelope keys (PhotonGuard's pattern) as a later option for customers who
  require it.
- **Voicemail to email:** through Postmark on its own message stream; it needs a paid tier (the free 100 mails a month would be gone in a day
  across customers; suite OPERATIONS R9). Transcription later, through a speech-to-text service, off by default (privacy).

---

## 14. Metering and billing hooks

PhotonVox meters from day one, before anything is charged (suite: "meter before pricing").

| Meter | From | Unit |
|---|---|---|
| Seats | extensions with a user, softphone logins | per day |
| Phones | provisioned devices (for hardware leasing, if offered) | per day |
| Numbers | local, toll-free | per day |
| Minutes | rated calls (§ below): inbound, outbound local/national, toll-free inbound, international | seconds, and cost |
| Texts | SMS segments and MMS, in and out | count |
| 10DLC | brand and campaign fees (pass-through) | events |
| Recording storage | bytes held per retention | GB-days |
| 911 | numbers with an emergency record (carrier fees) | per day |

- **Rating:** each call, after ingest, is matched to its trunk and priced from the carrier's rate deck (cost) and Photon's price list
  (`rate_deck`, data, not code); the margin is visible to platform staff only.
- **`usage_day`** per organization, meter and UTC day (PhotonGuard's `usage_camera_day` shape), rewritten for two days to catch late CDRs.
- **Billing model:** Photon bills partners wholesale, partners bill customers; Photon's direct customers sit under partner "Photon" (suite
  §13.3, proposed). Stripe Billing as PhotonBoard does, when billing is built (Step 10).
- **Telecom taxes and regulatory fees** (federal Universal Service, 911 fees by state and county, state and local telecom taxes) apply to
  voice service and depend on where each line is. They are a business decision before the first invoice (decision 17, §19): a telecom tax
  service (e.g. Avalara for Communications) or an accountant's method; the service address per number comes from its emergency address.
- **Never dark over billing:** a restricted organization keeps inbound calls, its numbers, voicemail and 911; it loses new numbers,
  international calling and new campaigns.

---

## 15. Hosting, redundancy and the ASN plan

### Where things run

| What | Where | Notes |
|---|---|---|
| **Engine leg A** | The colo in HTC's central office: a Proxmox LXC on `py` (today LXC 600, `10.10.0.21`) | On-net with HTC; primary |
| **Engine leg B** (Step 6) | Equinix DC10, Ashburn (Misaka, as the suite plans), a small VPS or server | Standby; beside HTC's coming cloud softswitch and the second carrier |
| **PhotonVox app** | Its own small VPS, Misaka Ashburn, 2 vCPU / 4 GB (decision 13) | Standalone Caddy layout, like PhotonGuard; reaches the legs over mgmtnet |
| Staging engine | A staging LXC in the colo (suite OPERATIONS §2.8), same versions as production, isolated from production phones | Step 0 |

Transit is small: a G.711 call is about 87 kbit/s each way with packet overhead (about 80 MB for an hour, both directions); Opus less.
Ten calls at once are under 2 Mbit/s. Media flows through the engine leg (FreeSWITCH anchors it), never through the app's host.

### Redundancy, in stages (the suite's stages, applied)

| Stage | What | Failover | When |
|---|---|---|---|
| **1. Rebuild fast, lose nothing** | Nightly encrypted backup of the engine (FusionPBX database, FreeSWITCH and FusionPBX configuration, voicemail, greetings) into the host backup pattern and B2; a written rebuild of a leg from the backup onto a new LXC, drilled on staging; **phones on DNS names**; unused gateways removed | rebuild: hours | Step 2 (before anything else changes) |
| **2. Warm standby at DC10** | Leg B with FreeSWITCH + FusionPBX installed, FusionPBX's Postgres a streaming replica of leg A's (over mgmtnet), files (voicemail, greetings, provisioning templates, FreeSWITCH configuration) synced continuously; phones list leg B as secondary; carriers deliver to leg B when leg A fails | **by runbook: promote the replica, start FreeSWITCH, phones and carriers follow by themselves; target 15 minutes**, drilled quarterly | Step 6 |
| **3. Active/active** | Kamailio at each leg (registrations replicated between them), both FreeSWITCH legs carrying calls, one configuration source (this is where option B of §3 comes back) | automatic, seconds | only when a contract requires it |

Why not active/active now: two live FusionPBX databases need multi-master replication, which FusionPBX supports only through extra
products, and two primaries are the classic way to lose data (suite OPERATIONS §5.4). A drilled 15-minute failover is the right level for
the size; the suite reached the same conclusion for every other product.

**The colo's own single points** (one cable, one core router, one HTC switch; suite OPERATIONS §5.5) are leg A's biggest risk today, and
they are why leg B matters more for PhotonVox than for any other product. The §12 forwarding does not help here (it runs on the engine). Until
leg B exists the only mitigation is at the carrier: a per-number failover destination (a mobile or an answering service) that the carrier
uses when the engine does not answer, if HTC offers it (question §22). Honest summary: **before leg B, a colo outage stops PhotonVox calls**.

Leg B's two-leg shape follows suite OPERATIONS §5.6: "PhotonVox gets a leg in each site, not a move." In the CO, internal and local calls keep
working if the Ashburn route is down; in DC10, outside calls keep working if the CO is down.

### The ASN plan (suite OPERATIONS §5.6; pending ARIN)

- **SIP and RTP are not anycast.** Each leg has its own unicast addresses; failover is SIP's own (primary and secondary servers, DNS SRV),
  as the suite already decided.
- **What Photon's own addresses would buy PhotonVox:** addresses that survive a change of host or provider, which matters because carriers
  (HTC's IP-authenticated trunk) and customers' firewalls allowlist them; a clean reputation for SIP; and **peering with HTC and Prizm**, which
  would put customers on Prizm member networks one hop from the engine.
- **The /24 cannot be split between sites.** If it is announced from both sites, a leg's address reaches its leg over a backhaul, which adds
  latency to media. So: leg A's and leg B's SIP addresses stay on their provider's (or HTC's) space until the network design document says
  how per-site IPv4 is handled; IPv6 /48s per leg are easy and phones that support IPv6 can use them.
- **PhotonVox depends on none of it.** Phones use names; carriers are told both legs' addresses; a later move to Photon's space is a
  planned change with both addresses allowed during the overlap.

---

## 16. Migrating today's live customers with no downtime

Today: HUEPC (domain `huepc.pbx-pa.photoninfra.xyz`, 9 extensions, Grandstream phones, HTC trunk, two numbers known) and Connor's own domain
(`pbx-pa.photoninfra.xyz`, gateways VoIP.ms and HTC), maybe more (question §22). The rule for every step: **the call path does not change until
the step that moves it, each change is made in a quiet hour with Connor's go-ahead, and each has a tested way back.**

| # | Step | Customer-visible | Way back |
|---|---|---|---|
| 1 | **Adopt read-only.** PhotonVox imports each live domain (extensions, phones, numbers, call flows, history) and links it to its organization in the directory. Nothing is written to the engine | nothing; their admin may start using PhotonVox's pages | none needed |
| 2 | **Protect.** Backups and the rebuild drill (Stage 1); fraud defaults (§17); provisioning authentication; FusionPBX's screens off the internet; unused gateways removed. One change at a time, each followed by test calls (inbound per number, outbound, a 933 call) | nothing | each change reverted on its own |
| 3 | **Phones to names.** Change each phone's server from an address to `sip-a.<infra>` (which resolves to today's address) through provisioning; phones pick it up at their next check or a reboot after hours. Connor's own phone first | a reboot after hours, if one is needed | change the setting back |
| 4 | **Console onto the feed.** PhotonConsole switches from its direct FusionPBX poller to PhotonVox's feed with the same point keys (§18), so later engine moves do not touch Console | nothing (points continue) | switch the poller back |
| 5 | **New engine pair.** Build a new leg A (current FusionPBX, FreeSWITCH, Debian) beside LXC 600 in the colo, and leg B at DC10 as its standby. Restore a copy of the configuration; **a SIP trunk between the old and new engines** | nothing | the old engine is untouched |
| 6 | **Move one domain at a time** (Connor's own first, HUEPC after it has run clean for a week): (a) final copy of the domain's configuration and voicemail; (b) the old engine routes every call for that domain over the inter-engine trunk to the new one, so voicemail is left only on the new engine from then; (c) `sip-a.<infra>` for that domain's phones points at the new engine (phones re-register within minutes; calls in progress finish where they are); (d) the carrier sends that domain's numbers to the new engine's address; (e) test calls; (f) after a week, the old engine's copy of the domain is removed | nothing, if (b) is in place before (c) | reverse (c) and (d); the old engine still has the domain until (f) |
| 7 | **Retire LXC 600** when no domain is left on it, after a backup kept for 60 days. PhotonConsole's `photon_ro`, the shim and the mgmtnet gateway `fusionpbx` move or are removed with it | nothing | restore the LXC from its backup |

Notes: whether HTC can deliver numbers to a new address without an outage, and whether it can deliver to two addresses (primary and
failover), decides how (d) is done (question §22). If the phones reach the engine by a public address that can move to the new engine
instead, (c) becomes moving that address, which is a few seconds of re-registration; the inter-engine trunk keeps it call-safe either way.

---

## 17. Security and toll fraud

**Toll fraud is the largest financial risk in a phone system**: attackers who get one SIP login, a voicemail PIN or a forwarding setting call
premium international numbers all night, and the carrier bills Photon. Defaults for every organization (decision 15), applied to the live
engine in Step 2:

| Defense | How |
|---|---|
| **Call classes** | Each organization and extension has a class: `local`, `national` (NANP, excluding the high-cost Caribbean and other NANP area codes that bill as international: the classic one-ring scam targets), `toll_free`, `international` (off by default; switched on per country, by an owner, audited), `premium` (900/976 and premium international ranges: always off). Enforced in the engine's outbound routes, not only in the app |
| **Spend breaker** | vox-worker rates calls in progress (live channels from vox-agent every 10 seconds) and finished ones; when an organization passes its daily limit (a default such as $50, set per organization) its outbound calls stop (except 911), calls in progress to the costly destinations are hung up, and Photon staff and the organization's owners are alerted at once. The carriers' own limits (channel caps, spend alerts, international off at HTC) are set as a second line |
| **Strong, unseen SIP logins** | Random 24+ character passwords, one per phone and softphone, generated by PhotonVox, never shown to customers, delivered only by authenticated provisioning; removed with the device |
| **Registration limits** | Where an organization's sites have fixed public addresses, its desk-phone logins are limited to them; FusionPBX's event guard (or fail2ban) blocks addresses that fail registration repeatedly; SIP scanners are dropped at the firewall by rate; Kamailio's flood limits later |
| **Authenticated provisioning** | §11. Plain HTTP and unauthenticated MAC-based provisioning are off |
| **Voicemail** | PINs at least 6 digits, never the extension number or a sequence, changed at first use; no outdial or callback from voicemail; repeated wrong PINs lock the box |
| **Forwarding** | Forwarding, follow-me and "unreachable" destinations to outside numbers obey the extension's call class; every change is audited and the user is told by email |
| **No DISA** | No dial-in-then-dial-out features |
| **Engine exposure** | Only SIP (TLS, and UDP where needed), RTP, and WSS are public. FusionPBX's web screens, the event socket, Postgres and `vox-agent` are reachable only over mgmtnet. Admin screens need MFA |
| **Caller ID** | Only the organization's own numbers; STIR/SHAKEN by the carrier |
| **Watching** | Calls to new countries, spikes after hours, registration storms and failed-login rates are PhotonConsole points with rules (§18), so Photon's own Console alerts on them |

Other security decisions:
- **Encryption:** SIP over TLS and SRTP where phones support it; WSS and DTLS-SRTP for the browser; HTTPS for provisioning.
- **Secrets at rest:** SIP and provisioning passwords encrypted (Fernet with `SECRETS_KEY`, suite §4); carrier API keys likewise; nothing
  printed or logged.
- **Who can listen:** recordings, live monitoring and shared inboxes are sensitive capabilities (§6), authorized at the moment of use and
  audited; the customer can see every staff and partner access.
- **CPNI:** call records and account details are customer proprietary network information under FCC rules: access only by authorized people,
  breaches reported, an annual certification (§19).
- **Lawful requests** (subpoenas, CALEA): a written procedure owned by Connor; PhotonVox can export one organization's call records and
  recordings for a time range, audited (§19).
- **RLS, tenant-isolation tests on every route, critical modules at 100% branch coverage** (BUILD-GUIDE §7), as in every product.

---

## 18. Monitoring: what PhotonConsole keeps watching

### Today (PhotonConsole's `photon_pbx` source, live)

PhotonConsole reads FusionPBX directly: Postgres as `photon_ro` (`v_xml_cdr`, `v_extensions`, `v_domains`, the non-secret columns of
`v_gateways`) and the read-only shim's `/status`, from `photon-infra-a` over mgmtnet (`10.2.1.5` → gateway `fusionpbx`, tcp/5432 and 8780).
Points per organization: `ext_<n>_registered`, registrations, `active_call_count`, `cdr_count_7d`, `enabled_extension_count`,
`concurrent_calls_peak_month`, and per trunk `trunk_<key>_minutes_today` / `_month` / `_month_inbound` / `_month_outbound`,
`trunk_<key>_channels_in_use`, `trunk_<key>_channels_peak_month`. Staff provision it per tenant (`api/app/api/routes/pbx.py`).

### Next (decision 16)

- **PhotonVox publishes the feed** every product publishes: `GET /integrations/console/v1/phone-systems`, a per-organization token from
  PhotonVox's Settings → PhotonConsole connection (scope `vox:read`, shown once, hashed), naming the organization's directory id; PhotonConsole
  refuses a document naming another organization (PhotonBoard's pattern).
- **Same point keys** as today, so rules and dashboards carry over; plus: per phone `phone_<id>_registered` (named by the phone, not only the
  extension), per number inbound calls today, per queue waiting and longest wait, texting delivery failures, emergency-address problems (a
  phone without a validated location), and the fraud breaker's state.
- **PhotonConsole's change:** a `photonvox` poller replaces `photon_pbx` for each tenant, with the point keys kept. A PhotonConsole code change:
  Connor's go-ahead (Step 4). After it, PhotonConsole no longer holds a database credential that can read every customer's call records, and
  engine moves (§16) never touch Console.
- **Photon's own health** goes to Photon's own PhotonConsole organization: each leg up and its role, registrations total, SIP error rates,
  trunk state per carrier, calls in progress against capacity, the replica's lag (Stage 2), backup age, spend per organization, 10DLC
  campaign states, the app's `/readyz`.

### PhotonVox watching itself

vox-worker raises alerts (email, and the suite's second channel) on: a leg down or its replica behind; a trunk failing; registrations of a
site dropping together (says "the site's uplink", not "eight phones"); the spend breaker tripping; a 911 call (to Photon staff as well, as a
record that one happened); B2 uploads failing; a campaign rejected.

---

## 19. Regulatory obligations to confirm

PhotonVox makes Photon an **interconnected VoIP provider** selling to end customers (directly or through partners), unless it sells as HTC's
agent. Each item below needs a telecom attorney's or accountant's confirmation before customers are added beyond today's; none is legal
advice, and some may already be covered by Photon's arrangement with HTC (question §22).

| Obligation | What it asks | PhotonVox's part |
|---|---|---|
| FCC registration (Form 499, Universal Service) | A filer ID; annual and quarterly revenue reports; contributions or reseller certificates | Revenue by category from metering (§14) |
| Robocall Mitigation Database and STIR/SHAKEN | A filing describing robocall mitigation; signing through the carrier | Caller ID limited to owned numbers; KYC on new organizations |
| 911 (interconnected VoIP rules, Kari's Law, RAY BAUM'S Act) | 911 service, registered and dispatchable locations, direct dialing, notification, customer notices of limits | §8 |
| CPNI | Protect call records and account data; annual certification; breach notices | §17, audit log |
| CALEA | Interconnected VoIP providers must support lawful intercept and file a security plan | A written procedure; possibly through the carrier |
| Telecom taxes and 911 fees | Collected per line by service address, remitted by state and county | §14; a tax service |
| 10DLC and TCPA | Registered brands and campaigns; consent for marketing texts; opt-outs | §9 |
| Call recording consent | All-party consent in Pennsylvania and other states | §13 |
| State registrations | Some states require VoIP providers to register | Business decision |

---

## 20. Links with the other products

| From → to | What | When |
|---|---|---|
| PhotonID → PhotonVox | organizations, sites, people, access (notify then pull) | Step 0 |
| PhotonVox → PhotonConsole | the per-organization feed; Photon's platform health | Step 4 |
| PhotonConsole → PhotonVox | an automation step "Send a text" / "Call and play a message" (alert notifications by voice and SMS, the "notification transport" PhotonConsole lists as open) through PhotonVox's API with a scoped token | later, with Connor's go-ahead |
| PhotonGuard → PhotonVox | alarm notifications to keyholders by text and voice call; a door station (SIP intercom) rings desk phones and shows the PhotonGuard camera beside the call | later |
| PhotonVox → PhotonGuard | a call from a door station or an emergency button can put an event on the camera that sees it (PhotonGuard's ingest API, §7.6 there) | later |
| PhotonEdge hub ↔ PhotonVox | `vox-sitekit` on PhotonEdges, if built (§12) | later |
| Every product → people | PhotonVox texts as a second notification channel next to Postmark | after the suite's own campaign is approved |

---

## 21. Names and identifiers

- Product **PhotonVox**; directory product key `vox` (already in the directory's catalog as "coming").
- Hostnames: `vox.photonind.com` (app), `api.vox.photonind.com` (API; the directory's notice address is
  `https://api.vox.photonind.com/directory/v1/notify`, as the catalog already assumes). SIP and provisioning names on the neutral
  infrastructure domain (`sip-a.`, `sip-b.`, `prov.` under it; question §22). Cloudflare DNS, gray cloud.
- Repo `photonvox` (`~/projects/photonvox`); database owner `photonvox`, app role `vox_app`, system role `vox_system`; token scope `vox:read`
  (the Console feed); headers `X-PhotonVox-Signature`; Python package `app`.
- Internal names that stay (suite §13): PhotonConsole's `photon_pbx`, `pbx_instance`, `can_provision_pbx`; FusionPBX's `photon_ro`; the
  `photon-fpbx-shim` until `vox-agent` replaces it.

---

## 22. Open questions (only Connor can answer)

**The live system** (none of this was read; a read-only inventory script is Step 0.2 of the build guide, to run with your go-ahead):
1. FusionPBX and FreeSWITCH versions, and how they were installed.
2. How many domains are live, which organizations they are, and how many extensions and phones each has. Is HUEPC in the directory (or in
   PhotonConsole since it was emptied on 10-29)?
3. Which carriers and gateways carry production calls: HTC only? Is VoIP.ms used for anything? How many numbers, and who holds them (HTC)?
4. How phones reach the engine: a public address forwarded to `10.10.0.21`, or across HTC's network? Which address? UDP or TLS? How are
   phones provisioned today (FusionPBX provisioning, GDMS, by hand), and is provisioning authenticated?
5. How 911 is routed today, and are HUEPC's emergency addresses registered with HTC?
6. Is LXC 600 backed up today (Proxmox backups? where?), and has a restore ever been tried?
7. Are call recording or voicemail-to-email in use, and through which mail server?
8. What were LXC 601 (`kamailio`, stopped) and the `kamailio_ro` database role (from `10.10.0.22`) for? Can they go?
9. Any fax machines, analog adapters, paging systems or door phones on the live sites?
10. Does anyone outside Photon log into FusionPBX's screens today?
11. Is `photoninfra.xyz` Photon's neutral infrastructure domain for the long term?

**The business:**
12. Photon's regulatory standing for selling voice (FCC 499 filer ID, Robocall Mitigation Database, CPNI): does Photon hold these, or does
    the arrangement with HTC cover them? Is there a telecom attorney to ask (§19)?
13. HTC: can it deliver numbers to two addresses (primary and failover) and change the address without an outage? Can it port numbers to
    itself and offer numbers outside its area or texting? When does its softswitch move to Ashburn, and how will 911 be routed then? Does it
    support 933 test calls?
14. Scale and priorities: how many seats and organizations in year one and two, and which comes first after voice: texting, chat, call
    queues, or mobile?
15. Budget: the second carrier's account and numbers, a white-label mobile softphone (per user), the PhotonVox VPS, Postmark's paid tier.

---

## 23. Proposed changes to the suite documents (not applied)

For Connor to accept; each is small:
- **`photon-suite/ARCHITECTURE.md` §1:** PhotonVox row: repo `photonvox`, hostnames `vox.` and `api.vox.photonind.com`, state "planned
  (design 2026-11-13); engine live", docs `docs/ARCHITECTURE.md`, `docs/BUILD-GUIDE.md`.
- **§5 role table:** PhotonVox: owner, admin, supervisor, user; site-limitable all but owner.
- **§7 table:** PhotonVox → PhotonConsole feed (`GET /integrations/console/v1/phone-systems`), replacing "FusionPBX over mgmtnet" once Step 4
  is done.
- **§10 hosting:** the PhotonVox VPS (Misaka, Ashburn) and engine leg B at DC10.
- **§11 roadmap:** phase **V1** = PhotonVox Steps 0–4 (`photonvox/docs/BUILD-GUIDE.md`), after D1 (it needs the directory); V2 = Steps 5–6;
  later steps after.
- **§13:** question 2 answered by decisions 6 and 7 here (once Connor agrees).
- **OPERATIONS.md §5.5–5.6:** nothing contradicts; add that PhotonVox leg A's colo single points are the main reason leg B is scheduled.
- **`photonid` directory:** make `vox` available in `app/catalogue.py` when Step 0 publishes PhotonVox's roles (a directory change, its own
  session).
