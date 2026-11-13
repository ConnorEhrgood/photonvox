# Inventory of the live phone system (BUILD-GUIDE Step 0.2)

Read-only scripts that answer ARCHITECTURE §22 question 9 about the live FusionPBX. **Written, never run by an agent**: Connor runs them, or
approves each run (suite rules: read-only production checks need his go-ahead too).

| Script | Where it runs | What it reports |
|---|---|---|
| `engine.sh` | inside the FusionPBX container, as root: `pct exec 600 -- bash -s < engine.sh > engine-inventory.txt` | versions; domains and, per domain, extensions, phones, numbers, ring groups, menus, queues, voicemail, fax; phones by vendor and model; live registrations by domain, model, transport and private/public source; gateways and their state, calls through each; dial plans by app; numbers whose dial plan is missing; provisioning, email and recording settings (secret values shown only as "set"); toll-fraud exposure counts; call volume; SIP profiles, listening ports, NAT mode; fail2ban/event guard/firewall; storage; backup cron files |
| `host.sh` | on the Proxmox host, as root: `bash host.sh 600 601 > host-inventory.txt` | the engine container's resources, storage and network settings (no addresses), the backup jobs that include it and its newest backups, what container 601 is |

Both change nothing: the database is read in a read-only transaction with a statement timeout, FreeSWITCH gets only status commands, and
nothing is written to disk. Reports hold counts and categories, domain names and gateway names; never people's names, numbers, MAC or IP
addresses, usernames or passwords. **Read a report before sending it on.**

Checked so far (2026-11-13): every table, column and app uuid the SQL uses against FusionPBX's own schema definitions (`app_config.php` on its
master branch, 5.7); the FreeSWITCH-output parsers against sample output with `mawk` (Debian's default awk): `tests/test_parsers.sh`. **Not
checked:** the SQL has not run against a real FusionPBX database (an older release may lack a table or column: each query then prints "not
available" rather than stopping), and the FreeSWITCH output format of the installed version.
