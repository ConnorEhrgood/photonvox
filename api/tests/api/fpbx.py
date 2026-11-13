"""A database shaped like FusionPBX's, for tests: the builder's own tables and columns (from a build of the sample), the columns phone users set
that PhotonVox must leave alone, and the instance-wide tables. In a schema of its own on the test database."""
from __future__ import annotations

import os

from sqlalchemy import create_engine, text

from app.engine import fusionpbx
from app.engine.fusionpbx import KEYS, TABLES, Target
from tests.unit.test_compiler import plan

SCHEMA = "fpbx_test"
EXTRA = {"v_extensions": "forward_all_enabled boolean, do_not_disturb text"}     # set by phone users (feature codes), never by PhotonVox


def _type(col, values):
    if col.endswith("_uuid"):
        return "uuid"
    v = next((x for x in values if x is not None), None)
    return {bool: "boolean", int: "numeric", list: "json", dict: "json"}.get(type(v), "text")


def create():
    e = create_engine(os.environ["MIGRATE_DATABASE_URL"], connect_args={"options": f"-c search_path={SCHEMA}"})
    sample = fusionpbx.build(plan(), Target("0b5e8c1a-0000-4000-8000-000000000001", "0b5e8c1a-0000-4000-8000-0000000000d0",
                                            {"htc": "0b5e8c1a-0000-4000-8000-0000000000a1", "upstream-b": "0b5e8c1a-0000-4000-8000-0000000000a2"}))
    with e.begin() as c:
        c.execute(text(f"drop schema if exists {SCHEMA} cascade; create schema {SCHEMA}"))
        for t in TABLES:
            cols = {}
            for r in sample.rows[t]:
                for k in r:
                    cols.setdefault(k, []).append(r[k])
            cols.setdefault("forward_user_not_registered_destination", [None])
            body = ", ".join(f"{k} {_type(k, v)}" + (" primary key" if k == KEYS[t] else "") for k, v in cols.items())
            extra = (", " + EXTRA[t]) if t in EXTRA else ""
            c.execute(text(f"create table {t} ({body}{extra}, insert_date timestamptz, update_date timestamptz)"))
        c.execute(text("alter table v_dialplans alter column app_uuid type uuid using app_uuid::uuid"))
        c.execute(text("create table v_domains (domain_uuid uuid primary key, domain_name text, domain_enabled boolean, domain_description text, "
                       "insert_date timestamptz, update_date timestamptz)"))
        c.execute(text("create table v_gateways (gateway_uuid uuid primary key, domain_uuid uuid, gateway text, username text, password text, "
                       "proxy text, register boolean, expire_seconds numeric, retry_seconds numeric, distinct_to boolean, caller_id_in_from boolean, "
                       "supress_cng boolean, contact_in_ping boolean, channels numeric, context text, profile text, enabled boolean, description text, "
                       "insert_date timestamptz, update_date timestamptz)"))
        c.execute(text("create table v_default_settings (default_setting_uuid uuid primary key, default_setting_category text, "
                       "default_setting_subcategory text, default_setting_name text, default_setting_value text, default_setting_enabled boolean, "
                       "default_setting_description text)"))
        for sub in ("smtp_host", "smtp_port", "smtp_secure", "smtp_auth", "smtp_username", "smtp_from"):     # an install has these, not all
            c.execute(text("insert into v_default_settings values (gen_random_uuid(), 'email', :s, 'text', '', false, '')"), {"s": sub})
        c.execute(text("create table v_access_controls (access_control_uuid uuid primary key, access_control_name text)"))
        c.execute(text("create table v_access_control_nodes (access_control_node_uuid uuid primary key, access_control_uuid uuid, node_type text, "
                       "node_cidr text, node_description text, insert_date timestamptz, update_date timestamptz)"))
    return e


def drop(e):
    with e.begin() as c:
        c.execute(text(f"drop schema {SCHEMA} cascade"))
    e.dispose()
