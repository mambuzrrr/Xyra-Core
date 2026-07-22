import os
import base64
import posixpath
import shlex
import stat
import hashlib
import json
import uuid
import errno
import threading
import re
from datetime import datetime

from xyra.app_constants import KNOWN_HOSTS_FILE
from xyra.path_utils import normalize_api_path, join_remote_path
from xyra.permissions import mode_value

try:
    import paramiko
except Exception:
    paramiko = None


if paramiko is not None:
    class _ConfirmHostKeyPolicy(paramiko.MissingHostKeyPolicy):
        def __init__(self, known_hosts_path: str, verifier):
            self.known_hosts_path = known_hosts_path
            self.verifier = verifier

        def missing_host_key(self, client, hostname, key):
            digest = hashlib.sha256(key.asbytes()).digest()
            fingerprint = "SHA256:" + base64.b64encode(digest).decode("ascii").rstrip("=")
            accepted = bool(
                self.verifier
                and self.verifier(hostname, key.get_name(), fingerprint)
            )
            if not accepted:
                raise paramiko.SSHException(
                    f"Unknown SSH host key for {hostname} was not accepted."
                )

            client.get_host_keys().add(hostname, key.get_name(), key)
            os.makedirs(os.path.dirname(self.known_hosts_path), exist_ok=True)
            client.save_host_keys(self.known_hosts_path)


class SshRemoteBackend:
    MAX_ARCHIVE_ENTRIES = 100_000
    MAX_INLINE_READ_BYTES = 16 * 1024 * 1024
    MAX_RECURSIVE_PERMISSION_TARGETS = 25_000

    def __init__(self, cfg: dict, host_key_verifier=None):
        self.host = (cfg.get("ssh_host") or "").strip()
        self.port = int(cfg.get("ssh_port", 22) or 22)
        self.username = (cfg.get("ssh_username") or "").strip()
        self.password = cfg.get("ssh_password") or ""
        self.key_path = (cfg.get("ssh_key_path") or "").strip()
        self.root = (cfg.get("ssh_root") or ".").replace("\\", "/").strip() or "."
        self.host_key_verifier = host_key_verifier
        self.client = None
        self.sftp = None
        self.connection_generation = 0
        self.operation_lock = threading.RLock()

    def is_configured(self) -> bool:
        return bool(self.host and self.username)

    def is_connected(self) -> bool:
        if self.client is None or self.sftp is None:
            return False
        try:
            transport = self.client.get_transport()
        except AttributeError:
            # Lightweight test/fallback clients may not expose a transport.
            return True
        except Exception:
            return False
        if transport is None:
            return False
        try:
            return bool(transport.is_active() and transport.is_authenticated())
        except Exception:
            return False

    @staticmethod
    def is_connection_error(error: Exception) -> bool:
        """Separate broken transports from ordinary remote file errors."""
        if isinstance(error, (FileNotFoundError, PermissionError)):
            return False
        if isinstance(error, (EOFError, ConnectionError, TimeoutError)):
            return True
        if isinstance(error, OSError):
            if error.errno in {errno.ENOENT, errno.EACCES, errno.EPERM, errno.ENOTDIR}:
                return False
            if error.errno in {
                errno.ECONNABORTED, errno.ECONNREFUSED, errno.ECONNRESET,
                errno.ENETDOWN, errno.ENETRESET, errno.ENETUNREACH,
                errno.EHOSTDOWN, errno.EHOSTUNREACH, errno.ETIMEDOUT,
                errno.EPIPE,
            }:
                return True
        if paramiko is not None and isinstance(error, paramiko.SSHException):
            return True
        text = str(error).lower()
        return any(marker in text for marker in (
            "server connection dropped", "connection reset", "connection aborted",
            "connection closed", "socket is closed", "socket closed", "broken pipe",
            "eof during negotiation", "ssh session not active", "ssh connection is not active",
            "channel closed",
        ))

    def connect(self, *, allow_host_key_prompt: bool = True):
        if paramiko is None:
            raise RuntimeError("paramiko is not installed. Please install it first.")
        if not self.is_configured():
            raise RuntimeError("SSH host and username are required.")

        self.disconnect()

        client = paramiko.SSHClient()
        if os.path.exists(KNOWN_HOSTS_FILE):
            client.load_host_keys(KNOWN_HOSTS_FILE)
        client.set_missing_host_key_policy(
            _ConfirmHostKeyPolicy(
                KNOWN_HOSTS_FILE,
                self.host_key_verifier if allow_host_key_prompt else None,
            )
        )

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

        try:
            client.connect(**connect_kwargs)
            transport = client.get_transport()
            if transport is not None:
                transport.set_keepalive(20)
            sftp = client.open_sftp()
            canonical_root = posixpath.normpath(sftp.normalize(self.root))
        except Exception:
            client.close()
            raise

        self.client = client
        self.sftp = sftp
        self.root = canonical_root
        self.connection_generation += 1

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
            raise RuntimeError(
                "SSH connection is not active. Reconnect from the Remote menu."
            )

    def _full_path(self, remote_path: str) -> str:
        rp = normalize_api_path(remote_path)
        rp_norm = posixpath.normpath(rp)
        if rp_norm == ".." or rp_norm.startswith("../"):
            raise RuntimeError("Access outside SSH root is not allowed.")

        root_norm = posixpath.normpath(self.root)
        if rp in ("", "."):
            return root_norm

        full = posixpath.normpath(posixpath.join(root_norm, rp_norm))
        root_prefix = root_norm.rstrip("/")
        if root_norm != "/" and full != root_norm and not full.startswith(root_prefix + "/"):
            raise RuntimeError("Access outside SSH root is not allowed.")
        if self.sftp is not None:
            self._assert_full_path_within_root(full)
        return full

    def _assert_full_path_within_root(self, full_path: str):
        """Reject paths whose existing portion resolves outside the SSH root."""
        root_norm = posixpath.normpath(self.root)
        if root_norm == "/":
            return

        current = posixpath.normpath(full_path)
        missing_parts = []
        while True:
            try:
                resolved = posixpath.normpath(self.sftp.normalize(current))
                break
            except IOError:
                parent = posixpath.dirname(current)
                if parent == current:
                    raise RuntimeError("Unable to validate remote path boundary.")
                missing_parts.insert(0, posixpath.basename(current))
                current = parent

        if missing_parts:
            resolved = posixpath.normpath(posixpath.join(resolved, *missing_parts))

        root_prefix = root_norm.rstrip("/")
        if resolved != root_norm and not resolved.startswith(root_prefix + "/"):
            raise RuntimeError(
                "Access through a path or symbolic link outside SSH root is not allowed."
            )

    def _is_root_path(self, remote_path: str) -> bool:
        return normalize_api_path(remote_path) in ("", ".")

    def list_dir(self, path: str):
        self._ensure_connected()
        full = self._full_path(path)
        result = []
        for entry in self.sftp.listdir_attr(full):
            is_link = stat.S_ISLNK(entry.st_mode)
            is_dir = stat.S_ISDIR(entry.st_mode)
            is_accessible = True
            link_error = ""

            if is_link:
                try:
                    child_path = join_remote_path(path, entry.filename)
                    child_full = self._full_path(child_path)
                    target_attrs = self.sftp.stat(child_full)
                    is_dir = stat.S_ISDIR(target_attrs.st_mode)
                except Exception as exc:
                    is_accessible = False
                    link_error = str(exc) or "The symbolic-link target is unavailable."

            result.append({
                "name": entry.filename,
                "isDir": is_dir,
                "isLink": is_link,
                "isAccessible": is_accessible,
                "linkError": link_error,
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
        size = int(self.sftp.stat(full).st_size)
        if size > self.MAX_INLINE_READ_BYTES:
            raise RuntimeError(
                "File is too large to open in the built-in editor "
                f"({size / (1024 * 1024):.1f} MB; limit is "
                f"{self.MAX_INLINE_READ_BYTES // (1024 * 1024)} MB)."
            )
        with self.sftp.open(full, "rb") as f:
            data = f.read(self.MAX_INLINE_READ_BYTES + 1)
        if len(data) > self.MAX_INLINE_READ_BYTES:
            raise RuntimeError("File exceeded the safe built-in editor limit.")
        return data

    def compute_checksums(self, remote_path: str):
        self._ensure_connected()
        full = self._full_path(remote_path)
        attrs = self.sftp.stat(full)
        if stat.S_ISDIR(attrs.st_mode):
            raise RuntimeError("Checksums are only available for files.")

        hashes = {
            "MD5": hashlib.md5(),
            "SHA1": hashlib.sha1(),
            "SHA256": hashlib.sha256(),
        }
        with self.sftp.open(full, "rb") as f:
            while True:
                chunk = f.read(1024 * 1024)
                if not chunk:
                    break
                for h in hashes.values():
                    h.update(chunk)

        return {name: h.hexdigest() for name, h in hashes.items()}

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

        meta_path = self._full_path(posixpath.join(".xyra-trash", timestamp, ".xyra-meta.json"))
        meta = {
            "original_path": source_norm,
            "trash_path": trash_path,
            "deleted_at": timestamp,
        }
        try:
            with self.sftp.open(meta_path, "wb") as f:
                f.write(json.dumps(meta, indent=2).encode("utf-8"))
        except Exception:
            pass

        return trash_path

    def list_trash_items(self):
        self._ensure_connected()
        trash_root = normalize_api_path(".xyra-trash")
        trash_full = self._full_path(trash_root)
        try:
            entries = self.sftp.listdir_attr(trash_full)
        except Exception:
            return []

        items = []
        for entry in entries:
            if not stat.S_ISDIR(entry.st_mode):
                continue
            stamp = entry.filename
            stamp_rel = normalize_api_path(posixpath.join(trash_root, stamp))
            stamp_full = self._full_path(stamp_rel)
            meta = self._read_trash_meta(stamp_full)
            trash_path = normalize_api_path(meta.get("trash_path") or "")
            original_path = normalize_api_path(meta.get("original_path") or "")
            deleted_at = meta.get("deleted_at") or stamp

            if not trash_path:
                trash_path = self._first_trash_payload_path(stamp_rel)
            if not trash_path:
                continue

            try:
                attrs = self.sftp.stat(self._full_path(trash_path))
            except Exception:
                continue

            display_source = original_path if original_path else trash_path
            items.append({
                "name": posixpath.basename(display_source.rstrip("/")) or display_source,
                "original_path": original_path,
                "trash_path": trash_path,
                "deleted_at": deleted_at,
                "isDir": stat.S_ISDIR(attrs.st_mode),
                "size": int(attrs.st_size),
                "modTime": int(attrs.st_mtime),
            })

        items.sort(key=lambda item: item.get("deleted_at", ""), reverse=True)
        return items

    def restore_trash_item(self, trash_path: str, original_path: str, *, overwrite: bool = False):
        self._ensure_connected()
        trash_norm = normalize_api_path(trash_path)
        target_norm = normalize_api_path(original_path)
        if not trash_norm.startswith(".xyra-trash/"):
            raise RuntimeError("Only Xyra trash items can be restored.")
        if not target_norm or target_norm in (".", ".xyra-trash") or target_norm.startswith(".xyra-trash/"):
            raise RuntimeError("Trash item does not have a safe original path.")

        source_full = self._full_path(trash_norm)
        target_full = self._full_path(target_norm)
        self._move_full_path(source_full, target_full, overwrite=overwrite)
        self._cleanup_empty_trash_stamp(trash_norm)

    def delete_trash_item(self, trash_path: str):
        self._ensure_connected()
        trash_norm = normalize_api_path(trash_path)
        if not trash_norm.startswith(".xyra-trash/"):
            raise RuntimeError("Only Xyra trash items can be deleted here.")
        self.delete_path(trash_norm)
        self._cleanup_empty_trash_stamp(trash_norm)

    def empty_trash(self):
        self._ensure_connected()
        try:
            self.sftp.stat(self._full_path(".xyra-trash"))
        except IOError:
            return
        self.delete_path(".xyra-trash")

    def _read_trash_meta(self, stamp_full: str):
        meta_full = posixpath.join(stamp_full, ".xyra-meta.json")
        try:
            with self.sftp.open(meta_full, "rb") as f:
                data = f.read().decode("utf-8", errors="ignore")
            meta = json.loads(data)
            return meta if isinstance(meta, dict) else {}
        except Exception:
            return {}

    def _first_trash_payload_path(self, stamp_rel: str):
        current_rel = normalize_api_path(stamp_rel)
        for _ in range(20):
            try:
                entries = [
                    e for e in self.sftp.listdir_attr(self._full_path(current_rel))
                    if e.filename != ".xyra-meta.json"
                ]
            except Exception:
                return current_rel
            if len(entries) != 1:
                return current_rel
            child = entries[0]
            child_rel = normalize_api_path(posixpath.join(current_rel, child.filename))
            if not stat.S_ISDIR(child.st_mode):
                return child_rel
            current_rel = child_rel
        return current_rel

    def _cleanup_empty_trash_stamp(self, trash_path: str):
        parts = normalize_api_path(trash_path).split("/")
        if len(parts) < 2 or parts[0] != ".xyra-trash":
            return
        stamp_rel = normalize_api_path(posixpath.join(parts[0], parts[1]))
        stamp_full = self._full_path(stamp_rel)
        try:
            self._delete_full_path(posixpath.join(stamp_full, ".xyra-meta.json"))
        except Exception:
            pass
        try:
            self._delete_full_path(stamp_full)
        except Exception:
            try:
                self._delete_empty_dirs(stamp_full, stop_full=self._full_path(".xyra-trash"))
            except Exception:
                pass

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

    def rename(self, old_path: str, new_path: str, *, overwrite: bool = False):
        self._ensure_connected()
        if self._is_root_path(old_path):
            raise RuntimeError("Refusing to rename the configured SSH root.")
        self._move_full_path(
            self._full_path(old_path),
            self._full_path(new_path),
            overwrite=overwrite,
        )

    def copy_path(self, source_path: str, dest_path: str, *, overwrite: bool = False):
        self._ensure_connected()
        self._copy_full_path_safely(
            self._full_path(source_path),
            self._full_path(dest_path),
            overwrite=overwrite,
        )

    def move_path(self, source_path: str, dest_path: str, *, overwrite: bool = False):
        self._ensure_connected()
        if self._is_root_path(source_path):
            raise RuntimeError("Refusing to move the configured SSH root.")
        self._move_full_path(
            self._full_path(source_path),
            self._full_path(dest_path),
            overwrite=overwrite,
        )

    def _local_path_size(self, local_path: str) -> int:
        if os.path.isfile(local_path):
            try:
                return int(os.path.getsize(local_path))
            except Exception:
                return 0
        total = 0
        for root, _dirs, files in os.walk(local_path):
            for file_name in files:
                try:
                    total += int(os.path.getsize(os.path.join(root, file_name)))
                except Exception:
                    pass
        return total

    def _upload_file_to_target(self, local_path: str, target: str, *, overwrite: bool = False, progress_callback=None, cancel_callback=None, counter=None, total_bytes: int | None = None):
        counter = counter if counter is not None else {"done": 0}
        file_size = self._local_path_size(local_path)
        total_bytes = total_bytes if total_bytes is not None else file_size
        temp_target = f"{target}.xyra-upload-{uuid.uuid4().hex[:10]}.tmp"

        try:
            with open(local_path, "rb") as src, self.sftp.open(temp_target, "wb") as dst:
                while True:
                    if cancel_callback and cancel_callback():
                        raise RuntimeError("Transfer cancelled.")
                    chunk = src.read(1024 * 256)
                    if not chunk:
                        break
                    dst.write(chunk)
                    counter["done"] += len(chunk)
                    if progress_callback:
                        progress_callback(counter["done"], total_bytes)

            if cancel_callback and cancel_callback():
                raise RuntimeError("Transfer cancelled.")

            self._commit_staged_path(temp_target, target, overwrite=overwrite)
        except Exception:
            try:
                self.sftp.remove(temp_target)
            except Exception:
                pass
            raise

    def upload_file(self, local_path: str, remote_dir: str, *, overwrite: bool = False, progress_callback=None, cancel_callback=None):
        self._ensure_connected()
        target_dir = self._full_path(remote_dir)
        self.mkdir(remote_dir)
        target = posixpath.join(target_dir, os.path.basename(local_path))
        self._upload_file_to_target(local_path, target, overwrite=overwrite, progress_callback=progress_callback, cancel_callback=cancel_callback)

    def upload_path(self, local_path: str, remote_dir: str, *, overwrite: bool = False, progress_callback=None, cancel_callback=None):
        self._ensure_connected()
        local_path = os.path.abspath(local_path)
        total_bytes = self._local_path_size(local_path)
        counter = {"done": 0}
        if os.path.isfile(local_path):
            self.upload_file(local_path, remote_dir, overwrite=overwrite, progress_callback=progress_callback, cancel_callback=cancel_callback)
            return
        if os.path.isdir(local_path):
            remote_base = normalize_api_path(posixpath.join(remote_dir, os.path.basename(local_path)))
            remote_base_full = self._full_path(remote_base)
            if self._path_exists_full(remote_base_full) and not overwrite:
                raise RuntimeError(
                    f"Remote item already exists with the same name: {os.path.basename(local_path)}"
                )
            staged_base_full = self._temporary_sibling(remote_base_full, "upload")
            try:
                self._mkdir_full(staged_base_full)
                for root, dirs, files in os.walk(local_path):
                    if cancel_callback and cancel_callback():
                        raise RuntimeError("Transfer cancelled.")
                    rel_root = os.path.relpath(root, local_path)
                    current_full = (
                        staged_base_full
                        if rel_root in (".", "")
                        else posixpath.join(staged_base_full, rel_root.replace("\\", "/"))
                    )
                    self._mkdir_full(current_full)
                    for dir_name in dirs:
                        self._mkdir_full(posixpath.join(current_full, dir_name))
                    for file_name in files:
                        source_file = os.path.join(root, file_name)
                        target = posixpath.join(current_full, file_name)
                        self._upload_file_to_target(
                            source_file,
                            target,
                            overwrite=False,
                            progress_callback=progress_callback,
                            cancel_callback=cancel_callback,
                            counter=counter,
                            total_bytes=total_bytes,
                        )
                if cancel_callback and cancel_callback():
                    raise RuntimeError("Transfer cancelled.")
                self._commit_staged_path(staged_base_full, remote_base_full, overwrite=overwrite)
            except Exception:
                try:
                    if self._path_exists_full(staged_base_full):
                        self._delete_full_path(staged_base_full)
                except Exception:
                    pass
                raise
            return
        raise RuntimeError(f"Local path not found or unsupported: {local_path}")

    def download_file(self, remote_path: str, local_path: str, *, overwrite: bool = False, progress_callback=None, cancel_callback=None):
        self._ensure_connected()
        if os.path.exists(local_path) and not overwrite:
            raise RuntimeError("Local download target already exists.")
        remote_full = self._full_path(remote_path)
        remote_size = 0
        try:
            remote_size = int(self.sftp.stat(remote_full).st_size)
        except Exception:
            remote_size = 0

        local_dir = os.path.dirname(os.path.abspath(local_path))
        if local_dir:
            os.makedirs(local_dir, exist_ok=True)

        temp_local = f"{local_path}.xyra-download-{uuid.uuid4().hex[:10]}.tmp"
        downloaded = 0

        try:
            with self.sftp.open(remote_full, "rb") as src, open(temp_local, "wb") as dst:
                while True:
                    if cancel_callback and cancel_callback():
                        raise RuntimeError("Transfer cancelled.")
                    chunk = src.read(1024 * 256)
                    if not chunk:
                        break
                    dst.write(chunk)
                    downloaded += len(chunk)
                    if progress_callback:
                        progress_callback(downloaded, remote_size)
            if overwrite:
                os.replace(temp_local, local_path)
            else:
                # A hard link provides an atomic create-if-absent operation, so
                # a file appearing after the UI preflight is never overwritten.
                os.link(temp_local, local_path)
                os.remove(temp_local)
        except Exception:
            try:
                os.remove(temp_local)
            except Exception:
                pass
            raise

    def describe(self) -> str:
        return f"SSH {self.username}@{self.host}:{self.port}"

    def get_path_info(self, remote_path: str):
        self._ensure_connected()
        full = self._full_path(remote_path)
        attrs = self.sftp.stat(full)
        name = posixpath.basename(full.rstrip("/")) or "/"
        uid = getattr(attrs, "st_uid", None)
        gid = getattr(attrs, "st_gid", None)
        return {
            "name": name,
            "path": remote_path,
            "full_path": full,
            "isDir": stat.S_ISDIR(attrs.st_mode),
            "size": int(attrs.st_size),
            "modTime": int(attrs.st_mtime),
            "mode": attrs.st_mode,
            "uid": uid,
            "gid": gid,
            "owner": self._resolve_user_name(uid),
            "group": self._resolve_group_name(gid),
            "permissions": stat.filemode(attrs.st_mode),
            "octal": format(stat.S_IMODE(attrs.st_mode), "03o"),
        }

    def chmod_path(self, remote_path: str, mode_text: str):
        return self.change_permissions(remote_path, mode_text)

    def _resolve_account_id(self, value: str, *, group: bool) -> int | None:
        text = str(value or "").strip()
        if not text:
            return None
        if text.isdecimal():
            account_id = int(text)
            if account_id > 2_147_483_647:
                raise RuntimeError("Owner and group IDs must fit in a signed 32-bit integer.")
            return account_id
        if len(text) > 128 or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.-]*", text):
            label = "Group" if group else "Owner"
            raise RuntimeError(f"{label} must be a valid account name or numeric ID.")
        database = "group" if group else "passwd"
        field = 3 if group else 3
        output = self.run_command(
            f"getent {database} {shlex.quote(text)} | cut -d: -f{field}"
        ).strip()
        if not output.isdecimal():
            label = "Group" if group else "Owner"
            raise RuntimeError(f"{label} '{text}' does not exist on the server.")
        return int(output)

    def _permission_targets(self, full_path: str, *, recursive: bool):
        lstat = getattr(self.sftp, "lstat", self.sftp.stat)
        root_attrs = lstat(full_path)
        if stat.S_ISLNK(root_attrs.st_mode):
            raise RuntimeError("Permissions on symbolic links are not changed by Xyra.")
        targets = [(full_path, root_attrs)]
        skipped_links = 0
        if not recursive or not stat.S_ISDIR(root_attrs.st_mode):
            return targets, skipped_links

        pending = [full_path]
        while pending:
            parent = pending.pop()
            for entry in self.sftp.listdir_attr(parent):
                name = str(getattr(entry, "filename", ""))
                if not name or name in (".", "..") or "/" in name:
                    continue
                child = posixpath.join(parent, name)
                self._assert_full_path_within_root(child)
                if stat.S_ISLNK(entry.st_mode):
                    skipped_links += 1
                    continue
                targets.append((child, entry))
                if len(targets) > self.MAX_RECURSIVE_PERMISSION_TARGETS:
                    raise RuntimeError(
                        "Recursive permission change exceeds the safety limit of "
                        f"{self.MAX_RECURSIVE_PERMISSION_TARGETS:,} items."
                    )
                if stat.S_ISDIR(entry.st_mode):
                    pending.append(child)
        targets.sort(key=lambda item: item[0].count("/"), reverse=True)
        return targets, skipped_links

    def change_permissions(
        self,
        remote_path: str,
        mode_text: str,
        *,
        owner: str = "",
        group: str = "",
        recursive: bool = False,
        file_mode_text: str = "",
    ) -> dict:
        self._ensure_connected()
        try:
            requested_mode = mode_value(mode_text)
        except ValueError as exc:
            raise RuntimeError(str(exc)) from exc
        requested_file_mode = requested_mode
        if recursive and file_mode_text:
            try:
                requested_file_mode = mode_value(file_mode_text)
            except ValueError as exc:
                raise RuntimeError(f"Recursive file mode: {exc}") from exc
        requested_uid = self._resolve_account_id(owner, group=False)
        requested_gid = self._resolve_account_id(group, group=True)
        full_path = self._full_path(remote_path)
        targets, skipped_links = self._permission_targets(full_path, recursive=recursive)

        completed = 0
        try:
            for target, original_attrs in targets:
                current_attrs = getattr(self.sftp, "lstat", self.sftp.stat)(target)
                if stat.S_ISLNK(current_attrs.st_mode):
                    skipped_links += 1
                    continue
                target_mode = (
                    requested_mode
                    if stat.S_ISDIR(current_attrs.st_mode)
                    else requested_file_mode
                )
                uid = requested_uid if requested_uid is not None else getattr(current_attrs, "st_uid", None)
                gid = requested_gid if requested_gid is not None else getattr(current_attrs, "st_gid", None)
                if requested_uid is not None or requested_gid is not None:
                    if uid is None or gid is None:
                        raise RuntimeError("The server did not provide the current owner and group IDs.")
                    self.sftp.chown(target, int(uid), int(gid))
                self.sftp.chmod(target, target_mode)

                verified = self.sftp.stat(target)
                if stat.S_IMODE(verified.st_mode) != target_mode:
                    raise RuntimeError("The server reported different permissions after the update.")
                if requested_uid is not None and getattr(verified, "st_uid", None) != requested_uid:
                    raise RuntimeError("The server did not apply the requested owner.")
                if requested_gid is not None and getattr(verified, "st_gid", None) != requested_gid:
                    raise RuntimeError("The server did not apply the requested group.")
                completed += 1
        except Exception as exc:
            if len(targets) > 1:
                raise RuntimeError(
                    f"Permission update stopped after {completed} of {len(targets)} items. "
                    f"Some earlier items may already be changed. Server response: {exc}"
                ) from exc
            raise

        updated = self.get_path_info(remote_path)
        updated["updatedCount"] = completed
        updated["skippedLinks"] = skipped_links
        return updated

    def run_command(self, command: str, max_output_bytes: int = 4 * 1024 * 1024):
        self._ensure_connected()
        stdin, stdout, stderr = self.client.exec_command(command)
        stdout.channel.set_combine_stderr(True)
        raw = stdout.read(max_output_bytes + 1)
        if len(raw) > max_output_bytes:
            stdout.channel.close()
            raise RuntimeError("Remote command output exceeded the safety limit.")
        exit_code = stdout.channel.recv_exit_status()
        out = raw.decode("utf-8", errors="ignore")
        if exit_code != 0:
            message = out.strip() or f"Remote command failed with exit code {exit_code}."
            raise RuntimeError(message)
        return out

    def _resolve_user_name(self, uid):
        if uid is None:
            return ""
        try:
            out = self.run_command(f"getent passwd {int(uid)} | cut -d: -f1")
            return out.strip()
        except Exception:
            return ""

    def _resolve_group_name(self, gid):
        if gid is None:
            return ""
        try:
            out = self.run_command(f"getent group {int(gid)} | cut -d: -f1")
            return out.strip()
        except Exception:
            return ""

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

        quoted_archive = shlex.quote(archive_full)
        quoted_dest = shlex.quote(dest_full)
        commands = []
        listing_commands = []

        if archive_name.endswith((".zip", ".pk3", ".iwd", ".jar")):
            listing_commands = [
                (f"unzip -Z1 {quoted_archive}", "lines"),
                (f"bsdtar -tf {quoted_archive}", "lines"),
                (f"7z l -slt {quoted_archive}", "7z"),
            ]
            commands = [
                f"unzip -o {quoted_archive} -d {quoted_dest}",
                f"bsdtar -xf {quoted_archive} -C {quoted_dest}",
                f"7z x -y -o{quoted_dest} {quoted_archive}",
            ]
        elif archive_name.endswith((".tar.gz", ".tgz")):
            listing_commands = [(f"tar -tzf {quoted_archive}", "lines")]
            commands = [f"tar -xzf {quoted_archive} -C {quoted_dest}"]
        elif archive_name.endswith((".tar.bz2", ".tbz2")):
            listing_commands = [(f"tar -tjf {quoted_archive}", "lines")]
            commands = [f"tar -xjf {quoted_archive} -C {quoted_dest}"]
        elif archive_name.endswith((".tar.xz", ".txz")):
            listing_commands = [(f"tar -tJf {quoted_archive}", "lines")]
            commands = [f"tar -xJf {quoted_archive} -C {quoted_dest}"]
        elif archive_name.endswith(".tar"):
            listing_commands = [(f"tar -tf {quoted_archive}", "lines")]
            commands = [f"tar -xf {quoted_archive} -C {quoted_dest}"]
        elif archive_name.endswith(".rar"):
            listing_commands = [
                (f"unrar lb {quoted_archive}", "lines"),
                (f"7z l -slt {quoted_archive}", "7z"),
                (f"bsdtar -tf {quoted_archive}", "lines"),
            ]
            commands = [
                f"unrar x -o+ {quoted_archive} {quoted_dest}",
                f"7z x -y -o{quoted_dest} {quoted_archive}",
                f"bsdtar -xf {quoted_archive} -C {quoted_dest}",
            ]
        elif archive_name.endswith(".7z"):
            listing_commands = [(f"7z l -slt {quoted_archive}", "7z")]
            commands = [f"7z x -y -o{quoted_dest} {quoted_archive}"]
        else:
            raise RuntimeError("Unsupported archive format.")

        entries = self._list_archive_entries(listing_commands, archive_full)
        self._validate_archive_entries(entries)
        self._mkdir_full(dest_full)
        self._run_fallback_commands(commands)

    def _list_archive_entries(self, commands, archive_full: str):
        last_error = None
        for command, parser in commands:
            try:
                output = self.run_command(command, max_output_bytes=16 * 1024 * 1024)
                if parser == "7z":
                    entries = [
                        line.split(" = ", 1)[1]
                        for line in output.splitlines()
                        if line.startswith("Path = ")
                    ]
                    archive_variants = {
                        archive_full,
                        posixpath.basename(archive_full),
                    }
                    if entries and entries[0] in archive_variants:
                        entries = entries[1:]
                else:
                    entries = [line for line in output.splitlines() if line.strip()]
                if entries:
                    return entries
                raise RuntimeError("Archive contains no readable entries.")
            except Exception as exc:
                last_error = exc

        message = str(last_error) if last_error else "No archive listing tool is available."
        raise RuntimeError(
            "Archive extraction was blocked because its contents could not be "
            f"validated safely: {message}"
        )

    def _validate_archive_entries(self, entries):
        if len(entries) > self.MAX_ARCHIVE_ENTRIES:
            raise RuntimeError(
                f"Archive contains too many entries ({len(entries):,})."
            )

        for raw_entry in entries:
            entry = str(raw_entry).strip().replace("\\", "/")
            if not entry:
                continue
            if "\x00" in entry or entry.startswith("/"):
                raise RuntimeError(f"Unsafe absolute path in archive: {raw_entry}")
            if len(entry) >= 2 and entry[1] == ":":
                raise RuntimeError(f"Unsafe drive path in archive: {raw_entry}")
            parts = [part for part in entry.split("/") if part not in ("", ".")]
            if ".." in parts:
                raise RuntimeError(f"Unsafe parent path in archive: {raw_entry}")

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

    def _path_exists_full(self, full_path: str) -> bool:
        try:
            self.sftp.stat(full_path)
            return True
        except OSError as exc:
            if getattr(exc, "errno", None) == errno.ENOENT:
                return False
            raise

    @staticmethod
    def _temporary_sibling(full_path: str, label: str) -> str:
        parent = posixpath.dirname(full_path)
        name = posixpath.basename(full_path.rstrip("/")) or "item"
        return posixpath.join(parent, f".{name}.xyra-{label}-{uuid.uuid4().hex[:12]}")

    def _validate_source_destination(self, source_full: str, dest_full: str):
        source = posixpath.normpath(source_full)
        dest = posixpath.normpath(dest_full)
        if source == dest:
            raise RuntimeError("Source and destination are the same item.")
        try:
            attrs = self.sftp.stat(source)
        except OSError as exc:
            raise RuntimeError("Source item no longer exists.") from exc
        if stat.S_ISDIR(attrs.st_mode) and dest.startswith(source.rstrip("/") + "/"):
            raise RuntimeError("A folder cannot be copied or moved into itself.")

    def _commit_staged_path(self, staged_full: str, dest_full: str, *, overwrite: bool):
        destination_exists = self._path_exists_full(dest_full)
        if destination_exists and not overwrite:
            raise RuntimeError("Destination already exists. Choose Replace explicitly to overwrite it.")

        backup_full = None
        if destination_exists:
            backup_full = self._temporary_sibling(dest_full, "previous")
            self.sftp.rename(dest_full, backup_full)

        try:
            self.sftp.rename(staged_full, dest_full)
        except Exception:
            if backup_full is not None:
                try:
                    self.sftp.rename(backup_full, dest_full)
                except Exception as rollback_error:
                    raise RuntimeError(
                        "Replacing the destination failed and its previous item could not be restored automatically. "
                        f"Recovery item: {backup_full}"
                    ) from rollback_error
            raise

        if backup_full is not None:
            try:
                self._delete_full_path(backup_full)
            except Exception:
                # The requested target is already valid. A hidden recovery copy
                # is safer than rolling back a successful operation.
                pass

    def _copy_full_path_safely(self, source_full: str, dest_full: str, *, overwrite: bool):
        self._assert_full_path_within_root(source_full)
        self._assert_full_path_within_root(dest_full)
        self._validate_source_destination(source_full, dest_full)
        if self._path_exists_full(dest_full) and not overwrite:
            raise RuntimeError("Destination already exists. Choose Replace explicitly to overwrite it.")

        staged_full = self._temporary_sibling(dest_full, "copy")
        try:
            self._copy_full_path(source_full, staged_full)
            self._commit_staged_path(staged_full, dest_full, overwrite=overwrite)
        except Exception:
            try:
                if self._path_exists_full(staged_full):
                    self._delete_full_path(staged_full)
            except Exception:
                pass
            raise

    def _move_full_path(self, source_full: str, dest_full: str, *, overwrite: bool):
        self._assert_full_path_within_root(source_full)
        self._assert_full_path_within_root(dest_full)
        self._validate_source_destination(source_full, dest_full)
        destination_exists = self._path_exists_full(dest_full)
        if destination_exists and not overwrite:
            raise RuntimeError("Destination already exists. Choose Replace explicitly to overwrite it.")

        # With no conflict, prefer the server's atomic rename. If the server
        # reports a cross-filesystem move, fall back to staged copy + delete.
        if not destination_exists:
            try:
                self.sftp.rename(source_full, dest_full)
                return
            except Exception:
                if self._path_exists_full(dest_full):
                    raise RuntimeError(
                        "Destination appeared while moving. Nothing was overwritten; try again."
                    )

        self._copy_full_path_safely(source_full, dest_full, overwrite=overwrite)
        try:
            self._delete_full_path(source_full)
        except Exception as exc:
            raise RuntimeError(
                "The destination is complete, but the source could not be removed. "
                "Both copies were kept to avoid data loss."
            ) from exc

    def _copy_full_path(self, source_full: str, dest_full: str):
        self._assert_full_path_within_root(source_full)
        self._assert_full_path_within_root(dest_full)
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
        self._assert_full_path_within_root(full_path)
        attrs = self.sftp.stat(full_path)
        if stat.S_ISDIR(attrs.st_mode):
            for item in self.sftp.listdir_attr(full_path):
                self._delete_full_path(posixpath.join(full_path, item.filename))
            self.sftp.rmdir(full_path)
            return
        self.sftp.remove(full_path)

    def _delete_empty_dirs(self, full_path: str, stop_full: str):
        current = posixpath.normpath(full_path)
        stop = posixpath.normpath(stop_full)
        while current and current != stop and current.startswith(stop.rstrip("/") + "/"):
            try:
                entries = self.sftp.listdir_attr(current)
            except Exception:
                break
            visible = [entry for entry in entries if entry.filename != ".xyra-meta.json"]
            if visible:
                break
            try:
                self.sftp.rmdir(current)
            except Exception:
                break
            parent = posixpath.dirname(current)
            if parent == current:
                break
            current = parent

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
