"""Text-to-speech for greetings (decision 30): spoken once, when the phone system is published, and kept, so a call never waits on the
provider and the engine plays a file. The provider is behind `Speech`; Photon's is Google Cloud Text-to-Speech, Chirp 3 HD (app/speech/google.py).
Audio is cached by a hash of the voice and the text: the same words in the same voice are never paid for twice."""
from __future__ import annotations

import hashlib
from typing import Dict, Protocol

# The voices integrators choose from (proposed 2026-11-13 for the listening test on real phones; Google's Chirp 3 HD names).
VOICES: Dict[str, Dict[str, str]] = {
    "en-US-Chirp3-HD-Kore": {"label": "Kore (US English, female)", "language": "en-US"},
    "en-US-Chirp3-HD-Charon": {"label": "Charon (US English, male)", "language": "en-US"},
    "en-US-Chirp3-HD-Aoede": {"label": "Aoede (US English, female, lighter)", "language": "en-US"},
    "es-US-Chirp3-HD-Kore": {"label": "Kore (US Spanish, female)", "language": "es-US"},
}
DEFAULT_VOICE = "en-US-Chirp3-HD-Kore"
SAMPLE_RATE = 16000          # wideband; FreeSWITCH resamples to 8 kHz for G.711 calls


class Speech(Protocol):
    def synthesize(self, text: str, voice: str) -> bytes:
        """A WAV file (16-bit PCM, SAMPLE_RATE, mono) of `text` spoken in `voice`."""


def audio_key(text: str, voice: str) -> str:
    return hashlib.sha256(f"{voice}\n{text}".encode()).hexdigest()[:32]


def file_name(text: str, voice: str) -> str:
    """The greeting's file in the domain's recordings directory on the engine (FusionPBX looks a bare name up there)."""
    return f"photonvox-{audio_key(text, voice)}.wav"
