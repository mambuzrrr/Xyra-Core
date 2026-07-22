"""Unix permission parsing, presentation and safety guidance."""

import stat


FILE_PERMISSION_PRESETS = (
    ("Standard file - readable by everyone", "0644"),
    ("Private file - owner only", "0600"),
    ("Executable or script", "0755"),
    ("Shared writable file", "0664"),
)

FOLDER_PERMISSION_PRESETS = (
    ("Standard folder - readable by everyone", "0755"),
    ("Private folder - owner only", "0700"),
    ("Shared team folder", "0775"),
    ("Shared folder with sticky protection", "1777"),
)


def normalize_octal_mode(value: str) -> str:
    text = str(value or "").strip()
    if len(text) not in (3, 4) or any(character not in "01234567" for character in text):
        raise ValueError("Permissions must be 3 or 4 octal digits, for example 644 or 0755.")
    return format(int(text, 8), "04o")


def mode_value(value: str) -> int:
    return int(normalize_octal_mode(value), 8)


def symbolic_mode(value: str | int, *, is_dir: bool) -> str:
    parsed = value if isinstance(value, int) else mode_value(value)
    file_type = stat.S_IFDIR if is_dir else stat.S_IFREG
    return stat.filemode(file_type | stat.S_IMODE(parsed))


def permission_summary(value: str | int) -> str:
    parsed = value if isinstance(value, int) else mode_value(value)
    labels = []
    for title, shift in (("Owner", 6), ("Group", 3), ("Others", 0)):
        digit = (parsed >> shift) & 0o7
        rights = []
        if digit & 4:
            rights.append("read")
        if digit & 2:
            rights.append("write")
        if digit & 1:
            rights.append("execute")
        labels.append(f"{title}: {', '.join(rights) if rights else 'none'}")
    return " | ".join(labels)


def permission_risks(value: str | int, *, recursive: bool = False) -> list[str]:
    parsed = value if isinstance(value, int) else mode_value(value)
    risks = []
    if parsed & 0o002:
        risks.append("Every server account can modify this item.")
    if parsed & 0o020:
        risks.append("Members of the assigned group can modify this item.")
    if parsed & 0o4000:
        risks.append("Set UID is enabled and can execute with the owner's identity.")
    if parsed & 0o2000:
        risks.append("Set GID is enabled and can inherit or execute with the group's identity.")
    if recursive:
        risks.append("The change will affect every accessible child without following symbolic links.")
    return risks


def permission_presets(*, is_dir: bool):
    return FOLDER_PERMISSION_PRESETS if is_dir else FILE_PERMISSION_PRESETS


def suggested_file_mode(folder_mode: str | int) -> str:
    """Derive a non-executable file mode from a recursive folder mode."""
    parsed = folder_mode if isinstance(folder_mode, int) else mode_value(folder_mode)
    return format(parsed & 0o666, "04o")
