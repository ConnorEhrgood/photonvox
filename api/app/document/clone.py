"""Clone (ARCHITECTURE §3): another customer's call flows as a starting point. A franchise or a second office of the same kind is the case:
their hours, calling policy, features, ring groups, menus and shared mailboxes are copied; this customer's sites, numbers and people stay.
People in groups and menus are matched by extension; one with no match here is left out of a group (a group left empty is dropped) or left
pointing at nobody, which the document's problems then name, for the integrator to fix."""
from __future__ import annotations

from typing import Any, Dict, Mapping, Optional

COPIED = ("hours", "calling", "features", "boxes")


def clone(source: Mapping[str, Any], target: Mapping[str, Any]) -> Dict[str, Any]:
    by_ext = {u["extension"]: uid for uid, u in target.get("users", {}).items()}
    ids = {uid: by_ext.get(u["extension"]) for uid, u in source.get("users", {}).items()}

    def person(uid: str) -> Optional[str]:
        return ids.get(uid)

    def target_(t: Mapping[str, str]) -> Dict[str, str]:
        kind, key = next(iter(t.items()))
        if kind in ("user", "voicemail") and key in ids:
            return {kind: person(key) or key}          # matched by extension, or left as it was (a problem to fix)
        return dict(t)

    out: Dict[str, Any] = {k: v for k, v in target.items() if k not in COPIED + ("groups", "menus")}
    out.update({k: source[k] for k in COPIED if k in source})
    # Mailboxes come without the other organization's email addresses (review L7): this customer fills in its own.
    out["boxes"] = {k: {**b, "email": None} for k, b in source.get("boxes", {}).items()} if "boxes" in source else target.get("boxes", {})
    groups = {}
    for key, g in source.get("groups", {}).items():
        members = [m for m in (person(x) for x in g["members"]) if m]
        if members:
            groups[key] = {**g, "members": members, **({"then": target_(g.get("then"))} if g.get("then") else {})}
    out["groups"] = groups
    out["menus"] = {key: {**m, "options": {d: target_(t) for d, t in m["options"].items()}, "timeout": target_(m.get("timeout"))}
                    for key, m in source.get("menus", {}).items()}
    return out
