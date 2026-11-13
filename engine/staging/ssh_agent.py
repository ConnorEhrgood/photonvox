"""vox-agent's operations on the staging engine, over SSH, until vox-agent exists (app/engine/agent.py). Staging only."""
from __future__ import annotations

import os
import re
import shlex
import subprocess
from typing import Sequence

HOST = os.environ.get("VOX_STAGING", "root@10.10.0.60")
KEY = os.path.expanduser(os.environ.get("VOX_STAGING_KEY", "~/.ssh/vox_staging"))
SAFE = re.compile(r"^[A-Za-z0-9@.+_:-]+$")      # cache file names are built from our own ids, numbers and domains


def run(command: str) -> str:
    return subprocess.run(["ssh", "-i", KEY, "-o", "ConnectTimeout=10", HOST, command], check=True, capture_output=True, text=True).stdout


class SshAgent:
    def seed_domain(self) -> None:
        run("cd /var/www/fusionpbx && sudo -u www-data php core/upgrade/upgrade.php --defaults > /dev/null 2>&1")

    def clear_cache(self, keys: Sequence[str]) -> None:
        bad = [k for k in keys if not SAFE.match(k)]
        if bad:
            raise ValueError(f"unexpected cache key {bad[0]!r}")
        if keys:
            run("cd /var/cache/fusionpbx && rm -f " + " ".join(shlex.quote(k) for k in keys))

    def rescan(self, profiles: Sequence[str], kill: Sequence[str] = ()) -> None:
        cmds = [f"fs_cli -x 'sofia profile {p} killgw {g}'" for g in kill for p in profiles]
        cmds += [f"fs_cli -x 'sofia profile {p} rescan'" for p in profiles]
        run(" ; ".join(cmds) + " > /dev/null")

    def reload_acl(self) -> None:
        run("fs_cli -x reloadacl > /dev/null")
