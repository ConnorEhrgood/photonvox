"""Call classes: which outside numbers belong to which class, as FreeSWITCH (PCRE) patterns (ARCHITECTURE §15). Data, kept in one place.

The patterns see the digits as dialed after an optional outside-line prefix (the compiler adds it) and capture the number to send to the
upstream in +1 / +cc form. Premium numbers (900, and 976 exchanges) match no class: no route is ever generated for them. The high-cost
North American area codes (the Caribbean and other places billed as international, where one-ring scams send calls) are left out of
"national"; an owner may switch one on as if it were a country ("1876" for Jamaica).
"""
from __future__ import annotations

from typing import Dict, Tuple

EMERGENCY = ("911", "933")                          # 933: the address read-back test, routed exactly like 911 (§11)
SERVICES = ("988", "711", "211", "311", "511", "811")   # the crisis line, relay services and local information lines: always allowed

HIGH_COST_NANP: Tuple[str, ...] = (
    "242", "246", "264", "268", "284", "345", "441", "473", "649", "658", "664", "721", "758", "767", "784", "809", "829", "849", "868", "869", "876",
)
PREMIUM_NPA = ("900",)
TOLL_FREE_NPA = ("800", "833", "844", "855", "866", "877", "888")
PREMIUM_NXX = ("976",)

_NOT = "|".join(HIGH_COST_NANP + PREMIUM_NPA + TOLL_FREE_NPA)
PATTERNS: Dict[str, str] = {
    # 10 digits, or 11 with a leading 1; area code and exchange start 2-9; not premium, not high-cost, not toll-free (its own class).
    "national": rf"^1?((?!{_NOT})[2-9]\d{{2}}(?!{'|'.join(PREMIUM_NXX)})[2-9]\d{{6}})$",
    "toll_free": rf"^1?((?:{'|'.join(TOLL_FREE_NPA)})[2-9]\d{{6}})$",
}


def international_pattern(code: str) -> str:
    """A country calling code ("44"), or a high-cost North American area code switched on as if it were one ("1876")."""
    if len(code) == 4 and code.startswith("1"):
        return rf"^1?({code[1:]}[2-9]\d{{6}})$"
    return rf"^011({code}\d{{4,13}})$"


def is_valid_international(code: str) -> bool:
    return code.isdigit() and (1 <= len(code) <= 3 and not code.startswith(("0", "1")) or (len(code) == 4 and code[1:] in HIGH_COST_NANP))
