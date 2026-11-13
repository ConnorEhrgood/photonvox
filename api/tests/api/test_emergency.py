"""Numbers' 911 registrations with the carrier (app/emergency.py, decision 31), rule by rule, on the database: what is asked, when nothing is,
and how the carrier's answer moves each number."""
import uuid

import pytest
from sqlalchemy import select

from app import emergency
from app.config import settings
from app.db import SystemSession
from app.models import CarrierRequest, EmergencyLocation, EmergencyNumber, PhoneSystem

N1, N2 = "+17245550100", "+17245550111"
ADDR = {"street": "100 Main St", "unit": "", "city": "Pittsburgh", "state": "PA", "zip": "15222"}


@pytest.fixture()
def setup(world):
    with SystemSession() as s:
        ps = PhoneSystem(tenant_id=uuid.UUID(world.a), instance_id=uuid.uuid4(), domain_name="x.sip.test", domain_uuid=uuid.uuid4(), draft={})
        main = EmergencyLocation(tenant_id=ps.tenant_id, site_id=uuid.UUID(world.a1), key="main", address=ADDR, status="validated")
        floor = EmergencyLocation(tenant_id=ps.tenant_id, site_id=uuid.UUID(world.a1), key="floor-2", address={**ADDR, "unit": "Floor 2"}, status="validated")
        s.add_all([ps, main, floor])
        s.commit()
        return {"ps": ps.id, "main": main.id, "floor": floor.id, "a1": world.a1}


def doc(site, location, numbers):
    return {"sites": {site: {"emergency_location": location}}, "numbers": {n: {"site": site} for n in numbers}}


def sync(setup, location, numbers):
    with SystemSession() as s:
        req = emergency.sync_numbers(s, s.get(PhoneSystem, setup["ps"]), doc(setup["a1"], location, numbers))
        s.commit()
        return req and {"id": req.id, "items": req.items}


def confirm(req_id, ok=True):
    with SystemSession() as s:
        emergency.close(s, s.get(CarrierRequest, req_id), ok, "staff")
        s.commit()


def numbers():
    with SystemSession() as s:
        return {n.number: n.status for n in s.execute(select(EmergencyNumber)).scalars()}


def test_nothing_is_asked_twice_and_an_unchanged_publish_asks_nothing(setup):
    first = sync(setup, "main", [N1])
    assert [i["action"] for i in first["items"]] == ["add"]
    assert sync(setup, "main", [N1]) is None                 # already asked at this address
    confirm(first["id"])
    assert sync(setup, "main", [N1]) is None and numbers() == {N1: "confirmed"}


def test_moving_back_to_the_confirmed_address_needs_no_request(setup):
    confirm(sync(setup, "main", [N1])["id"])
    moved = sync(setup, "floor-2", [N1])
    assert moved["items"][0]["action"] == "change" and numbers() == {N1: "unconfirmed"}
    assert sync(setup, "main", [N1]) is None and numbers() == {N1: "confirmed"}


def test_a_number_given_up_before_it_was_confirmed_is_just_forgotten(setup):
    sync(setup, "main", [N1, N2])
    assert sync(setup, "main", [N1]) is None and numbers() == {N1: "unconfirmed"}


def test_a_removal_already_asked_for_is_not_asked_again(setup):
    confirm(sync(setup, "main", [N1, N2])["id"])
    removal = sync(setup, "main", [N1])
    assert removal["items"] == [{"number": N2, "action": "remove", "address": None}]
    with SystemSession() as s:
        emergency.mark_sent(s, s.get(CarrierRequest, removal["id"]), "msg")
        s.commit()
    assert sync(setup, "main", [N1]) is None
    confirm(removal["id"])
    assert numbers() == {N1: "confirmed"}


def test_a_failed_send_leaves_the_request_open(setup, monkeypatch):
    req = sync(setup, "main", [N1])
    monkeypatch.setattr(settings, "htc_e911_email", "911@htc.example")
    with SystemSession() as s:
        assert emergency.send_open(s, lambda *a: None) == 0
    with SystemSession() as s:
        assert s.get(CarrierRequest, req["id"]).status == "open"


def test_the_email_reads_well_for_one_number_and_for_a_unit():
    req = CarrierRequest(id=uuid.UUID(int=7), items=[{"number": N1, "action": "change", "address": {**ADDR, "unit": "Suite 4"}}])
    msg = emergency.compose(req, "Cedar Works")
    assert msg["subject"] == "911 address update 00000000: Cedar Works (1 number)"
    assert "Change  +17245550100  at  100 Main St, Suite 4, Pittsburgh, PA 15222" in msg["body"] and "reference 00000000" in msg["body"]


def test_a_number_given_up_after_its_request_was_sent_is_asked_to_be_removed(setup):
    req = sync(setup, "main", [N1, N2])
    with SystemSession() as s:
        emergency.mark_sent(s, s.get(CarrierRequest, req["id"]), "msg")
        s.commit()
    removal = sync(setup, "main", [N1])
    assert removal["items"] == [{"number": N2, "action": "remove", "address": None}]


def test_a_request_left_with_nothing_to_ask_is_set_aside(setup):
    req = sync(setup, "main", [N2])
    assert sync(setup, "main", []) is None and numbers() == {}
    with SystemSession() as s:
        assert s.get(CarrierRequest, req["id"]).status == "superseded"


def test_a_rejected_number_then_given_up_is_just_forgotten(setup):
    confirm(sync(setup, "main", [N1])["id"], ok=False)
    assert sync(setup, "main", []) is None and numbers() == {}
