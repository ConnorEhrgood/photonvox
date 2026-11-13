"""The takeover, offline (ARCHITECTURE §17.2–17.4): a domain export in (engine/live/export_domain.py), and out come the document, the adoption,
the report of what could not be expressed, and the compare: the rows the first publish would write against the live rows (it must be empty)
and what a regenerated build would do differently (the understanding check).

    python engine/live/takeover.py <export.json> <out dir> --site <site id> --phone-system <id> --gateway <upstream key>=<gateway id>

Reads and writes files only. Exit 0 when the first publish is identical to the live rows.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "api"))

from app.compiler.compile import CompileError, Context, compile_plan  # noqa: E402
from app.document.model import PhoneSystem  # noqa: E402
from app.engine import compare, fusionpbx, importer  # noqa: E402


def run(export: dict, site: str, phone_system: str, gateways: dict, timezone: str = "America/New_York"):
    imp = importer.import_domain(export, site)
    doc = PhoneSystem.model_validate(imp.document)
    D = export["domain"]["domain_uuid"]
    upstream = next(iter(gateways))
    ctx = Context(domain=export["domain"]["domain_name"], timezones={site: timezone}, upstreams={"national": [upstream]}, emergency_gateway=upstream,
                  assigned_numbers=set(doc.numbers), adopted=True)
    plan = compile_plan(doc, ctx)
    fresh = fusionpbx.Adoption(objects=imp.objects, rows=imp.rows, ids=imp.ids, meanings={})
    regenerated = fusionpbx.build(plan, fusionpbx.Target(phone_system, D, gateways, adoption=fresh))
    adoption = fusionpbx.Adoption(objects=imp.objects, rows=imp.rows, ids=imp.ids, meanings=regenerated.meanings)
    first = fusionpbx.build(plan, fusionpbx.Target(phone_system, D, gateways, adoption=adoption))
    live = compare.live_rows(export)
    diff = compare.rows_diff(first, live)
    understanding = compare.behavior_diff(compare.behavior(live, D), compare.behavior(compare.as_rows(regenerated), D))
    return imp, doc, plan, adoption, first, diff, understanding


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("export"); ap.add_argument("out")
    ap.add_argument("--site", required=True); ap.add_argument("--phone-system", required=True)
    ap.add_argument("--gateway", required=True, help="upstream key=gateway id")
    a = ap.parse_args()
    export = json.loads(Path(a.export).read_text())
    key, _, gw = a.gateway.partition("=")
    try:
        imp, doc, plan, adoption, first, diff, understanding = run(export, a.site, a.phone_system, {key: gw})
    except CompileError as e:
        print("the document does not compile:", [(p.path, p.code, p.message) for p in e.problems])
        return 2
    out = Path(a.out)
    out.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.umask(0o077)
    (out / "document.json").write_text(json.dumps(doc.model_dump(mode="json"), indent=2, sort_keys=True))
    (out / "adoption.json").write_text(json.dumps({"objects": adoption.objects, "rows": adoption.rows, "ids": adoption.ids,
                                                   "meanings": adoption.meanings, "extras": imp.extras}, indent=1, sort_keys=True, default=str))
    (out / "diff.json").write_text(json.dumps(diff, indent=1, default=str))
    managed = {t: len(first.rows[t]) for t in fusionpbx.TABLES if first.rows[t]}
    lines = ["# Takeover import and compare", "",
             f"Objects adopted: {len(first.adopted)} of {len(first.meanings)} ({', '.join(sorted(first.adopted))})",
             f"Rows PhotonVox manages: {sum(managed.values())} {managed}",
             f"Hand-built extras (untouched, watched): {len(imp.extras)} rows", "",
             "## The first publish against the live rows", "",
             "IDENTICAL: no row added, none changed (the publish is a no-op)" if not diff else
             f"NOT IDENTICAL: {compare.summary(diff)[0]} new rows, {compare.summary(diff)[1]} changed rows (diff.json)", "",
             "## Regenerated from the document, against the live behavior (the understanding check)", ""]
    lines += [f"- {u}" for u in understanding] or ["- the same: every number, extension, voicemail box and menu key does what it does today"]
    lines += ["", "## What could not be expressed, and what happens to it", ""]
    lines += [f"- **{i.what}** ({i.outcome}): {i.detail}" for i in imp.report]
    (out / "report.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines[:12]))
    return 0 if not diff else 1


if __name__ == "__main__":
    sys.exit(main())
