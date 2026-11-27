# PhotonVox in production: the first deploy

Prepared 2026-11-13 and **deployed the same evening with Connor's go-ahead** (see "Deployed" below). Hosting is decision 18 (ARCHITECTURE
§16): PhotonVox's cloud runs on the shared Photon host until there are paying customers or the host gets tight; the PBX engines stay in the
colo. GATE 1c and the write role were applied on 2026-11-13/14 and PhotonVox writes to the live engine: see "The live engine" below
(the sections after this one describe the first deploy as it was planned and done).

## The live engine (FusionPBX on CT 600, 10.10.0.21), since 2026-11-14

Updated 2026-11-21 (audit VOX-B-19). PhotonVox manages one adopted customer domain (HUEPC) on the production FusionPBX, with the protections
version live (BUILD-LOG 2026-11-14). What it can do there, and how to take it away:

| What | Where | Can |
|---|---|---|
| `photonvox_ro` (GATE 1c, `engine/live/gate-1c.sql`) | Postgres on CT 600, `pg_hba` from 10.2.1.5 only | read 15 tables, column by column, every domain (no SIP passwords, PINs or gateway logins) |
| `photonvox_rw` (`engine/live/gate-rw.sql`) | the same, from 10.2.1.5 only; the instance `live-a` logs in with it | insert, update and delete on nine tables, **every domain**: PhotonVox scopes each statement to its domain, the role does not (audit VOX-B-1; `engine/live/gate-rw-scope.sql` is the proposed fix, not applied) |
| vox-agent 0.1.0 | CT 600, 10.10.0.21:8781 (iptables: from 10.2.1.5 on wg-mgmt only), as www-data, writing only FusionPBX's cache (`engine/live/vox-agent-live.conf`) | `status`, `cache/delete`, `check` only (`engine/live/vox-agent-live.env`) |

- **Credentials:** sealed in PhotonVox's database (`SECRETS_KEY`). Copies of record with Connor. The runner still had plaintext copies in
  `~/.config/photonvox/` on 2026-11-17 (audit VOX-B-13): to delete or rotate.
- **Updating the agent:** `agent/install.sh root@10.10.0.21 <key>` keeps `/etc/vox-agent.env` as it is (secret, bind, operations); give a
  bind or operations list only to change it. The update since 0.1.0 refuses emergency and service numbers in `check` and can be limited to
  the managed domains (`VOX_AGENT_DOMAINS`, to add with HUEPC's domain name).
- **Undo (take PhotonVox's write access away):** `engine/live/gate-rw.sh undo` (drops `photonvox_rw` and its `pg_hba` line), stop and
  disable vox-agent (`systemctl disable --now vox-agent`) and remove its iptables line (backup `rules.v4.bak-vox-8781`); the read role:
  `engine/live/gate-1c.sh undo`. The domain's rows stay as PhotonVox last wrote them; the protections' own undo is `app.manage republish
  <org> 2` (before the access is taken away).
- **Deploys** wait until no version is queued or being published before the worker is recreated (`scripts/deploy.sh`); a version a
  stopped worker left "publishing" is marked failed after 20 minutes, or at once with `app.manage recover <org>`.

## Deployed (2026-11-13, commit ba15639)

Done as one phase: b1 applied the PhotonBoard change (photonboard fea8028, 2ee8ad3) and put the overlay and the new deploy, restore, backup
and watch scripts on the host without recreating the proxy; id1 registered PhotonVox in PhotonID (project "PhotonVox", project ID
399485154214543363 = `OIDC_AUDIENCE` = `VITE_OIDC_AUDIENCE_PROJECT`; client 399485154533310467; redirect `/auth/callback`; post-logout
`/auth/signed-out` and `/`) and connected it to the directory (production directory 9c6cad9 with `vox`), appending its seven keys to the
host's `.env`; then the steps below, in order.

| Check | Result |
|---|---|
| Stack | `api`, `db`, `worker`, `web` running and healthy, `migrate` exited 0; no host ports |
| Directory | the worker's first sync answered 200 and it published the role catalog (`PUT /v1/products/vox/roles` 200) |
| Proxy | joined `vox-edge` with `docker network connect`; `caddy validate` then `caddy reload`; **not restarted** (still started 20:43:37Z) and kept its five networks; account.photonind.com answered 24 of 24 requests during the reload |
| Certificates | both obtained on the first attempt (DNS checked on Google's and Cloudflare's resolvers first) |
| Public | `vox.photonind.com` 200 with its CSP, deep links 200; `api.vox.photonind.com/healthz` 200; CORS for the app's origin; the directory's notice address refuses an unsigned request (401) |
| Other sites | PhotonID, the directory (app and API), Console (app and API), Board (portal and API): all 200 |
| Backup | run once by hand (22:13 UTC, 21 s): `vox-db.dump.enc` 111 KB in it beside the others; `vox/.env` goes into the encrypted secrets by the script's rule (not listable here without the private key) |
| Watcher | checks PhotonVox's four containers; all running and healthy; its only problem is the host's pending reboot (before this deploy) |
| Memory | api 76 MB, worker 65 MB, db 62 MB, web 4 MB; host 1710 MB available afterwards |

**Learned:**
- **Create `.env` immediately before the stack starts.** The watcher keys on `/opt/photon/vox/.env`. The file existed about 15 minutes
  before the containers did (it was waiting for id1's keys), so the 22:00 run mailed Connor "Container photonvox-… does not exist". The
  22:15 run sent the recovery.
- `scripts/deploy.sh` was committed without its execute bit; fixed.
- The first `deploy.sh` run's public checks fail until the Caddy site exists (TLS alert), as the plan said.
- An authoritative DNS query from the runner is not reliable (its UDP 53 is intercepted: even known names answer SERVFAIL). Check names
  with DNS over HTTPS instead.

**Later deploys:**
- 2026-11-13 about 22:50 UTC, cd4ed49: sign-in on the suite's shared module (ph-auth). The API answered 503 through the proxy for about
  20 seconds while it was recreated (Caddy's 15-second health check), then 200; Board, the directory and Console answered throughout.
  Checked signed out in production (`web/scripts/signin-prod-check.mjs`): at 1440×900 and 390×844 a deep link goes straight to PhotonID's
  sign-in form with redirect `/auth/callback`, one trip, no page of PhotonVox's own, no iframe. id1 drops the old `/` post-logout address.

- 2026-11-13 about 22:36 UTC, 3a282eb: Photon staff from the directory, migration 0006. Backup first:
  `/opt/photon/backups-manual/pre-vox-staff-20261113T223517Z/vox-db.dump` (mode 600, read back: 37 tables of data; outside `backups/`, so it
  takes no rotation slot). `migrate` ran 0005 → 0006; api and worker healthy; Board, the directory and Console 200. Then id1 switched
  PhotonVox on for the organization PhotonConsole uses: the worker's next pull (22:37) brought in Connor with `is_staff` and
  `is_platform_admin` true (from the directory: platform administrator, partner Photon) and owner of that organization, one
  `directory.staff_flags` audit event, cursor 22, no error. Signed out, a deep link still goes straight to PhotonID at 1440 and 390.

- 2026-11-14 about 04:35 UTC, 6ff13a7 (protections for HUEPC, part P, Connor's go): backup first
  `/opt/photon/backups-manual/pre-vox-protections-20261114T043315Z/` (vox-db.dump 128 KB, read back: 37 tables of data; vox.env), mode 600.
  `.env` gained `OIDC_WEB_CLIENT_ID` (copied on the host from `VITE_OIDC_CLIENT_ID`) and `VITE_DIRECTORY_AUDIENCE_PROJECT`. `migrate` ran
  0007 → 0009; api, worker and web healthy (about 20 s of 503 while the API's container became healthy, as before); Board, the directory,
  Console and PhotonID 200. Staff count unchanged (1); HUEPC ready, version 1, adopted, drift 0; `/v1/summary` and the door-stations feed
  401 without a token; signed out, a deep link goes straight to PhotonID at 1440 and 390. id1 told the summary is live.
  (`signin-prod-check.mjs` takes a screenshot folder and runs from `web/`.)

- 2026-11-14 about 14:41 UTC, 643f983 (photon-ui's sign-in, 2bceada, re-vendored for id1; Connor's "Please deploy", the operator's go):
  web only, no migration (0009), nothing on CT 600. api, worker and web healthy; Board, the directory and Console 200; HUEPC ready,
  version 3. Signed out, a deep link goes straight to PhotonID at 1440 and 390. **As the QA account, a session begun without the
  directory's audience** (its token refused by the directory, 401, and its stored scope without it, as the older app left them): on
  reload it was dropped once, signed in again at once with the PhotonID session, and the switcher's request
  (`/v1/me/apps?organization=guardtest`, from vox.photonind.com) answered 200 with the account's six products; reloading again made no
  further trip (no loop). The QA account has no PhotonVox role, so it sees "No access to PhotonVox" and not the switcher itself.

- 2026-11-27 about 20:21 UTC, 51b9510 (audit 2026-11-17 fixes, incl. VOX-A-1, and photon-ui 031c370; Connor's go): no migration, nothing
  on CT 600. Checked first: `.env` has `OIDC_WEB_CLIENT_ID`; HUEPC ready, version 3, protections on, nothing queued or publishing; no
  hours span past 24:00 in the draft or any published version. Backup `/opt/photon/backups-manual/pre-vox-audit-20261127T202014Z/vox-db.dump`
  (mode 600, read back: 38 tables of data). About 20 s of 503 while the API became healthy; api, worker, web healthy, no error in the logs;
  Board, the directory and Console 200. vox-agent on CT 600 is NOT reinstalled yet (VOX-B-3, -7: still open).

**Open:**
- **Connor's first real sign-in:** PhotonVox now has his account and flags (PhotonVox switched on for PhotonConsole's organization,
  2026-11-13), but nobody has signed in yet.
- `PLATFORM_ADMIN_SUBS` is a fallback for one release: remove it in the next one.
- GATE 1c and Step 1's adoption of the live domains.

## Where it runs

| What | Where |
|---|---|
| Host | The Vultr host `photon-infra-a` (`ssh prod`, user `deploy`), beside PhotonID, the directory, PhotonConsole and PhotonBoard |
| Folder | `/opt/photon/vox` (owned by `deploy`); its `.env` exists only there (mode 600) and in the nightly encrypted backup |
| Stack | Compose project `photonvox`: `db` (its own Postgres, volume `photonvox_db_data`), `migrate` (one-shot), `api`, `worker`, `web`. Files: `docker-compose.yml` + `docker-compose.prod.yml` |
| Names | `vox.photonind.com` (the web app) and `api.vox.photonind.com` (the API), DNS only (grey cloud), pointing at the host (144.202.2.169) |
| Proxy | The shared Caddy (`photonboard-proxy-1`), site file `deploy/caddy/vox.caddy`, network `vox-edge`, containers addressed as `vox-web` and `vox-api` (never `web`/`api`: another product's `api` shares the proxy's other networks) |
| Engines | In the colo, reached over mgmtnet: the host is overlay peer `console-host`, 10.2.1.5; Docker masquerades the containers to it |

## Memory

The host has 3916 MB, about 1950 MB available (2026-11-13), 520 MB of swap in use. Measured in the rehearsal (idle, after start):

| Container | Ceiling | Idle use |
|---|---|---|
| api | 256 MB | 76 MB |
| worker | 160 MB | 66 MB |
| db | 256 MB (+128 MB swap), `shared_buffers` 64 MB, 40 connections | 42 MB |
| web | 32 MB | 5 MB |
| migrate | 192 MB, runs once per deploy and exits | |
| **Total** | **704 MB** (+192 during a deploy) | **about 190 MB** |

A deploy builds the two images on the host (pip and `npm ci` + Vite: a few hundred MB for a minute or two), as PhotonConsole's deploy does.
The watcher already alerts below 300 MB available. **The move to its own VPS** (decision 18) comes with paying customers, or when the host's
available memory stays under about 800 MB.

Seen while measuring (for the suite's OPERATIONS, not changed here): PhotonConsole's five containers have no memory ceilings, and the host
watcher's container list covers PhotonBoard and PhotonID only (not PhotonConsole or the directory).

## Rehearsed

`scripts/rehearse-deploy.sh` runs the whole deploy on LXC 800 with nothing of production and removes it afterwards (20 checks, passing
2026-11-13): the stack with the prod overlay, healthy, migrations run, no host ports; a stand-in for the shared proxy (the same `secure`
snippet and `import sites/*.caddy`, already serving another site) joined to `vox-edge` with `docker network connect`, `caddy validate`,
`caddy reload`; the other site answered throughout, the proxy was not restarted and kept its other network; `vox.photonind.com` serves the app
with its Content-Security-Policy, deep links work, the API's health, CORS for the app's origin, a 3 MB body refused by the proxy; the backup's
dump line (110 KB on an empty database, over the script's 4 KB sanity check).
GATE 1c's script was rehearsed on staging (13 checks, a second apply refused, undo, staging's `pg_hba` restored byte for byte).

## What needs Connor before the first deploy

1. **DNS:** `vox.photonind.com` and `api.vox.photonind.com`, A records to 144.202.2.169 (and AAAA if the other names have one), grey cloud.
2. **PhotonID:** an application for PhotonVox (PKCE, no secret): redirect `https://vox.photonind.com/auth/callback`, post-logout
   `https://vox.photonind.com/`. Its client ID and project ID go in `.env` (`VITE_OIDC_CLIENT_ID`, `VITE_OIDC_AUDIENCE_PROJECT`,
   `OIDC_AUDIENCE`). Connor's PhotonID subject in `PLATFORM_ADMIN_SUBS`.
3. **The directory (GATE 1b):** `vox` in its catalog and PhotonVox connected (`python -m app.manage connect-product vox` in the directory's
   API container, on the same host). In production the API refuses to start without `DIRECTORY_CLIENT_ID`, `DIRECTORY_CLIENT_SECRET` and
   `DIRECTORY_NOTICE_SECRET`. The secrets can go straight from that command into PhotonVox's `.env` on the host without being shown.
4. **The PhotonBoard change** (`deploy/proposals-photonboard.patch`, applies cleanly to photonboard `8f30b18`; a PhotonBoard repo change):
   - `docker-compose.vox-edge.yml`: keeps the proxy on `vox-edge` whenever it is recreated. **Without it, the next PhotonBoard deploy
     recreates the proxy without `vox-edge` and PhotonVox answers 502** (the directory's incident earlier today).
   - `deploy-photon-host.sh` and `restore-host.sh`: include that overlay when `vox.caddy` exists (as for the directory); the deploy also
     checks `vox.photonind.com`.
   - `backup-host.sh`: `vox-db.dump.enc` (encrypted like the others, with the same size check) and `vox/.env` in the encrypted secrets.
   - `photon-watch.sh`: PhotonVox's four containers, when it runs on the host.
   - `deploy/caddy/sites/vox.caddy.example`.
5. **Go-ahead for the host steps below** (production).

Not needed for the first deploy: GATE 1c (only when Step 1's adoption is built), the Postmark token for voicemail email, the Google key for
text-to-speech, the mgmtnet change (none: see "Reaching the engines").

## The first deploy (exact commands, from the runner, in this order)

```bash
# 1. The PhotonBoard change on the host, WITHOUT a PhotonBoard deploy (its deploy recreates the proxy). After it is committed in photonboard:
scp ~/projects/photonboard/docker-compose.vox-edge.yml prod:/opt/photon/photonboard/
scp ~/projects/photonboard/scripts/{backup-host,deploy-photon-host,restore-host,photon-watch}.sh prod:/opt/photon/photonboard/scripts/

# 2. The network and the folder.
ssh prod 'docker network create --label photon.product=vox vox-edge && mkdir -m 750 /opt/photon/vox'

# 3. The .env, generated on the host (the passwords and key are never shown or copied anywhere else).
ssh prod 'cd /opt/photon/vox && umask 077 && { for k in POSTGRES_PASSWORD APP_DB_PASSWORD SYSTEM_DB_PASSWORD; do echo "$k=$(openssl rand -hex 24)"; done
  echo "SECRETS_KEY=$(openssl rand 32 | base64 | tr "+/" "-_")"; } > .env'
#    Then the public values (from .env.example: OIDC_*, CORS_ORIGINS, DIRECTORY_URL, VITE_*, PLATFORM_ADMIN_SUBS) appended with `cat >> .env`,
#    and the directory's three values from connect-product (GATE 1b), piped in on the host.

# 4. Build and start (rsync of the current commit, `up -d --build`, checks). Its public checks fail until step 5: that is expected the first time.
scripts/deploy.sh

# 5. The proxy: join vox-edge, add the site, check it, reload gracefully. NEVER recreate the proxy for this.
ssh prod 'docker network connect vox-edge photonboard-proxy-1'
scp deploy/caddy/vox.caddy prod:/opt/photon/photonboard/deploy/caddy/sites/vox.caddy
ssh prod 'docker exec photonboard-proxy-1 caddy validate --config /etc/caddy/Caddyfile && docker exec photonboard-proxy-1 caddy reload --config /etc/caddy/Caddyfile'

# 6. Checks: PhotonVox, every other product on the proxy, memory.
curl -s -o /dev/null -w "vox %{http_code}\n" https://vox.photonind.com/; curl -fsS https://api.vox.photonind.com/healthz; echo
for u in https://board.photonind.com/ https://account.photonind.com/ https://console.photonind.com/ https://id.photonind.com/.well-known/openid-configuration; do curl -s -o /dev/null -w "$u %{http_code}\n" "$u"; done
ssh prod 'docker stats --no-stream --format "{{.Name}} {{.MemUsage}}" | grep photonvox; free -m | sed -n 2p'

# 7. One backup by hand, to see PhotonVox in it (the nightly one runs at 03:30).
ssh prod '/opt/photon/photonboard/scripts/backup-host.sh && ls -l "$(ls -1d /opt/photon/backups/2*/ | sort | tail -1)" | grep vox'
```

`caddy validate` failing stops step 5 before the reload: nothing changes for the other sites. Caddy gets the two certificates by itself
once DNS points at the host (step 1 of the go-ahead list before any of this).

**Later deploys:** `scripts/deploy.sh` alone (a clean tree; the host gets exactly the commit; `.env` never overwritten or deleted;
migrations run in the one-shot `migrate` service before the API and worker start; the proxy is not touched).

**Rollback:** the previous commit with `scripts/deploy.sh`. To take PhotonVox off the host entirely: remove `vox.caddy`, validate and reload
Caddy, `docker network disconnect vox-edge photonboard-proxy-1`, `docker compose -f docker-compose.yml -f docker-compose.prod.yml down` (the
volume stays until it is removed on purpose).

**Restore:** the nightly `vox-db.dump.enc` (decrypted with the backup key, which is on neither machine) into a fresh `db`:
`pg_restore -U photonvox -d photonvox --no-owner --clean --if-exists`, then the `.env` from the encrypted secrets.
(pg_dump warns about circular foreign keys in TimescaleDB's own catalog, as for PhotonConsole's dump; harmless.)

## Reaching the engines

- **mgmtnet: no change.** The existing grant `console → gateway:fusionpbx` on tcp/5432 and tcp/8780 is from the host's overlay address
  10.2.1.5, and PhotonVox's containers leave the host as that address. The live engine's iptables already accept 10.2.1.5 on 5432
  (PhotonConsole's `photon_ro`). Proposal for the mgmtnet repo: the `console` group's description ("reads the FusionPBX ... and nothing else")
  should name PhotonVox too, or PhotonVox gets its own group when it moves to its own VPS (a new peer and address, then a grant of its own).
- **Port 8780 on the live engine is PhotonConsole's status shim.** vox-agent (Step 2) needs another port there (8781): a grant change and
  an iptables rule for 10.2.1.5, in Step 2.
- **GATE 1c**, below: the read-only role and its `pg_hba` line.
- The live engine is registered in PhotonVox as **monitored only**. Apply (which writes upstreams and mail settings) must never run against
  it; Step 1 builds that refusal, and the role's read-only defaults and grants would refuse the writes anyway.

## GATE 1c: PhotonVox's read-only role on the live engine (for Connor's approval)

`engine/live/gate-1c.sql` (the grants) and `engine/live/gate-1c.sh` (`check`, `apply`, `verify`, `undo`). The role `photonvox_ro` logs in
from 10.2.1.5 only, is read-only by default (`default_transaction_read_only`, a 15-second statement timeout, 4 connections), and reads
column by column: domains; extensions without their SIP password; voicemail boxes without their PIN; numbers; menus without their PIN;
ring groups; upstreams by name only (no logins); call history without the raw XML/JSON, recordings or callers' network addresses. Nothing of
FusionPBX's users; no dial plans until R2. No iptables or mgmtnet change. No restart: `pg_reload_conf()`.

Each command needs approval; 3 and 5 are read-only.

```bash
# 1. Copy the two files to the Proxmox host's /tmp.
scp engine/live/gate-1c.sh engine/live/gate-1c.sql py:/tmp/
# 2. Into CT 600's /root/photon-changes (where the block route's SQL is kept), then remove the copies on py.
ssh py 'pct exec 600 -- mkdir -p /root/photon-changes && pct push 600 /tmp/gate-1c.sh /root/photon-changes/gate-1c.sh && pct push 600 /tmp/gate-1c.sql /root/photon-changes/gate-1c.sql && rm /tmp/gate-1c.sh /tmp/gate-1c.sql'
# 3. Read-only: photon_ro's line for 10.2.1.5 (the new line goes under it), the firewall rule, listen_addresses, no photonvox_ro yet, the 10 tables.
ssh py 'pct exec 600 -- bash /root/photon-changes/gate-1c.sh check'
# 4. The change: pg_hba line (a copy kept as pg_hba.conf.before-gate-1c), the role with a generated password (photonvox_ro.pass, mode 600), reload, verify.
ssh py 'pct exec 600 -- bash /root/photon-changes/gate-1c.sh apply'
# 5. Read-only, any time later: the same checks.
ssh py 'pct exec 600 -- bash /root/photon-changes/gate-1c.sh verify'
# Undo: removes the role and the line, reloads.
ssh py 'pct exec 600 -- bash /root/photon-changes/gate-1c.sh undo'
```

`apply` refuses to start if photon_ro's line is not there or `photonvox_ro` already exists, and stops on the first error (then `undo`).
The password is used once: entered in PhotonVox (Platform → Instances, sealed with `SECRETS_KEY`), then the file is deleted. The first real
login from the host is PhotonVox's own health check for the instance.
