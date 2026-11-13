from app import roles


def test_ranks_rise_from_user_to_owner():
    assert [roles.rank(r) for r in ("user", "admin", "owner")] == [1, 2, 3]


def test_the_catalog_is_what_the_directory_is_sent():
    cat = roles.catalog()
    assert [r["key"] for r in cat["roles"]] == ["user", "admin", "owner"]            # lowest rank first
    assert {r["key"]: r["site_limitable"] for r in cat["roles"]} == {"user": True, "admin": True, "owner": False}
    assert all(r["capabilities"] == sorted(r["capabilities"]) for r in cat["roles"])               # stable output, stable hash
    assert all(set(r["sensitive_capabilities"]) <= set(r["capabilities"]) for r in cat["roles"])
    owner = next(r for r in cat["roles"] if r["key"] == "owner")
    assert {"vox.number.port", "vox.number.release", "vox.site.emergency", "vox.forwarding.external"} <= set(owner["sensitive_capabilities"])
    assert "vox.phone_system.build" not in owner["sensitive_capabilities"]


def test_each_role_includes_everything_below_it():
    assert roles.ROLES["user"].capabilities < roles.ROLES["admin"].capabilities < roles.ROLES["owner"].capabilities


def test_an_integrator_admin_can_build_and_enroll_but_not_give_numbers_away_or_change_the_calling_policy():
    admin = roles.ROLES["admin"].capabilities
    assert {"vox.phone_system.build", "vox.phone.enroll", "vox.site.emergency", "vox.number.manage"} <= admin
    assert not {"vox.number.port", "vox.number.release", "vox.calling.policy", "vox.audit.view"} & admin


def test_a_user_manages_only_their_own_phone():
    assert roles.ROLES["user"].capabilities == {"vox.self.manage"}


def test_the_hash_is_stable_and_changes_with_the_catalog(monkeypatch):
    first = roles.catalog_hash()
    assert first == roles.catalog_hash() and len(first) == 64
    monkeypatch.setitem(roles.CAPABILITIES, "vox.number.port", False)
    assert roles.catalog_hash() != first
