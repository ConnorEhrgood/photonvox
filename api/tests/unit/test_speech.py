"""Text-to-speech (app/speech, decision 30): the voices, the cache key, Google's provider (its request and its failures), and the greeting a
menu names."""
import base64
import copy

import httpx
import pytest

from app import speech
from app.document.model import PhoneSystem
from app.engine import fusionpbx
from app.speech.google import GoogleSpeech, SpeechError
from tests.unit.test_compiler import plan
from tests.unit.test_document import SAMPLE

WAV = b"RIFF\x24\x00\x00\x00WAVEfmt " + b"\x00" * 28


def test_the_voices_include_men_women_and_spanish_and_the_default_is_one_of_them():
    labels = " ".join(v["label"] for v in speech.VOICES.values())
    assert "female" in labels and "male)" in labels and any(v["language"] == "es-US" for v in speech.VOICES.values())
    assert speech.DEFAULT_VOICE in speech.VOICES


def test_the_same_words_in_the_same_voice_have_one_file_and_anything_else_another():
    a = speech.file_name("Thanks for calling.", "en-US-Chirp3-HD-Kore")
    assert a == speech.file_name("Thanks for calling.", "en-US-Chirp3-HD-Kore") and a.startswith("photonvox-") and a.endswith(".wav")
    assert a != speech.file_name("Thanks for calling!", "en-US-Chirp3-HD-Kore") != speech.file_name("Thanks for calling.", "en-US-Chirp3-HD-Charon")


def test_google_is_asked_for_telephony_audio_in_the_voice_with_the_key_in_a_header():
    seen = {}

    def handler(req):
        seen["req"] = req
        return httpx.Response(200, json={"audioContent": base64.b64encode(WAV).decode()})

    g = GoogleSpeech("k-123", httpx.Client(transport=httpx.MockTransport(handler)))
    assert g.synthesize("Hello", "es-US-Chirp3-HD-Kore") == WAV
    req = seen["req"]
    body = req.read().decode()
    assert req.headers["X-Goog-Api-Key"] == "k-123" and "key=" not in str(req.url)
    assert '"languageCode":"es-US"' in body.replace(" ", "") and "telephony-class-application" in body and '"sampleRateHertz":16000' in body.replace(" ", "")


@pytest.mark.parametrize("response,voice", [
    (httpx.Response(403, json={"error": {"message": "API key not valid"}}), "en-US-Chirp3-HD-Kore"),
    (httpx.Response(200, json={"audioContent": base64.b64encode(b"ID3 mp3").decode()}), "en-US-Chirp3-HD-Kore"),
    (None, "fr-FR-Chirp3-HD-Kore"),
])
def test_a_refusal_an_unexpected_format_or_an_unknown_voice_is_an_error_without_the_key(response, voice):
    g = GoogleSpeech("k-secret", httpx.Client(transport=httpx.MockTransport(lambda r: response)))
    with pytest.raises(SpeechError) as e:
        g.synthesize("Hello", voice)
    assert "k-secret" not in str(e.value)


def test_a_menu_names_its_spoken_greeting_only_when_greetings_were_spoken():
    tgt = fusionpbx.Target("0b5e8c1a-0000-4000-8000-000000000001", "0b5e8c1a-0000-4000-8000-0000000000d0", {"htc": "0b5e8c1a-0000-4000-8000-0000000000a1", "upstream-b": "0b5e8c1a-0000-4000-8000-0000000000a2"})
    menu = lambda b: next(r for r in b.rows["v_ivr_menus"])
    assert menu(fusionpbx.build(plan(), tgt))["ivr_menu_greet_long"] is None
    spoken = fusionpbx.build(plan(), fusionpbx.Target(tgt.phone_system_id, tgt.domain_uuid, tgt.gateways, True))
    p = plan()
    assert menu(spoken)["ivr_menu_greet_long"] == speech.file_name(p["ivr_menus"][0]["greeting"], p["voice"])


def test_the_document_takes_only_known_voices():
    d = copy.deepcopy(SAMPLE)
    d["voice"] = "en-US-Chirp3-HD-Charon"
    assert PhoneSystem.model_validate(d).voice == "en-US-Chirp3-HD-Charon"
    d["voice"] = "en-GB-Standard-A"
    with pytest.raises(ValueError):
        PhoneSystem.model_validate(d)
