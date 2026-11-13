"""Who is Photon staff, from the directory's person document (directory/projection.py `staff_flags`)."""
import pytest

from app.directory.projection import staff_flags

PHOTON = {"partner_id": "p0", "slug": "photon", "role": "staff"}


@pytest.mark.parametrize("doc,want", [
    ({}, (False, False)),                                                                          # a document from before the fields existed
    ({"platform_admin": False, "partners": []}, (False, False)),
    ({"platform_admin": True, "partners": []}, (True, True)),                                      # a platform administrator is staff too
    ({"platform_admin": False, "partners": [PHOTON]}, (True, False)),                              # any member of partner Photon...
    ({"platform_admin": False, "partners": [{**PHOTON, "role": "owner"}]}, (True, False)),         # ...in any role
    ({"platform_admin": False, "partners": [{"partner_id": "p1", "slug": "cedar-it", "role": "owner"}]}, (False, False)),   # another partner's owner is not
    ({"platform_admin": False, "partners": [{"partner_id": "p1", "slug": "cedar-it", "role": "owner"}, PHOTON]}, (True, False)),
    ({"platform_admin": "true", "partners": "photon"}, (False, False)),                            # malformed: neither, never a guess
    ({"platform_admin": None, "partners": ["photon", None]}, (False, False)),
])
def test_staff_are_platform_admins_and_partner_photons_members(doc, want):
    assert staff_flags(doc) == want
