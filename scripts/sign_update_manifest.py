"""Create an Ed25519-authenticated Xyra update manifest."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import keyring
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from xyra.updater import canonical_signed_payload, numeric_version, require_https


KEYRING_SERVICE = "Xyra Release Signing"
KEYRING_ACCOUNT = "update-manifest-ed25519-v1"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--channel", choices=("stable", "prerelease"), required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--artifact", required=True)
    parser.add_argument("--url", required=True)
    parser.add_argument("--notes-url", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    numeric_version(args.version)
    artifact_path = Path(args.artifact).resolve(strict=True)
    artifact_url = require_https(args.url, "Artifact URL")
    notes_url = require_https(args.notes_url, "Release notes URL")
    private_b64 = keyring.get_password(KEYRING_SERVICE, KEYRING_ACCOUNT)
    if not private_b64:
        raise RuntimeError("Xyra update signing key is missing from Windows Credential Manager.")
    private_key = Ed25519PrivateKey.from_private_bytes(base64.b64decode(private_b64, validate=True))

    digest = hashlib.sha256()
    with artifact_path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    signed = {
        "schemaVersion": 1,
        "channel": args.channel,
        "version": args.version,
        "publishedAt": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "notesUrl": notes_url,
        "artifact": {
            "filename": artifact_path.name,
            "url": artifact_url,
            "bytes": artifact_path.stat().st_size,
            "sha256": digest.hexdigest(),
        },
    }
    envelope = {
        "signed": signed,
        "signature": base64.b64encode(private_key.sign(canonical_signed_payload(signed))).decode("ascii"),
    }
    output = Path(args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=output.name, suffix=".tmp", dir=output.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(envelope, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
        os.replace(temp_name, output)
    except Exception:
        try:
            os.remove(temp_name)
        except OSError:
            pass
        raise


if __name__ == "__main__":
    main()
