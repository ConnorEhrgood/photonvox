# PhotonVox's part of the demo organization, and the customer dashboard

Plan by v1, 2026-11-14, against the suite's spec `photon-suite/DEMO.md` (4ffd90a). Two jobs from Connor: (1) Vox for the demo organization
`demo`, simulated and live; (2) a customer dashboard that says what is going on in a facility ("I don't really understand what it's telling
me myself"). **Nothing goes to production until the operator brings Connor's go.** Build and test: the dev stack on LXC 800 (`photonvox-dev`)
and the staging engine CT 610.

## 1. What the demo shows

Organization **Photon Demo** (`demo`, `3560c835-5885-442d-bf55-6e250e4b5190`, the directory's fixed id: the same in dev and production).
One phone system with three of its four sites (`demo-billboards` has no phones; the slugs are photon-suite DEMO.md be6f221's). Numbers only from **(412) 555-0100 to 0199**.

| Site | Phones | Numbers | Call flows |
|---|---|---|---|
| `demo-hq` Headquarters, Pittsburgh (`72a17302-…`) | 12 extensions (100–111: reception, sales ×3, support ×3, accounts, operations, IT, a conference room, the lobby phone) | 0100 main; 0101–0104 direct lines | Menu "1 sales, 2 support, 3 accounts, 0 reception" (timeout: reception); ring groups Sales and Support (simultaneous, then voicemail); closed hours → the company's voicemail box |
| `demo-warehouse` Distribution Center, Washington PA (`736b1e29-…`) | 5 extensions (200–204: shipping desk, dock office, two forklift handsets, the supervisor) and 2 overhead speakers (220, 221; 211 is a service code) | 0140 main, 0141 the dock | Ring group Shipping; **paging** group 290 (every warehouse phone and both speakers) |
| `demo-apartments` Riverside Apartments, Wheeling WV (`e8088684-…`) | 4 extensions (300–303: leasing ×2, maintenance, the office) | 0170 leasing, 0171 maintenance line | Leasing ring group in office hours, then a box; the maintenance line rings the on-call phone, after hours its own box |

0180–0199 are "the outside world": the simulated callers and the numbers the phones call. They are never the organization's numbers.
Calling as a customer would have it: national, service and toll-free; international off; the protections on (the demo shows them as
a protected system). Hours `America/New_York` (id1's sites). Each site's 911 location is the site's city only, marked **not a real address**,
and is never sent to a carrier (the simulated engine has no carrier). The menu greetings use PhotonVox's normal voice (Google Cloud
Text-to-Speech, Chirp 3 HD "Kore", decision 30); that is the one voice source, and it goes to Connor (rule 3).

**Simulated activity** (live, all day, every day, at business-like rates in New York time):
- **Phones registered:** 22 SIP registrations (20 phones and 2 speakers). One hq phone (the conference room) is left unplugged, so the
  dashboard shows "21 of 22 online" and names it.
- **Calls:** inbound calls from 0180–0199 to the main numbers and direct lines (through the menu, the groups, to people); internal calls;
  outbound calls to 0180–0199. A few callers hang up while it rings (missed), some reach voicemail. About 150 calls a day at hq
  (peaks 10–11 and 14–15), 40 at the warehouse (two shifts, 06:00–22:00, a page every hour or so), 30 at the apartments (evenings too;
  the maintenance line at night). Calls last 20 seconds to 8 minutes. Quiet at night, as a real office is.
- **Call history back-filled** for 35 days (the same shapes), so "busiest hours" and "a typical day" have something to say on day one.
- **Voicemails:** callers who reach a box leave a 5 to 12-second **generated tone (no voice, no recording of anyone)**; most are marked
  listened to within the hour, one in five stays unheard for three days so "voicemails waiting" is not zero. Messages older than 14 days are
  removed.
- **Closed is closed:** outside a site's hours and on the federal holidays its main number goes to its voicemail box, as published; callers
  leave a message or hang up in the greeting.
- **No emergency call**, ever (never 911, 9911, 933, 988 or an N11 code, not even on staging). The dashboard's emergency card says
  "No emergency calls today". (Connor may want one shown: §6.)

## 2. How it is simulated

Real protocols end to end, on the staging engine, so PhotonVox sees the demo exactly as it sees Hickory Church:

- **The engine:** a domain `demo.vox.test` on **staging CT 610** (the spec's "staging at most"). Staging has no carrier gateways and
  Connor's nftables guard drops anything toward the HTC trunk or SIP to any public address. The only "carrier" is the SIPp upstream on
  LXC 800 (already staging's), so a demo call cannot leave by construction. PhotonVox publishes the demo there with its normal writer, so the
  dial plan, groups, menu and paging are the real FusionPBX/FreeSWITCH ones, checked by the normal post-publish test calls.
- **The phones:** a simulator, its own compose project **`vox-demo-sim`** on LXC 800 (labeled `com.photonvox.owner=vox-demo-sim`, capped at
  0.5 CPU and 256 MB, no global prune). A small Python scheduler (`sim/scheduler.py`) drives SIPp (as the build test does) from a traffic
  model (`sim/traffic.py`: the same day is the same every time, and a test holds it to the demo's document). As built (2026-11-27):
  - **Two containers, one for each side of the engine.** `carrier` runs on LXC 800's own address, which the engine knows as its carrier:
    one SIPp answers for every phone (port 5200, where the 22 registrations point; renewed every 5 minutes) and one for the carrier (5071,
    the demo's gateway), and it places the calls in. `phones` places the calls a phone makes (out, internal, a page). The engine takes
    anything from its carrier's address as the carrier without asking for a password, so the phones call from a network of their own
    (`172.31.61.0/29`, a Docker network in routed mode: no address translation), and the engine has a route back to it
    (`vox-demo-sim-route.service` on CT 610, `engine/staging/demo/`). Nothing else is on that network.
  - **Who answers is the caller's to say**, so that a call goes as the model has it: every simulated call carries `X-Sim-Answer` (an
    extension, `any` or `none`) and `X-Sim-Ring` (milliseconds), which FreeSWITCH passes to the phones it rings. The named phone answers after
    that ring; the others ring until the engine gives up on them, exactly as unanswered phones do.
  - No audio (calls end before FreeSWITCH's 300-second silence limit), except a voicemail caller's tone. Calls it could not place on time
    (the container was stopped) are skipped, never sent in a burst; at most 10 at once from each side.
  - The phones' SIP passwords go from the engine straight to a mode-600 file on LXC 800 (`config/phones.csv`), read by SIPp itself: never on a
    command line, in a log, on the runner or in git. Nothing traces a SIP message.
  - On CT 610, a timer (`vox-demo-voicemail-tidy`) keeps the voicemail boxes as §1 says.
- **Call history:** what FreeSWITCH writes (`v_xml_cdr`) for the live calls; the 35-day back-fill is inserted on CT 610 by a script, in the
  same columns FreeSWITCH writes (no XML/JSON), each back-filled row carrying `accountcode = 'photonvox-sim'`.
- **Marked as demo:** the instance in PhotonVox gets `simulated: true` (a new field). Staff see "Simulated" on the dashboard and in
  Platform. A guard in the publisher: a tenant the directory marks `demo` can be published **only** to a simulated instance, and a simulated
  instance takes only demo tenants. So the demo can never be published to live-a, and no customer to staging. The directory's `demo` flag is
  read and kept on the tenant; the demo is left out of `/v1/summary`'s counts across organizations, of platform alerts and of any usage or
  billing counts.
- **Reset and removal** (rule 6):
  - `manage demo seed <instance>`: idempotent. It writes the tenant from the directory's ids and the document above, and publishes. Run it
    again and the phone system is as written again (a visitor's edits gone). It makes new SIP passwords only for a phone system it creates,
    so the simulator keeps working across a re-seed; after `demo remove` and a new seed, run `demo-sim.sh up` again.
  - `manage demo remove`: removes the phone system from PhotonVox and the domain from CT 610.
  - `scripts/demo-dashboard.sh > answers.json` writes the demo's dashboard as the dev PhotonVox computes it, for
    `web/scripts/dashboard-shots.mjs` (screenshots; `SHOT_SCALE=2`, `SHOT_THEME=light`).
  - `scripts/demo-sim.sh up|reset|status|logs|down|remove` drives the simulator from the runner. `reset` makes the history again (the
    35-day back-fill replaces every call record of the demo's domain up to now) and empties the voicemail boxes. `remove` leaves nothing of
    it on LXC 800 or CT 610 (the route and the timer included).

## 3. The customer dashboard

Today's Overview is an administrator's page (publish state, versions, 911 confirmations): it says nothing about the phones or the calls.
The new home page (`/org/<slug>/`) answers "what is going on in my building right now and today?" for **the whole organization or one
site** (a site picker; `?site=<slug>`). The publishing page moves to **Phone system** (`/org/<slug>/phone-system`, builders only),
reached from a one-line status on the dashboard ("Phone system up to date, version 3").

**At the top, only when there is one: an emergency call today.** A red card: the time, who called (extension and name), the site and its
911 address as the carrier has it, how long, and whether it was answered. Otherwise a quiet "No emergency calls today".

**Now (refreshed every 10 seconds)**
- **Calls in progress:** the number, and each call: who (name/extension), the other side (an outside number shown as its last 4 digits,
  or a name), in, out or internal, and for how long.
- **Phones online:** "21 of 22", the offline ones named with "offline since …".
- **Lines in use:** calls on the carrier's lines now, and today's peak.
- **Outside calling in plain words:** "Calls in and out are working" / "Outside calls are failing since 10:42: we are on it", from the
  carrier gateways' state and the last outside calls' results.

**Today (refreshed every minute)**
- Tiles: **calls**, **minutes on the phone**, **missed calls** (callers who hung up or went unanswered), **voicemails waiting** (new
  messages, per box). Each one is compared with a typical day ("about the same as a usual Thursday").
- **Calls by hour:** a bar chart for today, inbound and outbound stacked, with a line for the typical day (the last 4 same weekdays).
- **Inbound vs outbound vs internal:** today and the last 7 days.
- **Busiest hours:** a weekday × hour heat map of the last 4 weeks.
- **Numbers:** each number, where it rings, calls today, the last call.

The design follows photon-ui's tokens (light and dark), works at 390 px, and uses no chart library (small inline SVG, labeled for screen
readers, with the numbers also in text). It works with few calls. Hickory Church's Tuesday might be "3 calls, 11 minutes", and the page
must read well then too (no empty charts: "A quiet day so far").

**Where the numbers come from**
- New `GET /tenants/{id}/dashboard?site=<slug>`, cached 10 seconds per tenant and site.
- **Call history:** PhotonVox's existing read of `v_xml_cdr`, which production's read role already has (every column but the raw XML/JSON,
  recordings, PINs and network addresses). Times are in the site's zone. A site's calls are those of its numbers (in) and its users'
  extensions (out and internal).
- **Phones, calls in progress, gateways:** a new **read-only** vox-agent operation `live`. For one domain it returns:
  - the registrations: the extension, when it registered, and the phone's model, but not its address;
  - the channels: direction, caller and callee numbers, start and state;
  - the gateways' states.
  It runs `show registrations`, `show channels` and `sofia status gateway` as JSON and filters them by the domain. It can change nothing.
- **Voicemails waiting:** counts from `v_voicemail_messages` (box, created, status only; never the caller, the audio or a transcription).
- **Emergency calls:** from the call history (destinations 911/933, and 9911 where a site dials 9), with the site's 911 location from
  PhotonVox's own record.

## 4. Build and test (dev and staging only)

1. API:
   - `simulated` on the instance, `demo` on the tenant (migration 0010);
   - the publisher's demo guard;
   - the `demo` flag read from the directory's sync;
   - the summary leaves the demo out;
   - `GET …/dashboard`;
   - `manage demo seed|remove`;
   - **paging groups** in the document (new: `pages`, with an extension and members; FreeSWITCH's conference page with auto-answer),
     compiled, written and checked like groups.
2. vox-agent: the `live` operation, with tests. It is staged on CT 610 with `VOX_AGENT_OPERATIONS` including it.
3. Web: the dashboard (site picker, the tiles, the charts), and the Phone system page (today's Overview, moved). Tests for every state:
   none, quiet, busy, an emergency today, the trunk down, phones offline, a viewer.
4. The simulator (`sim/`): the scheduler, SIPp scenarios (phone, caller, a page), the back-fill, `scripts/demo-sim.sh`. (Built 2026-11-27,
   with tests in `sim/tests`; running on LXC 800 against the dev PhotonVox's demo.)
5. On dev:
   - publish the demo to CT 610 from `photonvox-dev` (seeded with id1's ids, or pulled from the dev directory once id1 connects vox there);
   - run the simulator for a day;
   - screenshot the dashboard (whole org and each site, 1440 and 390, light and dark);
   - run the dashboard against a copy of Hickory Church's shape (its document on a staging domain, with test calls through the SIPp
     upstream) for the quiet case.
6. The screenshots go to Connor through the operator before anything is released.

## 5. Production steps (each its own file in `~/vox-takeover/`, each with the operator's go) and rollback

| # | Step | Rollback |
|---|---|---|
| P1 | Deploy PhotonVox with the dashboard, paging, the demo guard and migration 0010 (expand only). Backup first. | Redeploy the previous commit (0010 stays; its columns are unused) |
| P2 | CT 600 (Hickory's dashboard data): vox-agent with the `live` operation (read-only) and publish checks that leave no call record (2026-11-27: until then every publish adds a "missed call" or two to Hickory's dashboard), `VOX_AGENT_OPERATIONS` += `live`; `grant select (voicemail_message_uuid, domain_uuid, voicemail_uuid, created_epoch, message_status) on v_voicemail_messages to photonvox_ro`. No FusionPBX row, no restart of FreeSWITCH. | The previous `vox_agent.py` and env (kept as `.bak`); `revoke` the grant |
| P3 | The path production → CT 610: CT 610 joins mgmtnet as a gateway (mgmtnet's own process, its auto-revert and confirm), grant `console` → it tcp/5432,8780; CT 610's iptables and `pg_hba` admit 10.2.1.5 (one line each, as on CT 600). | Remove the grant and the lines |
| P4 | Register the instance `demo-sim` (CT 610, `simulated: true`, upstream the SIPp carrier only); `manage demo seed` (the tenant from the directory's ids; publish to CT 610; back-fill). | `manage demo remove`; remove the instance |
| P5 | `scripts/demo-sim.sh up` on LXC 800, then `reset` once. (On dev since 2026-11-27: P5 changes nothing but which PhotonVox reads the demo.) | `scripts/demo-sim.sh remove` |

P1 and P2 serve Hickory Church too and can go before the demo. Live doors (PhotonEntry) need `door-calls` in the same operations list
later; it is not part of this.

**Monthly cost: about $0.**
- CT 610 and LXC 800 are on Connor's Proxmox. The load: about 150 MB of memory more for FreeSWITCH and 256 MB at most for the simulator,
  well inside CT 610's 2 GB (1.6 GB free) and its 5.5 GB of free disk; voicemail tones total about 50 MB.
- On the Vultr host: a few kilobytes a second over WireGuard while someone looks at the dashboard.
- No B2 and no carrier.
- Text-to-speech for about ten greetings, once: inside Google's free tier.

## 6. Connor's decisions

**Answered (the operator, 2026-11-14):** 1. CT 610, as recommended; it rides Connor's one rollout go with the other products. 2. No emergency
call in the demo's history. 3. Google's Chirp 3 HD voices are fine; a synthetic voice reading our own fictional text needs no further
approval. The dashboard is built first (it helps Hickory Church now), then the demo; its screenshots go to the operator as soon as they look
right, with Hickory's real numbers and with the demo's.

The questions as asked:

1. **Production PhotonVox reads and publishes to the staging engine CT 610** (P3, a new mgmtnet path), the demo living there beside the
   build tests (they touch only their own domains). The alternative is a separate demo container built the same way (another 2 GB of memory
   on py), which keeps staging free for tests. Recommended: CT 610.
2. **An emergency call in the demo's history?** None (recommended), or one back-filled row (no call is ever placed) so prospects see the
   emergency card.
3. **The greeting voice:** Google Cloud Text-to-Speech, PhotonVox's normal voice (rule 3: a voice source goes to Connor).
