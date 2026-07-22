"""Stable profile identity and per-server workspace helpers."""

import hashlib
import posixpath

from xyra.path_utils import normalize_api_path


PROFILE_FIELDS = (
    "ssh_host", "ssh_port", "ssh_username", "ssh_password", "ssh_key_path", "ssh_root",
)
PROFILE_ACCENTS = ("#8bc7a8", "#d8c39a", "#c7b7d8", "#dfb86d", "#9fc4d8", "#d5a7a7")


def profile_identity(profile: dict | None) -> str:
    profile = profile or {}
    host = str(profile.get("ssh_host") or "").strip().lower()
    user = str(profile.get("ssh_username") or "").strip().lower()
    root = normalize_api_path(str(profile.get("ssh_root") or "."))
    try:
        port = int(profile.get("ssh_port", 22) or 22)
    except (TypeError, ValueError):
        port = 22
    material = f"{user}@{host}:{port}/{root}".encode("utf-8", errors="replace")
    return hashlib.sha256(material).hexdigest()[:20]


def profile_display_name(profile: dict | None) -> str:
    profile = profile or {}
    return str(
        profile.get("profile_name")
        or profile.get("ssh_host")
        or "Remote server"
    ).strip()


def profile_accent(profile: dict | None) -> str:
    identity = profile_identity(profile)
    return PROFILE_ACCENTS[int(identity[:8], 16) % len(PROFILE_ACCENTS)]


def active_profile_data(profile: dict | None) -> dict:
    profile = dict(profile or {})
    data = {field: profile.get(field, "") for field in PROFILE_FIELDS}
    data["ssh_port"] = int(profile.get("ssh_port", 22) or 22)
    data["ssh_root"] = str(profile.get("ssh_root") or "/")
    data["ssh_profile_name"] = profile_display_name(profile)
    return data


def clean_workspace(data: dict | None) -> dict:
    data = data if isinstance(data, dict) else {}

    def paths(value, limit):
        result = []
        for item in value if isinstance(value, list) else []:
            normalized = normalize_api_path(posixpath.normpath(str(item or "").replace("\\", "/")))
            if normalized not in result:
                result.append(normalized)
            if len(result) >= limit:
                break
        return result

    return {
        "current_path": normalize_api_path(posixpath.normpath(str(data.get("current_path") or data.get("start_path") or ".").replace("\\", "/"))),
        "start_path": normalize_api_path(posixpath.normpath(str(data.get("start_path") or ".").replace("\\", "/"))),
        "favorites": paths(data.get("favorites", []), 50),
        "recent_paths": paths(data.get("recent_paths", []), 10),
    }
