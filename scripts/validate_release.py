"""Fail a release when user-visible Windows version metadata disagrees."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _match(path: str, pattern: str) -> str:
    text = (ROOT / path).read_text(encoding="utf-8")
    found = re.search(pattern, text)
    if not found:
        raise RuntimeError(f"Could not read version from {path}")
    return found.group(1)


def release_metadata() -> dict:
    versions = {
        "application": _match("xyra/app_constants.py", r'APP_VERSION\s*=\s*"Xyra Core ([0-9]+\.[0-9]+\.[0-9]+)"'),
        "windows_file": _match("version_info.txt", r'StringStruct\("FileVersion",\s*"([0-9]+\.[0-9]+\.[0-9]+)"\)'),
        "windows_product": _match("version_info.txt", r'StringStruct\("ProductVersion",\s*"([0-9]+\.[0-9]+\.[0-9]+)"\)'),
        "manifest": _match("app.manifest", r'<assemblyIdentity\s+version="([0-9]+\.[0-9]+\.[0-9]+)\.0"'),
        "spec_version_file": _match("Xyra.spec", r'version="([^"]+)"'),
    }
    expected = versions["application"]
    comparable = {key: value for key, value in versions.items() if key != "spec_version_file"}
    mismatches = {key: value for key, value in comparable.items() if value != expected}
    if mismatches:
        details = ", ".join(f"{key}={value}" for key, value in mismatches.items())
        raise RuntimeError(f"Release versions disagree with {expected}: {details}")
    if versions["spec_version_file"] != "version_info.txt":
        raise RuntimeError("Xyra.spec must embed version_info.txt")
    return {"version": expected, "versions": versions}


if __name__ == "__main__":
    try:
        print(json.dumps(release_metadata(), indent=2))
    except Exception as exc:
        print(f"Release validation failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
