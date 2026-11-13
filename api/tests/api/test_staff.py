"""Photon staff come from the PhotonID directory (decided 2026-11-13, as PhotonConsole does): the directory's platform administrators, and every
member, in any role, of partner Photon. PLATFORM_ADMIN_SUBS stays as a fallback for one release."""
import uuid

from sqlalchemy import text

from app.config import settings
from tests.api.conftest import auth, pull

PHOTON = str(uuid.uuid4())


def staff_events(db, pid):
    return db.execute(text("select detail from audit_log where action = 'directory.staff_flags' and target_id = :p order by at"), {"p": str(pid)}).scalars().all()


def test_a_platform_administrator_is_staff_with_no_organization(client, world):
    me = client.get("/me", headers=auth("staff")).json()
    assert me["is_staff"] is True and me["is_platform_admin"] is True and me["tenants"] == []
    assert client.get("/platform/organizations", headers=auth("staff")).status_code == 200


def test_a_member_of_partner_photon_in_any_role_is_staff_and_another_partners_owner_is_not(client, world, fake):
    fake.add_person("pia", name="Pia", partners=[{"partner_id": PHOTON, "slug": "photon", "role": "staff"}])
    fake.add_person("oscar", name="Oscar", partners=[{"partner_id": world.partner, "slug": "cedar-it", "role": "owner"}])
    pull(fake)
    pia = client.get("/me", headers=auth("pia")).json()
    assert pia["is_staff"] is True and pia["is_platform_admin"] is False
    assert client.get("/platform/organizations", headers=auth("pia")).status_code == 200
    assert client.get("/me", headers=auth("oscar")).json()["is_staff"] is False
    assert client.get("/platform/organizations", headers=auth("oscar")).status_code == 403


def test_staff_follow_the_directory_and_each_change_is_audited(client, world, fake, db):
    pid = fake.add_person("sam", name="Sam", partners=[{"partner_id": PHOTON, "slug": "photon", "role": "admin"}])
    fake.grant(pid, world.a, "user")
    pull(fake)
    assert client.get("/platform/organizations", headers=auth("sam")).status_code == 200
    fake.add_person("sam", name="Sam Renamed", id=pid, partners=[{"partner_id": PHOTON, "slug": "photon", "role": "admin"}])
    pull(fake)                                                                     # a rename changes no flag: no event
    fake.add_person("sam", name="Sam Renamed", id=pid)                             # left partner Photon
    pull(fake)
    me = client.get("/me", headers=auth("sam")).json()
    assert me["is_staff"] is False and [t["role"] for t in me["tenants"]] == ["user"]      # their own grant stays
    assert client.get("/platform/organizations", headers=auth("sam")).status_code == 403
    fake.add_person("sam", name="Sam Renamed", id=pid, platform_admin=True)
    pull(fake)
    assert client.get("/me", headers=auth("sam")).json()["is_platform_admin"] is True
    fake.remove_person(pid)
    pull(fake)                                                                     # removed from the directory: both flags go
    events = staff_events(db, pid)
    assert [(e["is_staff"], e["is_platform_admin"]) for e in events] == [(True, False), (False, False), (True, True), (False, False)]
    row = db.execute(text("select actor_label, actor_source, actor_person_id from audit_log where action = 'directory.staff_flags' limit 1")).one()
    assert tuple(row) == ("directory", "directory", None)


def test_a_document_without_the_fields_counts_as_neither(client, world, fake):
    pid = fake.add_person("old", name="Old")
    del fake.people[pid]["platform_admin"], fake.people[pid]["partners"]
    fake.ref.put("person", pid, fake.people[pid])
    pull(fake)
    assert client.get("/me", headers=auth("old")).json()["is_staff"] is False


def test_platform_admin_subs_is_still_a_fallback_for_one_release(client, world, fake, monkeypatch):
    fake.add_person("legacy", name="Legacy")
    pull(fake)
    assert client.get("/platform/organizations", headers=auth("legacy")).status_code == 403
    monkeypatch.setattr(settings, "platform_admin_subs", "legacy")
    assert client.get("/platform/organizations", headers=auth("legacy")).status_code == 200
    assert client.get("/me", headers=auth("legacy")).json()["is_staff"] is True
