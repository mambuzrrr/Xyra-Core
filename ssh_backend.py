import os
import posixpath

from path_utils import normalize_api_path, join_remote_path

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
        full = self._full_path(remote_path)
        attrs = self.sftp.stat(full)
        if attrs.st_mode & 0o040000:
            for item in self.sftp.listdir_attr(full):
                child = join_remote_path(remote_path, item.filename)
                self.delete_path(child)
            self.sftp.rmdir(full)
        else:
            self.sftp.remove(full)

    def rename(self, old_path: str, new_path: str):
        self._ensure_connected()
        self.sftp.rename(self._full_path(old_path), self._full_path(new_path))

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
