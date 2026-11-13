from __future__ import annotations

import logging
import time
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Request, status

from app.config import settings
from app.db import SystemSession
from app.deps import get_directory
from app.models import utcnow
from app.sync import DirectoryFactory, pull
from app.throttle import Throttle
from photonid_directory_client import NoticeError
from photonid_directory_client.notice import verify_notice

router = APIRouter()
log = logging.getLogger("photonvox.directory")
# A real directory sends a notice per change, in bursts at most. This only stops someone hammering the endpoint with forgeries.
notify_throttle = Throttle(limit=120, window_s=60)


def run_pull(make_client: DirectoryFactory) -> None:
    with SystemSession() as db:
        pull(db, make_client, utcnow())


async def raw_body(request: Request) -> bytes:
    return await request.body()


@router.post("/directory/v1/notify", status_code=status.HTTP_202_ACCEPTED)
def notify(request: Request, background: BackgroundTasks, body: bytes = Depends(raw_body), signature: Optional[str] = Header(None, alias="X-PhotonID-Signature"),
           directory: Optional[DirectoryFactory] = Depends(get_directory)) -> dict:
    """The directory says something changed. The notice carries no data: if it is genuine we pull (in the background, so the directory is not kept
    waiting); a forged or replayed one costs at most one extra pull."""
    notify_throttle.check(request)
    try:
        verify_notice(signature or "", body, settings.notice_secrets, int(time.time()))
    except NoticeError as e:
        log.warning("refused a directory notice: %s", e)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid signature")
    if directory is not None:
        background.add_task(run_pull, directory)
    return {}
