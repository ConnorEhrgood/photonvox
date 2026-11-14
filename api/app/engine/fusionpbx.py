"""The FusionPBX adapter's builder: an engine plan (app/compiler) in, the FusionPBX rows that run it out. CRITICAL module (100% branch coverage).

Pure and deterministic: no database, no clock. Every row carries the phone system's `domain_uuid` (FusionPBX has no row-level security; this is
the scoping), and every id is derived from the phone system's own id and the object's key, so a republish addresses the same rows. The writer
(app/engine/writer.py) applies a build in one transaction; vox-agent then clears the cache entries it lists.

Rows and XML copy what FusionPBX 5.5.12's own pages write (docs/SPIKES.md §1), with these deliberate differences:
- call classes are matched anchored (`(^|:)national(:|$)`), since the pages' bare name would also match `international`;
- the emergency route takes the extension's emergency caller ID (as FusionPBX does only for the exact 911 pattern);
- the block route (decision 29) rejects with CALL_REJECTED and records its category in the call record (`photonvox_blocked`);
- one `call_direction-outbound` dial plan per domain, not one per route;
- dial plans are written as XML (what FreeSWITCH reads), with detail rows only where FusionPBX's editor would regenerate the XML from them
  (outbound routes, inbound numbers, time conditions) so a re-save in FusionPBX's screens does not erase them.
Secrets (SIP passwords, voicemail PINs) are not built here: the writer keeps the engine's value or generates one on first write.
"""
from __future__ import annotations

import hashlib
import json
import re
import uuid
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple
from xml.sax.saxutils import quoteattr

from app import speech

OUTBOUND_APP = "8c914ec3-9fc0-8ab5-4cda-6c9288bdc9a3"
INBOUND_APP = "c03b422e-13a8-bd1b-e42b-b6b9b4d27ce4"
TIME_APP = "4b821450-926b-175a-af93-a03c441818b1"
RING_GROUP_APP = "1d61fb65-1eec-bc73-a6ee-a6203b4fe6f2"
IVR_APP = "a5788e9b-58bc-bd1b-df59-fff5d51253ab"
# FusionPBX's standard per-domain dial plans that let one phone reach into another's calls (switched off unless the document says otherwise).
FEATURE_APPS = {"eavesdrop": ("e944af7e-8fcc-429b-a32f-0dcdce1585d8",),
                "intercept": ("2b7b2f82-edfe-4339-8cc5-7d0cf36e1e68", "15332e83-12f5-44d3-8472-633736eb4b9b")}
CONTINUE_ON_FAIL = "1,2,3,6,18,21,27,28,31,34,38,41,42,44,58,88,111,403,501,602,607,809"
SHARED_BOX_BASE = 9900          # shared voicemail boxes are 9901, 9902, … (extensions start 1-8, so they never collide)
HANGUP = "photonvox-hangup"     # where "unreachable: none" forwards: a one-line dial plan that hangs up

# FusionPBX's route orders run 100–300 (after its standard dial plans, before call forwarding's loop guard).
ORDER = {"synthetic": 1, "door": 2, "emergency": 100, "block": 105, "service": 110, "national": 120, "toll_free": 130, "international": 140, "group": 101, "menu": 101,
         "hangup": 102, "hours": 300, "inbound": 100}
# Tables, parents before children: the writer inserts in this order and deletes in reverse.
AUDIT = ("insert_date", "insert_user", "update_date", "update_user")     # FusionPBX's own bookkeeping columns: never written by PhotonVox
def norm(v: Any) -> Any:
    """Values compared the same however they were read (numbers as text, JSON text parsed): as app/engine/compare.py's norm."""
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return str(v)
    if isinstance(v, str) and v[:1] in "[{":
        try:
            return json.loads(v)
        except ValueError:
            return v
    return v


# What the protections version writes on every adopted extension, whatever else stays as it was: its call classes, and what its 911 calls show.
PROTECTED = {"v_extensions": ("toll_allow", "emergency_caller_id_number")}
TABLES = ("v_extensions", "v_voicemails", "v_ring_groups", "v_ring_group_destinations", "v_ivr_menus", "v_ivr_menu_options", "v_dialplans",
          "v_dialplan_details", "v_destinations")
KEYS = {"v_extensions": "extension_uuid", "v_voicemails": "voicemail_uuid", "v_ring_groups": "ring_group_uuid",
        "v_ring_group_destinations": "ring_group_destination_uuid", "v_ivr_menus": "ivr_menu_uuid", "v_ivr_menu_options": "ivr_menu_option_uuid",
        "v_dialplans": "dialplan_uuid", "v_dialplan_details": "dialplan_detail_uuid", "v_destinations": "destination_uuid"}
# US federal holidays as FreeSWITCH time conditions (a Monday-holiday is "the nth Monday": mday range plus wday 2). Fixed dates are not moved
# to a weekday (FusionPBX's presets do not either).
US_FEDERAL = (
    ("new-year", {"mon": "1", "mday": "1"}), ("mlk", {"mon": "1", "mday": "15-21", "wday": "2"}),
    ("presidents", {"mon": "2", "mday": "15-21", "wday": "2"}), ("memorial", {"mon": "5", "mday": "25-31", "wday": "2"}),
    ("juneteenth", {"mon": "6", "mday": "19"}), ("independence", {"mon": "7", "mday": "4"}), ("labor", {"mon": "9", "mday": "1-7", "wday": "2"}),
    ("columbus", {"mon": "10", "mday": "8-14", "wday": "2"}), ("veterans", {"mon": "11", "mday": "11"}),
    ("thanksgiving", {"mon": "11", "mday": "22-28", "wday": "5"}), ("christmas", {"mon": "12", "mday": "25"}),
)
WDAY = {"sun": 1, "mon": 2, "tue": 3, "wed": 4, "thu": 5, "fri": 6, "sat": 7}


class Secret(str):
    """A column the writer fills: the engine's current value if the row exists, else a new one of this kind ("sip" or "pin")."""


@dataclass(frozen=True)
class Target:
    """Where a phone system goes: its FusionPBX domain, the instance's gateways by upstream key, and the phone system's id (the namespace of
    every row id)."""
    phone_system_id: str
    domain_uuid: str
    gateways: Mapping[str, str]          # upstream key -> v_gateways.gateway_uuid
    speech: bool = False                 # greetings were spoken and put on the engine (app/speech): menus name their files
    adoption: Optional["Adoption"] = None   # a hand-built domain taken over in place (decision 32)


@dataclass(frozen=True)
class Adoption:
    """What the takeover importer (app/engine/importer.py) found, for a domain taken over in place (ARCHITECTURE §17.4):
    `objects`: builder object key ("extension:100", "inbound:+1…", "ivr:main") -> the live rows (table, id) that make it up;
    `rows`: "table:id" -> the live row; `ids`: builder name -> the live id it keeps; `meanings`: object key -> its meaning when adopted.
    While an object's meaning is unchanged the builder emits exactly its live rows, so a publish changes nothing; when it changes, the object is
    regenerated with the same ids, over its live columns. Outside calls, 911 and blocking stay the engine's own: no routes are generated."""
    objects: Mapping[str, Any]
    rows: Mapping[str, Mapping[str, Any]]
    ids: Mapping[str, str]
    meanings: Mapping[str, str]
    # The rows a fresh build of the adopted document gave ("table:id" -> row): when an object changes later, only the columns whose value the
    # document now gives differently are written; every other column keeps what is on the engine (hold music, a ring time the document has
    # no word for).
    fresh: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)
    # Hand-built dial plans PhotonVox manages from the protections on (ARCHITECTURE §17 stage 5): switched off in a protected version (the plan's
    # `protected`, from the document), and back on exactly as they were in one without, so an undo is a real undo. Never deleted.
    retire: Sequence[str] = ()                                           # v_dialplans ids
    retired_rows: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)   # "table:id" -> the row as it was (the dial plans and their details)


@dataclass
class Build:
    rows: Dict[str, List[Dict[str, Any]]] = field(default_factory=lambda: {t: [] for t in TABLES})
    secrets: Dict[Tuple[str, str], str] = field(default_factory=dict)   # (table, uuid) -> column holding a Secret
    meanings: Dict[str, str] = field(default_factory=dict)              # object key -> what it means (a hash of its part of the plan)
    adopted: List[str] = field(default_factory=list)                    # objects emitted exactly as they are on the engine
    row_cache: Dict[Tuple[str, str], List[str]] = field(default_factory=dict)   # (table, uuid) -> its object's cache entries, for a row rewritten alone
    features: Dict[str, bool] = field(default_factory=dict)             # standard dial plan app_uuid -> enabled
    cache: List[str] = field(default_factory=list)                      # /var/cache/fusionpbx file names to delete

    def manifest(self) -> List[Dict[str, str]]:
        """What was written, for PhotonVox's engine_object records: table, id and a hash of the columns (secrets excluded), sorted."""
        out = []
        for table in TABLES:
            for r in self.rows[table]:
                body = {k: v for k, v in r.items() if not isinstance(v, Secret)}
                digest = hashlib.sha256(json.dumps(body, sort_keys=True, default=str).encode()).hexdigest()
                out.append({"table": table, "uuid": r[KEYS[table]], "hash": digest})
        return sorted(out, key=lambda m: (TABLES.index(m["table"]), m["uuid"]))


def build(plan: Mapping[str, Any], target: Target) -> Build:
    return _Builder(plan, target).run()


def checks(plan: Mapping[str, Any], target: Target) -> List[Dict[str, Any]]:
    """The post-publish check (ARCHITECTURE §5): one synthetic call per inbound number (it must reach its outcome; a time condition either of
    its two), plus one premium number, which the block route must refuse. Each lists what the call may find, in the agent's words
    (app/engine/agent.py); anything else fails. **No call is ever placed to 911, 933 or 9911, not even a synthetic one** (operator's rule,
    2026-11-14): the emergency route is verified by reading what was built (`emergency_read`)."""
    b = _Builder(plan, target)
    hours = {tc["key"]: tc for tc in plan["time_conditions"]}
    # Where each number sends a call, as built (an adopted number keeps its live destination, which may name its menu or a person by extension).
    built = {r["destination_number"][-10:]: r["destination_data"] for r in _Builder(plan, target).run().rows["v_destinations"]}
    out: List[Dict[str, Any]] = []
    for n in plan["inbound"]:
        kind, _, key = n["to"].partition(":")
        dests = [hours[key]["open"], hours[key]["closed"]] if kind == "time_condition" else [n["to"]]
        expect = sorted({"reached " + b.transfer(d)[1].split(" ")[0] for d in dests})      # a number's outcomes are never "hang up"
        first = built[n["number"][-10:]].split(" ")[0]
        if kind != "time_condition" and not first.startswith("hours-"):
            expect = ["reached " + first]
        # Dialed as the ten digits, the form carriers send and every inbound route takes (a hand-built one may take nothing else).
        out.append({"kind": "inbound", "number": n["number"], "dial": n["number"][-10:], "expect": expect})
    block = next(r for r in plan["outbound_routes"] if r["key"] == "block")
    if any(c["category"] == "premium" for c in block["categories"]):
        out.append({"kind": "route", "number": "19005550100", "expect": ["blocked premium"]})
    return out


def emergency_read(plan: Mapping[str, Any], target: Target) -> List[Dict[str, Any]]:
    """The emergency route, verified by reading the plan as built, never by calling: 911 and 933, with and without each outside-line prefix,
    are matched first by the emergency route (it is ordered before every other route), which sends the number dialed through the instance's
    911 upstream; and no blocked category matches them. One result per number, in the checks' shape (kind "emergency, read")."""
    routes = plan["outbound_routes"]
    emergency = next(r for r in routes if r["key"] == "emergency")
    gws = [target.gateways.get(g) for g in emergency["gateways"]]
    first = min(routes, key=lambda r: ORDER.get(r["key"], ORDER["international"]))
    blocked = [c["pattern"] for r in routes if r.get("reject") for c in r["categories"]]
    out: List[Dict[str, Any]] = []
    for p in [""] + list(plan["outside_prefixes"]):
        for code in ("911", "933"):
            m = re.search(emergency["pattern"], p + code)
            ok = (first is emergency and m is not None and m.group(1) == code and all(gws) and gws == [target.gateways.get(plan_gw) for plan_gw in emergency["gateways"]]
                  and not any(re.search(b, p + code) for b in blocked))
            out.append({"kind": "emergency, read", "number": p + code, "expect": [f"emergency {','.join(map(str, gws))} {code}"],
                        "got": f"emergency {','.join(map(str, gws))} {m.group(1)}" if m else None, "ok": ok})
    return out


class _Builder:
    def __init__(self, plan: Mapping[str, Any], target: Target) -> None:
        self.p, self.t, self.b = plan, target, Build()
        self.domain = plan["domain"]
        self.ns = uuid.UUID(target.phone_system_id)
        boxes = [x["key"] for x in plan["voicemail_boxes"]]
        self.box_id = {k: str(SHARED_BOX_BASE + i + 1) for i, k in enumerate(boxes)}
        self.a = target.adoption
        self.obj: Optional[str] = None                     # the object being built: its rows and cache entries are recorded under it
        self.obj_rows: Dict[str, List[Tuple[str, Dict[str, Any]]]] = {}
        self.obj_cache: Dict[str, List[str]] = {}

    # ---- helpers ----
    def uid(self, name: str) -> str:
        if self.a and name in self.a.ids:          # an adopted row keeps its id
            return self.a.ids[name]
        return str(uuid.uuid5(self.ns, name))

    def begin(self, obj: str, fragment: Any) -> None:
        """Start an object: what follows belongs to it; its meaning is its part of the plan."""
        self.obj = obj
        self.b.meanings[obj] = hashlib.sha256(json.dumps(fragment, sort_keys=True, default=str).encode()).hexdigest()

    def cache(self, entry: str) -> None:
        """A cache entry of the object being built (every one belongs to an object; the domain's own entry is added in run)."""
        self.b.cache.append(entry)
        self.obj_cache.setdefault(str(self.obj), []).append(entry)

    def row(self, table: str, **cols: Any) -> Dict[str, Any]:
        cols["domain_uuid"] = self.t.domain_uuid
        self.b.rows[table].append(cols)
        if self.obj:
            self.obj_rows.setdefault(self.obj, []).append((table, cols))
        for k, v in cols.items():
            if isinstance(v, Secret):
                self.b.secrets[(table, cols[KEYS[table]])] = k
        return cols

    def transfer(self, dest: str) -> Tuple[str, str]:
        """An engine destination from the plan as a FusionPBX (application, data) pair."""
        kind, _, key = dest.partition(":")
        if kind == "hangup":
            return "hangup", "NORMAL_CLEARING"
        if kind == "voicemail_box":
            number = f"*99{self.box_id[key]}"
        else:
            number = {"extension": key, "voicemail": f"*99{key}", "ring_group": f"group-{key}", "ivr": f"menu-{key}",
                      "time_condition": f"hours-{key}"}[kind]
        return "transfer", f"{number} XML {self.domain}"

    def dialplan(self, key: str, name: str, order: int, app_uuid: Optional[str], body: str, number: Optional[str] = None, context: Optional[str] = None,
                 cont: bool = False, details: Optional[List[Tuple[Any, ...]]] = None) -> str:
        dp = self.uid("dialplan:" + key)
        xml = f'<extension name={quoteattr(name)} continue="{"true" if cont else "false"}" uuid="{dp}">\n{body}</extension>'
        check_xml(xml)
        self.row("v_dialplans", dialplan_uuid=dp, app_uuid=app_uuid, dialplan_context=context or self.domain, dialplan_name=name,
                 dialplan_number=number, dialplan_continue=cont, dialplan_xml=xml, dialplan_order=order, dialplan_enabled=True,
                 dialplan_description="PhotonVox")
        for i, (tag, typ, data, inline, *group) in enumerate(details or []):
            self.row("v_dialplan_details", dialplan_detail_uuid=self.uid(f"detail:{key}:{i}"), dialplan_uuid=dp, dialplan_detail_tag=tag,
                     dialplan_detail_type=typ, dialplan_detail_data=data, dialplan_detail_inline="true" if inline else None,
                     dialplan_detail_group=group[0] if group else 0, dialplan_detail_order=(i + 1) * 10, dialplan_detail_enabled=True)
        return dp

    # ---- the parts ----
    def run(self) -> Build:
        for x in self.p["extensions"]:
            self.begin("extension:" + x["extension"], x)
            self.extension(x)
        for box in self.p["voicemail_boxes"]:
            self.begin("box:" + box["key"], box)
            self.voicemail(self.box_id[box["key"]], box["name"], box.get("email"), f"box:{box['key']}")
        self.obj = None
        if not self.a or self.p.get("protected"):
            # An adopted domain keeps its own outside calls, 911 and blocking (hand-built) until the protections version: none generated before.
            self.direction()
            self.hangup()
            self.synthetic()
            for r in self.p["outbound_routes"]:
                self.block(r) if r.get("reject") else self.route(r)
        for g in self.p["ring_groups"]:
            self.begin("ring_group:" + g["key"], g)
            self.ring_group(g)
        for m in self.p["ivr_menus"]:
            self.begin("ivr:" + m["key"], m)
            self.menu(m)
        for tc in self.p["time_conditions"]:
            self.begin("hours:" + tc["key"], tc)
            self.hours(tc)
        for n in self.p["inbound"]:
            self.begin("inbound:" + n["number"], n)
            self.inbound(n)
        for d in self.p.get("doors", []):
            self.begin("door:" + d["key"], d)
            self.door(d)
        self.obj = None
        if not self.a:
            for name, enabled in self.p["features"].items():
                for app in FEATURE_APPS[name]:
                    self.b.features[app] = enabled
        self.b.cache.append(f"dialplan.{self.domain}")
        if self.a:
            self.adopt()
        for obj, built in self.obj_rows.items():
            for table, cols in built:
                self.b.row_cache[(table, cols[KEYS[table]])] = sorted(set(self.obj_cache.get(obj, [])))
        if self.a:
            for obj in self.b.adopted:
                for table, uid in self.a.objects[obj]:
                    self.b.row_cache[(table, uid)] = sorted(set(self.obj_cache.get(obj, [])))
        self.b.cache = sorted(set(self.b.cache))
        return self.b

    def adopt(self) -> None:
        """Objects whose meaning is what it was when adopted: their live rows, exactly. Changed or new objects: as built, over the live columns of
        rows that keep their id, writing only the columns whose value the document now gives differently from when it was adopted (what the
        document does not say stays as it was). Protected: the PROTECTED columns as built on every adopted row too. Only the cache entries of
        what changed are cleared."""
        assert self.a
        keep: List[str] = []
        prot = {t: cols for t, cols in PROTECTED.items()} if self.p.get("protected") else {}
        for obj, built in self.obj_rows.items():
            live = self.a.objects.get(obj)
            if live is not None and self.a.meanings.get(obj) == self.b.meanings[obj]:
                by_id = {(t, c[KEYS[t]]): c for t, c in built}
                for table, cols in built:
                    self.b.rows[table].remove(cols)
                for table, uid in live:
                    row = {**self.a.rows[f"{table}:{uid}"]}
                    for c in prot.get(table, ()):
                        if (table, uid) in by_id and norm(row.get(c)) != norm(by_id[(table, uid)].get(c)):
                            row[c] = by_id[(table, uid)][c]
                            keep += self.obj_cache.get(obj, [])
                    self.b.rows[table].append(row)
                self.b.adopted.append(obj)
                continue
            for table, cols in built:
                base = self.a.rows.get(f"{table}:{cols[KEYS[table]]}")
                if base:
                    fresh = self.a.fresh.get(f"{table}:{cols[KEYS[table]]}")
                    merged = {k: v for k, v in base.items() if k not in AUDIT}
                    for c, v in cols.items():
                        if fresh is None or c not in fresh or c in prot.get(table, ()) or norm(fresh[c]) != norm(v) or isinstance(v, Secret):
                            merged[c] = v
                    cols.clear()
                    cols.update(merged)
            keep += self.obj_cache.get(obj, [])
        changed = set(self.obj_rows) - set(self.b.adopted)
        for uid in self.a.retire:                  # off while protected, as they were otherwise (their details are left as they are)
            row = {**self.a.retired_rows[f"v_dialplans:{uid}"]}
            row["dialplan_enabled"] = False if self.p.get("protected") else row.get("dialplan_enabled")
            self.b.rows["v_dialplans"].append(row)
        domain_wide = changed or self.p.get("protected") or self.a.retire
        self.b.cache = sorted(set(keep) | ({f"dialplan.{self.domain}"} if domain_wide else set()))
        for table in TABLES:
            self.b.rows[table].sort(key=lambda r: r[KEYS[table]])

    def extension(self, x: Mapping[str, Any]) -> None:
        ext = x["extension"]
        none = x["unreachable"] == "hangup"
        self.row("v_extensions", extension_uuid=self.uid("extension:" + ext), extension=ext, password=Secret("sip"), accountcode=self.domain,
                 effective_caller_id_name=x["name"], effective_caller_id_number=ext, outbound_caller_id_name=None,
                 outbound_caller_id_number=x["caller_id_number"], emergency_caller_id_name=None,
                 emergency_caller_id_number=x["emergency_caller_id_number"], directory_first_name=x["name"], directory_visible=False,
                 directory_exten_visible=False, limit_max="5", limit_destination="!USER_BUSY", user_context=self.domain,
                 toll_allow=f"door:{ext}" if x.get("door") else ":".join(x["toll_allow"]), call_timeout=30, call_screen_enabled=False, extension_dialect="us",
                 extension_voice="callie", extension_type="default", enabled=True, description="PhotonVox", force_ping=False,
                 forward_user_not_registered_enabled=none, forward_user_not_registered_destination=HANGUP if none else None)
        if not x.get("door"):                       # a door station has no voicemail box at all
            self.voicemail(ext, x["name"], x.get("email"), "extension:" + ext, x.get("voicemail", True))
        self.cache(f"directory.{ext}@{self.domain}")

    def voicemail(self, box: str, name: str, email: Optional[str], key: str, enabled: bool = True) -> None:
        self.row("v_voicemails", voicemail_uuid=self.uid("voicemail:" + key), voicemail_id=box, voicemail_password=Secret("pin"),
                 voicemail_mail_to=email, voicemail_file="attach" if email else None, voicemail_local_after_email=True, voicemail_enabled=enabled,
                 voicemail_recording_instructions=True, voicemail_recording_options=True, voicemail_description=name)

    def direction(self) -> None:
        body = ('\t<condition field="${user_exists}" expression="false"/>\n\t<condition field="${call_direction}" expression="^$"/>\n'
                '\t<condition field="destination_number" expression="^.+$">\n' + _act("export", "call_direction=outbound", True) + "\t</condition>\n")
        self.dialplan("call-direction", "call_direction-outbound", 22, OUTBOUND_APP, body, cont=True)

    def synthetic(self) -> None:
        """First in the domain: a synthetic inbound call (the post-publish check) stops at the first place its number sends it and logs where,
        so no phone rings. Time conditions are let through, so the check also sees them choose. Real calls never carry the variable."""
        body = ('\t<condition field="${photonvox_synthetic}" expression="^inbound$"/>\n'
                '\t<condition field="destination_number" expression="^(?!hours-)(.+)$">\n'
                + _act("log", "NOTICE PhotonVox-synthetic token=${photonvox_token} reached=$1") + _act("hangup", "NORMAL_CLEARING")
                + "\t</condition>\n")
        self.dialplan("synthetic", "photonvox.synthetic", ORDER["synthetic"], None, body)

    def hangup(self) -> None:
        body = f'\t<condition field="destination_number" expression="^{HANGUP}$">\n' + _act("hangup", "NO_USER_RESPONSE") + "\t</condition>\n"
        self.dialplan("hangup", HANGUP, ORDER["hangup"], None, body)

    def route(self, r: Mapping[str, Any]) -> None:
        key = r["key"]
        order = ORDER.get(key) or ORDER["international"] + [x["key"] for x in self.p["outbound_routes"]].index(key)
        details = [("condition", "${user_exists}", "false", None)]
        conds = '\t<condition field="${user_exists}" expression="false"/>\n'
        if r["requires"]:
            cls = f"(^|:){r['requires']}(:|$)"
            conds += f'\t<condition field="${{toll_allow}}" expression={quoteattr(cls)}/>\n'
            details.append(("condition", "${toll_allow}", cls, None))
        conds += f'\t<condition field="destination_number" expression={quoteattr(r["pattern"])}>\n'
        details.append(("condition", "destination_number", r["pattern"], None))
        cid = "emergency_caller_id" if r["caller_id"] == "emergency_caller_id_number" else "outbound_caller_id"
        actions = [("export", "call_direction=outbound", True), ("unset", "call_timeout", False), ("set", "hangup_after_bridge=true", False),
                   ("set", f"effective_caller_id_name=${{{cid}_name}}", False), ("set", f"effective_caller_id_number=${{{cid}_number}}", False),
                   ("set", "inherit_codec=true", False), ("set", "ignore_display_updates=true", False), ("set", "callee_id_number=$1", False),
                   ("set", f"continue_on_fail={CONTINUE_ON_FAIL}", False),
                   # The number to send is captured here: $1 means the matching condition's capture, and the bridges below sit in another one.
                   ("set", f"photonvox_dial={r['send']}", False)]
        bridges = [f"sofia/gateway/{self.t.gateways[g]}/${{photonvox_dial}}" for g in r["gateways"]]
        gws = ",".join(self.t.gateways[g] for g in r["gateways"])
        # The bridges sit behind a condition every real call passes (the variable is never set on one). The post-publish check's synthetic
        # call sets it, and gets this route's name and gateways in the log instead of a call leaving the engine (ARCHITECTURE §5).
        probe = [("log", f"NOTICE PhotonVox-synthetic token=${{photonvox_token}} route={key} gateways={gws} dial=${{photonvox_dial}}"),
                 ("hangup", "NORMAL_CLEARING")]
        body = (conds + "".join(_act(a, d, i) for a, d, i in actions) + "\t</condition>\n"
                + '\t<condition field="${photonvox_synthetic}" expression="^$">\n' + "".join(_act("bridge", b) for b in bridges)
                + "".join(_act(a, d, anti=True) for a, d in probe) + "\t</condition>\n")
        details += [("action", a, d, i or None) for a, d, i in actions]
        details += ([("condition", "${photonvox_synthetic}", "^$", None, 1)] + [("action", "bridge", b, None, 1) for b in bridges]
                    + [("anti-action", a, d, None, 1) for a, d in probe])
        self.dialplan("route:" + key, f"photonvox.{key}", order, OUTBOUND_APP, body, details=details)

    def block(self, r: Mapping[str, Any]) -> None:
        """One condition per category (the first match names the block), behind an optional exception gate."""
        body = ""
        if r["except"]:
            body += f'\t<condition field="destination_number" expression={quoteattr("^(?!" + r["except"][1:-1] + "$)")}/>\n'
        for c in r["categories"]:
            body += (f'\t<condition field="destination_number" expression={quoteattr(c["pattern"])} break="on-true">\n'
                     + _act("export", f"photonvox_blocked={c['category']}", True)
                     + _act("log", f"WARNING PhotonVox blocked {c['category']} call to ${{destination_number}} from ${{caller_id_number}} "
                            "token=${photonvox_token}")
                     + _act("hangup", "CALL_REJECTED") + "\t</condition>\n")
        self.dialplan("route:block", "photonvox.block", ORDER["block"], OUTBOUND_APP, body)

    def ring_group(self, g: Mapping[str, Any]) -> None:
        key = g["key"]
        rg = self.uid("ring_group:" + key)
        number = f"group-{key}"
        body = (f'\t<condition field="destination_number" expression={_exact(number)}>\n' + _act("ring_ready", "") + _act("set", f"ring_group_uuid={rg}")
                + _act("lua", "app.lua ring_groups") + "\t</condition>\n")
        dp = self.dialplan("ring_group:" + key, f"photonvox.group.{key}", ORDER["group"], RING_GROUP_APP, body, number=number)
        app, data = self.transfer(g["then"])
        self.row("v_ring_groups", ring_group_uuid=rg, ring_group_name=key, ring_group_extension=number, ring_group_call_timeout=g["ring_seconds"],
                 ring_group_forward_enabled=False, ring_group_strategy=g["strategy"], ring_group_timeout_app=app, ring_group_timeout_data=data,
                 ring_group_call_screen_enabled=False, ring_group_call_forward_enabled=False, ring_group_follow_me_enabled=False,
                 ring_group_context=self.domain, ring_group_enabled=True, ring_group_description="PhotonVox", dialplan_uuid=dp)
        for m in g["members"]:
            self.row("v_ring_group_destinations", ring_group_destination_uuid=self.uid(f"ring_group:{key}:{m}"), ring_group_uuid=rg,
                     destination_number=m, destination_delay=0, destination_timeout=g["ring_seconds"], destination_enabled=True)

    def menu(self, m: Mapping[str, Any]) -> None:
        key = m["key"]
        menu = self.uid("ivr:" + key)
        number = f"menu-{key}"
        app, data = self.transfer(m["timeout"])
        body = (f'\t<condition field="destination_number" expression={_exact(number)}>\n' + _act("ring_ready", "") + _act("answer", "")
                + _act("sleep", "1000") + _act("set", "hangup_after_bridge=true") + _act("set", f"ivr_menu_uuid={menu}") + _act("ivr", menu)
                + _act(app, data) + "\t</condition>\n")
        dp = self.dialplan("ivr:" + key, f"photonvox.menu.{key}", ORDER["menu"], IVR_APP, body, number=number)
        # The greeting is text in the document, spoken at publish (decision 30) into a file in the domain's recordings, which FusionPBX finds by name.
        if m["greeting"].startswith("recording:"):
            greeting: Optional[str] = m["greeting"][len("recording:"):]        # a recording already in the domain's recordings
        else:
            greeting = speech.file_name(m["greeting"], self.p.get("voice", speech.DEFAULT_VOICE)) if self.t.speech else None
        self.row("v_ivr_menus", ivr_menu_uuid=menu, dialplan_uuid=dp, ivr_menu_name=key, ivr_menu_extension=number, ivr_menu_greet_long=greeting,
                 ivr_menu_dialect="us", ivr_menu_voice="callie", ivr_menu_confirm_attempts=1, ivr_menu_timeout=3000, ivr_menu_exit_app=app,
                 ivr_menu_exit_data=data, ivr_menu_inter_digit_timeout=2000, ivr_menu_max_failures=1, ivr_menu_max_timeouts=1,
                 ivr_menu_digit_len=1, ivr_menu_direct_dial=False, ivr_menu_ringback="local_stream://default", ivr_menu_context=self.domain,
                 ivr_menu_enabled=True, ivr_menu_description=m["greeting"][:255])
        for i, (digits, dest) in enumerate(sorted(m["options"].items())):
            oa, od = self.transfer(dest)
            self.row("v_ivr_menu_options", ivr_menu_option_uuid=self.uid(f"ivr:{key}:{digits}"), ivr_menu_uuid=menu, ivr_menu_option_digits=digits,
                     ivr_menu_option_action="menu-exec-app", ivr_menu_option_param=f"{oa} {od}", ivr_menu_option_order=i,
                     ivr_menu_option_enabled=True)
        self.cache(f"configuration.ivr.conf.{menu}")

    def hours(self, tc: Mapping[str, Any]) -> None:
        """Open hours in the site's time zone (FreeSWITCH evaluates time conditions in the `timezone` channel variable, set inline first);
        holidays closed; the first condition that holds decides."""
        key = tc["key"]
        number = f"hours-{key}"
        oa, od = self.transfer(tc["open"])
        ca, cd = self.transfer(tc["closed"])
        body = (f'\t<condition field="destination_number" expression={_exact(number)}>\n' + _act("set", f"timezone={tc['timezone']}", True)
                + "\t</condition>\n")
        details: List[Tuple[str, str, str, Optional[bool]]] = [("condition", "destination_number", f"^{number}$", None),
                                                               ("action", "set", f"timezone={tc['timezone']}", True)]
        if tc["holidays"] == "us-federal":
            for _name, when in US_FEDERAL:
                body += "\t<condition " + " ".join(f'{k}="{v}"' for k, v in when.items()) + ' break="on-true">\n' + _act(ca, cd) + "\t</condition>\n"
        for day, spans in tc["week"].items():
            for span in spans:
                start, end = span.split("-")
                body += (f'\t<condition wday="{WDAY[day]}" time-of-day="{start}-{_before(end)}" break="on-true">\n' + _act(oa, od)
                         + "\t</condition>\n")
        body += f'\t<condition field="destination_number" expression={_exact(number)}>\n' + _act(ca, cd) + "\t</condition>\n"
        self.dialplan("hours:" + key, f"photonvox.hours.{key}", ORDER["hours"], TIME_APP, body, number=number, details=details)

    def door(self, d: Mapping[str, Any]) -> None:
        """A door station's calls: whatever it dials goes to its flow, once (the transfer comes back through the dial plan; the variable set
        here lets it pass the second time), except 911 and 933 with or without an outside-line prefix, which go on to the emergency route.
        Its toll_allow ("door:<extension>", from the directory, which a phone cannot change) is what recognizes it: another phone dialing
        anything never comes here, and the door reaches nothing but its flow and 911. Ordered right after the synthetic check, before any
        hand-built route of an adopted domain. Nothing here touches the call's DTMF: the "#" the person answering presses reaches the
        intercom as RFC 2833 (PhotonEntry's unlock code). Two log lines say when the call started and who answered it (vox-agent reads them
        for PhotonEntry's door-calls); the second runs when the door's own leg is answered, which is when the flow's call is bridged, and
        names the leg it was bridged to (callee_id_number: the extension, or the number sent out). Its variables are escaped twice, so they
        are expanded then (an exported one would be refused by the answering leg; the hangup hook is FusionPBX's own after the transfer)."""
        ext, key = d["extension"], d["key"]
        app, data = self.transfer(d["to"])
        started = f"NOTICE PhotonVox-door domain={self.domain} door={ext} call=${{uuid}} started=${{strepoch()}}"
        late = "\\\\\\$"         # \\\$ : survives the action's expansion and `set`'s own, so it is expanded when the call is answered
        answered = (f"api_on_answer=log NOTICE PhotonVox-door domain={self.domain} door={ext} call=${{uuid}} answered={late}{{strepoch()}} "
                    f"callee={late}{{callee_id_number}}")
        actions = [("set", f"photonvox_door={key}", True), ("log", started, False), ("set", answered, False),
                   ("unset", "bridge_terminate_key", False), ("set", "hangup_after_bridge=true", False), (app, data, False)]
        conds = [("${toll_allow}", "^door:" + ext + "$"), ("${photonvox_door}", "^$"), ("destination_number", DOOR_NOT_EMERGENCY)]
        body = ("".join(f"\t<condition field={quoteattr(f)} expression={quoteattr(e)}/>\n" for f, e in conds[:-1])
                + f"\t<condition field={quoteattr(conds[-1][0])} expression={quoteattr(conds[-1][1])}>\n"
                + "".join(_act(a, v, i) for a, v, i in actions) + "\t</condition>\n")
        details = [("condition", f, e, None) for f, e in conds] + [("action", a, v, i or None) for a, v, i in actions]
        self.dialplan("door:" + key, f"photonvox.door.{key}", ORDER["door"], None, body, details=details)

    def inbound(self, n: Mapping[str, Any]) -> None:
        """The destination row and its public dial plan describe the same number, in every form a carrier may send it: +1NXXNXXXXXX,
        1NXXNXXXXXX or NXXNXXXXXX (FusionPBX's single mode matches prefix + number, + prefix + number, or the number alone)."""
        number = n["number"]
        ten = number[2:]
        regex = f"^\\+?1?({ten})$"
        app, data = self.transfer(n["to"])
        actions = [("export", "call_direction=inbound", True), ("set", f"domain_uuid={self.t.domain_uuid}", True),
                   ("set", f"domain_name={self.domain}", True), (app, data, False)]
        body = (f'\t<condition field="destination_number" expression={quoteattr(regex)}>\n' + "".join(_act(a, d, i) for a, d, i in actions)
                + "\t</condition>\n")
        details = [("condition", "destination_number", regex, None)] + [("action", a, d, i or None) for a, d, i in actions]
        dp = self.dialplan("inbound:" + number, number, ORDER["inbound"], INBOUND_APP, body, number=number, context="public", details=details)
        self.row("v_destinations", destination_uuid=self.uid("destination:" + number), dialplan_uuid=dp, destination_type="inbound",
                 destination_prefix="1", destination_number=ten, destination_number_regex=regex, destination_context="public",
                 destination_record=False, destination_actions=[{"destination_app": app, "destination_data": data}], destination_app=app,
                 destination_data=data, destination_order=100, destination_enabled=True, destination_description="PhotonVox")
        for form in (number, number[1:], ten):
            self.cache(f"dialplan.public.{form}")


# Every number a door may dial except an emergency one (911 or 933, with an 8 or 9 in front or not): those go on to the emergency route.
DOOR_NOT_EMERGENCY = r"^(?![89]?(?:911|933)$)"
# The one command a PhotonVox dial plan has the engine run on an event: a door call's answering leg logs who it is (checked in check_xml).
DOOR_ANSWERED = re.compile(r"^api_on_answer=log NOTICE PhotonVox-door domain=[a-z0-9.-]+ door=[1-8][0-9]{1,4} call=\$\{uuid\} "
                           r"answered=\\\\\\\$\{strepoch\(\)\} callee=\\\\\\\$\{callee_id_number\}$")


def _exact(number: str) -> str:
    """A destination matched exactly, as an XML attribute: regex-escaped and quoted (names are constrained by the document too: review C1)."""
    return quoteattr("^" + re.escape(number) + "$")


# What PhotonVox's dial plans may do. Every dial plan is parsed and checked against this before it is written, so nothing a document says can
# become another application (FreeSWITCH's `system`, `eavesdrop`, a bridge to anywhere): security review C1, 2026-11-13.
ALLOWED_APPS = {"answer", "bridge", "export", "hangup", "ivr", "log", "lua", "ring_ready", "set", "sleep", "transfer", "unset"}
ALLOWED_ELEMENTS = {"extension", "condition", "action", "anti-action"}


def check_xml(xml: str) -> None:
    root = ET.fromstring(xml)
    for el in root.iter():
        if el.tag not in ALLOWED_ELEMENTS:
            raise ValueError(f"dial plan element {el.tag!r} is not one PhotonVox writes")
        app = el.get("application")
        if el.tag in ("action", "anti-action") and app not in ALLOWED_APPS:
            raise ValueError(f"dial plan application {app!r} is not one PhotonVox writes")
        if app == "lua" and el.get("data") != "app.lua ring_groups":
            raise ValueError("the only Lua a PhotonVox dial plan runs is FusionPBX's ring groups")
        if app in ("set", "export"):
            var = el.get("data", "").split("=", 1)[0].removeprefix("nolocal:")
            if re.match(r"^(api_|execute_on_|exec_after_bridge|bridge_pre_execute)", var) and not DOOR_ANSWERED.match(el.get("data", "")):
                raise ValueError(f"a PhotonVox dial plan never sets {var!r} (it would run a command), except the door's own answer log")
        if app == "bridge" and not re.match(r"^sofia/gateway/[0-9a-f-]{36}/\$\{photonvox_dial\}$", el.get("data", "")):
            raise ValueError("a PhotonVox dial plan bridges only to an upstream gateway")


def _act(app: str, data: str, inline: bool = False, anti: bool = False) -> str:
    flag = ' inline="true"' if inline else ""
    tag = "anti-action" if anti else "action"
    return f"\t\t<{tag} application={quoteattr(app)} data={quoteattr(data)}{flag}/>\n"


def _before(end: str) -> str:
    """FreeSWITCH's time-of-day includes its end; a span "08:00-17:00" ends at 16:59:59 (and 24:00 at 23:59:59)."""
    h, m = (int(x) for x in end.split(":"))
    total = h * 60 + m - 1
    return f"{total // 60:02d}:{total % 60:02d}:59"
