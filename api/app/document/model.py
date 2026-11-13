"""The phone-system document: what an integrator builds, as plain outcomes (ARCHITECTURE §8).

Integrators never see dial plans, routes, gateways or caller-ID rules; they choose what each number rings, when, and what each site's calls
show. This is the stored, versioned, cloned and templated form of those choices. The compiler (app/compiler) turns it into the engine's objects;
nothing else does. Ids are PhotonVox's own: sites are the directory's site ids, users are phone users, menus/groups/boxes are short names.
"""
from __future__ import annotations

import re
from typing import Dict, List, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator

E164 = r"^\+1[2-9][0-9]{2}[2-9][0-9]{6}$"          # North American numbers only in R1
NAME = r"^[a-z0-9][a-z0-9_-]{0,39}$"
DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
SPAN = re.compile(r"^([01][0-9]|2[0-3]):([0-5][0-9])-([01][0-9]|2[0-4]):([0-5][0-9])$")


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


# ---- where a call goes (an outcome) ----

class ToUser(Strict):
    user: str


class ToGroup(Strict):
    group: str = Field(pattern=NAME)


class ToMenu(Strict):
    menu: str = Field(pattern=NAME)


class ToVoicemail(Strict):
    voicemail: str          # a user's id (their own box) or a shared box's name


Target = Union[ToUser, ToGroup, ToMenu, ToVoicemail]


# ---- the parts ----

class Hours(Strict):
    """Open hours per weekday, in the site's time zone, as "HH:MM-HH:MM" spans (24:00 allowed as an end); days not listed are closed."""
    week: Dict[Literal["mon", "tue", "wed", "thu", "fri", "sat", "sun"], List[str]] = Field(default_factory=dict)
    holidays: Literal["none", "us-federal"] = "none"

    @field_validator("week")
    @classmethod
    def _spans(cls, week: Dict[str, List[str]]) -> Dict[str, List[str]]:
        for day, spans in week.items():
            for span in spans:
                m = SPAN.match(span)
                if not m or (m.group(1), m.group(2)) >= (m.group(3), m.group(4)):
                    raise ValueError(f"{day}: {span!r} is not a span like 08:00-17:00")
        return week


class Site(Strict):
    """Per site: its 911 (the emergency location and the number registered at it, both locked: §11), what its calls show, its hours."""
    emergency_location: str
    emergency_number: str = Field(pattern=E164)
    caller_id: str = Field(pattern=E164)
    hours: Optional[str] = Field(None, pattern=NAME)
    unreachable: Literal["voicemail", "none"] = "voicemail"     # where calls go when a user's phones are not registered
    outside_prefix: Optional[Literal["8", "9"]] = None          # a site that dials 9 for an outside line; 9-911 then works too (Kari's Law)


class Number(Strict):
    """A number the organization holds and what it rings. Without `closed`, it rings `open` at all hours."""
    site: str
    open: Target
    closed: Optional[Target] = None
    hours: Optional[str] = Field(None, pattern=NAME)   # defaults to the site's hours


class Menu(Strict):
    greeting: str = Field(min_length=1, max_length=500)          # text to speak, or a recording's id once recordings exist
    options: Dict[Literal["0", "1", "2", "3", "4", "5", "6", "7", "8", "9"], Target] = Field(default_factory=dict)
    timeout: Target


class Group(Strict):
    members: List[str] = Field(min_length=1)
    strategy: Literal["simultaneous", "sequence"] = "simultaneous"
    ring_seconds: int = Field(25, ge=10, le=120)
    then: Optional[Target] = None


class User(Strict):
    name: str = Field(min_length=1, max_length=100)
    site: str
    extension: str = Field(pattern=r"^[1-8][0-9]{1,4}$")
    direct_number: Optional[str] = Field(None, pattern=E164)
    show: Literal["site", "direct"] = "site"
    email: Optional[str] = Field(None, max_length=320)


class Box(Strict):
    """A shared voicemail box ("general"), separate from users' own."""
    name: str = Field(min_length=1, max_length=100)
    email: Optional[str] = Field(None, max_length=320)


class Calling(Strict):
    """What outside calls the organization may make (§15). Emergency, 988 and relay services are always allowed and are not listed here."""
    national: bool = True
    toll_free: bool = True
    international: List[str] = Field(default_factory=list)       # country calling codes switched on by an owner ("44", "52"); empty = none
    spend_limit_usd: int = Field(50, ge=0, le=100_000)


class PhoneSystem(Strict):
    version: Literal[1] = 1
    sites: Dict[str, Site] = Field(default_factory=dict)
    hours: Dict[str, Hours] = Field(default_factory=dict)
    numbers: Dict[str, Number] = Field(default_factory=dict)
    menus: Dict[str, Menu] = Field(default_factory=dict)
    groups: Dict[str, Group] = Field(default_factory=dict)
    users: Dict[str, User] = Field(default_factory=dict)
    boxes: Dict[str, Box] = Field(default_factory=dict)
    calling: Calling = Field(default_factory=Calling)

    @field_validator("numbers")
    @classmethod
    def _numbers_are_e164(cls, numbers: Dict[str, Number]) -> Dict[str, Number]:
        bad = [n for n in numbers if not re.match(E164, n)]
        if bad:
            raise ValueError(f"not a North American number in +1 form: {', '.join(sorted(bad))}")
        return numbers
