import json
import os

from app_constants import CONFIG_FILE, ICONS_POS_FILE
from secret_storage import load_password, save_password, keyring_is_available


def load_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            if not isinstance(cfg, dict):
                return {}

            needs_secret_migration = (
                "ssh_password" in cfg
                or "ssh_password_enc" in cfg
                or (cfg.get("secret_backend") == "dpapi" and keyring_is_available())
            )

            cfg["ssh_password"] = load_password(cfg)
            if cfg.get("ssh_password") and needs_secret_migration:
                cfg["_migrate_secret_storage"] = True

            return cfg
        except Exception:
            return {}
    return {}


def save_config(cfg: dict):
    try:
        cfg_to_save = dict(cfg or {})
        cfg_to_save.pop("_migrate_secret_storage", None)
        password = cfg_to_save.pop("ssh_password", "") or ""
        cfg_to_save.pop("secret_backend", None)
        cfg_to_save.pop("secret_key", None)
        cfg_to_save.pop("ssh_password_enc", None)
        cfg_to_save.pop("ssh_password", None)

        secret_meta = save_password(cfg_to_save, password)
        if secret_meta:
            cfg_to_save.update(secret_meta)

        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg_to_save, f, indent=2)
    except Exception as e:
        print("Cannot save config:", e)


def load_icons_pos():
    if os.path.exists(ICONS_POS_FILE):
        try:
            with open(ICONS_POS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def save_icons_pos(data):
    try:
        with open(ICONS_POS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        print("Cannot save icons positions:", e)
