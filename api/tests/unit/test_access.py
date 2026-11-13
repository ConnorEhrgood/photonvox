"""Authorization, as a table: role x scope. Pure functions, so the whole matrix runs without a database."""
import itertools
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app import access
from app.access import Entry, Grant
from app.roles import CAPABILITIES, ROLES

NOW = datetime(2026, 11, 13, 12, 0, tzinfo=timezone.utc)
S1, S2, S3 = uuid.UUID(int=1), uuid.UUID(int=2), uuid.UUID(int=3)


def g(role, sites=None, **kw):
    return Grant(role, scope_all=sites is None, site_ids=frozenset(sites or ()), **kw)


# What ARCHITECTURE §7 says each role can do, written out independently of app/roles.py so a slip there is caught.
EXPECTED = {"user": {"vox.self.manage"}}
EXPECTED["admin"] = EXPECTED["user"] | {"vox.phone_system.view", "vox.phone_system.build", "vox.phone.enroll", "vox.phone.control", "vox.site.emergency",
                                        "vox.number.manage", "vox.forwarding.external", "vox.console.manage", "vox.members.view"}
EXPECTED["owner"] = EXPECTED["admin"] | {"vox.number.port", "vox.number.release", "vox.calling.policy", "vox.audit.view"}


@pytest.mark.parametrize("role", list(EXPECTED))
def test_each_role_has_exactly_the_capabilities_the_architecture_gives_it(role):
    assert set(ROLES[role].capabilities) == EXPECTED[role]


@pytest.mark.parametrize("role,cap", list(itertools.product(EXPECTED, sorted(CAPABILITIES))))
def test_role_by_capability_matrix(role, cap):
    assert access.allowed(g(role), cap, NOW) is (cap in EXPECTED[role])


def test_only_owner_is_not_site_limitable():
    assert {k for k, r in ROLES.items() if not r.site_limitable} == {"owner"}


@pytest.mark.parametrize("role", ["user", "admin"])
def test_a_site_limited_grant_works_on_its_sites_and_nowhere_else(role):
    grant = g(role, [S1, S2])
    for cap in EXPECTED[role]:
        assert access.allowed(grant, cap, NOW, site_id=S1)
        assert access.allowed(grant, cap, NOW, site_id=S2)
        assert not access.allowed(grant, cap, NOW, site_id=S3)
        assert access.allowed(grant, cap, NOW)          # a role question with no site
    assert not access.allowed(grant, "vox.audit.view", NOW)    # not this role's, site or not


def test_a_whole_organization_grant_reaches_every_site():
    assert access.allowed(g("admin"), "vox.phone.enroll", NOW, site_id=S3)


def test_an_expired_grant_allows_nothing_and_an_unexpired_one_works():
    assert not access.allowed(g("owner", expires_at=NOW - timedelta(seconds=1)), "vox.self.manage", NOW)
    assert not access.allowed(g("owner", expires_at=NOW), "vox.self.manage", NOW)            # the instant itself is past
    assert access.allowed(g("owner", expires_at=NOW + timedelta(seconds=1)), "vox.self.manage", NOW)
    assert access.capabilities(g("owner", expires_at=NOW), NOW) == frozenset()


def test_a_role_this_build_does_not_know_allows_nothing():
    assert not access.is_active(g("operator"), NOW)
    assert not access.allowed(g("operator"), "vox.self.manage", NOW)
    assert access.capabilities(g("operator"), NOW) == frozenset()


def test_the_strongest_entry_that_covers_a_site_decides_and_scopes_are_never_merged():
    # A site-limited admin (S1) who is also a whole-organization user through the partner: admin on S1, user elsewhere (suite §5).
    grant = Grant("admin", scope_all=False, site_ids=frozenset({S1}), others=(Entry("user"),))
    assert access.role_at(grant, S1) == "admin"
    assert access.role_at(grant, S2) == "user"
    assert access.allowed(grant, "vox.phone.enroll", NOW, site_id=S1)
    assert not access.allowed(grant, "vox.phone.enroll", NOW, site_id=S2)
    assert access.allowed(grant, "vox.self.manage", NOW, site_id=S2)
    assert grant.reach_all and access.visible_site_ids(grant, {S1, S2, S3}) == {S1, S2, S3}


def test_no_entry_covering_a_site_means_no_role_there_and_unknown_roles_in_others_are_skipped():
    grant = Grant("user", scope_all=False, site_ids=frozenset({S1}), others=(Entry("operator", False, frozenset({S2})), Entry("admin", False, frozenset({S3}))))
    assert access.role_at(grant, S2) is None
    assert access.role_at(grant, S3) == "admin"
    assert access.role_at(grant, S1) == "user"
    assert not access.allowed(grant, "vox.self.manage", NOW, site_id=S2)


def test_a_weaker_entry_never_lowers_a_stronger_one():
    grant = Grant("admin", others=(Entry("user"),))
    assert access.role_at(grant, S1) == "admin"


def test_capabilities_are_everything_allowed_somewhere():
    grant = Grant("user", scope_all=False, site_ids=frozenset({S1}), others=(Entry("admin", False, frozenset({S2})), Entry("operator")))
    assert access.capabilities(grant, NOW) == EXPECTED["admin"]


def test_visible_sites_and_reach():
    grant = g("admin", [S1, S2])
    assert not grant.reach_all and grant.reach_sites == {S1, S2}
    assert access.visible_site_ids(grant, {S1, S3}) == {S1}
    assert access.visible_site_ids(g("user"), {S1, S3}) == {S1, S3}


def test_who_sees_whom_in_a_people_list():
    assert access.sees_member(g("admin"), g("user", [S3]))                 # a whole-organization admin sees everyone
    assert access.sees_member(g("admin", [S1]), g("owner"))                # everyone sees whole-organization people
    assert access.sees_member(g("admin", [S1]), g("user", [S1, S2]))       # overlapping sites
    assert not access.sees_member(g("admin", [S1]), g("user", [S2]))


def test_a_grant_is_read_from_its_row_with_its_others():
    row = SimpleNamespace(role="admin", scope_all=False, site_ids=[S1], source="partner", expires_at=None,
                          others=[{"role": "user", "scope": {"type": "all"}, "source": "direct"},
                                  {"role": "user", "scope": {"type": "sites", "site_ids": [str(S2)]}, "source": "direct"}])
    grant = Grant.from_row(row)
    assert grant.source == "partner" and grant.site_ids == {S1}
    assert grant.others == (Entry("user"), Entry("user", False, frozenset({S2})))
    empty = Grant.from_row(SimpleNamespace(role="user", scope_all=True, site_ids=None, source="direct", expires_at=None, others=None))
    assert empty.others == () and empty.site_ids == frozenset()
