"""contract/phone-system: the JSON Schema is generated from app/document/model.py and must match it; every sample validates against it and the
model. The schema is what the web app and partners' tools build documents against."""
import json
import pathlib

import jsonschema

from app.document.model import PhoneSystem

ROOT = pathlib.Path(__file__).resolve().parents[3] / "contract/phone-system"


def test_the_schema_file_is_generated_from_the_model():
    schema = PhoneSystem.model_json_schema()
    schema["$id"] = "https://vox.photonind.com/contract/phone-system/v1.schema.json"
    schema["title"] = "PhotonVox phone-system document, version 1"
    assert json.loads((ROOT / "schema.json").read_text()) == json.loads(json.dumps(schema)), "regenerate contract/phone-system/schema.json"


def test_every_sample_validates_against_the_schema_and_the_model():
    schema = json.loads((ROOT / "schema.json").read_text())
    samples = sorted(ROOT.glob("*.sample.json"))
    assert samples
    for s in samples:
        data = json.loads(s.read_text())
        jsonschema.validate(data, schema)
        PhoneSystem.model_validate(data)
