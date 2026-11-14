"""The phone-system document: what an integrator builds, as plain outcomes (ARCHITECTURE §8).

Integrators never see dial plans, routes, gateways or caller-ID rules; they choose what each number rings, when, and what each site's calls
show. This is the stored, versioned, cloned and templated form of those choices. The compiler (app/compiler) turns it into the engine's objects;
nothing else does. Ids are PhotonVox's own: sites are the directory's site ids, users are phone users, menus/groups/boxes are short names.
"""
from __future__ import annotations

import re
from typing import Annotated, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator

E164 = r"^\+1[2-9][0-9]{2}[2-9][0-9]{6}$"          # North American numbers only in R1
NAME = r"^[a-z0-9][a-z0-9_-]{0,39}$"
UUID_RE = r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"

# Every name the document uses as a key, and every free text, is constrained here: keys reach the engine's dial plans (security review C1,
# 2026-11-13), and names and addresses reach emails and FusionPBX's own screens (L6).
Key = Annotated[str, Field(pattern=NAME)]
SiteId = Annotated[str, Field(pattern=UUID_RE)]                # a site is the directory's site id
Label = Annotated[str, Field(min_length=1, max_length=100, pattern=r"^[^<>%\x00-\x1f\x7f]+$")]
Email = Annotated[str, Field(max_length=320, pattern=r"^[^@\s<>\"'%,;]+@[^@\s<>\"'%,;]+\.[^@\s<>\"'%,;]+$")]
DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
SPAN = re.compile(r"^([01][0-9]|2[0-3]):([0-5][0-9])-([01][0-9]|2[0-4]):([0-5][0-9])$")


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


# ---- where a call goes (an outcome) ----

class ToUser(Strict):
    user: Key


class ToGroup(Strict):
    group: str = Field(pattern=NAME)


class ToMenu(Strict):
    menu: str = Field(pattern=NAME)


class ToVoicemail(Strict):
    voicemail: Key          # a user's id (their own box) or a shared box's name


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
    emergency_location: Key
    emergency_number: str = Field(pattern=E164)
    caller_id: str = Field(pattern=E164)
    hours: Optional[str] = Field(None, pattern=NAME)
    unreachable: Literal["voicemail", "none"] = "voicemail"     # where calls go when a user's phones are not registered
    outside_prefix: Optional[Literal["8", "9"]] = None          # a site that dials 9 for an outside line; 9-911 then works too (Kari's Law)


class Number(Strict):
    """A number the organization holds and what it rings. Without `closed`, it rings `open` at all hours."""
    site: SiteId
    open: Target
    closed: Optional[Target] = None
    hours: Optional[str] = Field(None, pattern=NAME)   # defaults to the site's hours


# A greeting that is a recording already on the engine (a domain taken over in place keeps its own: decision 32), not text to speak.
RECORDING = re.compile(r"^recording:[A-Za-z0-9._-]{1,200}$")


class Menu(Strict):
    # Text to speak (decision 30), or "recording:<file>" for a recording already in the domain's recordings.
    greeting: str = Field(min_length=1, max_length=500, pattern=r"^[^\x00-\x1f\x7f]+$")
    options: Dict[Literal["0", "1", "2", "3", "4", "5", "6", "7", "8", "9"], Target] = Field(default_factory=dict)
    timeout: Optional[Target] = None            # where the call goes when nobody presses a key; none: the call ends

    @field_validator("greeting")
    @classmethod
    def _recording_name(cls, g: str) -> str:
        if g.startswith("recording:") and not RECORDING.match(g):
            raise ValueError("a recording is named by its file: letters, digits, dots, dashes and underscores")
        return g


class Group(Strict):
    members: List[Key] = Field(min_length=1, max_length=200)
    strategy: Literal["simultaneous", "sequence"] = "simultaneous"
    ring_seconds: int = Field(25, ge=10, le=120)
    then: Optional[Target] = None


class User(Strict):
    name: Label
    site: SiteId
    extension: str = Field(pattern=r"^[1-8][0-9]{1,4}$")
    direct_number: Optional[str] = Field(None, pattern=E164)
    show: Literal["site", "direct"] = "site"
    email: Optional[Email] = None
    voicemail: bool = True                       # the user's own voicemail box answers; False: the box is kept but switched off
    # What this user's outside calls AND 911 calls show, when it is not the site's: one of the organization's numbers (its 911 address on file
    # with the carrier). An elevator or a second line, for example. A direct number shown (show "direct") takes precedence for outside calls.
    caller_id: Optional[str] = Field(None, pattern=E164)


class Door(Strict):
    """A door station (a SIP intercom, PhotonEntry's: docs/VOX.md in photonaccess): an extension with no voicemail that can call only its own
    flow. Whatever it dials goes to `open` (or `closed` outside its hours); 911 and 933 still go to the emergency route. Its flow rings
    people (a user or a ring group), never a menu (the menu would take the "#" that opens the door) or voicemail."""
    name: Label
    site: SiteId
    extension: str = Field(pattern=r"^[1-8][0-9]{1,4}$")
    open: Union[ToUser, ToGroup]
    closed: Optional[Union[ToUser, ToGroup]] = None
    hours: Optional[str] = Field(None, pattern=NAME)   # defaults to the site's hours


class Box(Strict):
    """A shared voicemail box ("general"), separate from users' own."""
    name: Label
    email: Optional[Email] = None


# a number or prefix in + form ("+1212555", "+44"); a North American one has at most 10 digits after +1 (more would match nothing)
PLUS_PREFIX = Annotated[str, Field(pattern=r"^\+(1[2-9][0-9]{0,9}|[2-9][0-9]{0,14})$")]
NANP_PREFIX = Annotated[str, Field(pattern=r"^\+1[2-9][0-9]{0,9}$")]        # a North American number or prefix in +1 form


class Blocking(Strict):
    """The organization's Call blocking page (§15a, decision 29). Photon's default list blocks international (except the countries switched on
    in `Calling.international`), premium, the high-cost North American codes and satellite ranges; this says what the organization changes."""
    allow: List[Literal["high_cost_nanp", "satellite", "premium"]] = Field(default_factory=list)   # categories let through (premium: staff only)
    block: List[PLUS_PREFIX] = Field(default_factory=list, max_length=500)           # extra numbers or prefixes to block
    allow_numbers: List[NANP_PREFIX] = Field(default_factory=list, max_length=500)   # let through a blocked category


class Calling(Strict):
    """What outside calls the organization may make (§15). Emergency, 988 and relay services are always allowed and are not listed here."""
    national: bool = True
    toll_free: bool = True
    international: List[str] = Field(default_factory=list)       # country calling codes switched on by an owner ("44", "52"); empty = none
    spend_limit_usd: int = Field(50, ge=0, le=100_000)
    blocking: Blocking = Field(default_factory=Blocking)


class Features(Strict):
    """Engine features that let one phone reach into another's calls. Off unless an admin switches them on (the spike found FusionPBX enables
    them in every new domain)."""
    eavesdrop: bool = False
    intercept: bool = False


class PhoneSystem(Strict):
    version: Literal[1] = 1
    # A domain taken over in place (decision 32) starts with its own outside calls, 911 and blocking (False); the protections version sets True:
    # PhotonVox's routes, block route and call classes, and the hand-built routes it was told to retire switched off. A version holds it, so an
    # undo to an earlier version undoes it. Ignored for a phone system PhotonVox built itself (always protected).
    protections: Optional[bool] = None
    voice: str = "en-US-Chirp3-HD-Kore"         # the voice greetings are spoken in (app/speech VOICES; decision 30)
    sites: Dict[SiteId, Site] = Field(default_factory=dict, max_length=200)
    hours: Dict[Key, Hours] = Field(default_factory=dict, max_length=50)
    numbers: Dict[str, Number] = Field(default_factory=dict, max_length=1000)
    menus: Dict[Key, Menu] = Field(default_factory=dict, max_length=100)
    groups: Dict[Key, Group] = Field(default_factory=dict, max_length=200)
    users: Dict[Key, User] = Field(default_factory=dict, max_length=2000)
    boxes: Dict[Key, Box] = Field(default_factory=dict, max_length=100)
    doors: Dict[Key, Door] = Field(default_factory=dict, max_length=200)
    calling: Calling = Field(default_factory=Calling)
    features: Features = Field(default_factory=Features)

    @field_validator("voice")
    @classmethod
    def _known_voice(cls, voice: str) -> str:
        from app.speech import VOICES
        if voice not in VOICES:
            raise ValueError(f"not one of the voices: {', '.join(VOICES)}")
        return voice

    @field_validator("numbers")
    @classmethod
    def _numbers_are_e164(cls, numbers: Dict[str, Number]) -> Dict[str, Number]:
        bad = [n for n in numbers if not re.match(E164, n)]
        if bad:
            raise ValueError(f"not a North American number in +1 form: {', '.join(sorted(bad))}")
        return numbers
