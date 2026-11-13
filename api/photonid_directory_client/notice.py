"""Notices: signed, data-free hints that the directory has changed. `X-PhotonID-Signature: t=<unix>,v1=<hex>[,v1=<hex>]` where each `v1` is the hex
HMAC-SHA256 of `"<t>.<raw body>"` under a notice secret. During a rotation the directory signs with both the new and the previous secret, so a product
holding either one verifies."""
from __future__ import annotations

import hashlib
import hmac
import json
import time
from typing import Any, Dict, Iterable, Optional

TOLERANCE_S = 300
HEADER = "X-PhotonID-Signature"


class NoticeError(Exception):
    pass


def sign_notice(secrets: Iterable[str], body: bytes, now: Optional[int] = None) -> str:
    """Make a header exactly as the directory does (for the fake directory and for tests)."""
    now = int(time.time()) if now is None else now
    sigs = [hmac.new(s.encode(), f"{now}.".encode() + body, hashlib.sha256).hexdigest() for s in secrets]
    if not sigs:
        raise ValueError("no signing secret")
    return f"t={now}," + ",".join(f"v1={s}" for s in sigs)


def verify_notice(header: str, body: bytes, secrets: Iterable[str], now: Optional[int] = None, tolerance_s: int = TOLERANCE_S) -> Dict[str, Any]:
    """The notice's content if the header is genuine and recent; otherwise raises NoticeError. Pass the RAW body, exactly as received."""
    now = int(time.time()) if now is None else now
    pairs = [tuple(p.strip().split("=", 1)) for p in (header or "").split(",") if "=" in p]
    stamps = [v for k, v in pairs if k == "t"]
    sigs = [v for k, v in pairs if k == "v1"]
    if len(stamps) != 1 or not (stamps[0].isascii() and stamps[0].isdigit()) or not sigs or not all(s.isascii() for s in sigs):      # (str.isdigit accepts digits like '²', which int() refuses)
        raise NoticeError("malformed signature header")
    t = int(stamps[0])
    if abs(now - t) > tolerance_s:
        raise NoticeError("signature too old or from the future")
    ok = False
    for secret in secrets:
        expected = hmac.new(secret.encode(), f"{t}.".encode() + body, hashlib.sha256).hexdigest()
        for sig in sigs:
            ok |= hmac.compare_digest(expected, sig)       # no early exit: the time taken does not say which secret or signature matched
    if not ok:
        raise NoticeError("signature does not match")
    try:
        data = json.loads(body)
    except ValueError as e:
        raise NoticeError("body is not JSON") from e
    if not isinstance(data, dict):
        raise NoticeError("body is not an object")
    return data
