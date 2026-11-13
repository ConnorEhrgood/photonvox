"""What the adapter needs from vox-agent on an instance (ARCHITECTURE §5): fixed operations only. vox-agent itself is not built yet; the
staging harness implements this over SSH (engine/staging/ssh_agent.py) until it is."""
from __future__ import annotations

from typing import Protocol, Sequence


class Agent(Protocol):
    def seed_domain(self) -> None:
        """Run FusionPBX's own `upgrade.php --defaults`, which gives a new domain its standard dial plans (SPIKES §1c)."""

    def clear_cache(self, keys: Sequence[str]) -> None:
        """Delete these entries from FusionPBX's cache (file names under /var/cache/fusionpbx)."""

    def rescan(self, profiles: Sequence[str], kill: Sequence[str] = ()) -> None:
        """Stop these gateways (removed ones), then rescan these SIP profiles so new and changed gateways start."""

    def reload_acl(self) -> None:
        """Reload FreeSWITCH's access lists (`reloadacl`)."""
