"""The vendored directory client is the PhotonID directory's, byte for byte: re-copy it from photonid, never edit it here."""
import hashlib
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[2] / "photonid_directory_client"


def test_the_vendored_client_matches_its_recorded_checksums():
    lines = (ROOT / "SOURCE.sha256").read_text().splitlines()
    assert len(lines) == 5
    for line in lines:
        digest, name = line.split()
        assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == digest, f"{name} was edited here"
