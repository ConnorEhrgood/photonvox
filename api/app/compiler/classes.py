"""Call classes: which outside numbers belong to which class, as FreeSWITCH (PCRE) patterns (ARCHITECTURE §15). Data, kept in one place.

The patterns see the digits as dialed after an optional outside-line prefix (the compiler adds it) and capture the number to send to the
upstream in +1 / +cc form. What is blocked is the block route's job (app/compiler/blocking.py, decision 29), which comes before every class
route: the high-cost North American area codes (the Caribbean and other places billed as international, where one-ring scams send calls) are
blocked there, so an organization can let one through. Premium numbers (900, and 976 exchanges) are also left out of "national" itself, a
second line in case the block route were ever missing.
"""
from __future__ import annotations

from typing import Dict, Tuple

EMERGENCY = ("911", "933")                          # 933: the address read-back test, routed exactly like 911 (§11)
# Routed to the carrier for every phone system, whatever its classes block (decision 33, Connor 2026-11-14): the crisis line, the relay service
# and the city's information line. 933 follows 911 (EMERGENCY). 211, 411, 511, 611 and 811 are not routed (411 and 611 by decision; 211,
# 511 and 811 until Connor says otherwise): a call to them fails, as before.
SERVICES = ("988", "711", "311")

HIGH_COST_NANP: Tuple[str, ...] = (
    "242", "246", "264", "268", "284", "345", "441", "473", "649", "658", "664", "721", "758", "767", "784", "809", "829", "849", "868", "869", "876",
)
PREMIUM_NPA = ("900",)
TOLL_FREE_NPA = ("800", "833", "844", "855", "866", "877", "888")
PREMIUM_NXX = ("976",)

_NOT = "|".join(PREMIUM_NPA + TOLL_FREE_NPA)
PATTERNS: Dict[str, str] = {
    # 10 digits, or 11 with a leading 1 (or +1); area code and exchange start 2-9; not premium, not toll-free (its own class).
    "national": rf"^(?:\+1|1)?((?!{_NOT})[2-9]\d{{2}}(?!{'|'.join(PREMIUM_NXX)})[2-9]\d{{6}})$",
    "toll_free": rf"^(?:\+1|1)?((?:{'|'.join(TOLL_FREE_NPA)})[2-9]\d{{6}})$",
}


def international_pattern(code: str) -> str:
    """A country calling code ("44"), or a high-cost North American area code switched on as if it were one ("1876")."""
    if len(code) == 4 and code.startswith("1"):
        return rf"^(?:\+1|1)?({code[1:]}[2-9]\d{{6}})$"
    return rf"^(?:011|\+)({code}\d{{4,13}})$"


# Country calling codes (ITU-T E.164 assignments, 2026) an owner may switch on. A code must be a whole country: a prefix such as "2" or "21"
# would open a whole world zone (security review M1). Left out: international networks, satellite, shared-cost and premium ranges.
COUNTRY_CODES = frozenset("""
7 20 27 30 31 32 33 34 36 39 40 41 43 44 45 46 47 48 49 51 52 53 54 55 56 57 58 60 61 62 63 64 65 66 81 82 84 86 90 91 92 93 94 95 98
211 212 213 216 218 220 221 222 223 224 225 226 227 228 229 230 231 232 233 234 235 236 237 238 239 240 241 242 243 244 245 246 247 248 249
250 251 252 253 254 255 256 257 258 260 261 262 263 264 265 266 267 268 269 290 291 297 298 299 350 351 352 353 354 355 356 357 358 359
370 371 372 373 374 375 376 377 378 380 381 382 383 385 386 387 389 420 421 423 500 501 502 503 504 505 506 507 508 509 590 591 592 593
594 595 596 597 598 599 670 672 673 674 675 676 677 678 679 680 681 682 683 685 686 687 688 689 690 691 692 850 852 853 855 856 880 886
960 961 962 963 964 965 966 967 968 970 971 972 973 974 975 976 977 992 993 994 995 996 998
""".split())


def is_valid_international(code: str) -> bool:
    return code in COUNTRY_CODES or (len(code) == 4 and code.startswith("1") and code[1:] in HIGH_COST_NANP)
