"""Google Cloud Text-to-Speech (decision 30: Chirp 3 HD), over its REST API with an API key restricted to that API and to PhotonVox's
server's address (docs: ARCHITECTURE §8a lists what Connor creates). The telephony audio profile shapes the sound for phone lines."""
from __future__ import annotations

import base64
from typing import Optional

import httpx

from app.speech import SAMPLE_RATE, VOICES

URL = "https://texttospeech.googleapis.com/v1/text:synthesize"


class SpeechError(Exception):
    pass


class GoogleSpeech:
    def __init__(self, api_key: str, client: Optional[httpx.Client] = None) -> None:
        self.api_key = api_key
        self.client = client or httpx.Client(timeout=30)

    def synthesize(self, text: str, voice: str) -> bytes:
        if voice not in VOICES:
            raise SpeechError(f"unknown voice {voice!r}")
        r = self.client.post(URL, headers={"X-Goog-Api-Key": self.api_key}, json={
            "input": {"text": text},
            "voice": {"languageCode": VOICES[voice]["language"], "name": voice},
            "audioConfig": {"audioEncoding": "LINEAR16", "sampleRateHertz": SAMPLE_RATE, "effectsProfileId": ["telephony-class-application"]},
        })
        if r.status_code != 200:
            raise SpeechError(f"text-to-speech: HTTP {r.status_code}")      # never the key, never the text
        audio = base64.b64decode(r.json()["audioContent"])
        if audio[:4] != b"RIFF":                                            # LINEAR16 comes back as a WAV file
            raise SpeechError("text-to-speech: not a WAV file")
        return audio
