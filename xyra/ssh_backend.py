import os
import posixpath
import shlex
import stat
from datetime import datetime

from xyra.path_utils import normalize_api_path, join_remote_path

try:
    import paramiko
except Exception:
    paramiko = None


class SshRemoteBackend:
    def __init__(self, cfg: dict):
        self.host = (cfg.get("ssh_host") or "").strip()
        self.port = int(cfg.get("ssh_port", 22) or 22)
        self.username = (cfg.get("ssh_username") or "").strip()
        self.password = cfg.get("ssh_password") or ""
        self.key_path = (cfg.get("ssh_key_path") or "").strip()
        self.root = (cfg.get("ssh_root") or ".").replace("\\", "/").strip() or "."
        self.client = None
        self.sftp = None

    def is_configured(self) -> bool:
        return bool(self.host and self.username)

    def is_connected(self) -> bool:
        return self.client is not None and self.sftp is not None

    def connect(self):
        if paramiko is None:
            raise RuntimeError("paramiko is not installed. Please install it first.")
        if not self.is_configured():
            raise RuntimeError("SSH host and username are required.")

        self.disconnect()

        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        connect_kwargs = {
            "hostname": self.host,
            "port": self.port,
            "username": self.username,
            "timeout": 10,
            "look_for_keys": False,
            "allow_agent": False,
        }

        if self.key_path:
            connect_kwargs["key_filename"] = self.key_path
        else:
            connect_kwargs["password"] = self.password

        client.connect(**connect_kwargs)
        self.client = client
        self.sftp = client.open_sftp()

    def disconnect(self):
        try:
            if self.sftp:
                self.sftp.close()
        except Exception:
            pass
        try:
            if self.client:
                self.client.close()
        except Exception:
            pass
        self.sftp = None
        self.client = None

    def _ensure_connected(self):
        if not self.is_connected():
            self.connect()

    def _full_path(self, remote_path: str) -> str:
        rp = normalize_api_path(remote_path)
        root = self.root
        if root in ("", "."):
            full = "." if rp in ("", ".") else rp
            return full.replace("\\", "/")

        root_norm = posixpath.normpath(root)
        if rp in ("", "."):
            return root_norm

        full = posixpath.normpath(posixpath.join(root_norm, rp))
        root_prefix = root_norm.rstrip("/")
        if full != root_norm and not full.startswith(root_prefix + "/"):
            raise RuntimeError("Access outside SSH root is not allowed.")
        return full

    def _is_root_path(self, remote_path: str) -> bool:
        return normalize_api_path(remote_path) in ("", ".")

    def list_dir(self, path: str):
        self._ensure_connected()
        full = self._full_path(path)
        result = []
        for entry in self.sftp.listdir_attr(full):
            result.append({
                "name": entry.filename,
                "isDir": bool(entry.st_mode & 0o040000),
                "size": int(entry.st_size),
                "modTime": int(entry.st_mtime),
            })
        return result

    def search_files(self, start_path: str, query: str, max_depth: int = 4, max_results: int = 250, cancel_callback=None):
        self._ensure_connected()
        query = (query or "").strip().lower()
        if not query:
            return []

        start_norm = normalize_api_path(start_path)
        start_full = self._full_path(start_norm)
        results = []
        skip_dirs = {".git", "__pycache__", ".xyra-trash", ".xyra-backups"}

        def rel_join(base: str, child: str) -> str:
            if base in ("", "."):
                return normalize_api_path(child)
            return normalize_api_path(posixpath.join(base, child))

        def walk(rel_path: str, full_path: str, depth: int):
            if cancel_callback and cancel_callback():
                raise RuntimeError("Search cancelled.")
            if len(results) >= max_results:
                return
            try:
                entries = self.sftp.listdir_attr(full_path)
            except Exception:
                return

            for entry in entries:
                if cancel_callback and cancel_callback():
                    raise RuntimeError("Search cancelled.")
                if len(results) >= max_results:
                    return

                name = entry.filename
                child_rel = rel_join(rel_path, name)
                is_dir = stat.S_ISDIR(entry.st_mode)

                if query in name.lower():
                    parent = normalize_api_path(rel_path)
                    results.append({
                        "name": name,
                        "path": child_rel,
                        "parent": parent,
                        "isDir": is_dir,
                        "size": int(entry.st_size),
                        "modTime": int(entry.st_mtime),
                    })

                if is_dir and depth < max_depth and name not in skip_dirs:
                    walk(child_rel, posixpath.join(full_path, name), depth + 1)

        walk(start_norm, start_full, 0)
        return results

    def read_bytes(self, remote_path: str) -> bytes:
        self._ensure_connected()
        full = self._full_path(remote_path)
        with self.sftp.open(full, "rb") as f:
            return f.read()

    def write_text(self, remote_path: str, content: str):
        self._ensure_connected()
        full = self._full_path(remote_path)
        with self.sftp.open(full, "wb") as f:
            f.write(content.encode("utf-8"))

    def mkdir(self, remote_path: str):
        self._ensure_connected()
        full = self._full_path(remote_path)
        parts = []
        cur = full
        while cur not in ("", "/", "."):
            parts.append(cur)
            parent = posixpath.dirname(cur)
            if parent == cur:
                break
            cur = parent
        for part in reversed(parts):
            try:
                self.sftp.stat(part)
            except IOError:
                self.sftp.mkdir(part)

    def delete_path(self, remote_path: str):
        self._ensure_connected()
        if self._is_root_path(remote_path):
            raise RuntimeError("Refusing to delete the configured SSH root.")
        full = self._full_path(remote_path)
        attrs = self.sftp.stat(full)
        if attrs.st_mode & 0o040000:
            for item in self.sftp.listdir_attr(full):
                child = join_remote_path(remote_path, item.filename)
                self.delete_path(child)
            self.sftp.rmdir(full)
        else:
            self.sftp.remove(full)

    def trash_path(self, remote_path: str) -> str:
        self._ensure_connected()
        if self._is_root_path(remote_path):
            raise RuntimeError("Refusing to trash the configured SSH root.")

        source_norm = normalize_api_path(remote_path)
        if source_norm == ".xyra-trash" or source_norm.startswith(".xyra-trash/"):
            raise RuntimeError("Items already inside .xyra-trash must be deleted permanently.")

        source_full = self._full_path(source_norm)
        self.sftp.stat(source_full)

        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        trash_path = normalize_api_path(posixpath.join(".xyra-trash", timestamp, source_norm))
        trash_full = self._full_path(trash_path)
        trash_parent = posixpath.dirname(trash_full)
        if trash_parent:
            self._mkdir_full(trash_parent)

        try:
            self.sftp.rename(source_full, trash_full)
        except Exception:
            self._copy_full_path(source_full, trash_full)
            self._delete_full_path(source_full)

        return trash_path

    def backup_file(self, remote_path: str) -> str:
        self._ensure_connected()
        source_norm = normalize_api_path(remote_path)
        if self._is_root_path(source_norm):
            raise RuntimeError("Refusing to back up the configured SSH root.")
        if source_norm.startswith(".xyra-backups/") or source_norm.startswith(".xyra-trash/"):
            raise RuntimeError("Refusing to back up internal Xyra state folders.")

        source_full = self._full_path(source_norm)
        attrs = self.sftp.stat(source_full)
        if stat.S_ISDIR(attrs.st_mode):
            raise RuntimeError("Only files can be backed up before editing.")

        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup_path = normalize_api_path(posixpath.join(".xyra-backups", timestamp, source_norm))
        backup_full = self._full_path(backup_path)
        backup_parent = posixpath.dirname(backup_full)
        if backup_parent:
            self._mkdir_full(backup_parent)

        self._copy_full_path(source_full, backup_full)
        return backup_path

    def rename(self, old_path: str, new_path: str):
        self._ensure_connected()
        self.sftp.rename(self._full_path(old_path), self._full_path(new_path))

    def copy_path(self, source_path: str, dest_path: str):
        self._ensure_connected()
        self._copy_full_path(self._full_path(source_path), self._full_path(dest_path))

    def move_path(self, source_path: str, dest_path: str):
        self._ensure_connected()
        if self._is_root_path(source_path):
            raise RuntimeError("Refusing to move the configured SSH root.")
        source_full = self._full_path(source_path)
        dest_full = self._full_path(dest_path)
        try:
            self.sftp.rename(source_full, dest_full)
            return
        except Exception:
            pass

        self._copy_full_path(source_full, dest_full)
        self._delete_full_path(source_full)

    def upload_file(self, local_path: str, remote_dir: str):
        self._ensure_connected()
        target_dir = self._full_path(remote_dir)
        self.mkdir(remote_dir)
        target = posixpath.join(target_dir, os.path.basename(local_path))
        self.sftp.put(local_path, target)

    def download_file(self, remote_path: str, local_path: str):
        self._ensure_connected()
        self.sftp.get(self._full_path(remote_path), local_path)

    def describe(self) -> str:
        return f"SSH {self.username}@{self.host}:{self.port}"

    def get_path_info(self, remote_path: str):
        self._ensure_connected()
        full = self._full_path(remote_path)
        attrs = self.sftp.stat(full)
        name = posixpath.basename(full.rstrip("/")) or "/"
        return {
            "name": name,
            "path": remote_path,
            "full_path": full,
            "isDir": stat.S_ISDIR(attrs.st_mode),
            "size": int(attrs.st_size),
            "modTime": int(attrs.st_mtime),
            "mode": attrs.st_mode,
            "permissions": stat.filemode(attrs.st_mode),
            "octal": format(stat.S_IMODE(attrs.st_mode), "03o"),
        }

    def chmod_path(self, remote_path: str, mode_text: str):
        self._ensure_connected()
        mode_text = (mode_text or "").strip()
        if not mode_text:
            raise RuntimeError("Permission mode cannot be empty.")
        if len(mode_text) not in (3, 4) or any(ch not in "01234567" for ch in mode_text):
            raise RuntimeError("Permission mode must be octal, e.g. 755 or 0644.")
        mode_value = int(mode_text, 8)
        self.sftp.chmod(self._full_path(remote_path), mode_value)

    def run_command(self, command: str):
        self._ensure_connected()
        stdin, stdout, stderr = self.client.exec_command(command)
        exit_code = stdout.channel.recv_exit_status()
        out = stdout.read().decode("utf-8", errors="ignore")
        err = stderr.read().decode("utf-8", errors="ignore")
        if exit_code != 0:
            message = err.strip() or out.strip() or f"Remote command failed with exit code {exit_code}."
            raise RuntimeError(message)
        return out

    def get_server_health(self, current_path: str = "."):
        self._ensure_connected()
        target_full = shlex.quote(self._full_path(current_path))
        root_full = shlex.quote(self._full_path("."))
        command = (
            "printf 'Host: '; hostname 2>/dev/null || true; "
            "printf 'User: '; whoami 2>/dev/null || true; "
            "printf 'SSH root: '; pwd 2>/dev/null || true; "
            f"printf 'Xyra path: '; printf '%s\\n' {target_full}; "
            "printf 'Load: '; awk '{print $1, $2, $3}' /proc/loadavg 2>/dev/null || true; "
            "printf 'Memory: '; free -h 2>/dev/null | awk '/^Mem:/ {print $3 \" / \" $2 \" used\"}' || true; "
            "printf '\\nDisk for current path:\\n'; "
            f"df -h {target_full} 2>&1 || true; "
            "printf '\\nDisk for SSH root:\\n'; "
            f"df -h {root_full} 2>&1 || true; "
            "printf '\\nUptime:\\n'; uptime 2>&1 || true; "
            "printf '\\nSystem:\\n'; uname -a 2>&1 || true; "
            "true"
        )
        return self.run_command(command).strip()

    def extract_archive(self, remote_path: str, dest_dir: str):
        archive_full = self._full_path(remote_path)
        dest_full = self._full_path(dest_dir)
        archive_name = posixpath.basename(archive_full).lower()
        self._mkdir_full(dest_full)

        quoted_archive = shlex.quote(archive_full)
        quoted_dest = shlex.quote(dest_full)
        commands = []

        if archive_name.endswith((".zip", ".pk3", ".iwd", ".jar")):
            commands = [
                f"unzip -o {quoted_archive} -d {quoted_dest}",
                f"bsdtar -xf {quoted_archive} -C {quoted_dest}",
                f"7z x -y -o{quoted_dest} {quoted_archive}",
            ]
        elif archive_name.endswith((".tar.gz", ".tgz")):
            commands = [f"tar -xzf {quoted_archive} -C {quoted_dest}"]
        elif archive_name.endswith((".tar.bz2", ".tbz2")):
            commands = [f"tar -xjf {quoted_archive} -C {quoted_dest}"]
        elif archive_name.endswith((".tar.xz", ".txz")):
            commands = [f"tar -xJf {quoted_archive} -C {quoted_dest}"]
        elif archive_name.endswith(".tar"):
            commands = [f"tar -xf {quoted_archive} -C {quoted_dest}"]
        elif archive_name.endswith(".rar"):
            commands = [
                f"unrar x -o+ {quoted_archive} {quoted_dest}",
                f"7z x -y -o{quoted_dest} {quoted_archive}",
                f"bsdtar -xf {quoted_archive} -C {quoted_dest}",
            ]
        elif archive_name.endswith(".7z"):
            commands = [f"7z x -y -o{quoted_dest} {quoted_archive}"]
        else:
            raise RuntimeError("Unsupported archive format.")

        self._run_fallback_commands(commands)

    def compress_to_zip(self, source_path: str, archive_path: str):
        source_full = self._full_path(source_path)
        archive_full = self._full_path(archive_path)
        source_name = posixpath.basename(source_full)
        source_parent = posixpath.dirname(source_full) or "."
        archive_parent = posixpath.dirname(archive_full) or "."
        archive_name = posixpath.basename(archive_full)
        self._mkdir_full(archive_parent)

        quoted_source_parent = shlex.quote(source_parent)
        quoted_archive_parent = shlex.quote(archive_parent)
        quoted_source_name = shlex.quote(source_name)
        quoted_archive_name = shlex.quote(archive_name)

        commands = [
            f"cd {quoted_source_parent} && zip -r {quoted_archive_parent}/{quoted_archive_name} {quoted_source_name}",
            f"cd {quoted_source_parent} && 7z a {quoted_archive_parent}/{quoted_archive_name} {quoted_source_name}",
            f"cd {quoted_source_parent} && bsdtar -a -cf {quoted_archive_parent}/{quoted_archive_name} {quoted_source_name}",
        ]
        self._run_fallback_commands(commands)

    def _copy_full_path(self, source_full: str, dest_full: str):
        attrs = self.sftp.stat(source_full)
        if stat.S_ISDIR(attrs.st_mode):
            self._mkdir_full(dest_full)
            for entry in self.sftp.listdir_attr(source_full):
                child_source = posixpath.join(source_full, entry.filename)
                child_dest = posixpath.join(dest_full, entry.filename)
                self._copy_full_path(child_source, child_dest)
            return

        parent = posixpath.dirname(dest_full)
        if parent:
            self._mkdir_full(parent)
        with self.sftp.open(source_full, "rb") as src, self.sftp.open(dest_full, "wb") as dst:
            while True:
                chunk = src.read(1024 * 256)
                if not chunk:
                    break
                dst.write(chunk)

    def _delete_full_path(self, full_path: str):
        attrs = self.sftp.stat(full_path)
        if stat.S_ISDIR(attrs.st_mode):
            for item in self.sftp.listdir_attr(full_path):
                self._delete_full_path(posixpath.join(full_path, item.filename))
            self.sftp.rmdir(full_path)
            return
        self.sftp.remove(full_path)

    def _mkdir_full(self, full_path: str):
        parts = []
        cur = full_path
        while cur not in ("", "/", "."):
            parts.append(cur)
            parent = posixpath.dirname(cur)
            if parent == cur:
                break
            cur = parent
        for part in reversed(parts):
            try:
                self.sftp.stat(part)
            except IOError:
                self.sftp.mkdir(part)

    def _run_fallback_commands(self, commands):
        last_error = None
        for command in commands:
            try:
                self.run_command(command)
                return
            except Exception as e:
                last_error = e
        if last_error is not None:
            raise last_error
        raise RuntimeError("No archive command available.")
