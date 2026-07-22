"""User-facing authenticated update workflow."""

import os
import sys
import threading

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QMessageBox, QProgressDialog

from xyra.app_constants import APP_VERSION, UPDATE_MANIFEST_URLS, USER_DATA_DIR
from xyra.storage_utils import save_config
from xyra.update_key import UPDATE_PUBLIC_KEY_B64
from xyra.updater import UpdateClient


class DashboardUpdatesMixin:
    def _setup_updates(self):
        self._update_check_active = False
        self._update_download_active = False
        self._update_cancel = threading.Event()
        self._update_progress_dialog = None
        self.update_check_done.connect(self._finish_update_check)
        self.update_check_failed.connect(self._finish_update_check_error)
        self.update_download_progress.connect(self._update_download_progress_ui)
        self.update_download_done.connect(self._finish_update_download)
        self.update_download_failed.connect(self._finish_update_download_error)

    def _update_client(self):
        return UpdateClient(UPDATE_MANIFEST_URLS, UPDATE_PUBLIC_KEY_B64)

    def set_update_channel(self, channel: str):
        if channel not in ("stable", "prerelease"):
            return
        self.cfg["update_channel"] = channel
        save_config(self.cfg)
        label = "Stable" if channel == "stable" else "Preview"
        self.show_toast(f"Update channel: {label}", "fa6s.arrows-rotate", "#d8c39a")

    def toggle_automatic_update_checks(self):
        enabled = not bool(self.cfg.get("automatic_update_checks", True))
        self.cfg["automatic_update_checks"] = enabled
        save_config(self.cfg)
        self.show_toast(
            f"Automatic update checks {'enabled' if enabled else 'disabled'}",
            "fa6s.shield-halved", "#8bc7a8" if enabled else "#c7c3bc",
        )

    def check_for_updates(self, *, manual: bool = True):
        if self._update_check_active or self._update_download_active:
            if manual:
                self.show_toast("An update check is already running.", "fa6s.clock", "#f4c76b")
            return
        self._update_check_active = True
        channel = self.cfg.get("update_channel", "stable")
        if manual:
            self.show_toast("Checking for signed updates...", "fa6s.arrows-rotate", "#d8c39a")

        def worker():
            try:
                info = self._update_client().fetch_manifest(channel)
                self.update_check_done.emit(info, manual)
            except Exception as exc:
                self.update_check_failed.emit(str(exc), manual)

        threading.Thread(target=worker, daemon=True).start()

    def _finish_update_check(self, info, manual: bool):
        self._update_check_active = False
        client = self._update_client()
        if not client.is_newer(info, APP_VERSION):
            if manual:
                QMessageBox.information(self, "Xyra Updates", "You already have the newest Xyra version.")
            return
        size_mb = info.artifact.size / (1024 * 1024)
        channel = "Preview" if info.channel == "prerelease" else "Stable"
        answer = QMessageBox.question(
            self,
            "Signed Xyra update available",
            f"Xyra {info.version} is available on the {channel} channel.\n\n"
            f"Download: {size_mb:.1f} MB\n"
            "The installer will be verified against Xyra's embedded update key before it can run.\n\n"
            "Download this update now?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self._start_update_download(info)

    def _finish_update_check_error(self, message: str, manual: bool):
        self._update_check_active = False
        if manual:
            QMessageBox.warning(self, "Xyra Updates", f"Update check failed safely:\n\n{message}")

    def _start_update_download(self, info):
        self._update_download_active = True
        self._update_cancel.clear()
        dialog = QProgressDialog("Downloading and verifying update...", "Cancel", 0, 100, self)
        dialog.setWindowTitle("Xyra Updates")
        dialog.setWindowModality(Qt.WindowModality.WindowModal)
        dialog.setAutoClose(False)
        dialog.setAutoReset(False)
        dialog.canceled.connect(self._update_cancel.set)
        dialog.setValue(0)
        dialog.show()
        self._update_progress_dialog = dialog

        def worker():
            try:
                path = self._update_client().download(
                    info,
                    os.path.join(USER_DATA_DIR, "updates"),
                    progress=lambda done, total: self.update_download_progress.emit(done, total),
                    cancelled=self._update_cancel.is_set,
                )
                self.update_download_done.emit(path, info)
            except Exception as exc:
                self.update_download_failed.emit(str(exc))

        threading.Thread(target=worker, daemon=True).start()

    def _update_download_progress_ui(self, done: int, total: int):
        if self._update_progress_dialog is not None and total > 0:
            self._update_progress_dialog.setValue(min(100, int(done * 100 / total)))

    def _close_update_progress(self):
        if self._update_progress_dialog is not None:
            self._update_progress_dialog.close()
            self._update_progress_dialog.deleteLater()
            self._update_progress_dialog = None
        self._update_download_active = False

    def _finish_update_download_error(self, message: str):
        cancelled = self._update_cancel.is_set()
        self._close_update_progress()
        if cancelled:
            self.show_toast("Update download cancelled.", "fa6s.ban", "#c7c3bc")
        else:
            QMessageBox.warning(self, "Xyra Updates", f"Update was not installed:\n\n{message}")

    def _finish_update_download(self, path: str, info):
        self._close_update_progress()
        answer = QMessageBox.question(
            self,
            "Verified update ready",
            f"Xyra {info.version} was downloaded and verified successfully.\n\n"
            "Close Xyra and start the installer now?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            self.show_toast("Verified update kept for later.", "fa6s.shield-halved", "#8bc7a8")
            return
        try:
            self._update_client().launch_installer(path)
        except Exception as exc:
            QMessageBox.warning(self, "Xyra Updates", f"Installer could not be started:\n\n{exc}")
            return
        self.close()

    def schedule_automatic_update_check(self):
        if getattr(sys, "frozen", False) and self.cfg.get("automatic_update_checks", True):
            from PyQt6.QtCore import QTimer
            QTimer.singleShot(6000, lambda: self.check_for_updates(manual=False))
