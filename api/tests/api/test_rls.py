"""Row-level security, tested at the database: these tests query the tables directly, with no tenant filter, the way a route that forgot one would.
Whatever the application code does, the database must still show each person only what is theirs."""
import uuid

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError, ProgrammingError

from app import audit, rls
from app.db import SessionLocal
from app.models import Access, AuditLog, Person, Site, Tenant
from tests.api.conftest import as_person


def ids(s, model, col="id"):
    return {str(getattr(r, col)) for r in s.execute(select(model)).scalars()}


# ---- the shape of the schema ----

def test_the_app_and_system_logins_are_restricted_roles(db):
    for url_role in ("vox_app", "vox_system"):
        r = db.execute(text("select rolsuper, rolbypassrls, rolcreatedb, rolcreaterole from pg_roles where rolname = :n"), {"n": url_role}).one()
        assert tuple(r) == (False, False, False, False), url_role
    with SessionLocal() as s:
        assert s.execute(text("select current_user")).scalar() == "vox_app"
    assert db.execute(text("select current_user")).scalar() == "vox_system"


def test_every_table_has_row_level_security_and_a_policy_for_the_system_role(db):
    rows = db.execute(text("select c.relname, c.relrowsecurity from pg_class c join pg_namespace n on n.oid = c.relnamespace "
                           "where n.nspname = 'public' and c.relkind = 'r'")).all()
    unprotected = sorted(n for n, on in rows if not on)
    assert unprotected == ["alembic_version"], f"a new table needs row-level security: {unprotected}"
    pols = {(t, r) for t, r in db.execute(text("select tablename, unnest(roles)::text from pg_policies where schemaname = 'public'")).all()}
    for table, _ in rows:
        if table != "alembic_version":
            assert (table, "vox_system") in pols, f"{table} has no policy for vox_system"


# What the app role may see of each table, by design: tables with no policy for it are the system's own.
SYSTEM_ONLY = {"sync_state", "alembic_version"}


def test_every_table_either_has_an_app_policy_or_is_deliberately_system_only(db):
    names = {r[0] for r in db.execute(text("select relname from pg_class c join pg_namespace n on n.oid = c.relnamespace where n.nspname = 'public' and c.relkind = 'r'"))}
    with_app_policy = {t for (t,) in db.execute(text("select distinct tablename from pg_policies where schemaname = 'public' and 'vox_app' = any(roles::text[])"))}
    assert names - with_app_policy == SYSTEM_ONLY


def test_every_table_with_a_tenant_column_is_covered_by_tenant_scoped_policies(db):
    tenant_tables = {r[0] for r in db.execute(text("select table_name from information_schema.columns where table_schema = 'public' and column_name = 'tenant_id'"))}
    assert {"site", "access", "audit_log"} <= tenant_tables
    for t in sorted(tenant_tables - SYSTEM_ONLY):
        using = " ".join(q or "" for (q,) in db.execute(text("select coalesce(qual, '') || ' ' || coalesce(with_check, '') from pg_policies "
                                                              "where schemaname = 'public' and tablename = :t and 'vox_app' = any(roles::text[])"), {"t": t}))
        assert "vx_" in using, f"{t}: a tenant table whose app policies do not call the tenant helpers"


# ---- who sees what ----

def test_a_session_that_has_not_said_who_it_is_sees_nothing(world):
    with SessionLocal() as s:
        for model in (Tenant, Site, Person, Access, AuditLog):
            assert s.execute(select(model)).first() is None, model.__name__


def test_the_app_role_cannot_read_the_syncs_own_table(world):
    with SessionLocal() as s:
        with pytest.raises(ProgrammingError):          # no privilege at all, not just no rows
            s.execute(text("select * from sync_state"))


def test_an_owner_sees_only_their_own_organization(world):
    with as_person(world.pid("a-owner")) as s:
        assert ids(s, Tenant) == {world.a}
        assert ids(s, Site) == {world.a1, world.a2}
    with as_person(world.pid("b-owner")) as s:
        assert ids(s, Tenant) == {world.b}
        assert ids(s, Site) == {world.b1}


def test_a_partner_technician_sees_every_customer_of_the_partner_and_nothing_else(world, fake):
    other = fake.add_org("Elm Ltd")                      # another partner's customer
    fake.add_site(other, "elm-hq", "HQ")
    from tests.api.conftest import pull
    assert pull(fake).ok
    with as_person(world.pid("tech")) as s:
        assert ids(s, Tenant) == {world.a, world.b}
        assert ids(s, Site) == {world.a1, world.a2, world.b1}


def test_a_stranger_sees_nothing_and_nobody_else(world):
    with as_person(world.pid("stranger")) as s:
        for model in (Tenant, Site, Access, AuditLog):
            assert s.execute(select(model)).first() is None, model.__name__
        assert ids(s, Person) == {world.people["stranger"]}          # themselves only


def test_a_site_limited_person_sees_only_their_sites_even_with_no_filter(world):
    with as_person(world.pid("a-admin-s1")) as s:
        assert ids(s, Site) == {world.a1}
    with as_person(world.pid("a-user-s2")) as s:
        assert ids(s, Site) == {world.a2}
    with as_person(world.pid("a-user")) as s:
        assert ids(s, Site) == {world.a1, world.a2}


def test_only_admins_and_owners_can_see_colleagues(world):
    team = {world.people[k] for k in ("a-owner", "a-admin", "a-admin-s1", "a-user", "a-user-s2", "tech")}
    for who in ("a-owner", "a-admin", "a-admin-s1"):
        with as_person(world.pid(who)) as s:
            assert ids(s, Person) == team, who
            assert {str(a.person_id) for a in s.execute(select(Access)).scalars()} == team, who
    with as_person(world.pid("tech")) as s:                                      # the integrator: both customers' people
        assert ids(s, Person) == team | {world.people["b-owner"]}
    for who in ("a-user", "a-user-s2"):
        with as_person(world.pid(who)) as s:
            assert ids(s, Person) == {world.people[who]}, who
            assert {str(a.person_id) for a in s.execute(select(Access)).scalars()} == {world.people[who]}, who


def test_an_expired_grant_stops_showing_the_organization_immediately(world, db):
    db.execute(text("update access set expires_at = now() - interval '1 minute' where person_id = :p"), {"p": world.people["a-admin"]})
    db.commit()
    with as_person(world.pid("a-admin")) as s:
        assert s.execute(select(Tenant)).first() is None
        assert s.execute(select(Site)).first() is None
        assert ids(s, Person) == {world.people["a-admin"]}          # no colleagues either
        assert len(s.execute(select(Access)).all()) == 1               # their own row, so /me can say it has lapsed


def test_the_app_role_cannot_write_the_directory_copy(world):
    for sql in ("insert into tenant (id, name) values (gen_random_uuid(), 'x')", "update tenant set name = 'hijacked'", "delete from tenant",
                "update site set name = 'x'", "update access set role = 'owner'", "update person set is_platform_admin = true", "delete from access"):
        with as_person(world.pid("a-owner")) as s:
            with pytest.raises(ProgrammingError):
                s.execute(text(sql))


# ---- the audit log ----

def test_the_audit_log_is_append_only_and_owner_readable(world, db):
    me = world.pid("a-admin")
    with as_person(me) as s:
        audit.record(s, actor_id=me, actor_label="A Admin", actor_source="direct", action="test.write", tenant_id=uuid.UUID(world.a))
        s.commit()
        assert s.execute(select(AuditLog)).first() is None                    # an admin wrote it but cannot read the log back
        for sql in ("update audit_log set action = 'x'", "delete from audit_log"):
            with pytest.raises(ProgrammingError):
                s.execute(text(sql))
            s.rollback()
    with as_person(world.pid("a-owner")) as s:
        assert [e.action for e in s.execute(select(AuditLog)).scalars()] == ["test.write"]
    with as_person(world.pid("b-owner")) as s:
        assert s.execute(select(AuditLog)).first() is None
    for sql in ("update audit_log set action = 'x'", "delete from audit_log"):             # not even the system role can rewrite history
        with pytest.raises(ProgrammingError):
            db.execute(text(sql))
        db.rollback()


def test_nobody_can_write_audit_rows_as_someone_else_or_into_another_organization(world):
    with as_person(world.pid("a-admin")) as s:
        with pytest.raises(DBAPIError):
            audit.record(s, actor_id=world.pid("a-owner"), actor_label="x", actor_source="direct", action="forged", tenant_id=uuid.UUID(world.a))
    with as_person(world.pid("a-admin")) as s:
        with pytest.raises(DBAPIError):
            audit.record(s, actor_id=world.pid("a-admin"), actor_label="x", actor_source="direct", action="into-b", tenant_id=uuid.UUID(world.b))


# ---- platform staff ----

def test_platform_staff_see_that_organizations_exist_but_not_inside_them(world):
    with as_person(world.pid("staff"), platform_admin=True) as s:
        assert ids(s, Tenant) == {world.a, world.b}
        for model in (Site, Access, AuditLog):
            assert s.execute(select(model)).first() is None, model.__name__
    with as_person(world.pid("staff"), platform_admin=False) as s:            # the flag is the session's, not the person's: no flag, no privilege
        assert s.execute(select(Tenant)).first() is None


def test_the_context_survives_a_commit(world):
    with as_person(world.pid("a-owner")) as s:
        s.execute(select(Tenant)).all()
        s.commit()
        assert ids(s, Tenant) == {world.a}              # a new transaction re-applies who we are


def test_setting_who_you_are_applies_to_the_transaction_already_open(world):
    s = SessionLocal()
    assert s.execute(select(Tenant)).first() is None             # a transaction is now open, as nobody
    rls.as_person(s, world.pid("a-owner"))
    assert ids(s, Tenant) == {world.a}                           # and the very next statement already sees as the owner
    s.close()
