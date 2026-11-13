from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Dict

import jwt
import pytest
from alembic import command
from alembic.config import Config
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from sqlalchemy import text

os.environ.setdefault("OIDC_ISSUER", "https://idp.test")
os.environ.setdefault("OIDC_AUDIENCE", "photonvox")
os.environ.setdefault("DIRECTORY_URL", "https://directory.test")
os.environ.setdefault("PLATFORM_ADMIN_SUBS", "staff")      # the directory sends no platform flag: staff are named in the configuration
os.environ.setdefault("DIRECTORY_NOTICE_SECRET", "notice-secret-for-tests-0123456789-abcdef")

from app import rls, sync  # noqa: E402
from app.config import settings  # noqa: E402
from app.db import SessionLocal, SystemSession, owner_engine  # noqa: E402
from app.deps import get_directory, get_verifier, resolve_throttle  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Base  # noqa: E402
from app.oidc import TokenVerifier  # noqa: E402
from app.routes import directory_notify  # noqa: E402
from tests.fake_directory import FakeDirectory  # noqa: E402

KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
VERIFIER = TokenVerifier(settings.oidc_issuer, settings.oidc_audience, ["RS256"], lambda _t: KEY.public_key())


@pytest.fixture(scope="session", autouse=True)
def schema():
    """Build the schema with the real migration (as the owner), so the tests also prove the migration works on the production image."""
    root = os.path.join(os.path.dirname(__file__), "..", "..")
    cfg = Config(os.path.join(root, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(root, "alembic"))
    command.upgrade(cfg, "head")
    yield


@pytest.fixture(autouse=True)
def clean(schema):
    with owner_engine.begin() as c:
        names = ", ".join(f'"{t.name}"' for t in Base.metadata.sorted_tables)
        c.execute(text(f"TRUNCATE {names} RESTART IDENTITY CASCADE"))
    resolve_throttle.hits.clear()
    directory_notify.notify_throttle.hits.clear()


@pytest.fixture()
def db():
    """For a test to look at the database as the system would (the all-access policies of vox_system)."""
    with SystemSession() as s:
        yield s


def as_person(person_id, platform_admin: bool = False):
    """A session the way the API sees one signed-in person: vox_app with that person's context."""
    s = SessionLocal()
    rls.as_person(s, person_id, platform_admin)
    return s


@pytest.fixture()
def fake() -> FakeDirectory:
    return FakeDirectory()


@pytest.fixture()
def client(fake):
    app.dependency_overrides[get_verifier] = lambda: VERIFIER
    app.dependency_overrides[get_directory] = lambda: fake.factory()
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def token_for(sub: str, **over) -> str:
    claims = {"sub": sub, "iss": settings.oidc_issuer, "aud": settings.oidc_audience, "exp": datetime.now(timezone.utc) + timedelta(minutes=5)}
    claims.update(over)
    return jwt.encode(claims, KEY, algorithm="RS256")


def auth(sub: str) -> Dict[str, str]:
    return {"Authorization": f"Bearer {token_for(sub)}"}


def pull(fake: FakeDirectory) -> sync.PullResult:
    """One sync pass from the fake, as the worker would run it."""
    with SystemSession() as s:
        return sync.pull(s, fake.factory(), datetime.now(timezone.utc))


class World:
    """Two customers of a partner in the fake directory, with sites and one person at each level, already synced into our copy.

    Cedar Works (A): sites a1, a2. owner `a-owner`, admin `a-admin`, site-limited admin `a-admin-s1` (a1 only), user `a-user`, user on a2 only `a-user-s2`.
    Birch Co (B): site b1; owner `b-owner`. `tech` is the partner's technician: admin of both through the partner grant (an integrator).
    `stranger` is in the directory with no access anywhere. `staff` is a platform admin.
    """

    def __init__(self, fake: FakeDirectory) -> None:
        self.fake = fake
        self.partner = str(uuid.uuid4())
        self.a = fake.add_org("Cedar Works", partner_id=self.partner)
        self.b = fake.add_org("Birch Co", partner_id=self.partner)
        self.a1 = fake.add_site(self.a, "cw-main", "Main office")
        self.a2 = fake.add_site(self.a, "cw-annex", "Annex")
        self.b1 = fake.add_site(self.b, "bc-shop", "Shop")
        self.people: Dict[str, str] = {}
        for sub, org, role, sites in (
            ("a-owner", self.a, "owner", None), ("a-admin", self.a, "admin", None), ("a-admin-s1", self.a, "admin", [self.a1]),
            ("a-user", self.a, "user", None), ("a-user-s2", self.a, "user", [self.a2]), ("b-owner", self.b, "owner", None),
        ):
            pid = fake.add_person(sub, name=sub.replace("-", " ").title())
            fake.grant(pid, org, role, sites)
            self.people[sub] = pid
        self.people["tech"] = fake.add_person("tech", name="Tech")
        for org in (self.a, self.b):
            fake.grant(self.people["tech"], org, "admin", source="partner")
        self.people["stranger"] = fake.add_person("stranger", name="Stranger")
        self.people["staff"] = fake.add_person("staff", name="Staff")
        assert pull(fake).ok

    def pid(self, sub: str) -> uuid.UUID:
        return uuid.UUID(self.people[sub])


@pytest.fixture()
def world(fake) -> World:
    return World(fake)
