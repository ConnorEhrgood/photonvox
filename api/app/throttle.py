from __future__ import annotations

import ipaddress
import time
from collections import defaultdict, deque
from typing import Callable, Deque, Dict

from fastapi import HTTPException, Request, status


def client_key(request: Request) -> str:
    """Who a request counts against. An IPv6 address is a whole /64 (a home or a carrier hands one person 2^64 of them), so group by prefix."""
    host = request.client.host if request.client else "unknown"
    try:
        ip = ipaddress.ip_address(host.split("%")[0])
    except ValueError:
        return host
    if ip.version == 6:
        return str(ipaddress.ip_network(f"{ip}/64", strict=False))
    return host


class Throttle:
    """Sliding-window limiter, in memory (per process). Enough to stop code-guessing against the
    pairing endpoint; put a shared limiter (Redis/proxy) in front when running several workers."""

    def __init__(self, limit: int, window_s: float, clock: Callable[[], float] = time.monotonic) -> None:
        self.limit, self.window_s, self.clock = limit, window_s, clock
        self.hits: Dict[str, Deque[float]] = defaultdict(deque)
        self._next_sweep = 0.0

    def _sweep(self, now: float) -> None:
        """Forget keys whose window has emptied: keys can be chosen by a stranger (a token they made up), so they must not accumulate."""
        if now < self._next_sweep and len(self.hits) < 50_000:
            return
        self._next_sweep = now + self.window_s
        for k in [k for k, q in self.hits.items() if not q or now - q[-1] > self.window_s]:
            del self.hits[k]

    def allow(self, key: str) -> bool:
        now = self.clock()
        self._sweep(now)
        q = self.hits[key]
        while q and now - q[0] > self.window_s:
            q.popleft()
        if len(q) >= self.limit:
            return False
        q.append(now)
        return True

    def check(self, request: Request) -> None:
        if not self.allow(client_key(request)):
            raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many attempts")
