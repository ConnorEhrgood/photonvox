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
