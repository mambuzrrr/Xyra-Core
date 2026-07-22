import configparser
import json
import os
import sqlite3
from contextlib import contextmanager

from xyra.app_constants import CONFIG_FILE, GUI_CONFIG_FILE, ICONS_POS_FILE, STATE_DB_FILE
from xyra.secret_storage import clear_password, load_password, save_password


GUI_DEFAULTS = {
    "background": "",
    "icon_pack_key": "",
    "icon_pack_path": "",
    "window_width": 1600,
    "window_height": 900,
    "show_favorites_only": False,
}

STATE_DEFAULTS = {
    "favorites": [],
    "recent_paths": [],
    "start_path": ".",
    "connection_mode": "none",
    "ssh_profile_name": "",
    "putty_path": "",
    "termius_path": "",
    "server_workspaces": {},
    "update_channel": "stable",
    "automatic_update_checks": True,
}


def _load_profile(profile: dict) -> dict:
    prof = dict(profile or {})
    prof["ssh_password"] = load_password(prof)
    return prof


def _save_profile(profile: dict) -> dict:
    prof = dict(profile or {})
    password = prof.pop("ssh_password", "") or ""
    prof.pop("secret_backend", None)
    prof.pop("secret_key", None)
    prof.pop("ssh_password_enc", None)
    secret_meta = save_password(prof, password)
    if secret_meta:
        prof.update(secret_meta)
    return prof


def load_config():
    gui_cfg = _load_gui_config()
    state_cfg = _load_state_config()
    cfg = {}
    cfg.update(gui_cfg)
    cfg.update(state_cfg)
    cfg["_migrate_storage_layout"] = (
        os.path.exists(CONFIG_FILE) and not os.path.exists(GUI_CONFIG_FILE)
    )
    return cfg


def save_config(cfg: dict):
    try:
        cfg_data = dict(cfg or {})
        cfg_data.pop("_migrate_secret_storage", None)
        cfg_data.pop("_migrate_storage_layout", None)
        _save_gui_config(cfg_data)
        _save_state_config(cfg_data)
    except Exception as e:
        print("Cannot save config:", e)


def save_recent_paths(paths):
    try:
        with _state_db() as con:
            _init_state_db(con)
            _state_set(con, "recent_paths", json.dumps(paths or []))
            con.commit()
    except Exception as e:
        print("Cannot save recent paths:", e)


def save_favorites(paths):
    try:
        with _state_db() as con:
            _init_state_db(con)
            _state_set(con, "favorites", json.dumps(paths or []))
            con.commit()
    except Exception as e:
        print("Cannot save favorites:", e)


def save_server_workspace(identity: str, workspace: dict):
    if not identity:
        return
    try:
        with _state_db() as con:
            _init_state_db(con)
            con.execute("BEGIN IMMEDIATE")
            workspaces = _json_state_get(con, "server_workspaces", {})
            if not isinstance(workspaces, dict):
                workspaces = {}
            workspaces[str(identity)] = dict(workspace or {})
            _state_set(con, "server_workspaces", json.dumps(workspaces))
            con.commit()
    except Exception as e:
        print("Cannot save server workspace:", e)


def load_icons_pos():
    try:
        with _state_db() as con:
            _init_state_db(con)
            _migrate_legacy_state(con)
            rows = con.execute(
                "SELECT folder_path, positions_json FROM icon_positions"
            ).fetchall()

        data = {}
        for folder_path, positions_json in rows:
            try:
                data[folder_path] = json.loads(positions_json)
            except Exception:
                data[folder_path] = {}
        return data
    except Exception as e:
        print("Cannot load icons positions:", e)
        return {}


def save_icons_pos(data):
    try:
        with _state_db() as con:
            _init_state_db(con)
            con.execute("DELETE FROM icon_positions")
            for folder_path, positions in (data or {}).items():
                con.execute(
                    "INSERT OR REPLACE INTO icon_positions (folder_path, positions_json) VALUES (?, ?)",
                    (str(folder_path), json.dumps(positions or {})),
                )
            con.commit()
    except Exception as e:
        print("Cannot save icons positions:", e)


def _load_gui_config():
    cfg = {
        "background": GUI_DEFAULTS["background"],
        "icon_pack_key": GUI_DEFAULTS["icon_pack_key"],
        "icon_pack_path": GUI_DEFAULTS["icon_pack_path"],
        "window_size": [GUI_DEFAULTS["window_width"], GUI_DEFAULTS["window_height"]],
        "show_favorites_only": GUI_DEFAULTS["show_favorites_only"],
    }

    parser = configparser.ConfigParser()
    if not os.path.exists(GUI_CONFIG_FILE):
        return cfg

    try:
        parser.read(GUI_CONFIG_FILE, encoding="utf-8")
        if parser.has_section("window"):
            width = parser.getint("window", "width", fallback=GUI_DEFAULTS["window_width"])
            height = parser.getint("window", "height", fallback=GUI_DEFAULTS["window_height"])
            cfg["window_size"] = [max(200, width), max(200, height)]
        if parser.has_section("display"):
            cfg["background"] = parser.get("display", "background", fallback=GUI_DEFAULTS["background"])
            cfg["icon_pack_key"] = parser.get("display", "icon_pack_key", fallback=GUI_DEFAULTS["icon_pack_key"])
            cfg["icon_pack_path"] = parser.get("display", "icon_pack_path", fallback=GUI_DEFAULTS["icon_pack_path"])
        if parser.has_section("view"):
            cfg["show_favorites_only"] = parser.getboolean(
                "view",
                "show_favorites_only",
                fallback=GUI_DEFAULTS["show_favorites_only"],
            )
    except Exception:
        pass

    if not os.path.exists(GUI_CONFIG_FILE) and os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                legacy = json.load(f)
            if isinstance(legacy, dict):
                bg = legacy.get("background")
                if isinstance(bg, str):
                    cfg["background"] = bg
                icon_pack_path = legacy.get("icon_pack_path")
                if isinstance(icon_pack_path, str):
                    cfg["icon_pack_path"] = icon_pack_path
                icon_pack_key = legacy.get("icon_pack_key")
                if isinstance(icon_pack_key, str):
                    cfg["icon_pack_key"] = icon_pack_key
                ws = legacy.get("window_size")
                if isinstance(ws, (list, tuple)) and len(ws) == 2:
                    cfg["window_size"] = [max(200, int(ws[0])), max(200, int(ws[1]))]
                cfg["show_favorites_only"] = bool(legacy.get("show_favorites_only", cfg["show_favorites_only"]))
        except Exception:
            pass
    return cfg


def _save_gui_config(cfg: dict):
    parser = configparser.ConfigParser()
    window_size = cfg.get("window_size") or [GUI_DEFAULTS["window_width"], GUI_DEFAULTS["window_height"]]
    width = GUI_DEFAULTS["window_width"]
    height = GUI_DEFAULTS["window_height"]
    if isinstance(window_size, (list, tuple)) and len(window_size) == 2:
        try:
            width = max(200, int(window_size[0]))
            height = max(200, int(window_size[1]))
        except Exception:
            pass

    parser["window"] = {
        "width": str(width),
        "height": str(height),
    }
    parser["display"] = {
        "background": str(cfg.get("background") or ""),
        "icon_pack_key": str(cfg.get("icon_pack_key") or ""),
        "icon_pack_path": str(cfg.get("icon_pack_path") or ""),
    }
    parser["view"] = {
        "show_favorites_only": "true" if cfg.get("show_favorites_only") else "false",
    }

    with open(GUI_CONFIG_FILE, "w", encoding="utf-8") as f:
        parser.write(f)


def _load_state_config():
    cfg = dict(STATE_DEFAULTS)
    try:
        with _state_db() as con:
            _init_state_db(con)
            _migrate_legacy_state(con)
            cfg["favorites"] = _json_state_get(con, "favorites", [])
            cfg["recent_paths"] = _json_state_get(con, "recent_paths", [])
            cfg["start_path"] = _text_state_get(con, "start_path", STATE_DEFAULTS["start_path"])
            cfg["connection_mode"] = _text_state_get(con, "connection_mode", STATE_DEFAULTS["connection_mode"])
            cfg["ssh_profile_name"] = _text_state_get(con, "ssh_profile_name", STATE_DEFAULTS["ssh_profile_name"])
            cfg["putty_path"] = _text_state_get(con, "putty_path", STATE_DEFAULTS["putty_path"])
            cfg["termius_path"] = _text_state_get(con, "termius_path", STATE_DEFAULTS["termius_path"])
            cfg["server_workspaces"] = _json_state_get(con, "server_workspaces", {})
            channel = _text_state_get(con, "update_channel", STATE_DEFAULTS["update_channel"])
            cfg["update_channel"] = channel if channel in ("stable", "prerelease") else "stable"
            cfg["automatic_update_checks"] = _text_state_get(
                con, "automatic_update_checks", "1"
            ) != "0"
            cfg["ssh_profiles"] = _load_profiles_from_db(con)
            active_profile = _resolve_active_profile(cfg)
            cfg.update(active_profile)
    except Exception:
        cfg["ssh_profiles"] = []
    return cfg


def _save_state_config(cfg: dict):
    with _state_db() as con:
        _init_state_db(con)

        _state_set(con, "favorites", json.dumps(cfg.get("favorites", [])))
        _state_set(con, "recent_paths", json.dumps(cfg.get("recent_paths", [])))
        _state_set(con, "start_path", str(cfg.get("start_path") or "."))
        _state_set(con, "connection_mode", str(cfg.get("connection_mode") or "none"))
        _state_set(con, "ssh_profile_name", str(cfg.get("ssh_profile_name") or cfg.get("profile_name") or ""))
        _state_set(con, "putty_path", str(cfg.get("putty_path") or ""))
        _state_set(con, "termius_path", str(cfg.get("termius_path") or ""))
        channel = str(cfg.get("update_channel") or "stable")
        _state_set(con, "update_channel", channel if channel in ("stable", "prerelease") else "stable")
        _state_set(con, "automatic_update_checks", "1" if cfg.get("automatic_update_checks", True) else "0")
        profiles = cfg.get("ssh_profiles")
        if isinstance(profiles, list):
            _save_profiles_to_db(con, profiles)
        con.commit()


@contextmanager
def _state_db():
    con = sqlite3.connect(STATE_DB_FILE, timeout=5.0)
    con.execute("PRAGMA busy_timeout = 5000")
    try:
        yield con
    finally:
        con.close()


def _init_state_db(con):
    con.execute("""
        CREATE TABLE IF NOT EXISTS icon_positions (
            folder_path TEXT PRIMARY KEY,
            positions_json TEXT NOT NULL
        )
    """)
    con.execute("""
        CREATE TABLE IF NOT EXISTS app_state (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
    """)
    con.execute("""
        CREATE TABLE IF NOT EXISTS ssh_profiles (
            profile_name TEXT PRIMARY KEY,
            ssh_host TEXT,
            ssh_port INTEGER,
            ssh_username TEXT,
            ssh_key_path TEXT,
            ssh_root TEXT,
            secret_backend TEXT,
            secret_key TEXT,
            ssh_password_enc TEXT
        )
    """)
    con.commit()


def _migrate_legacy_state(con):
    _migrate_icons_json_to_db(con)
    _migrate_legacy_config_to_db(con)


def _migrate_icons_json_to_db(con):
    existing = con.execute("SELECT COUNT(*) FROM icon_positions").fetchone()[0]
    if existing > 0:
        return
    if not os.path.exists(ICONS_POS_FILE):
        return

    try:
        with open(ICONS_POS_FILE, "r", encoding="utf-8") as f:
            old_data = json.load(f)
        if not isinstance(old_data, dict):
            return

        for folder_path, positions in old_data.items():
            con.execute(
                "INSERT OR REPLACE INTO icon_positions (folder_path, positions_json) VALUES (?, ?)",
                (str(folder_path), json.dumps(positions or {})),
            )
        con.commit()
    except Exception:
        pass


def _migrate_legacy_config_to_db(con):
    has_state = con.execute("SELECT COUNT(*) FROM app_state").fetchone()[0] > 0
    has_profiles = con.execute("SELECT COUNT(*) FROM ssh_profiles").fetchone()[0] > 0
    if has_state or has_profiles:
        return
    if not os.path.exists(CONFIG_FILE):
        return

    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            legacy = json.load(f)
        if not isinstance(legacy, dict):
            return
    except Exception:
        return

    try:
        if "favorites" in legacy:
            _state_set(con, "favorites", json.dumps(legacy.get("favorites") or []))
        if "recent_paths" in legacy:
            _state_set(con, "recent_paths", json.dumps(legacy.get("recent_paths") or []))
        if "start_path" in legacy:
            _state_set(con, "start_path", str(legacy.get("start_path") or "."))
        if "connection_mode" in legacy:
            _state_set(con, "connection_mode", str(legacy.get("connection_mode") or "none"))

        active_profile_name = str(legacy.get("ssh_profile_name") or legacy.get("profile_name") or "")
        if active_profile_name:
            _state_set(con, "ssh_profile_name", active_profile_name)

        if "putty_path" in legacy:
            _state_set(con, "putty_path", str(legacy.get("putty_path") or ""))
        if "termius_path" in legacy:
            _state_set(con, "termius_path", str(legacy.get("termius_path") or ""))

        raw_profiles = legacy.get("ssh_profiles")
        profiles_to_migrate = []
        if isinstance(raw_profiles, list) and raw_profiles:
            for profile in raw_profiles:
                if isinstance(profile, dict):
                    profiles_to_migrate.append(profile)

        if not profiles_to_migrate and legacy.get("ssh_host") and legacy.get("ssh_username"):
            fallback_profile = {
                "profile_name": active_profile_name or "Default Server",
                "ssh_host": legacy.get("ssh_host") or "",
                "ssh_port": legacy.get("ssh_port", 22),
                "ssh_username": legacy.get("ssh_username") or "",
                "ssh_key_path": legacy.get("ssh_key_path") or "",
                "ssh_root": legacy.get("ssh_root") or "/",
                "secret_backend": legacy.get("secret_backend") or "",
                "secret_key": legacy.get("secret_key") or "",
                "ssh_password_enc": legacy.get("ssh_password_enc") or "",
            }
            if legacy.get("ssh_password"):
                fallback_profile["ssh_password"] = legacy.get("ssh_password") or ""
            profiles_to_migrate.append(fallback_profile)
            if not active_profile_name:
                _state_set(con, "ssh_profile_name", fallback_profile["profile_name"])

        if profiles_to_migrate:
            _save_profiles_to_db(con, profiles_to_migrate)

        con.commit()
    except Exception:
        pass


def _state_set(con, key: str, value: str):
    con.execute(
        "INSERT OR REPLACE INTO app_state (key, value) VALUES (?, ?)",
        (str(key), str(value)),
    )


def _text_state_get(con, key: str, default=""):
    row = con.execute("SELECT value FROM app_state WHERE key = ?", (key,)).fetchone()
    if not row:
        return default
    return row[0]


def _json_state_get(con, key: str, default):
    raw = _text_state_get(con, key, "")
    if not raw:
        return default
    try:
        return json.loads(raw)
    except Exception:
        return default


def _load_profiles_from_db(con):
    rows = con.execute("""
        SELECT profile_name, ssh_host, ssh_port, ssh_username, ssh_key_path, ssh_root,
               secret_backend, secret_key, ssh_password_enc
        FROM ssh_profiles
        ORDER BY profile_name COLLATE NOCASE
    """).fetchall()

    profiles = []
    for row in rows:
        profile = {
            "profile_name": row[0] or "",
            "ssh_host": row[1] or "",
            "ssh_port": int(row[2] or 22),
            "ssh_username": row[3] or "",
            "ssh_key_path": row[4] or "",
            "ssh_root": row[5] or "/",
            "secret_backend": row[6] or "",
            "secret_key": row[7] or "",
            "ssh_password_enc": row[8] or "",
        }
        if profile["ssh_host"] and profile["ssh_username"]:
            profiles.append(_load_profile(profile))
    return profiles


def _save_profiles_to_db(con, profiles):
    existing_profiles = _load_raw_profiles_from_db(con)
    for existing in existing_profiles:
        clear_password(existing)

    normalized_profiles = []
    seen = set()
    for profile in profiles:
        if not isinstance(profile, dict):
            continue
        saved = _save_profile(profile)
        profile_name = (saved.get("profile_name") or saved.get("ssh_host") or "").strip()
        if not profile_name or profile_name in seen:
            continue
        if not (saved.get("ssh_host") or "").strip() or not (saved.get("ssh_username") or "").strip():
            continue
        seen.add(profile_name)
        normalized_profiles.append(saved)

    con.execute("DELETE FROM ssh_profiles")
    for profile in normalized_profiles:
        con.execute("""
            INSERT OR REPLACE INTO ssh_profiles (
                profile_name, ssh_host, ssh_port, ssh_username, ssh_key_path,
                ssh_root, secret_backend, secret_key, ssh_password_enc
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            profile.get("profile_name") or "",
            profile.get("ssh_host") or "",
            int(profile.get("ssh_port", 22) or 22),
            profile.get("ssh_username") or "",
            profile.get("ssh_key_path") or "",
            profile.get("ssh_root") or "/",
            profile.get("secret_backend") or "",
            profile.get("secret_key") or "",
            profile.get("ssh_password_enc") or "",
        ))


def _load_raw_profiles_from_db(con):
    try:
        rows = con.execute("""
            SELECT profile_name, ssh_host, ssh_port, ssh_username, ssh_key_path, ssh_root,
                   secret_backend, secret_key, ssh_password_enc
            FROM ssh_profiles
        """).fetchall()
    except Exception:
        return []

    profiles = []
    for row in rows:
        profiles.append({
            "profile_name": row[0] or "",
            "ssh_host": row[1] or "",
            "ssh_port": int(row[2] or 22),
            "ssh_username": row[3] or "",
            "ssh_key_path": row[4] or "",
            "ssh_root": row[5] or "/",
            "secret_backend": row[6] or "",
            "secret_key": row[7] or "",
            "ssh_password_enc": row[8] or "",
        })
    return profiles


def _resolve_active_profile(cfg: dict):
    profiles = cfg.get("ssh_profiles", [])
    active_name = (cfg.get("ssh_profile_name") or "").strip()
    selected = None
    if active_name:
        for profile in profiles:
            if (profile.get("profile_name") or "").strip() == active_name:
                selected = profile
                break
    if not selected and profiles:
        selected = profiles[0]

    if not selected:
        return {
            "profile_name": "",
            "ssh_host": "",
            "ssh_port": 22,
            "ssh_username": "",
            "ssh_password": "",
            "ssh_key_path": "",
            "ssh_root": "/",
            "secret_backend": "",
            "secret_key": "",
        }

    return {
        "profile_name": selected.get("profile_name") or "",
        "ssh_host": selected.get("ssh_host") or "",
        "ssh_port": int(selected.get("ssh_port", 22) or 22),
        "ssh_username": selected.get("ssh_username") or "",
        "ssh_password": selected.get("ssh_password") or "",
        "ssh_key_path": selected.get("ssh_key_path") or "",
        "ssh_root": selected.get("ssh_root") or "/",
        "secret_backend": selected.get("secret_backend") or "",
        "secret_key": selected.get("secret_key") or "",
    }
