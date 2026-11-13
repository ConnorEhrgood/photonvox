# PhotonVox — architecture

**Status:** design, revision 2, 2026-11-13. Nothing is built. Revision 2 follows Connor's product direction of the same day (below), which
takes priority over revision 1 wherever they differ. The live phone system (FusionPBX in LXC 600, `10.10.0.21`) was **not read or touched**:
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

## Decisions for Connor

Each line is a yes/no; the recommendation is **yes** for every line. BUILD-GUIDE.md assumes these answers; a "no" changes the section named.

| # | Decision | Why yes | § |
|---|---|---|---|
| 1 | **The first release (R1) is: fast deployment (wizard, templates, bulk import), several FusionPBX instances, routing abstracted, Photon trunking with locked 911, GDMS, barcode enrollment, the monitoring pane and the PhotonConsole feed, toll-fraud defaults.** R2: partner trunks, taking over today's hand-built customers, the standby engine at DC10, number automation, the browser softphone, voicemail and recordings in the app, metering. R3: texting, chat, the mobile softphone | It is Connor's product, and the smallest release that delivers it | 1 |
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
| 18 | **PhotonVox's app on its own small VPS** (Misaka, Ashburn, 2 vCPU / 4 GB). *Costs money* | Calls never depend on the app; it should not share a failure with PhotonID or PhotonGuard | 16 |
| 19 | **Redundancy: a warm standby instance at Equinix DC10 in R2**, promoted by a drilled runbook (target 15 minutes). Phones point at names from day one (GDMS holds the server names, so a move is one edit and a push) | Matches the suite's Stage 3; names keep every later move invisible | 16 |

Dropped from revision 1 (no longer decisions now): Telnyx as the second carrier (replaced by 7), a login per phone (replaced by 13), and the
R3 items (texting, chat, mobile softphone, B2 bucket for recordings), which keep their design in §18 and come back as decisions before their
release.

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
| **R2** | Partner trunks; taking over today's live customers; the standby instance at DC10; number ordering, porting and E911 records through upstream APIs (where they exist); the browser softphone; voicemail and recordings in the app (B2); metering for billing; call queues with supervisor views; Yealink |
| **R3** | Texting and 10DLC; team chat; the mobile softphone; billing itself |

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
- **Writes go to FusionPBX's database** with a role limited to the tables the adapter writes, in one transaction per publish, followed by the
  engine's cache flush and XML reload through vox-agent. Whether some objects are better written through FusionPBX's own API (versions differ)
  is settled in Step 0.
- **Each object is written exactly as FusionPBX's own page would** (the known trap: an inbound number needs a destination row consistent with its
  dial plan, or calls drop silently). Every kind of write has a test on a staging instance of the same version, ending in a real SIP call.
- **Publish is checked**: after writing, vox-agent places a synthetic call through each new inbound route and the 911 route's selection
  (stopping before the call leaves the engine), and PhotonVox shows "Ready" only when they pass. A failed publish restores the previous
  version of the phone system (PhotonVox keeps every published version).
- **Drift:** the worker compares what FusionPBX holds with `engine_object` hashes every few minutes. A difference (someone edited FusionPBX by
  hand) is shown on the phone system ("changed outside PhotonVox") and replaced by the next publish (decision 5). Objects PhotonVox did not
  write are left alone and listed.
- **vox-agent** (one per instance) offers fixed operations only, signed (`X-PhotonVox-Signature: t=…,v1=…`) and over mgmtnet: status,
  registrations, channels, gateway states, cache flush, reload, synthetic call, hang up a call. The event socket never leaves localhost.

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
| unreachable phones | each extension's "not registered" forwarding to the site's choice |
| internal dialing | extension range, feature codes (voicemail `*97`, etc.), consistent in every phone system |

- **Deterministic:** the same document compiles to the same objects; a template applied twice gives the same phone system.
- **Validated before writing:** every number has an outcome; every site with phones has a validated emergency address and an emergency number;
  caller ID only from held numbers; no loops (a group whose "then" points back at itself); extension ranges do not collide with feature codes
  or 911/933/988/311-style service codes.
- **Versioned:** each publish is a version with who and when; "undo" publishes the previous one.

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
  have moved: its 911 address may be wrong"). Softphones (R2) ask the user for their location.
- **Customer notice of VoIP 911 limits**, accepted and recorded when a phone system is created (§19).
- **Never place a real 911 test call** without the PSAP's agreement; 933 and the engine's synthetic check are the tests.
- With HTC: how emergency records are created and changed (by hand, with what turnaround) and how 911 will be routed after HTC's softswitch
  moves to Ashburn are questions (§22).

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
| **Voicemail** | PINs of 6+ digits, random at creation, emailed to the user; no outdial or callback; lockout after repeated wrong PINs |
| **Forwarding** | Outside forwarding obeys the call class; changes audited and emailed to the user |
| **No DISA** | No dial-in-then-dial-out features are generated |
| **Engine exposure** | Only SIP, RTP (and WSS in R2) are public. FusionPBX's screens, Postgres and vox-agent only over mgmtnet; staff screens need MFA. FusionPBX's own phone provisioning is switched off for GDMS-provisioned phones |
| **GDMS** | The API user and secret encrypted; the GDMS web login for staff with MFA; phones' admin passwords set by Photon's template; the phones' web interface limited |
| **Caller ID** | Only held numbers; signed by the upstream |

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
| **Staging instance** | A staging LXC in the colo, same versions as production, isolated from production phones |

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

## 18. Later releases (designed, not in R1)

| Item | Release | Design notes kept from revision 1 |
|---|---|---|
| **Browser softphone** | R2 | SIP over WSS to the instance, DTLS-SRTP, in the PhotonVox web app; a TURN service only for networks that block UDP |
| **Voicemail and recordings in the app** | R2 | A PhotonVox B2 bucket (`prod/`, `dev/`, `test/`), vox-agent copies voicemail and uploads recordings; recording off by default, with a consent notice where law requires (Pennsylvania needs all parties' consent); every listen audited |
| **Metering** | R2 | `usage_day` per organization and meter (seats, phones, numbers, minutes by class and trunk, recordings); CDR rating against Photon's rate table; wholesale to partners; telecom taxes and fees decided before any invoice (§19) |
| **Call queues and supervisors** | R2 | FusionPBX call center as an outcome; the `supervisor` role |
| **Yealink** | R2 | Yealink's redirect service (RPS) or management cloud in place of GDMS, behind the same "phone" model |
| **Partners' own GDMS accounts** | R2+ | GDMS connection per partner; the same device flow |
| **Texting (SMS/MMS) and 10DLC** | R3 | Needs an upstream with messaging (§22). Brands and campaigns per organization through the upstream; shared inboxes and personal numbers; STOP/HELP enforced; MMS media in B2; Photon's own campaign for suite notifications |
| **Team chat** | R3 | Built in, one conversation model with texting; presence from registrations |
| **Mobile softphone** | R3 | White-label first (push for incoming calls), own app later |
| **PhotonEdge service** | later | Optional call-quality probes and phone discovery on sites that have a PhotonEdge; survivability only if a customer pays |

---

## 19. Regulatory obligations to confirm

Selling phone service makes Photon an **interconnected VoIP provider** unless it sells as HTC's agent. Each item needs a telecom attorney's or
accountant's confirmation before customers are added beyond today's (not legal advice; some may be covered by the arrangement with HTC):
FCC registration and Universal Service reporting (Form 499); the Robocall Mitigation Database and STIR/SHAKEN through the upstream; 911 rules
for interconnected VoIP, Kari's Law and RAY BAUM'S Act (§11); CPNI protection and annual certification; CALEA; telecom taxes and 911 fees per
line; state registrations; call-recording consent (R2); 10DLC and TCPA for texting (R3).

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
infrastructure domain. Repo `photonvox`; database owner `photonvox`, roles `vox_app` and `vox_system`; scope `vox:read`; header
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
6. E911: how are emergency records created and changed, how fast, and can addresses be validated before use? 933 support? How will 911 be
   routed after HTC's softswitch moves to Ashburn?
7. CNAM (caller-ID name) updates; per-number failover destinations; delivering to two addresses (an instance and its standby).
8. Texting (R3): does HTC offer SMS/MMS and 10DLC registration?

**The live system** (not read; the read-only inventory script is BUILD-GUIDE Step 0.2)
9. FusionPBX and FreeSWITCH versions; number of domains, extensions and phones; which gateways carry production calls (is VoIP.ms used?);
   how phones reach and are provisioned by the engine today; how 911 is routed today; whether LXC 600 is backed up; what LXC 601 (kamailio)
   was for; whether anyone outside Photon uses FusionPBX's screens.

**The business**
10. Photon's regulatory standing for selling voice (§19): what it holds, what HTC covers, and who to ask.
11. The first templates to build (which kinds of customers come first), and how many phone systems are expected in year one.
12. Budget: the PhotonVox VPS; Postmark's paid tier (voicemail to email and alerts); any upstream beyond HTC.

---

## 23. Proposed changes to the suite documents (not applied)

- **`photon-suite/ARCHITECTURE.md` §1:** PhotonVox row: repo `photonvox`, hostnames, state "planned (design rev 2, 2026-11-13); engine live",
  "a tool for integrators to deploy phone systems on Photon's FusionPBX instances and Grandstream GDMS".
- **§5 role table:** PhotonVox: owner, admin, user (supervisor later); site-limitable all but owner.
- **§7:** PhotonVox → PhotonConsole feed, replacing "FusionPBX over mgmtnet" once PhotonConsole moves to it; PhotonVox ↔ GDMS (outbound API
  and push callbacks).
- **§10:** the PhotonVox VPS; instances in the colo and later DC10.
- **§11 roadmap:** phase **V1** = PhotonVox R1 (BUILD-GUIDE Steps 0–6), after D1.
- **§13:** question 2 answered by decisions 7 and 8 here once Connor agrees.
- **`photonid`:** make `vox` available in `app/catalogue.py` once PhotonVox publishes its roles (its own session).
