#!/usr/bin/env python3
"""Snapshot FusionPBX's tables and diff two snapshots: what a page (or the adapter) actually wrote. Runs on the staging engine as root.

    snapshot.py save <name>          every v_* table, by primary key, to /root/spike/<name>.json
    snapshot.py diff <a> <b>         rows added, removed and changed (changed: only the columns that differ)

Staging only: its rows are test data. Columns that hold secrets are shown as "(secret, N chars)" so a diff can be pasted into notes.
"""
import json
import os
import subprocess
import sys

DIR = "/root/spike"
SECRET = ("password", "api_key", "salt", "token", "secret")
NOISY = {"v_user_logs", "v_database_transactions"}     # summarized as counts


def psql(sql):
    out = subprocess.run(["sudo", "-u", "postgres", "psql", "-d", "fusionpbx", "-qtAX", "-c", sql], check=True, capture_output=True, text=True)
    return out.stdout.strip()


def tables():
    rows = psql("select t.table_name, coalesce(string_agg(k.column_name, ',' order by k.ordinal_position), '') from information_schema.tables t "
                "left join information_schema.table_constraints c on c.table_name = t.table_name and c.constraint_type = 'PRIMARY KEY' "
                "left join information_schema.key_column_usage k on k.constraint_name = c.constraint_name and k.table_name = t.table_name "
                "where t.table_schema = 'public' and t.table_name like 'v\\_%' and t.table_type = 'BASE TABLE' group by 1 order by 1")
    return [r.split("|") for r in rows.splitlines()]


def save(name):
    snap = {}
    for table, pk in tables():
        data = json.loads(psql(f"select coalesce(json_agg(t), '[]') from {table} t") or "[]")
        keys = pk.split(",") if pk else None
        snap[table] = {("|".join(str(r[k]) for k in keys) if keys else json.dumps(r, sort_keys=True)): r for r in data}
    os.makedirs(DIR, exist_ok=True)
    with open(f"{DIR}/{name}.json", "w") as f:
        json.dump(snap, f)
    print(f"saved {name}: {sum(len(v) for v in snap.values())} rows in {len(snap)} tables")


def show(col, val):
    if val is not None and any(s in col for s in SECRET):
        return f"(secret, {len(str(val))} chars)"
    return json.dumps(val)


def diff(a, b):
    A, B = (json.load(open(f"{DIR}/{n}.json")) for n in (a, b))
    for table in sorted(set(A) | set(B)):
        old, new = A.get(table, {}), B.get(table, {})
        added = [k for k in new if k not in old]
        removed = [k for k in old if k not in new]
        changed = [k for k in new if k in old and new[k] != old[k]]
        if not (added or removed or changed):
            continue
        if table in NOISY:
            print(f"== {table}: +{len(added)} -{len(removed)} ~{len(changed)}")
            continue
        print(f"== {table}")
        for k in added:
            print(f"  + {k}")
            for col, val in new[k].items():
                if val not in (None, ""):
                    print(f"      {col} = {show(col, val)}")
        for k in removed:
            print(f"  - {k}")
        for k in changed:
            print(f"  ~ {k}")
            for col in new[k]:
                if new[k][col] != old[k].get(col):
                    print(f"      {col}: {show(col, old[k].get(col))} -> {show(col, new[k][col])}")


if __name__ == "__main__":
    {"save": lambda: save(sys.argv[2]), "diff": lambda: diff(sys.argv[2], sys.argv[3])}[sys.argv[1]]()
