"""PhotonVox's roles and capabilities: the catalog this product publishes to the PhotonID directory (suite ARCHITECTURE §5), and the one place that
says what each role can do. app/access.py applies it; nothing else decides who may do what.

The roles are ARCHITECTURE §7 (owner, admin, user; `supervisor` comes with call queues). They are decision 15, not yet answered by Connor: if he
changes them, this table and its tests change and nothing else does. A capability marked sensitive is one a customer will later be able to hold
back from partner staff (the suite's privacy-controls pass); nothing uses the mark yet.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Dict, FrozenSet

# key -> sensitive
CAPABILITIES: Dict[str, bool] = {
    "vox.phone_system.view": False,     # the customer's phone system: users, phones, numbers, call flows, status
    "vox.phone_system.build": False,    # change it: users, extensions, call flows, hours, outcomes of numbers; publish
    "vox.phone.enroll": False,          # add, move and remove phones (barcode enrollment)
    "vox.phone.control": False,         # reboot, re-provision, factory reset a phone
    "vox.site.emergency": True,         # set and validate a site's emergency address (911)
    "vox.number.manage": False,         # take numbers from stock, set what they ring
    "vox.number.port": True,            # request a port in
    "vox.number.release": True,         # give a number up
    "vox.calling.policy": False,        # call classes and the spend limit, within the platform's ceiling
    "vox.forwarding.external": True,    # forward an extension to a number outside the organization
    "vox.console.manage": False,        # the PhotonConsole connection token
    "vox.entry.manage": True,           # the PhotonEntry connection token (it reads the door stations' SIP passwords)
    "vox.members.view": False,          # who has access, with their roles
    "vox.audit.view": False,
    "vox.self.manage": False,           # your own voicemail, greetings, forwarding inside the organization, your phones' status
}

_USER = ["vox.self.manage"]
_ADMIN = _USER + [
    "vox.phone_system.view", "vox.phone_system.build", "vox.phone.enroll", "vox.phone.control", "vox.site.emergency", "vox.number.manage",
    "vox.forwarding.external", "vox.console.manage", "vox.entry.manage", "vox.members.view",
]
_OWNER = _ADMIN + ["vox.number.port", "vox.number.release", "vox.calling.policy", "vox.audit.view"]


@dataclass(frozen=True)
class RoleDef:
    key: str
    label: str
    rank: int                  # higher outranks lower
    site_limitable: bool       # the directory only offers site limits for these
    capabilities: FrozenSet[str]


ROLES: Dict[str, RoleDef] = {r.key: r for r in (
    RoleDef("user", "User", 1, True, frozenset(_USER)),
    RoleDef("admin", "Admin", 2, True, frozenset(_ADMIN)),
    RoleDef("owner", "Owner", 3, False, frozenset(_OWNER)),
)}
assert all(c in CAPABILITIES for r in ROLES.values() for c in r.capabilities), "a role names a capability that does not exist"


def rank(role: str) -> int:
    return ROLES[role].rank


def catalog() -> Dict[str, Any]:
    """What PUT /v1/products/vox/roles carries (photonid's contract/roles.schema.json): the roles, lowest rank first, with their capability keys
    and which of those are sensitive."""
    return {
        "roles": [
            {"key": r.key, "label": r.label, "rank": r.rank, "site_limitable": r.site_limitable, "capabilities": sorted(r.capabilities),
             "sensitive_capabilities": sorted(c for c in r.capabilities if CAPABILITIES[c])}
            for r in sorted(ROLES.values(), key=lambda r: r.rank)
        ],
    }


def catalog_hash() -> str:
    return hashlib.sha256(json.dumps(catalog(), sort_keys=True, separators=(",", ":")).encode()).hexdigest()
