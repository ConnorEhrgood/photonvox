"""The live simulator's scheduler: how a call of the model is placed (which side of the engine, which scenario, who answers and when), what it
keeps running, and that no password ever reaches a command line or the log."""
import os
import sys
import xml.dom.minidom
from datetime import datetime, timedelta, timezone

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import scenarios  # noqa: E402
import scheduler  # noqa: E402
import traffic  # noqa: E402

SECRET = "not-a-real-password"
START = datetime(2026, 11, 12, 15, 0, tzinfo=timezone.utc)             # a Thursday, 10 in the morning in New York


def call(kind="inbound", caller="4125550188", dialed="4125550101", reached="101", status="answered", ring=6, talk=90, **more):
    return traffic.Call(START.timestamp(), "demo-hq", kind, caller, dialed, reached, status, ring, talk, **more)


class Proc:
    def __init__(self, cmd, **how):
        self.cmd, self.how, self.returncode, self.ended = cmd, how, None, False

    def poll(self):
        return self.returncode

    def terminate(self):
        self.ended = True


@pytest.fixture()
def cfg(tmp_path):
    phones = tmp_path / "phones.csv"
    phones.write_text("SEQUENTIAL\n" + "".join(f"{e};[authentication username={e} password={SECRET}]\n" for e in ("100", "101", "102", "200", "300")))
    return scheduler.Config("10.10.0.60", "demo.vox.test", "10.10.0.80", credentials=str(phones), work=str(tmp_path / "run"))


def sim(role, cfg, at=START):
    clock, spawned = [at], []

    def spawn(cmd, **how):
        spawned.append(Proc(cmd, **how))
        return spawned[-1]
    s = scheduler.Simulator(role, cfg, now=lambda: clock[0], spawn=spawn)
    s.prepare()
    return s, clock, spawned


def test_every_scenario_is_well_formed():
    files = scenarios.all_()
    assert len(files) == 12 and "sim-answer.xml" in files and "sim-register.xml" in files
    for name, text in files.items():
        xml.dom.minidom.parseString(text.replace('<!DOCTYPE scenario SYSTEM "sipp.dtd">', "").encode("iso-8859-1"))
        assert "password" not in text and "trace" not in text, name
    for c in traffic.between(START, START + timedelta(days=3)):
        assert scheduler.placement(c).scenario in files


def test_how_each_call_is_placed():
    p = scheduler.placement
    # In from outside, on the carrier's side. A direct line, answered: that phone answers after its ring, and the call lasts its talk.
    assert p(call()) == scheduler.Placement("carrier", "sim-carrier.xml", "101", 6000, 90000)
    # Through the menu: the key, then the group's phone answers; the caller is connected from the menu on.
    assert p(call(dialed="4125550100", reached="102", digit="1")) == scheduler.Placement("carrier", "sim-carrier-digit.xml", "102", 6000, 96000, digit="1")
    # Nobody answers and the box takes it: no phone answers, the caller leaves a tone for the greeting and the message.
    assert p(call(reached="voicemail:101", status="voicemail", ring=30, talk=40)) == scheduler.Placement("carrier", "sim-carrier-speak.xml", "none",
                                                                                                         hold_ms=40000, speak=True)
    assert p(call(dialed="4125550100", reached="voicemail:sales", status="voicemail", ring=20, talk=40, digit="1")) == scheduler.Placement(
        "carrier", "sim-carrier-digit-speak.xml", "none", hold_ms=60000, digit="1", speak=True)
    # The caller gives up: a cancel while a phone rings; past the menu, a hang-up.
    assert p(call(reached="", status="missed", ring=9, talk=0)) == scheduler.Placement("carrier", "sim-carrier-cancel.xml", "none", give_up_ms=9000)
    assert p(call(dialed="4125550100", reached="", status="missed", ring=9, talk=0, digit="2")) == scheduler.Placement(
        "carrier", "sim-carrier-digit.xml", "none", hold_ms=9000, digit="2")
    # Closed: straight to the box, a message or a hang-up in its greeting.
    assert p(call(dialed="4125550100", reached="voicemail:company", status="voicemail", ring=0, talk=35, closed=True)) == scheduler.Placement(
        "carrier", "sim-carrier-speak.xml", "none", hold_ms=35000, speak=True)
    assert p(call(dialed="4125550100", reached="", status="missed", ring=5, talk=0, closed=True)) == scheduler.Placement(
        "carrier", "sim-carrier.xml", "none", hold_ms=5000)
    # From a phone, on the phones' side: out (the carrier answers), to another phone, a page (every paged phone answers at once), a give-up.
    assert p(call("outbound", "101", "4125550190", "outside", ring=8)) == scheduler.Placement("phones", "sim-phone.xml", "any", 8000, 90000)
    assert p(call("internal", "101", "102", "102", ring=4)) == scheduler.Placement("phones", "sim-phone.xml", "102", 4000, 90000)
    assert p(call("page", "200", "290", "290", ring=1, talk=12)) == scheduler.Placement("phones", "sim-phone.xml", "any", 0, 12000)
    for kind, dialed in (("outbound", "4125550190"), ("internal", "102")):
        assert p(call(kind, "101", dialed, "", "missed", 7, 0)) == scheduler.Placement("phones", "sim-phone-cancel.xml", "none", give_up_ms=7000)
    # A long call ends before the engine would end it for its silence.
    assert p(call(talk=1500)).hold_ms == 1000 * scheduler.MAX_TALK_S
    # Never an emergency or service number, never a number outside the fictional hundred.
    for bad in ("911", "933", "988", "411", "7245550100"):
        with pytest.raises(ValueError):
            p(call("outbound", "101", bad, "outside"))


def test_the_commands_carry_no_password(cfg):
    s, clock, spawned = sim("phones", cfg)
    inbound = scheduler.call_command(cfg, call(), 7)
    assert inbound[-1] == "10.10.0.60:5080" and inbound[inbound.index("-s") + 1] == "4125550101" and "-inf" not in inbound and "-mp" not in inbound
    assert inbound[inbound.index("from") + 1] == "4125550188" and inbound[inbound.index("-d") + 1] == "90000" and "-recv_timeout" not in inbound
    spoken = scheduler.call_command(cfg, call(reached="voicemail:101", status="voicemail", ring=30, talk=40), 7)
    assert spoken[spoken.index("-mp") + 1] == "6128" and spoken[spoken.index("-mi") + 1] == "10.10.0.80"
    gone = scheduler.call_command(cfg, call(reached="", status="missed", ring=9, talk=0), 8)
    assert gone[gone.index("-recv_timeout") + 1] == "9000"
    out = scheduler.call_command(cfg, call("outbound", "101", "4125550190", "outside"), 9)
    assert out[-1] == "10.10.0.60:5060" and out[out.index("-inf") + 1] == f"{cfg.work}/phone/101.csv" and out[out.index("domain") + 1] == "demo.vox.test"
    commands = [inbound, spoken, gone, out, scheduler.register_command(cfg, 5), scheduler.answer_command(cfg, 5200)]
    for cmd in commands:
        assert cmd[0] == "sipp" and SECRET not in " ".join(cmd) and not any(x.startswith("-trace") or x in ("-au", "-ap") for x in cmd)
    # The password is only where SIPp reads it: a file each, for the phone's owner alone.
    one = os.path.join(cfg.work, "phone", "101.csv")
    assert open(one).read() == f"SEQUENTIAL\n101;[authentication username=101 password={SECRET}]\n"
    assert os.stat(one).st_mode & 0o777 == 0o600 and os.stat(os.path.dirname(one)).st_mode & 0o777 == 0o700
    assert sorted(os.listdir(os.path.join(cfg.work, "scn"))) == sorted(scenarios.all_())


def test_the_carriers_side_answers_registers_and_calls_in(cfg, caplog):
    caplog.set_level("INFO")
    s, clock, spawned = sim("carrier", cfg)
    assert not os.path.exists(os.path.join(cfg.work, "phone"))
    s.step()
    answering = [p for p in spawned if "sim-answer.xml" in " ".join(p.cmd)]
    assert sorted(p.cmd[p.cmd.index("-p") + 1] for p in answering) == ["5071", "5200"]
    register, = [p for p in spawned if "sim-register.xml" in " ".join(p.cmd)]
    assert register.cmd[register.cmd.index("-m") + 1] == "5" and register.cmd[register.cmd.index("contact_port") + 1] == "5200"
    assert all(p.how["stdout"] == p.how["stderr"] == scheduler.subprocess.DEVNULL for p in spawned)
    # What answers is started again if it stops; the phones register again every five minutes, and sooner after a failure.
    answering[0].returncode, register.returncode = 1, 0
    clock[0] += timedelta(seconds=10)
    s.step()
    assert len([p for p in spawned if "sim-answer.xml" in " ".join(p.cmd)]) == 3 and len([p for p in spawned if "sim-register.xml" in " ".join(p.cmd)]) == 1
    clock[0] = START + timedelta(seconds=301)
    s.step()
    again = [p for p in spawned if "sim-register.xml" in " ".join(p.cmd)]
    assert len(again) == 2
    again[1].returncode = 1
    s.step()
    clock[0] += timedelta(seconds=31)
    s.step()
    assert len([p for p in spawned if "sim-register.xml" in " ".join(p.cmd)]) == 3
    # An hour of a business morning: its calls in, as they come due, and none from a phone.
    expected = [c for c in traffic.between(START, START + timedelta(hours=1)) if c.kind == "inbound" and c.start > clock[0].timestamp()]
    while clock[0] < START + timedelta(hours=1):
        clock[0] += timedelta(seconds=1)
        for p in s.calls:
            p.returncode = 0
        s.step()
    calls = [p.cmd for p in spawned if p.cmd[-1].endswith(":5080")]
    assert len(expected) > 10 and len(calls) == len(expected) == s.placed and s.failed == 0 and s.skipped == 0
    assert [c[c.index("-s") + 1] for c in calls] == [c.dialed for c in expected]
    assert not [p for p in spawned if p.cmd[-1].endswith(":5060") and "sim-register.xml" not in " ".join(p.cmd)]
    assert SECRET not in caplog.text and "Headquarters" not in caplog.text and "demo-hq: answered inbound call" in caplog.text
    s.stop()
    assert all(p.ended for p in s.answering.values())


def test_the_phones_side_calls_out_and_keeps_nothing(cfg):
    s, clock, spawned = sim("phones", cfg)
    expected = [c for c in traffic.between(START, START + timedelta(hours=1)) if c.kind != "inbound"]
    known = [c for c in expected if c.caller in ("100", "101", "102", "200", "300")]
    while clock[0] < START + timedelta(hours=1):
        s.step()
        clock[0] += timedelta(seconds=1)
        for p in s.calls:
            p.returncode = 0
    assert known and len(spawned) == len(known) == s.placed and s.skipped == len(expected) - len(known)       # a phone it has no line for is skipped
    assert all(p.cmd[-1] == "10.10.0.60:5060" and "-inf" in p.cmd for p in spawned)
    assert {p.cmd[p.cmd.index("-s") + 1] for p in spawned} == {c.dialed for c in known}


def test_late_calls_and_too_many_at_once_are_skipped(cfg):
    s, clock, spawned = sim("carrier", cfg)
    s.step()
    before = len(spawned)
    clock[0] += timedelta(minutes=30)                      # the container was stopped for half an hour: what was due is not placed in a burst
    s.step()
    assert len(spawned) - before <= 2 and s.skipped > 5
    s.calls = [Proc([]) for _ in range(scheduler.MAX_CONCURRENT)]
    assert s.place(call(), clock[0] - timedelta(minutes=30) + timedelta(seconds=1)) is False
    failing = Proc([])
    failing.returncode = 1
    s.calls = [failing]
    s.step()
    assert s.failed == 1 and s.calls == []
    with pytest.raises(SystemExit):
        scheduler.Simulator("upstream", cfg)
