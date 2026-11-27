"""The simulator's SIPp scenarios (SIPp 3.6.1), written out by the scheduler when it starts: the phones' registrations, what answers (every
phone, and the simulated carrier), and the callers. Made here from a few pieces rather than kept as eight near-identical XML files.

Who answers is the caller's to say, so that a call goes as the traffic model has it: every simulated call carries `X-Sim-Answer` (an extension,
`any` or `none`) and `X-Sim-Ring` (milliseconds), which FreeSWITCH passes on to the phones it rings. A phone answers when the header names it
(or says `any`, or is absent: a page, a test call) after ringing that long; otherwise it rings until the engine gives up on it.
"""
from __future__ import annotations

import os
from typing import Dict

HEAD = '<?xml version="1.0" encoding="ISO-8859-1" ?>\n<!DOCTYPE scenario SYSTEM "sipp.dtd">\n'
AGENT = "PhotonVox-demo-sim"
SDP = """
      v=0
      o=sim 53655765 2353687637 IN IP[local_ip_type] [local_ip]
      s=-
      c=IN IP[media_ip_type] [media_ip]
      t=0 0
      m=audio [media_port] RTP/AVP 0
      a=rtpmap:0 PCMU/8000"""


def _send(text: str, retrans: bool = True) -> str:
    return f'  <send{" retrans=" + chr(34) + "500" + chr(34) if retrans else ""}>\n    <![CDATA[\n{text.strip(chr(10)).rstrip()}\n    ]]>\n  </send>\n'


def register() -> str:
    """Every phone's registration in one run (-inf phones.csv, -m <phones>; a line is `<extension>;[authentication username=<extension>
    password=<password>]`: SIPp 3.6.1 takes no field inside that keyword). The Contact is the port where `answer` listens (-set contact_port),
    not the port this was sent from."""
    def message(cseq: int, auth: bool) -> str:
        return _send(f"""
      REGISTER sip:[$domain] SIP/2.0
      Via: SIP/2.0/[transport] [local_ip]:[local_port];branch=[branch]
      From: <sip:[field0]@[$domain]>;tag=[pid]reg[call_number]
      To: <sip:[field0]@[$domain]>
      Call-ID: [call_id]
      CSeq: {cseq} REGISTER
      Contact: <sip:[field0]@[local_ip]:[$contact_port];transport=[transport]>
{"      [field1]" + chr(10) if auth else ""}      Max-Forwards: 70
      Expires: 600
      User-Agent: {AGENT}
      Content-Length: 0""")
    return (HEAD + '<scenario name="sim-register">\n  <Global variables="domain,contact_port"/>\n' + message(1, False)
            + '  <recv response="401" auth="true"/>\n' + message(2, True) + '  <recv response="200"/>\n</scenario>\n')


def _reply(status: str, tag: bool = False, cseq: str = "[last_CSeq:]", body: bool = False) -> str:
    return _send(f"""
      SIP/2.0 {status}
      [last_Via:]
      [last_From:]
      [last_To:]{";tag=[pid]sim[call_number]" if tag else ""}
      [last_Call-ID:]
      {cseq}
      Contact: <sip:sim@[local_ip]:[local_port];transport=[transport]>
""" + ("      Content-Type: application/sdp\n      Content-Length: [len]\n" + SDP if body else "      Content-Length: 0"), retrans=body)


def answer() -> str:
    """What every phone and the simulated carrier do with a call (one SIPp on one port for all of them): see the module's note."""
    return HEAD + f"""<scenario name="sim-answer">
  <recv request="INVITE" crlf="true" test="told" next="told">
    <action>
      <ereg regexp="X-Sim-Answer: *([A-Za-z0-9]+)" search_in="msg" check_it="false" assign_to="told,want"/>
      <ereg regexp="X-Sim-Ring: *([0-9]+)" search_in="msg" check_it="false" assign_to="timed,ring"/>
      <ereg regexp="^INVITE sips?:\\+?([^@;]+)" search_in="msg" check_it="false" assign_to="line,me"/>
      <ereg regexp="[0-9]+" search_in="hdr" header="CSeq:" check_it="false" assign_to="cseq"/>
    </action>
  </recv>
  <nop next="answer"/>

  <label id="told"/>
  <nop>
    <action>
      <strcmp assign_to="differs" variable="want" variable2="me"/>
      <test assign_to="mine" variable="differs" compare="equal" value="0"/>
      <strcmp assign_to="notany" variable="want" value="any"/>
      <test assign_to="anyone" variable="notany" compare="equal" value="0"/>
      <todouble assign_to="ringms" variable="ring"/>
    </action>
  </nop>
  <nop test="mine" next="ring"/>
  <nop test="anyone" next="ring"/>

{_reply("180 Ringing", tag=True)}  <recv request="CANCEL" timeout="120000" ontimeout="done"/>
{_reply("200 OK")}{_reply("487 Request Terminated", tag=True, cseq="CSeq: [$cseq] INVITE")}  <recv request="ACK" timeout="5000" ontimeout="done" next="done"/>

  <label id="ring"/>
{_reply("180 Ringing", tag=True)}  <pause variable="ringms"/>

  <label id="answer"/>
{_reply("200 OK", tag=True, body=True)}  <recv request="ACK" timeout="10000" ontimeout="done"/>
  <recv request="BYE" timeout="900000" ontimeout="done"/>
{_reply("200 OK")}
  <label id="done"/>
  <nop/>
  <Reference variables="told,want,timed,ring,line,me,cseq,differs,mine,notany,anyone,ringms"/>
</scenario>
"""


def caller(phone: bool, digit: bool = False, speak: bool = False, cancel: bool = False, tone: str = "/scenarios/tone-ulaw.wav") -> str:
    """One call to [service]: from a phone (answers the engine's challenge; who it is comes from -inf, a one-line file as `register` reads, so
    no password is on a command line) or from the simulated carrier (no challenge, to the external profile; -set from). -set domain/answer/ring;
    held for -d ms once answered, then hung up. `digit`: a key pressed in the menu (-set digit). `speak`: a tone as the caller's voice, for a
    voicemail box. `cancel`: the caller gives up after -recv_timeout ms of ringing."""
    cseq = 2 if phone else 1
    who = "[field0]" if phone else "[$from]"

    def invite(n: int, auth: bool) -> str:
        return _send(f"""
      INVITE sip:[service]@[$domain] SIP/2.0
      Via: SIP/2.0/[transport] [local_ip]:[local_port];branch=[branch]
      From: <sip:{who}@[$domain]>;tag=[pid]sim[call_number]
      To: <sip:[service]@[$domain]>
      Call-ID: [call_id]
      CSeq: {n} INVITE
      Contact: <sip:{who}@[local_ip]:[local_port];transport=[transport]>
{"      [field1]" + chr(10) if auth else ""}      Max-Forwards: 70
      User-Agent: {AGENT}
      X-Sim-Answer: [$answer]
      X-Sim-Ring: [$ring]
      Content-Type: application/sdp
      Content-Length: [len]
""" + SDP)

    def within(method: str, extra: str = "") -> str:
        return _send(f"""
      {method} [next_url] SIP/2.0
      [routes]
      Via: SIP/2.0/[transport] [local_ip]:[local_port];branch=[branch]
      From: <sip:{who}@[$domain]>;tag=[pid]sim[call_number]
      To: <sip:[service]@[$domain]>[peer_tag_param]
      Call-ID: [call_id]
      CSeq: [cseq] {method}
      Max-Forwards: 70
""" + (extra or "      Content-Length: 0"), retrans=method != "ACK")

    def early(method: str) -> str:
        """Within the INVITE's own transaction (the same Via branch): the ACK to a challenge or to a 487, and a CANCEL."""
        return _send(f"""
      {method} sip:[service]@[$domain] SIP/2.0
      [last_Via:]
      From: <sip:{who}@[$domain]>;tag=[pid]sim[call_number]
      {"[last_To:]" if method == "ACK" else "To: <sip:[service]@[$domain]>"}
      [last_Call-ID:]
      CSeq: {"[cseq]" if method == "ACK" else cseq} {method}
      Max-Forwards: 70
      Content-Length: 0""", retrans=method != "ACK")

    s = (HEAD + f'<scenario name="{name(phone, digit, speak, cancel)[:-4]}">\n  <Global variables="domain,{"" if phone else "from,"}answer,ring'
         + f'{",digit" if digit else ""}"/>\n' + invite(1, False))
    s += '  <recv response="100" optional="true"/>\n'
    if phone:
        s += '  <recv response="407" auth="true"/>\n' + early("ACK").replace("CSeq: [cseq] ACK", "CSeq: 1 ACK") + invite(2, True)
        s += '  <recv response="100" optional="true"/>\n'
    gives_up = ' ontimeout="cancel"' if cancel else ""         # the timeout is the waiting message's, whichever of these it is
    s += f'  <recv response="180" optional="true"{gives_up}/>\n  <recv response="183" optional="true"{gives_up}/>\n'
    s += f'  <recv response="200" rrs="true"{gives_up}/>\n' + within("ACK")
    if cancel:          # answered after all (a voicemail box, say): hang up
        s += (within("BYE") + '  <recv response="200" next="done"/>\n\n  <label id="cancel"/>\n' + early("CANCEL")
              + '  <recv response="200"/>\n  <recv response="487"/>\n' + early("ACK").replace("CSeq: [cseq] ACK", f"CSeq: {cseq} ACK")
              + '\n  <label id="done"/>\n  <nop/>\n</scenario>\n')
        return s
    if speak:
        s += f'  <nop>\n    <action>\n      <exec rtp_stream="{tone},-1,0"/>\n    </action>\n  </nop>\n'
    if digit:
        s += ('  <pause milliseconds="1500"/>\n'
              + within("INFO", "      Content-Type: application/dtmf-relay\n      Content-Length: [len]\n\n      Signal=[$digit]\n      Duration=160")
              + '  <recv response="200"/>\n')
    return s + "  <pause/>\n" + within("BYE") + '  <recv response="200" crlf="true"/>\n</scenario>\n'


def name(phone: bool, digit: bool = False, speak: bool = False, cancel: bool = False) -> str:
    return "sim-" + ("phone" if phone else "carrier") + ("-digit" if digit else "") + ("-speak" if speak else "") + ("-cancel" if cancel else "") + ".xml"


def all_(tone: str = "/scenarios/tone-ulaw.wav") -> Dict[str, str]:
    """Every scenario by file name."""
    out = {"sim-register.xml": register(), "sim-answer.xml": answer()}
    for phone in (True, False):
        out[name(phone)] = caller(phone, tone=tone)
        out[name(phone, cancel=True)] = caller(phone, cancel=True, tone=tone)
        out[name(phone, digit=True)] = caller(phone, digit=True, tone=tone)
        out[name(phone, speak=True)] = caller(phone, speak=True, tone=tone)
        out[name(phone, digit=True, speak=True)] = caller(phone, digit=True, speak=True, tone=tone)
    return out


def write(directory: str, tone: str = "/scenarios/tone-ulaw.wav") -> None:
    os.makedirs(directory, exist_ok=True)
    for file, text in all_(tone).items():
        with open(os.path.join(directory, file), "w") as f:
            f.write(text)


if __name__ == "__main__":
    import sys
    write(sys.argv[1])
