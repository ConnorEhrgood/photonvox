import pytest
from fastapi import HTTPException

from app.throttle import Throttle, client_key


class Req:
    def __init__(self, host): self.client = type("C", (), {"host": host})() if host else None


def test_client_keys_group_ipv6_by_prefix_and_pass_others_through():
    assert client_key(Req("203.0.113.9")) == "203.0.113.9"
    assert client_key(Req("2001:db8:1:2:3:4:5:6")) == client_key(Req("2001:db8:1:2:ffff::1")) == "2001:db8:1:2::/64"
    assert client_key(Req("fe80::1%eth0")) == "fe80::/64"
    assert client_key(Req("not-an-ip")) == "not-an-ip"
    assert client_key(Req(None)) == "unknown"


def test_the_window_slides_and_forgotten_keys_are_swept():
    now = [0.0]
    t = Throttle(2, 10, clock=lambda: now[0])
    assert t.allow("a") and t.allow("a") and not t.allow("a")
    assert t.allow("b")
    now[0] = 11
    assert t.allow("a")                          # a's old hits aged out
    now[0] = 30
    t.allow("c")                                 # the sweep drops keys whose window has emptied
    assert set(t.hits) == {"c"}


def test_check_raises_429_when_over_the_limit():
    t = Throttle(1, 60)
    t.check(Req("1.2.3.4"))
    with pytest.raises(HTTPException) as e:
        t.check(Req("1.2.3.4"))
    assert e.value.status_code == 429


def test_only_the_hits_that_have_aged_out_are_forgotten():
    now = [0.0]
    t = Throttle(2, 10, clock=lambda: now[0])
    assert t.allow("a")
    now[0] = 8
    assert t.allow("a") and not t.allow("a")
    now[0] = 11                                   # the hit at 0 is out of the window, the one at 8 is not
    assert t.allow("a") and not t.allow("a")
