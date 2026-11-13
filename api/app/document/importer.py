"""Bulk import of users (ARCHITECTURE §3: "one paste"): rows pasted from a spreadsheet, checked one by one before anything changes. Columns, in
this order or named by a header row: name, extension, email, direct number, site. A blank extension is given the next free one from 100; a
blank site is the default the integrator chose."""
from __future__ import annotations

import csv
import io
import re
from typing import Any, Dict, List, Mapping, Optional

from app.document.model import E164
from app.document.validate import SERVICE_CODES

COLUMNS = ("name", "extension", "email", "direct_number", "site")
ALIASES = {"full name": "name", "ext": "extension", "e-mail": "email", "direct": "direct_number", "did": "direct_number",
           "direct number": "direct_number", "number": "direct_number", "location": "site"}
EMAIL = re.compile(r"^[^@\s<>\"'%,;]+@[^@\s<>\"'%,;]+\.[^@\s<>\"'%,;]+$")     # as the document's (app/document/model.py)
NAME_OK = re.compile(r"^[^<>%\x00-\x1f\x7f]{1,100}$")


def _number(raw: str) -> str:
    digits = re.sub(r"\D", "", raw)
    if len(digits) == 10:
        digits = "1" + digits
    return "+" + digits if digits else ""


def _slug(name: str, taken: set) -> str:
    base = "u-" + (re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:30] or "user")
    key, i = base, 2
    while key in taken:
        key, i = f"{base}-{i}", i + 1
    taken.add(key)
    return key


def preview(text: str, document: Mapping[str, Any], default_site: str, sites: Mapping[str, str]) -> List[Dict[str, Any]]:
    """Each pasted row as it would be imported, with its problems (in words). `sites`: site id -> name, for rows that name their site."""
    sample = text.strip()
    if not sample:
        return []
    dialect = "excel-tab" if "\t" in sample.splitlines()[0] else "excel"
    rows = [r for r in csv.reader(io.StringIO(sample), dialect=dialect) if any(c.strip() for c in r)]
    header = [ALIASES.get(c.strip().lower(), c.strip().lower()) for c in rows[0]]
    if "name" in header:
        cols, rows = header, rows[1:]
    else:
        cols = list(COLUMNS)
    by_name = {n.lower(): i for i, n in sites.items()}
    users = document.get("users", {})
    taken_ext = {u["extension"] for u in users.values()}
    held = set(document.get("numbers", {}))
    taken_ids = set(users)
    out = []
    for line, raw in enumerate(rows, start=2 if cols is header else 1):
        r = {c: (raw[i].strip() if i < len(raw) else "") for i, c in enumerate(cols) if c in COLUMNS}
        problems: List[str] = []
        if not r.get("name"):
            problems.append("no name")
        elif not NAME_OK.match(r["name"]):
            problems.append("the name has characters that cannot be used (<, >, %) or is over 100 characters")
        site = default_site
        if r.get("site"):
            site = r["site"] if r["site"] in sites else by_name.get(r["site"].lower(), "")
            if not site:
                problems.append(f"no site called {r['site']!r}")
        ext = r.get("extension", "")
        if ext:
            if not re.match(r"^[1-8][0-9]{1,4}$", ext) or ext in SERVICE_CODES:
                problems.append(f"{ext!r} cannot be an extension (2–5 digits, not starting 0 or 9, not a service code)")
            elif ext in taken_ext:
                problems.append(f"extension {ext} is taken")
        else:
            ext = next(str(n) for n in range(100, 100000) if str(n) not in taken_ext and str(n) not in SERVICE_CODES)
        taken_ext.add(ext)
        email = r.get("email", "")
        if email and not EMAIL.match(email):
            problems.append(f"{email!r} is not an email address")
        direct: Optional[str] = _number(r["direct_number"]) if r.get("direct_number") else None
        if direct and not re.match(E164, direct):
            problems.append(f"{r['direct_number']!r} is not a North American number")
        elif direct and direct not in held:
            problems.append(f"{direct} is not one of the organization's numbers")
        user: Dict[str, Any] = {"name": r.get("name", ""), "site": site, "extension": ext}
        if email:
            user["email"] = email
        if direct:
            user["direct_number"], user["show"] = direct, "direct"
        out.append({"line": line, "id": _slug(r.get("name", ""), taken_ids), "user": user, "problems": problems})
    return out


def apply(document: Mapping[str, Any], rows: List[Dict[str, Any]], group: Optional[str] = None) -> Dict[str, Any]:
    """The document with the rows' users added (only rows without problems), and, if named, added to that ring group."""
    d = dict(document)
    d["users"] = dict(d.get("users", {}))
    added = [r for r in rows if not r["problems"]]
    for r in added:
        d["users"][r["id"]] = r["user"]
    if group and group in d.get("groups", {}):
        d["groups"] = dict(d["groups"])
        g = dict(d["groups"][group])
        g["members"] = list(g["members"]) + [r["id"] for r in added if r["id"] not in g["members"]]
        d["groups"][group] = g
    return d
