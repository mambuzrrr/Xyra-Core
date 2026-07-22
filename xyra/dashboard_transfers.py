"""Background upload and download behavior for the dashboard."""

import os

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication

from xyra.conflicts import ConflictAction, ConflictDialog, ConflictEntry
from xyra.path_utils import join_server_path, normalize_api_path
from xyra.theme import OVERLAY_STYLE


class DashboardTransfersMixin:
    def _show_transfer_center(self):
        if self.transfer_center is None:
            from xyra.transfer_queue import TransferCenterDialog
            self.transfer_center = TransferCenterDialog(self.transfer_queue, self)
        self.transfer_center.show()
        self.transfer_center.raise_()
        self.transfer_center.activateWindow()

    def _handle_transfer_jobs_changed(self, jobs):
        active = sum(job["status"] == "running" for job in jobs)
        queued = sum(job["status"] == "queued" for job in jobs)
        failed = sum(job["status"] == "failed" for job in jobs)
        count = active + queued
        if hasattr(self, "task_transfers_button"):
            self.task_transfers_button.setText(f"Transfers · {count}" if count else "Transfers")
            if failed:
                self.task_transfers_button.setToolTip(f"{failed} failed transfer(s)")
            elif count:
                self.task_transfers_button.setToolTip(f"{active} active, {queued} queued")
            else:
                self.task_transfers_button.setToolTip("Open transfer center")

    def _handle_transfer_job_finished(self, job):
        status = job.get("status")
        direction = job.get("direction")
        name = job.get("name") or "transfer"
        if status == "completed":
            if direction == "upload" and normalize_api_path(job.get("target", ".")) == normalize_api_path(self.current_path):
                self.load_folder(self.current_path)
            label = "Upload finished" if direction == "upload" else "Download finished"
            self.show_toast(f"{label}: {name}", "fa6s.circle-check", "#8bc7a8")
        elif status == "failed":
            self.show_toast(
                f"Transfer failed: {name}. Open Transfers for details.",
                "fa6s.triangle-exclamation",
                "#e58f98",
            )

    def _has_local_files(self, event) -> bool:
        md = event.mimeData()
        if not md or not md.hasUrls():
            return False
        for u in md.urls():
            if u.isLocalFile():
                p = u.toLocalFile()
                if p and os.path.exists(p):
                    return True
        return False

    def _on_drag_enter(self, event):
        if self._has_local_files(event):
            event.setDropAction(Qt.DropAction.CopyAction)
            event.accept()
            self.drop_overlay.setGeometry(self.view.viewport().rect())
            self.drop_overlay.show()
            self.drop_overlay.raise_()
            return
        event.ignore()

    def _on_drag_move(self, event):
        if self._has_local_files(event):
            event.setDropAction(Qt.DropAction.CopyAction)
            event.accept()
            return
        event.ignore()

    def _on_drag_leave(self, event):
        self.drop_overlay.hide()
        event.accept()

    def _show_upload_overlay(self, text: str):
        self.upload_overlay.setText(text)
        self.upload_overlay.adjustSize()
        vp = self.view.viewport().rect()
        w = self.upload_overlay.width()
        h = self.upload_overlay.height()
        x = max(0, (vp.width() - w) // 2)
        y = max(0, (vp.height() - h) // 2)
        self.upload_overlay.setGeometry(x, y, w, h)
        self.upload_overlay.show()
        self.upload_overlay.raise_()
        QApplication.processEvents()

    def _hide_upload_overlay(self):
        self.upload_overlay.hide()
        self.search_cancel_button.hide()

    def _show_search_overlay(self, title: str, info: str):
        self.upload_overlay.setText(f"{title}\n{info}")
        self.upload_overlay.setStyleSheet(OVERLAY_STYLE)
        self.upload_overlay.adjustSize()
        vp = self.view.viewport().rect()
        w = self.upload_overlay.width()
        h = self.upload_overlay.height()
        x = max(0, (vp.width() - w) // 2)
        y = max(0, (vp.height() - h) // 2 - 20)
        self.upload_overlay.setGeometry(x, y, w, h)
        self.upload_overlay.show()
        self.upload_overlay.raise_()

        self.search_cancel_button.adjustSize()
        btn_w = self.search_cancel_button.width()
        btn_h = self.search_cancel_button.height()
        self.search_cancel_button.setGeometry(
            max(0, (vp.width() - btn_w) // 2),
            min(vp.height() - btn_h, y + h + 12),
            btn_w,
            btn_h,
        )
        self.search_cancel_button.show()
        self.search_cancel_button.raise_()
        QApplication.processEvents()

    def _hide_search_overlay(self):
        self._hide_upload_overlay()
        self.upload_overlay.setStyleSheet(OVERLAY_STYLE)

    @staticmethod
    def _local_conflict_entry(local_path: str) -> ConflictEntry:
        try:
            attrs = os.stat(local_path)
            size = int(attrs.st_size)
            modified = float(attrs.st_mtime)
        except OSError:
            size = None
            modified = None
        return ConflictEntry(
            path=os.path.abspath(local_path),
            is_dir=os.path.isdir(local_path),
            size=size,
            modified=modified,
        )

    def _remote_conflict_entry(self, remote_path: str, info: dict) -> ConflictEntry:
        return ConflictEntry(
            path=self._display_server_path(remote_path),
            is_dir=bool(info.get("isDir")),
            size=info.get("size"),
            modified=info.get("modTime"),
        )

    def _confirm_remote_destination(
        self,
        operation: str,
        source_path: str,
        target_path: str,
        *,
        parent=None,
    ) -> tuple[bool, bool]:
        try:
            target_info = self._backend_path_info_or_none(target_path)
            if not target_info:
                return True, False
            source_info = self._backend_get_path_info(source_path)
        except Exception as exc:
            self.show_toast(str(exc), "fa6s.triangle-exclamation", "#e58f98")
            return False, False

        decision = ConflictDialog(
            operation,
            self._remote_conflict_entry(source_path, source_info),
            self._remote_conflict_entry(target_path, target_info),
            parent or self,
        ).decision()
        return decision.action == ConflictAction.REPLACE, decision.action == ConflictAction.REPLACE

    def _confirm_upload_overwrite(
        self,
        local_path: str,
        *,
        allow_apply_to_all: bool = False,
        shared_action: ConflictAction | None = None,
    ):
        target_path = join_server_path(self.current_path, os.path.basename(local_path.rstrip("\\/")))
        try:
            info = self._backend_path_info_or_none(target_path)
        except Exception as exc:
            self.show_toast(str(exc), "fa6s.triangle-exclamation", "#e58f98")
            return "cancel", False, False
        if not info:
            return "upload", False, False

        if shared_action is not None:
            decision_action = shared_action
            apply_to_all = True
        else:
            decision = ConflictDialog(
                "Upload",
                self._local_conflict_entry(local_path),
                self._remote_conflict_entry(target_path, info),
                self,
                allow_apply_to_all=allow_apply_to_all,
            ).decision()
            decision_action = decision.action
            apply_to_all = decision.apply_to_all

        if decision_action == ConflictAction.REPLACE:
            return "upload", True, apply_to_all
        if decision_action == ConflictAction.SKIP:
            return "skip", False, apply_to_all
        return "cancel", False, False

    def _confirm_local_download_overwrite(self, remote_path: str, local_path: str) -> tuple[bool, bool]:
        if not os.path.exists(local_path):
            return True, False
        try:
            remote_info = self._backend_get_path_info(remote_path)
        except Exception as exc:
            self.show_toast(str(exc), "fa6s.triangle-exclamation", "#e58f98")
            return False, False
        decision = ConflictDialog(
            "Download",
            self._remote_conflict_entry(remote_path, remote_info),
            self._local_conflict_entry(local_path),
            self,
        ).decision()
        return decision.action == ConflictAction.REPLACE, decision.action == ConflictAction.REPLACE

    def _on_drop(self, event):
        self.drop_overlay.hide()

        md = event.mimeData()
        if not md or not md.hasUrls():
            event.ignore()
            return

        local_paths = []
        for u in md.urls():
            if u.isLocalFile():
                p = u.toLocalFile()
                if p and os.path.exists(p):
                    local_paths.append(p)

        if not local_paths:
            event.ignore()
            return

        if self._remote_job_active or self._remote_search_active:
            self.show_toast(self.T["remote_job_busy"], "fa6s.hourglass-half", "#f4c76b")
            event.ignore()
            return

        event.setDropAction(Qt.DropAction.CopyAction)
        event.accept()

        upload_jobs = []
        shared_action = None
        for p in local_paths:
            action, overwrite, apply_to_all = self._confirm_upload_overwrite(
                p,
                allow_apply_to_all=len(local_paths) > 1,
                shared_action=shared_action,
            )
            if action == "cancel":
                return
            if apply_to_all and shared_action is None:
                shared_action = ConflictAction.REPLACE if overwrite else ConflictAction.SKIP
            if action == "skip":
                continue
            upload_jobs.append((p, overwrite))

        if not upload_jobs:
            return

        target_remote_dir = self.current_path
        for local_path, overwrite in upload_jobs:
            item_name = os.path.basename(local_path.rstrip("\\/")) or local_path

            def runner(progress, cancel_event, source=local_path, replace=overwrite):
                self._backend_upload_path_with_options(
                    source,
                    target_remote_dir,
                    overwrite=replace,
                    progress_callback=progress,
                    cancel_callback=cancel_event.is_set,
                )

            self.transfer_queue.enqueue(
                direction="upload",
                name=item_name,
                source=local_path,
                target=target_remote_dir,
                runner=runner,
            )

        self.show_toast(
            f"{len(upload_jobs)} upload(s) added to Transfers",
            "fa6s.arrow-up-from-bracket",
            "#d8c39a",
        )
        self._show_transfer_center()
