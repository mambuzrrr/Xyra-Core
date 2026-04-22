import base64
import ctypes
from ctypes import wintypes

try:
    import keyring
except Exception:
    keyring = None


SERVICE_NAME = "XyraSSH"


def _is_windows() -> bool:
    return hasattr(ctypes, "windll")


if _is_windows():
    class DATA_BLOB(ctypes.Structure):
        _fields_ = [
            ("cbData", wintypes.DWORD),
            ("pbData", ctypes.POINTER(ctypes.c_byte)),
        ]


def _blob_from_bytes(data: bytes):
    buffer = ctypes.create_string_buffer(data)
    blob = DATA_BLOB()
    blob.cbData = len(data)
    blob.pbData = ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte))
    return blob, buffer


def _bytes_from_blob(blob) -> bytes:
    if not blob.cbData:
        return b""
    return ctypes.string_at(blob.pbData, blob.cbData)


def protect_string(value: str) -> str:
    if not value:
        return ""
    if not _is_windows():
        return ""

    raw = value.encode("utf-8")
    in_blob, in_buffer = _blob_from_bytes(raw)
    out_blob = DATA_BLOB()

    ok = ctypes.windll.crypt32.CryptProtectData(
        ctypes.byref(in_blob),
        None,
        None,
        None,
        None,
        0,
        ctypes.byref(out_blob),
    )
    if not ok:
        return ""

    try:
        protected = _bytes_from_blob(out_blob)
        return base64.b64encode(protected).decode("ascii")
    finally:
        ctypes.windll.kernel32.LocalFree(out_blob.pbData)


def unprotect_string(value: str) -> str:
    if not value:
        return ""
    if not _is_windows():
        return ""

    try:
        raw = base64.b64decode(value)
    except Exception:
        return ""

    in_blob, in_buffer = _blob_from_bytes(raw)
    out_blob = DATA_BLOB()

    ok = ctypes.windll.crypt32.CryptUnprotectData(
        ctypes.byref(in_blob),
        None,
        None,
        None,
        None,
        0,
        ctypes.byref(out_blob),
    )
    if not ok:
        return ""

    try:
        plain = _bytes_from_blob(out_blob)
        return plain.decode("utf-8", errors="ignore")
    finally:
        ctypes.windll.kernel32.LocalFree(out_blob.pbData)


def _secret_account(cfg: dict) -> str:
    host = (cfg.get("ssh_host") or "").strip().lower()
    port = int(cfg.get("ssh_port", 22) or 22)
    user = (cfg.get("ssh_username") or "").strip().lower()
    root = (cfg.get("ssh_root") or "/root").strip()
    return f"{user}@{host}:{port}|{root}"


def keyring_is_available() -> bool:
    return keyring is not None


def load_password(cfg: dict) -> str:
    backend = cfg.get("secret_backend") or ""
    secret_key = cfg.get("secret_key") or _secret_account(cfg)

    if backend == "keyring" and keyring is not None and secret_key:
        try:
            value = keyring.get_password(SERVICE_NAME, secret_key)
            if value is not None:
                return value
        except Exception:
            pass

    encrypted = cfg.get("ssh_password_enc") or ""
    if encrypted:
        return unprotect_string(encrypted)

    return cfg.get("ssh_password") or ""


def save_password(cfg: dict, password: str) -> dict:
    password = password or ""
    secret_key = _secret_account(cfg)

    if not password:
        clear_password(cfg)
        return {}

    if keyring is not None:
        try:
            keyring.set_password(SERVICE_NAME, secret_key, password)
            return {
                "secret_backend": "keyring",
                "secret_key": secret_key,
            }
        except Exception:
            pass

    protected = protect_string(password)
    if protected:
        return {
            "secret_backend": "dpapi",
            "ssh_password_enc": protected,
        }

    return {}


def clear_password(cfg: dict):
    backend = cfg.get("secret_backend") or ""
    secret_key = cfg.get("secret_key") or _secret_account(cfg)

    if backend == "keyring" and keyring is not None and secret_key:
        try:
            keyring.delete_password(SERVICE_NAME, secret_key)
        except Exception:
            pass
