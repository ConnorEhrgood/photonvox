# PhotonVox

Photon's phone system (formerly Photon PBX): a tool for integrators to deploy phone systems extremely fast on Photon's FusionPBX instances,
with Grandstream phones provisioned through GDMS and enrolled by a barcode scan, and one pane to monitor them. Signed in with PhotonID,
monitored by PhotonConsole.

**State (2026-11-13):** design only (revision 2). The engine runs in production in the colo (FusionPBX, LXC 600); this repo holds the plan for
the product around it.

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md): the design, with the decisions waiting for Connor at the top.
- [docs/BUILD-GUIDE.md](docs/BUILD-GUIDE.md): the build in steps with gates.
- [docs/BUILD-LOG.md](docs/BUILD-LOG.md): dated notes.

Suite-wide topics: `~/projects/photon-suite/ARCHITECTURE.md`.
