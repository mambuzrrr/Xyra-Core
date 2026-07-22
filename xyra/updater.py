"""Authenticated HTTPS update discovery and staging."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import ssl
import subprocess
import sys
import tempfile
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey


MAX_MANIFEST_BYTES = 256 * 1024
MAX_UPDATE_BYTES = 512 * 1024 * 1024
VERSION_RE = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")


@dataclass(frozen=True)
class UpdateArtifact:
    url: str
    sha256: str
    size: int
    filename: str


@dataclass(frozen=True)
class UpdateInfo:
    version: str
    channel: str
    published_at: str
    notes_url: str
    artifact: UpdateArtifact


def canonical_signed_payload(signed: dict) -> bytes:
    return json.dumps(
        signed, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def numeric_version(value: str) -> tuple[int, int, int]:
    text = str(value or "").strip()
    if not VERSION_RE.fullmatch(text):
        raise RuntimeError(f"Invalid update version: {text!r}")
    return tuple(int(part) for part in text.split("."))


def application_version(value: str) -> str:
    match = re.search(r"([0-9]+\.[0-9]+\.[0-9]+)", str(value or ""))
    if not match:
        raise RuntimeError("Current Xyra version is invalid.")
    return match.group(1)


def require_https(url: str, label: str) -> str:
    parsed = urlparse(str(url or "").strip())
    if parsed.scheme.lower() != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise RuntimeError(f"{label} must use a normal HTTPS URL.")
    return parsed.geturl()


class UpdateClient:
    def __init__(self, manifest_urls: dict[str, str], public_key_b64: str, *, timeout: float = 12):
        self.manifest_urls = dict(manifest_urls)
        try:
            raw_key = base64.b64decode(public_key_b64, validate=True)
            self.public_key = Ed25519PublicKey.from_public_bytes(raw_key)
        except Exception as exc:
            raise RuntimeError("Xyra update verification key is invalid.") from exc
        self.timeout = max(2.0, min(float(timeout), 60.0))
        self.ssl_context = ssl.create_default_context()

    def _open(self, url: str):
        request = urllib.request.Request(
            require_https(url, "Update URL"),
            headers={"User-Agent": "Xyra-Updater/1", "Accept": "application/json"},
        )
        response = urllib.request.urlopen(request, timeout=self.timeout, context=self.ssl_context)
        require_https(response.geturl(), "Final update URL")
        return response

    def fetch_manifest(self, channel: str) -> UpdateInfo:
        if channel not in ("stable", "prerelease"):
            raise RuntimeError("Update channel must be stable or prerelease.")
        url = self.manifest_urls.get(channel)
        if not url:
            raise RuntimeError(f"No manifest URL is configured for {channel} updates.")
        with self._open(url) as response:
            raw = response.read(MAX_MANIFEST_BYTES + 1)
        if len(raw) > MAX_MANIFEST_BYTES:
            raise RuntimeError("Update manifest is unexpectedly large.")
        try:
            envelope = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RuntimeError("Update manifest is not valid UTF-8 JSON.") from exc
        return self.verify_manifest(envelope, expected_channel=channel)

    def verify_manifest(self, envelope: dict, *, expected_channel: str) -> UpdateInfo:
        if not isinstance(envelope, dict) or set(envelope) != {"signed", "signature"}:
            raise RuntimeError("Update manifest envelope is invalid.")
        signed = envelope.get("signed")
        if not isinstance(signed, dict):
            raise RuntimeError("Update manifest payload is invalid.")
        try:
            signature = base64.b64decode(envelope["signature"], validate=True)
            self.public_key.verify(signature, canonical_signed_payload(signed))
        except (InvalidSignature, ValueError, TypeError) as exc:
            raise RuntimeError("Update manifest signature is invalid.") from exc

        if signed.get("schemaVersion") != 1:
            raise RuntimeError("Update manifest schema is unsupported.")
        channel = signed.get("channel")
        if channel != expected_channel or channel not in ("stable", "prerelease"):
            raise RuntimeError("Update manifest channel does not match the request.")
        version = str(signed.get("version") or "")
        numeric_version(version)
        artifact_data = signed.get("artifact")
        if not isinstance(artifact_data, dict):
            raise RuntimeError("Update artifact metadata is missing.")
        artifact_url = require_https(artifact_data.get("url"), "Update download")
        notes_url = require_https(signed.get("notesUrl"), "Release notes")
        sha256 = str(artifact_data.get("sha256") or "").lower()
        if not re.fullmatch(r"[0-9a-f]{64}", sha256):
            raise RuntimeError("Update SHA-256 is invalid.")
        size = int(artifact_data.get("bytes") or 0)
        if size <= 0 or size > MAX_UPDATE_BYTES:
            raise RuntimeError("Update size is outside the safety limit.")
        filename = str(artifact_data.get("filename") or "")
        if filename != os.path.basename(filename) or not filename.lower().endswith(".exe"):
            raise RuntimeError("Update filename is unsafe.")
        return UpdateInfo(
            version=version,
            channel=channel,
            published_at=str(signed.get("publishedAt") or ""),
            notes_url=notes_url,
            artifact=UpdateArtifact(artifact_url, sha256, size, filename),
        )

    @staticmethod
    def is_newer(info: UpdateInfo, current_version: str) -> bool:
        return numeric_version(info.version) > numeric_version(application_version(current_version))

    def download(self, info: UpdateInfo, staging_dir: str, *, progress=None, cancelled=None) -> str:
        target_dir = Path(staging_dir).resolve()
        target_dir.mkdir(parents=True, exist_ok=True)
        final_path = target_dir / info.artifact.filename
        temp_fd, temp_name = tempfile.mkstemp(prefix=".xyra-update-", suffix=".part", dir=target_dir)
        os.close(temp_fd)
        digest = hashlib.sha256()
        received = 0
        try:
            request = urllib.request.Request(
                info.artifact.url,
                headers={"User-Agent": "Xyra-Updater/1", "Accept": "application/octet-stream"},
            )
            with urllib.request.urlopen(request, timeout=self.timeout, context=self.ssl_context) as response, open(temp_name, "wb") as output:
                require_https(response.geturl(), "Final download URL")
                while True:
                    if cancelled and cancelled():
                        raise RuntimeError("Update download cancelled.")
                    chunk = response.read(256 * 1024)
                    if not chunk:
                        break
                    received += len(chunk)
                    if received > info.artifact.size or received > MAX_UPDATE_BYTES:
                        raise RuntimeError("Update download exceeded its signed size.")
                    digest.update(chunk)
                    output.write(chunk)
                    if progress:
                        progress(received, info.artifact.size)
            if received != info.artifact.size:
                raise RuntimeError("Update size does not match the signed manifest.")
            if digest.hexdigest().lower() != info.artifact.sha256:
                raise RuntimeError("Update SHA-256 does not match the signed manifest.")
            os.replace(temp_name, final_path)
            return str(final_path)
        except Exception:
            try:
                os.remove(temp_name)
            except OSError:
                pass
            raise

    @staticmethod
    def launch_installer(path: str):
        if sys.platform != "win32":
            raise RuntimeError("Automatic installation is only supported on Windows.")
        installer = os.path.abspath(path)
        if not os.path.isfile(installer) or not installer.lower().endswith(".exe"):
            raise RuntimeError("Verified update installer is missing.")
        subprocess.Popen(
            [installer, "/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/CLOSEAPPLICATIONS"],
            close_fds=True,
        )
