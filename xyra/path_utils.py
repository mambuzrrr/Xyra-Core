import os


def split_ext(name: str) -> str:
    return os.path.splitext(name)[1].lower()


def mb_size(path: str) -> float:
    try:
        return os.path.getsize(path) / (1024 * 1024)
    except Exception:
        return 0.0


def normalize_api_path(p: str) -> str:
    if not p:
        return "."
    p = p.replace("\\", "/").strip()
    if p == "/":
        return "."
    while p.startswith("/"):
        p = p[1:]
    return p or "."


def join_server_path(base: str, name: str) -> str:
    base = normalize_api_path(base)
    name = (name or "").replace("\\", "/").strip("/")
    if base in (".", ""):
        return name
    return base.rstrip("/") + "/" + name


def join_remote_path(base: str, name: str) -> str:
    base = normalize_api_path(base)
    name = (name or "").replace("\\", "/").strip("/")
    if base in (".", ""):
        return name
    return base.rstrip("/") + "/" + name


def is_valid_new_name(name: str) -> bool:
    if not name or name.strip() == "":
        return False
    if "/" in name or "\\" in name:
        return False
    return True
