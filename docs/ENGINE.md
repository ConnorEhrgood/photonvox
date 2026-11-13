# PhotonVox: the engines

What each FusionPBX instance runs, so a staging instance or a rebuild matches production exactly. Counts and versions only; the inventory
reports themselves (they name domains) stay out of git.

## Production: instance A (LXC 600 on Proxmox `py`, HTC's central office)

From the read-only inventory of 2026-11-13 (`scripts/inventory/`, ARCHITECTURE §17a):

| | |
|---|---|
| Debian | 12 (12.14) |
| FusionPBX | 5.5.12, installed with the FusionPBX install script |
| FreeSWITCH | 1.11.1 (release build of 2026-05-26) |
| PostgreSQL | 18 (18.4, from the PostgreSQL project's Debian repository) |
| Container | unprivileged LXC, 4 cores, 4 GB memory, 1 GB swap, 32 GB root disk on local LVM |
| SIP profiles | internal (5060), external (5080), `htc` (5082, the HTC trunk), and their IPv6 twins |
| NAT | FreeSWITCH autonat for SIP and RTP |
| Protection | fail2ban, FusionPBX's event guard, iptables policy DROP |

## Staging (not built: GATE 0a)

The same versions as production. **No carrier gateways, never the HTC trunk, outbound SIP to the internet blocked** (Connor, 2026-11-13); a SIPp
upstream on LXC 800 plays every carrier. The install steps go here as they are done, so the instance can be rebuilt from this file.
