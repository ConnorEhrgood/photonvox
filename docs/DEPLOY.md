# PhotonVox in production: the first deploy

Prepared 2026-11-13, **not run**. Nothing here has touched production; every production step below needs Connor's go-ahead. Hosting is
decision 18 (ARCHITECTURE §16): PhotonVox's cloud runs on the shared Photon host until there are paying customers or the host gets tight; the
PBX engines stay in the colo.

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
