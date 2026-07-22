"""Inline rename, previews, external opening and text editing behavior."""

import hashlib
import os
import threading

from PyQt6.QtCore import QEvent, QObject, QPointF, Qt
from PyQt6.QtGui import QFontMetrics, QKeyEvent
from PyQt6.QtWidgets import QMessageBox

from xyra.app_constants import DANGEROUS_OPEN_EXTS, TEXT_EXTS
from xyra.editor import TextEditorWindow
from xyra.path_utils import is_valid_new_name, join_server_path, normalize_api_path, split_ext
from xyra.ui_components import ImagePreviewDialog


class DashboardEditingMixin:
    def _start_inline_rename(self, name: str):
        it = self.item_by_name.get(name)
        if not it or not it.text_item:
            return

        if self.rename_editor.isVisible():
            self._cancel_inline_rename()

        label_scene_rect = it.text_item.sceneBoundingRect()
        vp_top_left = self.view.mapFromScene(QPointF(label_scene_rect.left(), label_scene_rect.top()))
        vp_bot_right = self.view.mapFromScene(QPointF(label_scene_rect.right(), label_scene_rect.bottom()))

        self.rename_editor.setFont(it.text_item.font())
        metrics = QFontMetrics(self.rename_editor.font())
        label_w = max(72, min(188, metrics.horizontalAdvance(name) + 28))
        label_h = max(24, min(34, int(vp_bot_right.y() - vp_top_left.y()) + 4))
        center_x = int((vp_top_left.x() + vp_bot_right.x()) / 2)
        x = center_x - (label_w // 2)
        y = int(vp_top_left.y()) + 1

        viewport_rect = self.view.viewport().rect()
        x = max(8, min(x, viewport_rect.width() - label_w - 8))
        y = max(8, min(y, viewport_rect.height() - label_h - 8))

        self.rename_target_item = it
        self.rename_old_name = name
        self.rename_hidden_text_item = it.text_item
        it.text_item.hide()

        self.rename_editor.setGeometry(x, y, label_w, label_h)
        self.rename_editor.setText(name)
        self.rename_editor.show()
        self.rename_editor.raise_()
        self.rename_editor.setFocus()

        ext = split_ext(name)
        if ext and name.lower().endswith(ext):
            base_len = len(name) - len(ext)
            self.rename_editor.setSelection(0, base_len)
        else:
            self.rename_editor.selectAll()

    def eventFilter(self, a0: QObject | None, a1: QEvent | None) -> bool:
        if a0 is self.rename_editor and isinstance(a1, QKeyEvent):
            if a1.type() == QEvent.Type.KeyPress and a1.key() == Qt.Key.Key_Escape:
                self._cancel_inline_rename()
                return True
        return super().eventFilter(a0, a1)

    def _cancel_inline_rename(self):
        if self.rename_hidden_text_item is not None:
            self.rename_hidden_text_item.show()
        self.rename_editor.hide()
        self.rename_target_item = None
        self.rename_old_name = ""
        self.rename_hidden_text_item = None

    def _commit_inline_rename(self):
        if not self.rename_editor.isVisible():
            return

        new_name = (self.rename_editor.text() or "").strip()
        old_name = self.rename_old_name
        target_item = self.rename_target_item

        self._cancel_inline_rename()

        if not target_item or not old_name:
            return
        if new_name == old_name:
            return
        if not is_valid_new_name(new_name):
            QMessageBox.warning(self, self.T["rename"], self.T["rename_invalid"])
            return

        old_path = join_server_path(self.current_path, old_name)
        new_path = join_server_path(self.current_path, new_name)

        proceed, overwrite = self._confirm_remote_destination("Rename", old_path, new_path)
        if not proceed:
            return

        try:
            self._backend_rename(old_path, new_path, overwrite=overwrite)
        except Exception as e:
            QMessageBox.warning(self, self.T["rename"], f"{self.T['rename_failed']}:\n{e}")
            return

        if old_name in self.current_order:
            self.current_order = [new_name if n == old_name else n for n in self.current_order]
            # after rename, enforce grouping again
            self._enforce_folder_first_grouping()
            self._save_order_for_current_folder(self.current_order)

        self.load_folder(self.current_path)

    # ---------------- open/save ----------------
    def _block_dangerous_external_open(self, name: str) -> bool:
        if split_ext(name) not in DANGEROUS_OPEN_EXTS:
            return False
        QMessageBox.warning(
            self,
            "Potentially unsafe file",
            "Xyra will not run this remote file directly because its type can "
            "execute code on your computer.\n\n"
            f"File: {os.path.basename(name) or name}\n\n"
            "Use Download if you intentionally want to save and inspect it.",
        )
        return True

    def icon_double_clicked_by_name(self, name: str, is_dir: bool, shift_open: bool):
        new_path = join_server_path(self.current_path, name)

        entry = getattr(self, "_entry_by_name", {}).get(name, {})
        if entry.get("isAccessible") is False:
            self._show_file_open_error(name, entry.get("linkError", ""))
            return

        try:
            current_info = self._backend_get_path_info(new_path)
            is_dir = bool(current_info.get("isDir", is_dir))
        except Exception as e:
            self._show_file_open_error(name, str(e))
            return

        if is_dir:
            if not self._can_change_path():
                return
            self._clear_local_search_filter()
            self.load_folder(normalize_api_path(new_path), navigation_mode="normal")
            return

        if not self._confirm_sensitive_action(new_path):
            return

        ext = split_ext(name)
        if shift_open:
            if self._block_dangerous_external_open(name):
                return
            self._download_and_open_external(new_path, name)
            return

        if ext in {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".tga", ".ico"}:
            self._download_and_open_image_preview(new_path, name)
            return

        if ext in TEXT_EXTS:
            for editor in list(self.open_editors):
                try:
                    if editor.focus_document(new_path):
                        return
                except RuntimeError:
                    self._on_editor_destroyed(editor)

            try:
                data = self._backend_read_bytes(new_path)
            except Exception as e:
                self._show_file_open_error(name, str(e))
                return
            try:
                text = data.decode("utf-8")
            except Exception:
                text = data.decode("utf-8", errors="replace")

            try:
                for editor in list(self.open_editors):
                    try:
                        editor.open_document(new_path, text, self.save_file_to_server)
                        return
                    except RuntimeError:
                        self._on_editor_destroyed(editor)

                editor = TextEditorWindow(new_path, text, self.save_file_to_server)
                self.open_editors.append(editor)
                editor.destroyed.connect(lambda _, e=editor: self._on_editor_destroyed(e))
                editor.show()
                editor.raise_()
                editor.activateWindow()
            except Exception as e:
                self._show_file_open_error(name, str(e))
            return

        if not self._block_dangerous_external_open(name):
            self._download_and_open_external(new_path, name)

    def _on_editor_destroyed(self, editor_obj):
        try:
            self.open_editors.remove(editor_obj)
        except ValueError:
            pass

    def _on_preview_destroyed(self, preview_obj):
        try:
            self.open_previews.remove(preview_obj)
        except ValueError:
            pass

    def _show_image_preview_dialog(self, local_path: str, display_name: str):
        preview = ImagePreviewDialog(
            local_path,
            display_name,
            open_external_cb=lambda p=local_path: os.startfile(p),
            parent=self,
        )
        self.open_previews.append(preview)
        preview.destroyed.connect(lambda _, p=preview: self._on_preview_destroyed(p))
        preview.show()
        preview.raise_()
        preview.activateWindow()

    def _show_file_open_error(self, name: str, error: str):
        detail = (error or "").strip()
        lowered = detail.lower()
        if not detail or lowered in {"failure", "failed"}:
            reason = "The item or its link target is unavailable."
        elif "permission denied" in lowered:
            reason = "Permission denied by the remote server."
        elif "outside ssh root" in lowered:
            reason = "The link points outside the allowed remote workspace."
        elif len(detail) > 110:
            reason = detail[:107].rstrip() + "…"
        else:
            reason = detail

        display_name = os.path.basename(name) or name or "item"
        self.show_toast(
            f"Could not open {display_name}: {reason}",
            "fa6s.triangle-exclamation",
            "#e58f98",
        )
        self.toast.setToolTip(detail or reason)

    def _download_and_open_image_preview(self, remote_path: str, name: str):
        task_key = normalize_api_path(remote_path)
        if task_key in self._active_external_opens:
            return

        self._active_external_opens.add(task_key)
        self.show_toast(f"Loading preview for {os.path.basename(name) or name}...", "fa6s.image", "#c7b7d8")

        def worker():
            try:
                suffix = split_ext(name) or ".png"
                safe_name = os.path.basename(name) or "image"
                digest = hashlib.sha1(task_key.encode("utf-8", errors="ignore")).hexdigest()[:12]
                tmp_path = os.path.join(self.external_open_dir, f"{digest}_{safe_name}")
                if suffix and not tmp_path.lower().endswith(suffix.lower()):
                    tmp_path += suffix

                self._backend_download_file(remote_path, tmp_path)
                self.preview_ready.emit(tmp_path, os.path.basename(name) or name)
            except Exception as e:
                self.file_open_failed.emit(name, str(e))
            finally:
                self._active_external_opens.discard(task_key)

        threading.Thread(target=worker, daemon=True).start()

    def _download_and_open_external(self, remote_path: str, name: str):
        if self._block_dangerous_external_open(name):
            return
        task_key = normalize_api_path(remote_path)
        if task_key in self._active_external_opens:
            return

        self._active_external_opens.add(task_key)
        self.show_toast(f"Opening {os.path.basename(name) or name}...", "fa6s.up-right-from-square", "#d8c39a")

        def worker():
            try:
                suffix = split_ext(name) or ".bin"
                safe_name = os.path.basename(name) or "download"
                digest = hashlib.sha1(task_key.encode("utf-8", errors="ignore")).hexdigest()[:12]
                tmp_path = os.path.join(self.external_open_dir, f"{digest}_{safe_name}")
                if suffix and not tmp_path.lower().endswith(suffix.lower()):
                    tmp_path += suffix

                self._backend_download_file(remote_path, tmp_path)
                os.startfile(tmp_path)
            except Exception as e:
                self.file_open_failed.emit(name, str(e))
            finally:
                self._active_external_opens.discard(task_key)

        threading.Thread(target=worker, daemon=True).start()

    def save_file_to_server(self, remote_path, content) -> tuple:
        try:
            backup_key = normalize_api_path(remote_path)
            if backup_key not in self._editor_backup_paths:
                self._backend_backup_file(remote_path)
                self._editor_backup_paths.add(backup_key)
            self._backend_write_text(remote_path, content)
        except Exception as e:
            return False, str(e)
        return True, ""
