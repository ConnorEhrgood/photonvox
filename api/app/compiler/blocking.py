"""Call blocking (ARCHITECTURE §15a, decision 29): Photon's default list, and the organization's changes to it, as the patterns of the locked
block route. CRITICAL module (100% branch coverage).

The block route comes right after the emergency routes, so 911 and 933 are never blocked; its patterns also cannot match them (every pattern
needs a full North American number, or 011 or + and a country code). A blocked call is rejected and recorded with its category.

Numbers are matched as dialed: an optional outside-line prefix, then for North American numbers an optional 1 or +1, for others 011 or +.
"""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from app.compiler import classes

# Photon keeps this list current suite-wide; a change reaches each organization at its next publish (every organization is republished).
LIST_VERSION = "2026-11-13"
SATELLITE = ("870", "881", "882", "883")     # Inmarsat, the global mobile satellite systems, international networks

# Categories in the order the route tests them (the first that matches names the block).
CATEGORIES = ("listed", "premium", "high_cost_nanp", "satellite", "international")


def _nanp(prefixes: List[str]) -> str:
    """North American numbers that start with one of these prefixes (the digits after +1)."""
    return "(?:\\+1|1)?(?:" + "|".join(f"{p}\\d{{{10 - len(p)}}}" for p in prefixes) + ")"


def _intl(prefixes: List[str]) -> str:
    return "(?:011|\\+)(?:" + "|".join(prefixes) + ")\\d*"


def _anchor(body: str, outside: List[str]) -> str:
    lead = "(?:" + "|".join(outside) + ")?" if outside else ""
    return f"^{lead}{body}$"


def block_route(allow: List[str], block: List[str], allow_numbers: List[str], countries: List[str], outside: List[str],
                premium_allowed: bool) -> Dict[str, object]:
    """The locked block route. `countries`: the international codes switched on (a 4-digit "1876" lets that North American code through);
    `premium_allowed`: Photon staff have let premium through for this organization (and the document asks for it)."""
    nanp_codes = [c[1:] for c in countries if len(c) == 4]
    intl_codes = [c for c in countries if len(c) < 4]
    cats: List[Tuple[str, Optional[str]]] = []

    listed_nanp = [b[2:] for b in block if b.startswith("+1")]
    listed_intl = [b[1:] for b in block if not b.startswith("+1")]
    listed = [x for x in ([_nanp(listed_nanp)] if listed_nanp else []) + ([_intl(listed_intl)] if listed_intl else [])]
    cats.append(("listed", "(?:" + "|".join(listed) + ")" if listed else None))

    premium = [f"{npa}\\d{{7}}" for npa in classes.PREMIUM_NPA] + [f"[2-9]\\d{{2}}{nxx}\\d{{4}}" for nxx in classes.PREMIUM_NXX]
    cats.append(("premium", None if "premium" in allow and premium_allowed else "(?:\\+1|1)?(?:" + "|".join(premium) + ")"))

    high_cost = [c for c in classes.HIGH_COST_NANP if c not in nanp_codes]
    cats.append(("high_cost_nanp", None if "high_cost_nanp" in allow or not high_cost else _nanp(high_cost)))
    cats.append(("satellite", None if "satellite" in allow else _intl(list(SATELLITE))))

    not_allowed = "(?!(?:" + "|".join(intl_codes) + "))" if intl_codes else ""
    cats.append(("international", f"(?:011|\\+(?!1)){not_allowed}\\d{{4,}}"))

    categories = [{"category": c, "pattern": _anchor(p, outside)} for c, p in cats if p is not None]
    exceptions = sorted(set(a[2:] for a in allow_numbers))
    return {
        "key": "block", "locked": True, "reject": True, "requires": None, "gateways": [], "list_version": LIST_VERSION,
        "categories": categories,
        "except": _anchor(_nanp(exceptions), outside) if exceptions else None,
    }
