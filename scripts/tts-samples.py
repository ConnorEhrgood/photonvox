#!/usr/bin/env python3
"""The listening test for decision 30: the same greeting in each proposed voice, as WAV files to play on real phones (G.711 and G.722).
Needs the Google Cloud Text-to-Speech API key Connor creates (ARCHITECTURE §8a):
    GOOGLE_TTS_API_KEY=... PYTHONPATH=api ~/.venvs/photonvox/bin/python scripts/tts-samples.py [out-dir]
About 1,000 characters in all: inside the free monthly allowance."""
import os
import pathlib
import sys

from app.speech import VOICES
from app.speech.google import GoogleSpeech

EN = "Thank you for calling Cedar Works. For the front desk, press 1. To leave a message, press 2. Our hours are eight to five, Monday to Friday."
ES = "Gracias por llamar a Cedar Works. Para la recepción, oprima 1. Para dejar un mensaje, oprima 2."

out = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "tts-samples")
out.mkdir(exist_ok=True)
g = GoogleSpeech(os.environ["GOOGLE_TTS_API_KEY"])
for voice, v in VOICES.items():
    path = out / f"{voice}.wav"
    path.write_bytes(g.synthesize(ES if v["language"] == "es-US" else EN, voice))
    print(path)
