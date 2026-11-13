"""The directory's notice endpoint, the worker's loop, and the start-up guard."""
import json
import time

import pytest
from sqlalchemy import select

from app import deps, worker
from app.db import engine, owner_engine
from app.main import app, refuse_a_database_role_that_bypasses_row_level_security
from app.models import SyncState, Tenant
import app.main as main

URL = "/directory/v1/notify"


def post(client, fake, **over):
    n = fake.notice()
    return client.post(URL, content=over.get("content", n["content"]), headers=over.get("headers", n["headers"]))


def test_a_genuine_notice_triggers_a_pull(client, fake, db):
    fake.add_org("Cedar Works")
    r = post(client, fake)
    assert r.status_code == 202 and r.json() == {}
    assert db.execute(select(Tenant.name)).scalars().all() == ["Cedar Works"]          # the background pull ran after the response
    assert db.get(SyncState, 1).cursor == fake.seq


def test_a_notice_is_answered_before_the_pull_so_a_slow_directory_cannot_hold_it_up(client, fake):
    assert post(client, fake).status_code == 202


@pytest.mark.parametrize("what", ["wrong secret", "stale", "tampered", "unsigned", "garbage"])
def test_a_forged_or_replayed_notice_is_401_and_pulls_nothing(client, fake, db, what):
    fake.add_org("Cedar Works")
    n = fake.notice()
    headers, content = dict(n["headers"]), n["content"]
    if what == "wrong secret":
        headers = fake.notice(secret="another-secret-0123456789abcdef0123456789")["headers"]
    elif what == "stale":
        headers = fake.notice(now=int(time.time()) - 3600)["headers"]
    elif what == "tampered":
        content = json.dumps({"product": "vox", "event": "changed", "x": 1}).encode()
    elif what == "unsigned":
        headers.pop("X-PhotonID-Signature")
    else:
        headers["X-PhotonID-Signature"] = "nonsense"
    r = client.post(URL, content=content, headers=headers)
    assert r.status_code == 401 and r.json() == {"detail": "Invalid signature"}
    assert db.execute(select(Tenant)).first() is None and fake.requests == []


def test_a_rotated_notice_secret_is_accepted_from_either(client, fake, monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "directory_notice_secret", "old-secret-0123456789abcdef0123456789,notice-secret-for-tests-0123456789-abcdef")
    assert post(client, fake).status_code == 202
    assert client.post(URL, content=fake.notice(secret="old-secret-0123456789abcdef0123456789")["content"],
                       headers=fake.notice(secret="old-secret-0123456789abcdef0123456789")["headers"]).status_code == 202


def test_without_a_configured_secret_every_notice_is_refused(client, fake, monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "directory_notice_secret", "")
    assert post(client, fake).status_code == 401


def test_with_no_directory_configured_a_good_notice_is_accepted_and_ignored(client, fake):
    app.dependency_overrides[deps.get_directory] = lambda: None
    assert post(client, fake).status_code == 202 and fake.requests == []


def test_notices_are_rate_limited(client, fake, monkeypatch):
    from app.routes import directory_notify
    monkeypatch.setattr(directory_notify, "notify_throttle", directory_notify.Throttle(limit=3, window_s=60))
    assert [post(client, fake).status_code for _ in range(4)] == [202, 202, 202, 429]


# ---- the worker ----

class Clock:
    def __init__(self): self.t = 1000.0
    def __call__(self): return self.t


@pytest.fixture()
def tick(fake, monkeypatch):
    monkeypatch.setattr(worker, "get_directory", lambda: fake.factory())
    clock, state = Clock(), {}
    def run(advance=0.0):
        clock.t += advance
        worker.tick(state, clock)
    return run


def test_the_first_tick_pulls_and_publishes_roles(fake, db, tick):
    fake.add_org("Cedar Works")
    tick()
    assert db.execute(select(Tenant.name)).scalars().all() == ["Cedar Works"] and fake.role_puts == 1


def test_later_ticks_do_nothing_until_the_interval_has_passed(fake, db, tick):
    tick()
    n = len(fake.requests)
    tick(10)
    assert len(fake.requests) == n
    fake.add_org("Late Org")
    tick(301)
    assert db.execute(select(Tenant.name)).scalars().all() == ["Late Org"]       # a lost notice is caught by the periodic pull
    assert fake.role_puts == 1                                                    # the catalog has not changed


def test_a_refused_catalog_is_retried_after_ten_minutes_not_every_tick(fake, tick):
    fake.fail_with = 500
    tick()
    assert fake.role_puts == 0
    fake.fail_with = None
    tick(60)
    assert fake.role_puts == 0
    tick(600)
    assert fake.role_puts == 1


def test_a_directory_that_is_down_does_not_stop_the_worker(fake, db, tick):
    fake.down = True
    tick()
    tick(400)
    fake.down = False
    fake.add_org("Back Again")
    tick(400)
    assert db.execute(select(Tenant.name)).scalars().all() == ["Back Again"]


def test_with_no_directory_the_worker_idles(monkeypatch):
    monkeypatch.setattr(worker, "get_directory", lambda: None)
    worker.tick({}, Clock())


def test_a_job_that_raises_is_logged_and_swallowed():
    def boom(db): raise RuntimeError("boom")
    assert worker.run_job("exploding job", boom) is None
    assert worker.run_job("fine job", lambda db: 7) == 7


def test_main_beats_a_heart_and_survives_a_tick_that_fails(monkeypatch, tmp_path):
    beats = tmp_path / "worker.ok"
    monkeypatch.setattr(worker, "HEARTBEAT_FILE", str(beats))
    calls = []
    def fake_sleep(s):
        calls.append(s)
        if len(calls) == 2:
            raise KeyboardInterrupt
    monkeypatch.setattr(worker.time, "sleep", fake_sleep)
    monkeypatch.setattr(worker, "tick", lambda state: None)
    with pytest.raises(KeyboardInterrupt):
        worker.main()
    assert beats.exists() and calls == [worker.TICK_S, worker.TICK_S]


def test_a_heartbeat_file_that_cannot_be_written_is_logged_not_fatal(monkeypatch, tmp_path):
    monkeypatch.setattr(worker, "HEARTBEAT_FILE", str(tmp_path / "no" / "such" / "dir" / "ok"))
    monkeypatch.setattr(worker, "tick", lambda state: None)
    monkeypatch.setattr(worker.time, "sleep", lambda s: (_ for _ in ()).throw(KeyboardInterrupt))
    with pytest.raises(KeyboardInterrupt):
        worker.main()


# ---- the app itself ----

def test_healthz_and_security_headers(client):
    r = client.get("/healthz")
    assert r.status_code == 200 and r.json() == {"ok": True}
    assert r.headers["x-content-type-options"] == "nosniff" and r.headers["referrer-policy"] == "no-referrer"


def test_a_value_the_database_refuses_is_a_422_not_a_500(client):
    from sqlalchemy.exc import DataError
    def bad():
        raise DataError("x", {}, Exception("NUL"))
    app.add_api_route("/__test_dataerror", bad)
    r = client.get("/__test_dataerror")
    assert r.status_code == 422 and "can't be stored" in r.json()["detail"]


def test_production_refuses_a_login_that_bypasses_row_level_security(monkeypatch):
    refuse_a_database_role_that_bypasses_row_level_security()           # development: nothing to check
    monkeypatch.setattr(main, "_prod", True)
    refuse_a_database_role_that_bypasses_row_level_security()           # the real app and system logins are restricted
    monkeypatch.setattr(main, "engine", owner_engine)
    with pytest.raises(RuntimeError, match="DATABASE_URL"):
        refuse_a_database_role_that_bypasses_row_level_security()
    monkeypatch.setattr(main, "engine", engine)
    monkeypatch.setattr(main, "system_engine", owner_engine)
    with pytest.raises(RuntimeError, match="SYSTEM_DATABASE_URL"):
        refuse_a_database_role_that_bypasses_row_level_security()


def test_production_configuration_problems_stop_the_app_from_starting(monkeypatch):
    import importlib
    from app.config import settings
    monkeypatch.setattr(settings, "environment", "production")
    with pytest.raises(RuntimeError, match="Unsafe production configuration"):
        importlib.reload(main)
    monkeypatch.setattr(settings, "environment", "development")
    importlib.reload(main)


def test_cors_is_only_added_when_origins_are_configured(monkeypatch):
    import importlib
    from fastapi.middleware.cors import CORSMiddleware
    from app.config import settings
    assert not any(m.cls is CORSMiddleware for m in main.app.user_middleware)
    monkeypatch.setattr(settings, "cors_origins", "https://vox.photonind.com")
    importlib.reload(main)
    assert any(m.cls is CORSMiddleware for m in main.app.user_middleware)
    monkeypatch.setattr(settings, "cors_origins", "")
    importlib.reload(main)


def test_the_worker_refuses_to_start_on_an_unsafe_production_configuration(monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "environment", "production")
    with pytest.raises(RuntimeError, match="Unsafe production configuration"):
        worker.main()


def test_readiness_needs_the_database(client, monkeypatch):
    assert client.get("/readyz").json() == {"ok": True}
