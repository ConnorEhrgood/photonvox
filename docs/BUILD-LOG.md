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
