# PhotonVox: Step 0.7 spikes

Findings with evidence. Each section says how it was found, what was measured, and what it decides.

## 1. The engine write path

**Question (BUILD-GUIDE 0.7):** for each object the compiler writes, how FusionPBX's own page writes it; whether this version has a usable API
of its own; a prototype write of each, proven by a SIPp call.

**Setup (2026-11-13).** Staging engine `vox-staging` (FusionPBX 5.5.12, FreeSWITCH 1.11.1: docs/ENGINE.md). A test domain `spike.vox.test`.
The SIPp upstream on LXC 800 (`scripts/sipp.sh`, image `photonvox-sipp:3.6.1`) plays the carrier on 10.10.0.80:5070 and the callers; SIPp
"phones" register as extensions and answer. Tools, in `engine/spike/`:
- `page.mjs` drives FusionPBX's own pages in headless Chromium as its admin (fills the form, presses Save), so every row below was written by
  FusionPBX itself;
- `snapshot.py` saves every `v_*` table by primary key on staging and diffs two snapshots, so the rows each page wrote are exact.

### 1a. What each page writes (measured)

| Object (page) | Rows written | Dial plan | Proven by |
|---|---|---|---|
| Domain (`core/domains`) | `v_domains`; **31 dial plans in the domain's context** and 1 in `conf-xfer@<domain>`, with 335 detail rows (the domain's copy of FusionPBX's standard dial plans: caller ID, call block, recordings, voicemail, paging, valet park, DISA (disabled) and more) | the standard set | the calls below, all in that domain |
| Gateway (`app/gateways`) | `v_gateways` (global: `domain_uuid` empty); no file; FreeSWITCH names the gateway by its uuid (`external::<uuid>`) and it is live at once (`NOREG` for IP authentication) | none | outbound calls |
| Upstream's address (`app/access_controls`) | `v_access_control_nodes` (allow `10.10.0.80/32`) in the `providers` list; the page reloads the list (`acl 10.10.0.80 providers` = true at once) | none | inbound calls: **without it the external profile challenges the carrier (407) and refuses it (403)** |
| Extension (`app/extensions`) | `v_extensions` (a generated 20-character SIP password; `accountcode` = domain; `user_context` = domain) and **`v_voicemails`** (box = extension, the PIN given) in the same save | none (the domain's standard dial plans route to it) | a SIPp phone registered as 1001; calls in and out |
| Outbound route (`app/dialplan_outbound`) | per route: a dial plan named `<gateway>.<pattern name>` (`app_uuid` 8c914ec3…, the order given) with ~20 detail rows, **and another `call_direction-outbound` dial plan (order 22) each time** | conditions `${user_exists}`=false, `${toll_allow}` (if set), `destination_number`; actions set caller ID, `continue_on_fail`, bridge `sofia/gateway/<uuid>/$1`; some rows written disabled (accountcode header, call date, limit, PIN) | national and 911 calls reached the upstream |
| Inbound number (`app/destinations`) | `v_destinations` (number, `destination_number_regex` `^\+(12125550100)$`, `destination_actions` JSON and the first action in `destination_app`/`destination_data`) and a **public-context dial plan named after the number** with 2 detail rows | sets `domain_uuid`, `domain_name`, `call_direction=inbound`, then the action | upstream → number → phone 1001 answered |
| Ring group (`app/ring_groups`) | `v_ring_groups`, `v_ring_group_destinations` (one per member) and a dial plan (order 101) **with `dialplan_xml` only, no detail rows** | `ring_ready`, `ring_group_uuid`, then `lua app.lua ring_groups` | upstream → number → ring group 2000 → both phones rang at once, one answered |
| IVR menu (`app/ivr_menus`) | `v_ivr_menus`, `v_ivr_menu_options` (action `menu-exec-app`, param `transfer 2000 XML <domain>`), a dial plan (order 101, XML only) | answer, sleep 1 s, `ivr <uuid>`, then the exit action | upstream → number → menu; no key pressed → timeout → exit to 1002, which rang (pressing a key: not yet tested) |
| Time condition (`app/time_conditions`) | a dial plan (`app_uuid` 4b821450…, order 300) and 5 detail rows; no table of its own | `<condition wday="1-7" break="never">` → the open action; a second `destination_number` condition → the closed action | upstream → number → time condition (every day) → 1001 rang, 1002 did not |

### 1b. Traps found

- **Call classes are matched as unanchored regular expressions.** The extension page stores the field `national,toll_free` as
  `national:toll_free`; a route's condition is `${toll_allow}` matched against the class name as a regex. `national` therefore also matches an
  extension whose classes include `international-44`. The compiler must write anchored expressions (`(^|:)national(:|$)`) and the colon form.
- **The 911 route is special in FusionPBX:** for a pattern containing 911 the page sets `effective_caller_id_name/number` from the extension's
  `emergency_caller_id_*` instead of the outbound ones. Our compiler already sets an emergency caller ID per extension; the route must use it the
  same way.
- **Every outbound route the page adds also adds a `call_direction-outbound` dial plan** (two routes, two copies, same content). Harmless; the
  adapter should write one per domain, not one per route.
- **Creating a domain also wrote 72 empty `v_dialplans` rows** (every column null but the uuid and insert date). Apparently a FusionPBX 5.5.12
  bug; harmless to calls; the adapter must not copy it, and drift checks must ignore rows with no domain and no context.
- **Caller ID reaches the carrier in `Remote-Party-ID`** (`"Spike Office" <sip:+12125550100@…>`); the From user is the gateway's username.
  Which header HTC reads is a question for HTC (P-Asserted-Identity is the usual one).
- **Inbound numbers match exactly as stored** (`^\+(12125550100)$`): the form the carrier delivers (E.164 with `+`, 11 digits, 10 digits) must
  be known per upstream, and the adapter writes that form.
- **Each domain's standard dial plans include eavesdrop and call intercept, enabled** (DISA is present but disabled). Whether integrators'
  customers should have them on is a defaults question (§15).

### 1c. Direct writes (the adapter's way): proven

A second domain, `proto.vox.test`, was written **without FusionPBX's pages**, by `engine/spike/direct.py` (SQL in one transaction, rows and
XML copied from what the pages wrote), and proven by `engine/spike/prove.sh`: **20 of 20 checks pass** (2026-11-13).

| Object | How it was written | Made live by | Proven |
|---|---|---|---|
| Domain | insert `v_domains`, then FusionPBX's own `php core/upgrade/upgrade.php --defaults` as `www-data` (1.1 s) | the same | it wrote the domain's 32 standard dial plans exactly as the domain page does |
| Gateway | insert `v_gateways` | delete `<hostname>.configuration.sofia.conf`, `sofia profile external rescan` | live at once; calls left by it |
| Upstream's address | insert/delete `v_access_control_nodes` | delete `configuration.acl.conf`, `reloadacl` | `acl 10.10.0.80 providers` true/false |
| Extension and voicemail box | insert `v_extensions` and `v_voicemails` | delete `directory.<ext>@<domain>` | registered; calls in and out |
| Outbound routes | one `v_dialplans` row each, `dialplan_xml` only; one `call_direction-outbound` per domain | delete `dialplan.<domain>` | national call with the outbound caller ID; 911 with the **emergency** caller ID; an extension without the class **refused** (anchored match), and nothing reached the upstream; 911 from it allowed |
| Inbound numbers | `v_destinations` + public `v_dialplans` row describing the same number | delete `dialplan.public.<number>` in each form a carrier may send (`+1…`, `1…`, 10 digits) | upstream → each number → its target |
| Ring group | `v_ring_groups`, `v_ring_group_destinations`, its dial plan | delete `dialplan.<domain>` | both phones rang |
| IVR menu | `v_ivr_menus`, `v_ivr_menu_options`, its dial plan | delete `dialplan.<domain>`, `configuration.ivr.conf.<uuid>` | key 1 (SIP INFO) → the ring group rang |
| Time condition | its dial plan | delete `dialplan.<domain>` | Monday–Thursday hours on a Friday → closed → 2002 rang, 2001 did not |

What it settles (with the source study of FusionPBX 5.5.12, kept outside git; its findings are folded in here):
- **FreeSWITCH reads only `v_dialplans.dialplan_xml` at call time**; `v_dialplan_details` serves FusionPBX's editor. A direct write must
  write the XML; detail rows matter only if FusionPBX's screens are used to view or re-save those dial plans (a re-save regenerates the XML
  from details, which would erase a dial plan written without them). **Recommendation:** the adapter writes the detail rows too for the kinds
  that have them (routes, inbound numbers, time conditions), so FusionPBX's screens show the truth; drift detection catches any re-save.
- **The cache is files that never expire** (`/var/cache/fusionpbx`, both PHP and Lua set to `file` on this install). After each publish the
  adapter (through vox-agent) deletes exactly the keys above; no restart and no `reloadxml` is needed except the profile rescan for gateways.
  Some pages delete the wrong key (adding an extension deletes the next number's directory entry; the voicemail page deletes none); the adapter
  must not copy that.
- **Inbound numbers (the known trap), precisely:** in this install's `single` mode, a public dial plan is loaded only if a `v_destinations` row
  points at it **and** its number columns equal the incoming number; the regex in the XML must also match it. The adapter writes both from one
  value and the publish check calls every number (ARCHITECTURE §5).
- **New domains are seeded by FusionPBX's own `--defaults`**, not by copying rows. It runs every application's defaults for every domain: on
  staging it also deleted the 72 empty dial plan rows the domain page had left and normalized a few null columns elsewhere. It is idempotent and
  is FusionPBX's own upgrade step, but on a production instance it touches every domain, so vox-agent runs it as one operation per publish of a
  new domain and the drift check runs after it.
- **Columns the pages fill that a direct write must fill too:** `insert_date` (and `insert_user`: left null here; the adapter can use a
  FusionPBX user of its own), the colon form of `toll_allow`, plaintext SIP and voicemail passwords (FusionPBX stores them so; they stay in the
  engine and PhotonVox keeps its own encrypted copy), `accountcode` and `user_context` = the domain. Pages also add a `v_database_transactions`
  row per save (FusionPBX's change log); the adapter keeps its own audit instead (open: whether to write theirs too).
- **The providers list applies to the internal profile as well** (FusionPBX's default): a phone at a carrier's address skips authentication.
  Harmless while carriers' addresses never host phones; staging's tests take the upstream's address out of the list for outbound tests.

Not covered yet: the voicemail page on its own (the extension page writes the same row), caller-ID name delivery to HTC (`Remote-Party-ID`
vs `P-Asserted-Identity`: HTC's answer), holidays and date ranges in time conditions, a publish that changes or removes objects (the same
writes plus deletes; next, with vox-agent's first version), and what FusionPBX's editor shows for XML-only dial plans.

### 1d. FusionPBX's own API

**None for writing** in 5.5.12: no REST or JSON write endpoints (the JSON pages are read-only lookups). What exists: any page accepts an
API key (`?key=` on a user's 32-character key) but still needs the form's CSRF token, so it is page automation; CSV import pages for
extensions, destinations and voicemail; the CLI `upgrade.php` (`--defaults`, `--schema`, `--permissions`, `--services`); PHP classes that
assume a logged-in session. **Decision taken by the spike: write the database directly** (as ARCHITECTURE §5 planned), seed domains with
`--defaults`, and clear the cache keys through vox-agent. Page automation stays a tool for the spike only.

### 1e. Tools and how to rerun

- `scripts/sipp.sh build` (image `photonvox-sipp:3.6.1`, 121 MB, on LXC 800 in `/root/vox-test/sipp`), then `engine/spike/prove.sh` after
  `python3 engine/spike/direct.py` is applied on staging (§1c). Containers are named `vox-sipp-*`, labeled `com.photonvox.owner=photonvox-tests`,
  removed when they exit; `scripts/sipp.sh clean` removes the logs, `clean --image` the image too.
- `scripts/staging-check.sh` was also proven to fail on a gateway that is not the SIPp upstream (one added to the database, then removed).
