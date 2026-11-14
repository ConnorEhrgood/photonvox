"""Writes sipp/scenarios/dtmf-hash.pcap: one key, "#", as RFC 2833 telephone-events (payload type 101, event 11), the way a desk phone
sends it, for SIPp's play_pcap_audio (phone-answer-hash.xml: the person answering a door's call opens it). SIPp rewrites the addresses and
ports; only the RTP inside matters. Run once: python3 sipp/make-dtmf-pcap.py"""
import pathlib
import struct


def _ip_checksum(h: bytes) -> int:
    s = sum(struct.unpack("!10H", h))
    s = (s >> 16) + (s & 0xFFFF)
    return ~(s + (s >> 16)) & 0xFFFF


def packet(seq: int, marker: bool, end: bool, duration: int) -> bytes:
    rtp = struct.pack("!BBHII", 0x80, (0x80 if marker else 0) | 101, seq, 160000, 0x50484F54)
    rtp += struct.pack("!BBH", 11, (0x80 if end else 0) | 10, duration)          # event 11 = "#", volume 10
    udp = struct.pack("!HHHH", 40000, 40000, 8 + len(rtp), 0) + rtp
    ip = struct.pack("!BBHHHBBH4s4s", 0x45, 0, 20 + len(udp), seq, 0, 64, 17, 0, bytes([10, 0, 0, 1]), bytes([10, 0, 0, 2]))
    ip = ip[:10] + struct.pack("!H", _ip_checksum(ip)) + ip[12:]
    return b"\x00" * 12 + b"\x08\x00" + ip + udp


frames = [packet(1, True, False, 160)] + [packet(1 + i, False, False, 160 * (i + 1)) for i in range(1, 6)]
frames += [packet(7 + i, False, True, 1120) for i in range(3)]                    # the end, three times (RFC 4733 §2.5.1.4)
out = struct.pack("<IHHiIII", 0xA1B2C3D4, 2, 4, 0, 0, 65535, 1)
for i, f in enumerate(frames):
    out += struct.pack("<IIII", 1, i * 20000, len(f), len(f)) + f
pathlib.Path(__file__).with_name("scenarios").joinpath("dtmf-hash.pcap").write_bytes(out)
