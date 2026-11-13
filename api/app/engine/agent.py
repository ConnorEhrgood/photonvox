"""What the adapter needs from vox-agent on an instance (ARCHITECTURE §5): fixed operations only. vox-agent is not built yet; `SshAgent` is
the interim implementation (staging), with the same operations, over SSH to the engine as root."""
from __future__ import annotations

import os
import re
import shlex
import subprocess
from typing import Optional, Protocol, Sequence

SAFE = re.compile(r"^[A-Za-z0-9@.+_:-]+$")      # cache file names and dialed numbers are built from our own ids, numbers and domains
# FreeSWITCH logs each line twice (the EXECUTE line wraps the data in "log(...)"), so values stop at a space or a closing parenthesis.
FOUND = re.compile(r"PhotonVox-synthetic token=(\w+) (?:reached=([^\s)]+)|route=([^\s)]+) gateways=([^\s)]+) dial=([^\s)]*))"
                   r"|PhotonVox blocked (\w+) .* token=(\w+)")


class Agent(Protocol):
    def seed_domain(self) -> None:
        """Run FusionPBX's own `upgrade.php --defaults`, which gives a new domain its standard dial plans (SPIKES §1c)."""

    def clear_cache(self, keys: Sequence[str]) -> None:
        """Delete these entries from FusionPBX's cache (file names under /var/cache/fusionpbx)."""

    def rescan(self, profiles: Sequence[str], kill: Sequence[str] = ()) -> None:
        """Stop these gateways (removed ones), then rescan these SIP profiles so new and changed gateways start."""

    def reload_acl(self) -> None:
        """Reload FreeSWITCH's access lists (`reloadacl`)."""

    def check(self, kind: str, number: str, domain_name: str, domain_uuid: str, token: str) -> Optional[str]:
        """Place one synthetic call (the post-publish check) and say what it found: "reached <destination>" for an inbound number, "<route>
        <gateways> <number sent>" or "blocked <category>" for a dialed one; None if it found nothing. No phone rings and nothing leaves the engine."""


def parse(log: str, token: str) -> Optional[str]:
    """What a synthetic call found, from the engine's log lines carrying its token (the dial plans write them: app/engine/fusionpbx.py)."""
    for m in FOUND.finditer(log):
        if m.group(1) == token:
            return f"reached {m.group(2)}" if m.group(2) else f"{m.group(3)} {m.group(4)} {m.group(5)}"
        if m.group(7) == token:
            return f"blocked {m.group(6)}"
    return None


class SshAgent:
    """The interim agent: `{"kind": "ssh", "host": "root@10.10.0.60", "key": "~/.ssh/vox_staging"}` in the instance's agent settings."""

    def __init__(self, host: str, key: str) -> None:
        self.host, self.key = host, os.path.expanduser(key)

    def run(self, command: str) -> str:
        return subprocess.run(["ssh", "-i", self.key, "-o", "ConnectTimeout=10", "-o", "BatchMode=yes", self.host, command], check=True,
                              capture_output=True, text=True, timeout=120).stdout

    def seed_domain(self) -> None:
        self.run("cd /var/www/fusionpbx && sudo -u www-data php core/upgrade/upgrade.php --defaults > /dev/null 2>&1")

    def clear_cache(self, keys: Sequence[str]) -> None:
        _safe(keys)
        if keys:
            self.run("cd /var/cache/fusionpbx && rm -f " + " ".join(shlex.quote(k) for k in keys))

    def rescan(self, profiles: Sequence[str], kill: Sequence[str] = ()) -> None:
        _safe(list(profiles) + list(kill))
        cmds = [f"fs_cli -x 'sofia profile {p} killgw {g}'" for g in kill for p in profiles] + [f"fs_cli -x 'sofia profile {p} rescan'" for p in profiles]
        if cmds:
            self.run(" ; ".join(cmds) + " > /dev/null")

    def reload_acl(self) -> None:
        self.run("fs_cli -x reloadacl > /dev/null")

    def check(self, kind: str, number: str, domain_name: str, domain_uuid: str, token: str) -> Optional[str]:
        _safe([kind, number, domain_name, domain_uuid, token])
        context = "public" if kind == "inbound" else domain_name
        synthetic = "inbound" if kind == "inbound" else "route"
        vars_ = (f"photonvox_synthetic={synthetic},photonvox_token={token},domain_name={domain_name},domain_uuid={domain_uuid},"
                 "origination_caller_id_number=2125550000,originate_timeout=10,ignore_early_media=true")
        log = self.run(f"fs_cli -x \"originate {{{vars_}}}loopback/{number}/{context} &park()\" > /dev/null; sleep 1; "
                       f"grep -F 'token={token}' /var/log/freeswitch/freeswitch.log | tail -5")
        return parse(log, token)


def _safe(values: Sequence[str]) -> None:
    bad = [v for v in values if not SAFE.match(v)]
    if bad:
        raise ValueError(f"unexpected value {bad[0]!r}")
