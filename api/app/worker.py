"""Background jobs. `python -m app.worker` runs them; keep it a single process.

Now: keep the directory copy current (a periodic pull, so a lost notice delays a change and never loses it) and publish our role catalog to the
directory; publish queued phone-system versions (with the post-publish check); look for hand edits on the engines; email open 911 address
requests to carriers. Later steps add engine and GDMS status collection, the fraud breaker and enrollment retries.
"""
from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from typing import Any, Callable

from app import emergency, sync
from app.config import settings
from app.db import SystemSession
from app.deps import get_directory
from app.engine import service
from app.models import utcnow

log = logging.getLogger("photonvox.worker")

TICK_S = 15
PUBLISH_RETRY_S = 600
DRIFT_EVERY_S = 300
HEARTBEAT_FILE = os.environ.get("WORKER_HEARTBEAT_FILE", "/tmp/worker.ok")   # the container healthcheck reads its age


def run_job(what: str, job: Callable[[Any], Any]) -> Any:
    """Run one job in a session of its own. A job that fails, or leaves its transaction broken, cannot take the next job down with it."""
    with SystemSession() as db:
        try:
            return job(db)
        except Exception:  # noqa: BLE001 - housekeeping must never take the worker down
            log.exception("%s failed", what)
            db.rollback()
            return None


def engine_jobs(state: dict, now: float, connect: service.Connect = service.connect) -> None:
    """Publishing comes first and every tick (an integrator is waiting); hand edits every few minutes; carrier requests every tick."""
    interrupted = run_job("interrupted publishes", service.recover_interrupted)
    if interrupted:
        log.warning("marked %d interrupted publish(es) failed", interrupted)
    published = run_job("publish", lambda db: service.publish_queued(db, connect))
    if published:
        log.info("published %d version(s)", published)
    run_job("carrier requests", emergency.send_open)
    if now - state.get("drift", float("-inf")) >= DRIFT_EVERY_S:
        state["drift"] = now
        run_job("drift", lambda db: service.check_all_drift(db, connect))


def tick(state: dict, clock: Callable[[], float] = time.monotonic, connect: service.Connect = service.connect) -> None:
    """One pass: whatever is due. `state` remembers when each job last ran."""
    now = clock()
    engine_jobs(state, now, connect)
    directory = get_directory()
    if directory is None:
        return
    if now - state.get("pull", float("-inf")) >= settings.directory_pull_every_s:
        state["pull"] = now
        result = run_job("directory pull", lambda db: sync.pull(db, directory, utcnow()))
        if result is not None and result.applied:
            log.info("directory: applied %d change(s)", result.applied)
    if now >= state.get("publish", float("-inf")):
        sent = run_job("role catalog", lambda db: sync.publish_roles(db, directory))
        # Until the directory has accepted the catalog, try again in ten minutes; after that the hash makes an hourly check free.
        state["publish"] = now + (PUBLISH_RETRY_S if sent is None else 3600)
        if sent:
            log.info("directory: published the role catalog")


def check_config() -> None:
    """The worker refuses to start on an unsafe production configuration, as the API does."""
    problem = settings.production_safe()
    if problem:
        raise RuntimeError(f"Unsafe production configuration: {problem}")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    check_config()
    state: dict = {}
    while True:
        tick(state)
        try:
            Path(HEARTBEAT_FILE).touch()
        except OSError:
            log.exception("could not write the heartbeat file")
        time.sleep(TICK_S)


if __name__ == "__main__":  # pragma: no cover
    main()
