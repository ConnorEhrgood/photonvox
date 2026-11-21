"""The directory copy: the reference client's pull applied by our `DbProjection`. Everything runs against the reference client's fake directory and ends by
comparing our tables with what it says exists. (The client's own behavior - paging, 409 resets, ordering - is tested upstream with it.)"""
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from app import roles, sync
from app.db import SystemSession
from app.directory import projection
from app.directory.projection import DbProjection
from app.models import Access, Person, Site, SyncState, Tenant
from photonid_directory_client import DirectoryError
from tests.api.conftest import pull
from tests.fake_directory import FakeDirectory

NOW = datetime(2026, 10, 30, 12, 0, tzinfo=timezone.utc)


def snapshot(db):
    """Our copy as plain data, soft-removed rows left out."""
    db.rollback()
    return {
        "tenant": {str(t.id): (t.name, t.status, t.home_region, str(t.partner_id) if t.partner_id else None)
                   for t in db.execute(select(Tenant).where(Tenant.status != "removed")).scalars()},
        "site": {str(s.id): (str(s.tenant_id), s.slug, s.name) for s in db.execute(select(Site).where(Site.status == "active")).scalars()},
        "person": {str(p.id): (p.sub, p.name) for p in db.execute(select(Person).where(Person.active.is_(True))).scalars()},
        "access": {f"{a.person_id}:{a.tenant_id}": (a.role, a.scope_all, sorted(str(s) for s in a.site_ids), a.source, a.expires_at.isoformat() if a.expires_at else None)
                   for a in db.execute(select(Access)).scalars()},
    }


def expected(fake: FakeDirectory):
    """What the directory says exists, in the same shape."""
    st = fake.ref.state()
    out = {"tenant": {}, "site": {}, "person": {}, "access": {}}
    for k, d in st["organization"].items():
        if d["status"] != "archived":
            out["tenant"][k] = (d["name"], d["status"], d["home_region"], d["partner_id"])
    for k, d in st["site"].items():
        out["site"][k] = (d["organization_id"], d["slug"], d["name"])
    for k, d in st["person"].items():
        out["person"][k] = (d["sub"], d["name"])
    for k, d in st["access"].items():
        sc = d["scope"]
        exp = datetime.fromisoformat(d["expires_at"].replace("Z", "+00:00")).isoformat() if d["expires_at"] else None
        out["access"][k] = (d["role"], sc["type"] == "all", sorted(sc.get("site_ids", [])), d["source"], exp)
    return out


def small(fake):
    org = fake.add_org("Cedar Works", partner_id=str(uuid.uuid4()))
    site = fake.add_site(org, "cw-main", "Main plant")
    ann = fake.add_person("ann", "Ann")
    fake.grant(ann, org, "owner")
    return org, site, ann


def test_a_first_pull_is_a_snapshot_and_ends_identical_to_the_directory(fake, db):
    small(fake)
    r = pull(fake)
    assert r.ok and r.applied == 4 and r.cursor == fake.seq
    assert snapshot(db) == expected(fake)


def test_incremental_changes_follow_the_cursor(fake, db):
    org, site, ann = small(fake)
    pull(fake)
    site2 = fake.add_site(org, "cw-yard", "Yard")
    bob = fake.add_person("bob", "Bob")
    fake.grant(bob, org, "user", [site2], source="partner", expires_at="2099-01-01T00:00:00+00:00")
    r = pull(fake)
    assert r.ok and r.applied == 3
    assert snapshot(db) == expected(fake)


def test_replaying_the_whole_feed_changes_nothing(fake, db):
    small(fake)
    pull(fake)
    before = snapshot(db)
    with SystemSession() as s:
        s.get(SyncState, 1).cursor = 0                      # as if the cursor were lost: a second snapshot over what we hold
        s.commit()
    assert pull(fake).ok
    assert snapshot(db) == before == expected(fake)


def test_a_lost_notice_only_delays_a_change(fake, db):
    org, site, ann = small(fake)
    pull(fake)
    fake.grant(ann, org, "admin")                          # no notice sent; the next periodic pull still finds it
    pull(fake)
    assert snapshot(db)["access"][f"{ann}:{org}"][0] == "admin"


def test_a_snapshot_removes_what_the_directory_no_longer_has(fake, db):
    org, site, ann = small(fake)
    bob = fake.add_person("bob", "Bob")
    fake.grant(bob, org, "user")
    pull(fake)
    fake.revoke(bob, org)
    fake.remove_person(bob)
    fake.remove_site(site)
    fake.compact()                                         # the removals are forgotten: only a snapshot can tell us
    with SystemSession() as s:
        s.get(SyncState, 1).cursor = fake.seq - 1
        s.commit()
    assert pull(fake).ok
    assert snapshot(db) == expected(fake)


def test_an_organization_that_is_no_longer_entitled_loses_all_access_even_if_only_it_is_removed(fake, db):
    org, site, ann = small(fake)
    pull(fake)
    fake.unentitle(org, cascade=False)
    pull(fake)
    snap = snapshot(db)
    assert snap["tenant"] == {} and snap["access"] == {} and snap["site"] == {}
    assert db.get(Tenant, uuid.UUID(org)).status == "removed"          # the row stays: history points at it


def test_an_organization_that_comes_back_is_active_again(fake, db):
    org, site, ann = small(fake)
    pull(fake)
    fake.unentitle(org)
    pull(fake)
    fake.add_org("Cedar Works", id=org)
    fake.add_site(org, "cw-main", "Main plant", id=site)
    fake.grant(ann, org, "owner")
    pull(fake)
    assert snapshot(db) == expected(fake)


def test_a_person_removed_from_the_directory_is_deactivated_and_loses_their_access(fake, db):
    org, site, ann = small(fake)
    pull(fake)
    fake.remove_person(ann)
    pull(fake)
    assert db.execute(select(Person.active).where(Person.id == uuid.UUID(ann))).scalar() is False
    assert snapshot(db)["access"] == {}


def test_a_person_the_directory_calls_disabled_is_inactive(fake, db):
    org, site, ann = small(fake)
    fake.add_person("ann", "Ann", id=ann, status="disabled")
    pull(fake)
    assert db.get(Person, uuid.UUID(ann)).active is False


def test_an_archived_organization_and_an_inactive_site_are_not_served(fake, db):
    org = fake.add_org("Old Co", status="archived")
    site = fake.add_site(org, "old-main", "Main", status="inactive")
    pull(fake)
    assert db.get(Tenant, uuid.UUID(org)).status == "removed" and db.get(Site, uuid.UUID(site)).status == "removed"


def test_a_suspended_organization_is_suspended(fake, db):
    org = fake.add_org("Late Co", status="suspended")
    pull(fake)
    assert db.get(Tenant, uuid.UUID(org)).status == "suspended"


def test_the_others_of_an_access_are_kept(fake, db):
    org = fake.add_org("Cedar Works")
    s1, s2 = fake.add_site(org, "a", "A"), fake.add_site(org, "b", "B")
    pat = fake.add_person("pat", "Pat")
    fake.grant(pat, org, "admin", [s1], others=[{"role": "user", "scope": {"type": "all"}, "source": "partner"}])
    pull(fake)
    a = db.get(Access, (uuid.UUID(pat), uuid.UUID(org)))
    assert a.role == "admin" and not a.scope_all and a.others == [{"role": "user", "scope": {"type": "all"}, "source": "partner"}]


def test_a_role_we_do_not_have_is_no_access(fake, db):
    org, site, ann = small(fake)
    bob = fake.add_person("bob", "Bob")
    fake.grant(bob, org, "technician")                      # not one of ours: retired, or a newer catalog
    fake.grant(ann, org, "owner", others=[{"role": "technician", "scope": {"type": "all"}, "source": "partner"}])
    pull(fake)
    assert db.get(Access, (uuid.UUID(bob), uuid.UUID(org))) is None
    assert db.get(Access, (uuid.UUID(ann), uuid.UUID(org))).others == []


def test_a_directory_that_is_down_keeps_the_copy_and_the_cursor_and_records_why(fake, db):
    small(fake)
    pull(fake)
    fake.ref.fail_next = [503]
    r = pull(fake)
    assert not r.ok and "DirectoryError" in r.error
    st = db.get(SyncState, 1)
    db.refresh(st)
    assert st.cursor == fake.seq and "503" in st.last_error and st.last_pull_at is not None
    assert pull(fake).ok
    db.expire_all()
    assert db.get(SyncState, 1).last_error is None


def test_a_wrong_credential_is_an_error_not_a_crash(fake, db):
    small(fake)
    fake.ref.credential = "somebody.else"
    r = sync.pull(db, lambda p, timeout_s=None: fake.ref.client(p), NOW)
    assert r.ok                                             # the client holds its own credential; flip the server's
    fake.ref.credential = "changed.after"
    c = fake.ref.client(DbProjection(db))
    fake.ref.credential = "rotated.away"
    r = sync.pull(db, lambda p, timeout_s=None: c.__class__(c.base_url, "wrong.credential", p, http=c.http), NOW)
    assert not r.ok and "AuthError" in r.error


def test_a_malformed_document_rolls_the_whole_batch_back_and_the_cursor_stays(fake, db):
    org, site, ann = small(fake)
    pull(fake)
    cursor = fake.seq
    fake.add_person("eve", "Eve")
    fake.ref.put("access", "x", {"person_id": "not-a-uuid", "organization_id": org, "role": "user", "scope": {"type": "all"}, "source": "direct",
                                 "expires_at": None, "others": []})
    r = pull(fake)
    assert not r.ok and "BadDocument" in r.error
    assert db.get(SyncState, 1).cursor == cursor and snapshot(db)["person"].keys() == {ann}


@pytest.mark.parametrize("doc,word", [
    ({"expires_at": "tomorrow"}, "not a time"),
    ({"scope": {"type": "sites", "site_ids": ["nope"]}}, "not a UUID"),
    ({"others": [{"role": "user", "scope": {"type": "sites", "site_ids": ["nope"]}, "source": "direct"}]}, "not a UUID"),
])
def test_bad_documents_are_named(fake, db, doc, word):
    org, site, ann = small(fake)
    good = {"person_id": ann, "organization_id": org, "role": "user", "scope": {"type": "all"}, "source": "direct", "expires_at": None, "others": []}
    fake.ref.put("access", f"{ann}:{org}", {**good, **doc})
    r = pull(fake)
    assert not r.ok and word in r.error


def test_only_one_pull_runs_at_a_time(fake, db):
    small(fake)
    from sqlalchemy import text
    with SystemSession() as holder:
        holder.execute(text("select pg_advisory_xact_lock(:k)"), {"k": sync.LOCK_KEY})
        r = pull(fake)
        assert r.ok and r.busy and r.applied == 0
    assert pull(fake).applied == 4


def test_resolve_brings_in_one_person_and_their_organizations(fake, db):
    org, site, ann = small(fake)
    with SystemSession() as s:
        assert sync.resolve(s, fake.factory(), "ann", 3.0) is True
    assert snapshot(db) == expected(fake)


def test_resolve_for_an_unknown_sub_says_so(fake, db):
    small(fake)
    with SystemSession() as s:
        assert sync.resolve(s, fake.factory(), "nobody", 3.0) is False
    assert snapshot(db)["person"] == {}


def test_resolve_for_a_person_with_no_photonvox_access_knows_the_person_only(fake, db):
    org, site, ann = small(fake)
    fake.add_person("lone", "Lone")
    with SystemSession() as s:
        assert sync.resolve(s, fake.factory(), "lone", 3.0) is True


def test_resolve_when_the_directory_is_down_raises(fake, db):
    small(fake)
    fake.ref.fail_next = [503]
    with SystemSession() as s, pytest.raises(DirectoryError):
        sync.resolve(s, fake.factory(), "ann", 3.0)


def test_resolve_when_the_pull_afterwards_fails_raises_too(fake, db):
    small(fake)
    fake.ref.fail_next = [200, 503]                          # not a usable answer for resolve? use a failing pull instead
    fake.ref.fail_next = []
    calls = []

    def factory(projection, timeout_s=None):
        client = fake.ref.client(projection)
        calls.append(1)
        if len(calls) == 2:
            fake.ref.fail_next = [503]
        return client
    with SystemSession() as s, pytest.raises(DirectoryError):
        sync.resolve(s, factory, "ann", 3.0)


def test_the_role_catalog_is_published_once_and_again_only_when_it_changes(fake, db, monkeypatch):
    with SystemSession() as s:
        assert sync.publish_roles(s, fake.factory()) is True
    assert [r["key"] for r in fake.ref.published] == ["user", "admin", "owner"]
    with SystemSession() as s:
        assert sync.publish_roles(s, fake.factory()) is False
    monkeypatch.setitem(roles.CAPABILITIES, "vox.number.port", False)         # a capability stops being sensitive: the published catalog differs
    with SystemSession() as s:
        assert sync.publish_roles(s, fake.factory()) is True


def test_a_refused_catalog_is_retried_not_remembered_as_sent(fake, db):
    fake.ref.fail_next = [422]
    with SystemSession() as s, pytest.raises(DirectoryError):
        sync.publish_roles(s, fake.factory())
    with SystemSession() as s:
        assert sync.publish_roles(s, fake.factory()) is True


def test_removing_what_was_never_held_is_not_an_error(db):
    p = DbProjection(db)
    for kind, key in (("organization", str(uuid.uuid4())), ("site", str(uuid.uuid4())), ("person", str(uuid.uuid4())), ("access", f"{uuid.uuid4()}:{uuid.uuid4()}")):
        p.remove(kind, key)
    assert list(p.known_keys("organization")) == [] and list(p.known_keys("access")) == []


def test_a_bad_id_in_a_removal_is_named(db):
    with pytest.raises(projection.BadDocument):
        DbProjection(db).remove("site", "not-a-uuid")


def test_a_projection_with_no_state_row_starts_at_zero(db):
    from app.db import owner_engine
    with owner_engine.begin() as c:
        c.execute(SyncState.__table__.delete())
    p = DbProjection(db)
    assert p.get_cursor() == 0
    p.set_cursor(7)
    assert p.get_cursor() == 7


def test_a_change_our_copy_cannot_take_is_recorded_not_only_logged(fake, db):
    """Audit VOX-A-11: a database error while applying the feed rolls back, keeps the cursor and is written to sync_state like any failure."""
    from sqlalchemy.exc import IntegrityError
    assert pull(fake).ok
    before = db.get(SyncState, 1).cursor

    class Broken:
        def sync_once(self):
            raise IntegrityError("insert into access ...", {}, Exception("duplicate key value violates unique constraint\nDETAIL: secret row"))
    with SystemSession() as s:
        result = sync.pull(s, lambda _projection, **_kw: Broken(), datetime.now(timezone.utc))
    assert not result.ok and result.error.startswith("IntegrityError")
    db.expire_all()
    st = db.get(SyncState, 1)
    assert st.cursor == before and st.last_error.startswith("IntegrityError") and "secret row" not in st.last_error
