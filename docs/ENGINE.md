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

## Staging: `vox-staging` (Proxmox CT 610, 10.10.0.60)

Created by Connor on 2026-11-13: Debian 12, 2 cores, 2 GB memory, 10 GB disk (small on purpose: it shares the Proxmox root disk). SSH from the
runner: `ssh -i ~/.ssh/vox_staging root@10.10.0.60`.

**Staging never reaches a carrier** (Connor, 2026-11-13): no carrier gateways, never the HTC trunk, no public port forward, no gateway or trunk
credentials copied from production (production configuration may be copied for reference with its secrets left out). Connor's nftables guard
(`/etc/nftables.conf`, table `inet vox_guard`) drops everything to 172.30.254.0/24 (the HTC trunk) and new SIP (ports 5060–5099) to any public
address, IPv4 or IPv6. **Never change or disable it.** `scripts/staging-check.sh` proves it from the runner: the guard's rules are present, no
gateway exists but the SIPp upstream, and an INVITE from FreeSWITCH to a public address (a documentation address) is dropped. A SIPp upstream on
LXC 800 plays every carrier (Step 0.6).

### How it is built

`engine/staging/build.sh`, run once as root on a fresh container (the command is at its top; about 12 minutes, 9 of them compiling
FreeSWITCH; it refuses a container that already has an install). It is **the FusionPBX install script as it stood when production was installed**, with production's versions pinned:

| | Pinned to | Why |
|---|---|---|
| fusionpbx-install.sh | `1d4100b` (2026-05-18) | the script from 2026-05-18 to 2026-07-30; production's FusionPBX (5.5.12: 2026-06-25 to 2026-07-30) was installed in that window |
| FusionPBX | `0d7a986` on branch 5.5 (2026-07-30) | the last commit at version 5.5.12. Production's exact commit is not known (its install has no git metadata the inventory could read) |
| FreeSWITCH | tag `v1.11.1` (`c2c5964`) | the commit production's build reports |
| sofia-sip | 1.13.17 | the script's setting at `1d4100b` |
| libks, spandsp, FusionPBX's optional apps | the last commit before 2026-07-31 | the script clones them at their head; pinned to the same window |
| PHP | 8.2 (packages.sury.org) | the script's setting at `1d4100b` |
| PostgreSQL | 18 (apt.postgresql.org) | as production |

Changes to the script, all made by `build.sh` with `sed` so the diff is short and visible (`git diff` in `/usr/src/fusionpbx-install.sh`):
- **No recommended packages** (Connor's rule): `APT::Install-Recommends "0"` for every install, and `--no-install-recommends` on the script's own.
- **Unprivileged container:** the realtime scheduling lines of the FreeSWITCH service are commented out, as the install script itself does since
  `6794bc1` (2026-10-14); an unprivileged LXC refuses them.
- The sound tarballs are deleted once unpacked; the FreeSWITCH build objects are cleaned at the end (the sources stay in `/usr/src`).
- The admin's password, which the install prints, goes to `/root/vox-staging-admin.txt` (mode 600) and never into `/root/vox-build.log`.

Left as the script does it, like production: the iptables rules (legacy iptables, policy DROP; they sit beside Connor's nftables guard and do not
touch it, and `build.sh` checks the guard is unchanged at the end), fail2ban, FusionPBX's event guard, the SNMP daemon (its port is closed by the
iptables rules), the single domain named after the container's address.

### Built

**Reset point:** Connor saved the fresh container (Debian 12, guard in place, nothing installed) as
`vzdump-lxc-610-2026_11_13-12_24_37.tar.zst` on `py`'s local storage (stop mode, 192 MB; the directory storage has no snapshots). He restores it
on request; a rebuild is then `build.sh` again.

**Second build, 2026-11-13: up.** On the reset container, the fixed `build.sh` ran in 8 minutes with no errors:
- FreeSWITCH `1.11.1-release+git~20260526T204126Z~c2c59645f6~64bit` (production's exact build), FusionPBX 5.5.12, PHP 8.2.35, PostgreSQL 18.7.
- Running: freeswitch, postgresql, nginx, php8.2-fpm, fail2ban, event_guard. SIP profiles `internal` (5060) and `external` (5080) and their IPv6
  twins, on 10.10.0.60. No `htc` profile, no gateway. The web login answers on 443. iptables policy DROP with 28 rules. 3.2 GB of the disk used.
- The guard was identical before and after. `scripts/staging-check.sh` passes: the guard's 3 rules are present, 0 gateways in FusionPBX and
  FreeSWITCH, an INVITE from FreeSWITCH to a public address was dropped by the guard, and a packet to the HTC trunk's network was dropped
  before leaving the container.
- The admin login is in `/root/vox-staging-admin.txt` on staging (root only), not in the log or in git.

**First build, 2026-11-13 (replaced):** The versions came out as planned:
FreeSWITCH reports production's exact build string (`1.11.1-release+git~20260526T204126Z~c2c59645f6~64bit`), FusionPBX 5.5.12, PHP 8.2,
PostgreSQL 18; the guard was unchanged (checked before and after); no gateway exists; 3.2 GB of the disk used. But the first `build.sh` set a
private umask around the whole install (meant only for the password file), so everything the install created outside the Debian packages is
readable by its owner only (18,540 files: FusionPBX's code and config, FreeSWITCH's configuration and sounds, systemd units, apt sources).
FreeSWITCH (running as `www-data`) cannot read `/etc/fusionpbx`, so it loads no SIP profiles. Repairing modes file by file would be guesswork
and not reproducible; the script is fixed (only the password file is made private) and needs a fresh container. fail2ban also failed to start
(its sshd jail started before rsyslog had written `auth.log`; the install says to reboot); the script now restarts it at the end.

Known differences from production, both minor releases the package repositories no longer serve at production's level: Debian 12.15 (production
12.14) and PostgreSQL 18.7 (production 18.4). Production gets the same on its next `apt upgrade`; matching them exactly would need old packages
from the archives, which is not worth it for staging.

### What is on it now

- Domains: the install's own (`10.10.0.60`), `spike.vox.test` (written by FusionPBX's pages in the write-path spike, kept as the reference) and
  `adapter.vox.test` (written by PhotonVox's adapter: `engine/staging/prove-publish.sh`). The spike's direct-write domain was removed.
- Gateways: two SIPp upstreams on LXC 800, `sipp-upstream` on 5070 (the spike's, by page) and on 5071 (the adapter's, PhotonVox-owned).
- The database role `photonvox_adapter`: select/insert/update/delete on the tables the adapter writes, insert on `v_domains`, select on
  `v_access_controls`, select/insert/update on `v_default_settings` (the adapter writes only its `email` rows), and (2026-11-14, for
  PhotonEntry's door-calls) select on six columns of `v_xml_cdr` (`xml_cdr_uuid, domain_uuid, caller_id_number, start_epoch, answer_epoch,
  end_epoch`; never its raw XML/JSON) and (2026-11-27, for the dashboard on the demo: `engine/staging/dashboard-grants.sql`) select on the
  dashboard's columns of `v_xml_cdr` and five columns of `v_voicemail_messages`; nothing else. Its password is on the runner in `~/.config/photonvox/staging-adapter.pass` (mode 600); the test phones'
  SIP passwords and PINs in `~/.config/photonvox/staging-secrets.json` (mode 600).
- **vox-agent** (`agent/install.sh root@10.10.0.60 ~/.ssh/vox_staging 10.10.0.60:8780`, the address it binds now): `/opt/vox-agent/vox_agent.py`, the unit
  `vox-agent.service` (as www-data, hardened), its secret in `/etc/vox-agent.env` (root:www-data 0640) and on the runner in
  `~/.config/photonvox/agent-10.10.0.60.secret` (reinstalled 2026-11-27 from the repository, for `live`; the file before it is kept beside it as
  `vox_agent.py.bak-20261127`). It listens on the engine's localhost; the harness reaches it, and the database, through one SSH
  tunnel until the management network does.
- **Outgoing mail:** FusionPBX's `email` settings point at Mailpit on LXC 800 (`scripts/sipp.sh mailpit start`, SMTP 2525, API 8026), a sink
  standing in for Postmark; nothing leaves. Production instances get Postmark's SMTP through Platform → the instance's mail, then Apply.
- **Reached from LXC 800** (the build test's API and worker, standing in for the management network): PostgreSQL listens on 10.10.0.60 too,
  `pg_hba` admits only `photonvox_adapter` from 10.10.0.80, vox-agent binds 10.10.0.60:8780, and iptables admits 5432 and 8780 from 10.10.0.80
  only (saved with netfilter-persistent).
