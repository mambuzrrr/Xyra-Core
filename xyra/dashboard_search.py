"""Search, navigation, status and information dialogs for the dashboard."""

import html
import os
import threading

from PyQt6.QtCore import Qt, QSize
from PyQt6.QtGui import QIcon, QPixmap
from PyQt6.QtWidgets import (
    QApplication, QDialog, QHBoxLayout, QInputDialog, QLabel, QListWidget,
    QListWidgetItem, QMenu, QMessageBox, QPlainTextEdit, QToolButton,
    QVBoxLayout,
)

from xyra.app_constants import (
    APP_CONTRIBUTORS, APP_DEVELOPER, APP_ICON_PATH, APP_LOGO_PATH, APP_NAME,
    APP_VERSION,
)
from xyra.path_utils import is_valid_new_name, join_server_path, normalize_api_path


class DashboardSearchMixin:
    def show_server_health(self):
        if self.backend is None:
            QMessageBox.warning(self, self.T["server_health_title"], self.DISCONNECTED_MESSAGE)
            return
        if self._remote_job_active or self._remote_search_active:
            self.show_toast(self.T["remote_job_busy"], "fa6s.hourglass-half", "#f4c76b")
            return

        self._remote_job_active = True
        self._show_upload_overlay(self.T["server_health_checking"])

        def worker():
            try:
                report = self._backend_server_health()
                self.server_health_done.emit(report)
            except Exception as e:
                self.server_health_failed.emit(str(e))

        threading.Thread(target=worker, daemon=True).start()

    def _show_server_health_dialog(self, report: str):
        self._remote_job_active = False
        self._hide_upload_overlay()

        def first_value(prefix: str, default: str = "Unknown") -> str:
            marker = f"{prefix}:"
            lines = (report or "").splitlines()
            for index, line in enumerate(lines):
                if line.startswith(marker):
                    value = line[len(marker):].strip()
                    if not value:
                        for candidate in lines[index + 1:]:
                            candidate = candidate.strip()
                            if candidate:
                                return candidate
                    return value or default
            return default

        def first_disk_row(section_title: str) -> str:
            lines = (report or "").splitlines()
            for index, line in enumerate(lines):
                if line.strip() == section_title:
                    for candidate in lines[index + 1:]:
                        if not candidate.strip():
                            break
                        if candidate.startswith("Filesystem"):
                            continue
                        parts = candidate.split()
                        if len(parts) >= 5:
                            return f"{parts[4]} used, {parts[3]} free"
            return "Unknown"

        def make_card(title_text: str, value_text: str, accent: str):
            card = QLabel(
                f"<div style='color:{accent};font-size:11px;font-weight:700;letter-spacing:0.4px'>{title_text}</div>"
                f"<div style='color:#f4f7fb;font-size:16px;font-weight:800;margin-top:4px'>{value_text}</div>"
            )
            card.setTextFormat(Qt.TextFormat.RichText)
            card.setMinimumHeight(74)
            card.setStyleSheet(
                "QLabel { background: rgba(255,255,255,0.055); "
                "border: 1px solid rgba(255,255,255,0.10); border-radius: 14px; padding: 12px; }"
            )
            return card

        host = first_value("Host")
        user = first_value("User")
        xyra_path = first_value("Xyra path", "/")
        load = first_value("Load")
        memory = first_value("Memory")
        disk = first_disk_row("Disk for current path:")
        uptime = first_value("Uptime")
        system = first_value("System")

        dlg = QDialog(self)
        dlg.setWindowTitle(self.T["server_health_title"])
        dlg.resize(820, 620)
        dlg.setStyleSheet("""
            QDialog { background: rgb(14,18,26); color: #eef3f9; }
            QLabel { color: #eef3f9; }
            QPlainTextEdit {
                color: #dbe7f5;
                background: rgba(255,255,255,0.045);
                border: 1px solid rgba(255,255,255,0.10);
                border-radius: 14px;
                padding: 12px;
                font-family: Consolas, "Cascadia Mono", monospace;
                font-size: 12px;
            }
            QPlainTextEdit:hover {
                border-color: rgba(216,195,154,0.22);
            }
            QToolButton {
                color: #eef3f9;
                background: rgba(255,255,255,0.08);
                border: 1px solid rgba(255,255,255,0.12);
                border-radius: 10px;
                padding: 8px 14px;
            }
            QToolButton:hover {
                background: rgba(216,195,154,0.14);
                border-color: rgba(216,195,154,0.32);
            }
        """)
        if os.path.exists(APP_ICON_PATH):
            dlg.setWindowIcon(QIcon(APP_ICON_PATH))

        layout = QVBoxLayout(dlg)
        layout.setContentsMargins(18, 18, 18, 16)
        layout.setSpacing(14)

        title = QLabel(
            f"<div style='font-size:20px;font-weight:900'>{self.T['server_health_title']}</div>"
            f"<div style='color:#97aac2;font-size:12px'>Read-only snapshot for the active SSH server.</div>"
        )
        title.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(title)

        card_row_one = QHBoxLayout()
        card_row_one.setSpacing(10)
        card_row_one.addWidget(make_card("HOST", host, "#8bc7a8"))
        card_row_one.addWidget(make_card("USER", user, "#c7b7d8"))
        card_row_one.addWidget(make_card("DISK", disk, "#f4c76b"))
        layout.addLayout(card_row_one)

        card_row_two = QHBoxLayout()
        card_row_two.setSpacing(10)
        card_row_two.addWidget(make_card("LOAD", load, "#ff9ea5"))
        card_row_two.addWidget(make_card("MEMORY", memory, "#caa9ff"))
        card_row_two.addWidget(make_card("PATH", xyra_path, "#b7f7d8"))
        layout.addLayout(card_row_two)

        meta = QLabel(
            f"<span style='color:#97aac2'>Uptime:</span> {uptime}<br>"
            f"<span style='color:#97aac2'>System:</span> {system}"
        )
        meta.setTextFormat(Qt.TextFormat.RichText)
        meta.setWordWrap(True)
        meta.setStyleSheet(
            "QLabel { background: rgba(255,255,255,0.035); "
            "border: 1px solid rgba(255,255,255,0.08); border-radius: 12px; padding: 10px 12px; }"
        )
        layout.addWidget(meta)

        raw_label = QLabel("<b>Raw report</b>")
        raw_label.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(raw_label)

        report_box = QPlainTextEdit()
        report_box.setReadOnly(True)
        report_box.setPlainText(report or "No health data returned.")
        layout.addWidget(report_box, 1)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_copy = QToolButton()
        btn_copy.setText(self.T["copy_report"])
        btn_close = QToolButton()
        btn_close.setText(self.T["about_close"])
        btn_row.addWidget(btn_copy)
        btn_row.addWidget(btn_close)
        layout.addLayout(btn_row)

        btn_copy.clicked.connect(lambda: QApplication.clipboard().setText(report_box.toPlainText()))
        btn_close.clicked.connect(dlg.accept)
        dlg.exec()

    def _finish_server_health_error(self, error_text: str):
        self._remote_job_active = False
        self._hide_upload_overlay()
        QMessageBox.warning(self, self.T["server_health_title"], f"{self.T['server_health_failed']}:\n{error_text}")

    def show_trash_manager(self):
        if self.backend is None:
            QMessageBox.warning(self, self.T["trash_manager"], self.DISCONNECTED_MESSAGE)
            return
        if self._remote_job_active or self._remote_search_active:
            self.show_toast(self.T["remote_job_busy"], "fa6s.hourglass-half", "#f4c76b")
            return

        try:
            trash_items = self._backend_list_trash()
        except Exception as e:
            QMessageBox.warning(self, self.T["trash_manager"], f"{self.T['trash_loaded_failed']}:\n{e}")
            return

        dlg = QDialog(self)
        dlg.setWindowTitle(self.T["trash_manager"])
        dlg.resize(860, 540)
        dlg.setStyleSheet("""
            QDialog { background: rgba(14,18,26,0.98); color: #eef3f9; }
            QLabel { color: #eef3f9; }
            QListWidget {
                color: #e8eef7;
                background: rgba(255,255,255,0.05);
                border: 1px solid rgba(255,255,255,0.10);
                border-radius: 14px;
                padding: 10px;
                outline: 0;
                selection-background-color: transparent;
            }
            QListWidget::item {
                min-height: 42px;
                padding: 8px 10px;
                margin: 1px;
                border-radius: 9px;
                border: 1px solid transparent;
            }
            QListWidget::item:hover {
                background: rgba(255,255,255,0.07);
                border-color: rgba(255,255,255,0.10);
            }
            QListWidget::item:selected,
            QListWidget::item:selected:active,
            QListWidget::item:selected:!active {
                color: #f7fbff;
                background: rgba(244,199,107,0.18);
                border-color: rgba(244,199,107,0.38);
            }
            QToolButton {
                color: #eef3f9;
                background: rgba(255,255,255,0.08);
                border: 1px solid rgba(255,255,255,0.12);
                border-radius: 10px;
                padding: 8px 14px;
            }
            QToolButton:hover { background: rgba(216,195,154,0.14); border-color: rgba(216,195,154,0.32); }
            QToolButton#dangerButton:hover { background: rgba(255,123,123,0.18); border-color: rgba(255,123,123,0.45); }
        """)

        layout = QVBoxLayout(dlg)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        title = QLabel(f"<b>{self.T['trash_manager']}</b>")
        title.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(title)

        trash_list = QListWidget()
        trash_list.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        for item_data in trash_items:
            original = item_data.get("original_path") or ""
            trash_path = item_data.get("trash_path") or ""
            display_path = self._display_server_path(original or trash_path)
            deleted_at = item_data.get("deleted_at") or "-"
            kind = self.T["folder"] if item_data.get("isDir") else self.T["file"]
            label = f"{display_path}\n{kind}  |  {deleted_at}"
            list_item = QListWidgetItem(label)
            list_item.setData(Qt.ItemDataRole.UserRole, item_data)
            list_item.setIcon(self._make_icon("fa6s.folder", "#d8c39a") if item_data.get("isDir") else self._make_icon("fa6s.file-lines", "#c7c3bc"))
            list_item.setSizeHint(QSize(0, 56))
            trash_list.addItem(list_item)
        layout.addWidget(trash_list, 1)

        if not trash_items:
            empty = QListWidgetItem(self.T["trash_empty"])
            empty.setFlags(Qt.ItemFlag.NoItemFlags)
            trash_list.addItem(empty)

        btn_row = QHBoxLayout()
        btn_restore = QToolButton()
        btn_restore.setText(self.T["trash_restore"])
        btn_restore.setIcon(self._make_icon("fa6s.rotate-left", "#8bc7a8"))
        btn_open = QToolButton()
        btn_open.setText(self.T["trash_open_original"])
        btn_open.setIcon(self._make_icon("fa6s.folder-open", "#d8c39a"))
        btn_delete = QToolButton()
        btn_delete.setText(self.T["trash_delete"])
        btn_delete.setIcon(self._make_icon("fa6s.trash", "#ff7b7b"))
        btn_delete.setObjectName("dangerButton")
        btn_empty = QToolButton()
        btn_empty.setText(self.T["trash_empty_all"])
        btn_empty.setIcon(self._make_icon("fa6s.broom", "#ffb86b"))
        btn_empty.setObjectName("dangerButton")
        btn_close = QToolButton()
        btn_close.setText(self.T["about_close"])

        btn_row.addWidget(btn_restore)
        btn_row.addWidget(btn_open)
        btn_row.addWidget(btn_delete)
        btn_row.addStretch()
        btn_row.addWidget(btn_empty)
        btn_row.addWidget(btn_close)
        layout.addLayout(btn_row)

        def selected_trash_item():
            current = trash_list.currentItem()
            if not current:
                return None
            data = current.data(Qt.ItemDataRole.UserRole)
            return data if isinstance(data, dict) else None

        def refresh_and_reopen():
            dlg.accept()
            self.show_trash_manager()

        def restore_selected():
            data = selected_trash_item()
            if not data:
                return
            original = data.get("original_path") or ""
            trash_path = data.get("trash_path") or ""
            proceed, overwrite = self._confirm_remote_destination(
                "Restore", trash_path, original, parent=dlg
            )
            if not proceed:
                return
            try:
                self._backend_restore_trash(trash_path, original, overwrite=overwrite)
            except Exception as e:
                QMessageBox.warning(dlg, self.T["trash_manager"], f"{self.T['trash_restore_failed']}:\n{e}")
                return
            self.show_toast(f"{self.T['trash_restored']}: {self._display_server_path(original)}", "fa6s.rotate-left", "#53d18b")
            self.load_folder(self.current_path)
            refresh_and_reopen()

        def open_original_folder():
            data = selected_trash_item()
            if not data:
                return
            original = normalize_api_path(data.get("original_path") or "")
            if not original:
                return
            parent = normalize_api_path(os.path.dirname(original.replace("\\", "/")) or ".")
            dlg.accept()
            self._navigate_to_path(parent)

        def delete_selected():
            data = selected_trash_item()
            if not data:
                return
            trash_path = data.get("trash_path") or ""
            res = QMessageBox.question(
                dlg,
                self.T["trash_manager"],
                self.T["permanent_delete_q"].format(path=self._display_server_path(trash_path)),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if res != QMessageBox.StandardButton.Yes:
                return
            try:
                self._backend_delete_trash(trash_path)
            except Exception as e:
                QMessageBox.warning(dlg, self.T["trash_manager"], f"{self.T['delete_failed']}:\n{e}")
                return
            self.show_toast(self.T["trash_deleted"], "fa6s.trash", "#ff7b7b")
            refresh_and_reopen()

        def empty_trash():
            if not trash_items:
                return
            res = QMessageBox.question(
                dlg,
                self.T["trash_manager"],
                self.T["trash_empty_q"],
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if res != QMessageBox.StandardButton.Yes:
                return
            try:
                self._backend_empty_trash()
            except Exception as e:
                QMessageBox.warning(dlg, self.T["trash_manager"], f"{self.T['delete_failed']}:\n{e}")
                return
            self.show_toast(self.T["trash_empty_done"], "fa6s.broom", "#f4c76b")
            self.load_folder(self.current_path)
            refresh_and_reopen()

        btn_restore.clicked.connect(restore_selected)
        btn_open.clicked.connect(open_original_folder)
        btn_delete.clicked.connect(delete_selected)
        btn_empty.clicked.connect(empty_trash)
        btn_close.clicked.connect(dlg.accept)
        trash_list.itemDoubleClicked.connect(lambda _item: restore_selected())
        dlg.exec()

    # ---------------- Search ----------------
    def _focus_search(self):
        self.search_box.setFocus()
        self.search_box.selectAll()

    def _on_search_changed(self, text: str):
        self.search_query = (text or "").strip()
        self._search_timer.start()

    def _clear_local_search_filter(self):
        if not (self.search_query or "").strip() and not self.search_box.text():
            return
        self._search_timer.stop()
        self.search_query = ""
        self.search_box.blockSignals(True)
        self.search_box.clear()
        self.search_box.blockSignals(False)

    def start_remote_search(self):
        if self.backend is None:
            QMessageBox.warning(self, self.T["remote_search_title"], self.DISCONNECTED_MESSAGE)
            return
        if self._remote_job_active or self._remote_search_active:
            self.show_toast(self.T["remote_job_busy"], "fa6s.hourglass-half", "#f4c76b")
            return

        query = (self.search_box.text() or "").strip()
        if not query:
            query, ok = QInputDialog.getText(self, self.T["remote_search_title"], self.T["remote_search_prompt"])
            if not ok:
                return
            query = (query or "").strip()
        if not query:
            return

        max_depth, ok = QInputDialog.getInt(self, self.T["remote_search_title"], self.T["remote_search_depth"], 4, 0, 12, 1)
        if not ok:
            return

        self._remote_search_id += 1
        search_id = self._remote_search_id
        self._remote_search_active = True
        self._remote_search_cancel_requested = False
        self._show_search_overlay(
            self.T["remote_searching"].format(query=query),
            self.T["remote_search_info"],
        )

        start_path = self.current_path

        def worker():
            try:
                def should_cancel():
                    return self._remote_search_cancel_requested or search_id != self._remote_search_id

                results = self._backend_search_files(start_path, query, max_depth, cancel_callback=should_cancel)
                self.remote_search_done.emit(search_id, query, results)
            except Exception as e:
                self.remote_search_failed.emit(search_id, str(e))

        threading.Thread(target=worker, daemon=True).start()

    def cancel_remote_search(self):
        if not self._remote_search_active:
            return
        self._remote_search_cancel_requested = True
        self._remote_search_id += 1
        self._remote_search_active = False
        self._hide_search_overlay()
        self.show_toast(self.T["remote_search_cancelled"], "fa6s.circle-xmark", "#f4c76b")

    def _finish_remote_search_error(self, search_id: int, error_text: str):
        if search_id != self._remote_search_id:
            return
        self._remote_search_active = False
        self._hide_search_overlay()
        if "cancel" in (error_text or "").lower():
            self.show_toast(self.T["remote_search_cancelled"], "fa6s.circle-xmark", "#f4c76b")
            return
        QMessageBox.warning(self, self.T["remote_search_title"], f"{self.T['remote_search_failed']}:\n{error_text}")

    def _show_remote_search_results(self, search_id: int, query: str, results: list):
        if search_id != self._remote_search_id:
            return
        self._remote_search_active = False
        self._hide_search_overlay()

        dlg = QDialog(self)
        dlg.setWindowTitle(f"{self.T['remote_search_results']} - {query}")
        dlg.resize(780, 520)
        dlg.setStyleSheet("""
            QDialog { background: rgba(14,18,26,0.98); color: #eef3f9; }
            QLabel { color: #eef3f9; }
            QListWidget {
                color: #e8eef7;
                background: rgba(255,255,255,0.05);
                border: 1px solid rgba(255,255,255,0.10);
                border-radius: 14px;
                padding: 10px;
                outline: 0;
                selection-background-color: transparent;
            }
            QListWidget::item {
                min-height: 28px;
                padding: 5px 10px;
                margin: 0px;
                border-radius: 8px;
                border: 1px solid transparent;
            }
            QListWidget::item:hover {
                background: rgba(255,255,255,0.07);
                border-color: rgba(255,255,255,0.10);
            }
            QListWidget::item:selected,
            QListWidget::item:selected:active,
            QListWidget::item:selected:!active {
                color: #f7fbff;
                background: rgba(216,195,154,0.20);
                border-color: rgba(216,195,154,0.40);
            }
            QToolButton {
                color: #eef3f9;
                background: rgba(255,255,255,0.08);
                border: 1px solid rgba(255,255,255,0.12);
                border-radius: 10px;
                padding: 8px 14px;
            }
            QToolButton:hover { background: rgba(216,195,154,0.14); border-color: rgba(216,195,154,0.32); }
        """)

        layout = QVBoxLayout(dlg)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        title = QLabel(f"<b>{len(results)}</b> result(s) for <b>{query}</b> from {self._display_server_path(self.current_path)}")
        title.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(title)

        hint = QLabel(self.T["remote_search_hint"] if results else self.T["remote_search_empty"])
        hint.setStyleSheet("color: #93a5ba;")
        layout.addWidget(hint)

        result_list = QListWidget()
        result_list.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        for result in results:
            path = normalize_api_path(result.get("path", "."))
            label = self._display_server_path(path)
            if result.get("isDir"):
                label += "  [folder]"
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, result)
            item.setIcon(self._make_icon("fa6s.folder", "#d8c39a") if result.get("isDir") else self._make_icon("fa6s.file-lines", "#c7c3bc"))
            item.setSizeHint(QSize(0, 34))
            result_list.addItem(item)
        layout.addWidget(result_list, 1)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_copy = QToolButton()
        btn_copy.setText(self.T["remote_search_copy_path"])
        btn_open = QToolButton()
        btn_open.setText(self.T["remote_search_open_folder"])
        btn_close = QToolButton()
        btn_close.setText(self.T["about_close"])
        btn_row.addWidget(btn_copy)
        btn_row.addWidget(btn_open)
        btn_row.addWidget(btn_close)
        layout.addLayout(btn_row)

        def selected_result():
            item = result_list.currentItem()
            return item.data(Qt.ItemDataRole.UserRole) if item else None

        def open_selected():
            result = selected_result()
            if not result:
                return
            target = normalize_api_path(result.get("path", ".") if result.get("isDir") else result.get("parent", "."))
            dlg.accept()
            self._navigate_to_path(target)

        def copy_selected():
            result = selected_result()
            if not result:
                return
            self._copy_remote_path_to_clipboard(result.get("path", "."))

        result_list.itemDoubleClicked.connect(lambda _: open_selected())
        btn_open.clicked.connect(open_selected)
        btn_copy.clicked.connect(copy_selected)
        btn_close.clicked.connect(dlg.accept)
        dlg.exec()

    # ---------------- Path badge ----------------
    def update_path_label(self):
        p = normalize_api_path(self.current_path)
        text = "/" if p in (".", "") else ("/" + p)
        self.path_badge.setText(text)
        self.path_badge.setToolTip(f"{self.T['path_menu']}: {text}")
        if hasattr(self, "task_path_label"):
            self.task_path_label.setText(text)
            self.task_path_label.setToolTip(f"{self.T['path_menu']}: {text}")
        self._reposition_path_badge()

    def _show_path_badge_menu(self, event, anchor_widget=None):
        menu = QMenu(self)
        current = normalize_api_path(self.current_path)

        for label, path in self._breadcrumb_paths(current):
            action = menu.addAction(f"{self.T['go_to']} {label}")
            action.setIcon(self._make_icon("fa6s.folder-open", "#d8c39a"))
            action.triggered.connect(lambda checked=False, p=path: self._navigate_to_path(p))

        menu.addSeparator()
        act_copy = menu.addAction(self.T["copy_current_path"])
        act_copy.setIcon(self._make_icon("fa6s.copy", "#c7c3bc"))
        act_start = menu.addAction(self.T["set_start_path"])
        act_start.setIcon(self._make_icon("fa6s.location-dot", "#f4c76b"))
        favorites = self._clean_saved_paths(self.cfg.get("favorites", []), limit=50)
        act_favorite = menu.addAction(self.T["remove_favorite"] if current in favorites else self.T["add_favorite"])
        act_favorite.setIcon(self._make_icon("fa6s.star", "#f4c76b"))

        if anchor_widget is not None:
            chosen = self._exec_menu_above_widget(menu, anchor_widget)
        else:
            chosen = menu.exec(event.globalPosition().toPoint())
        if chosen == act_copy:
            self._copy_remote_path_to_clipboard(self.current_path)
        elif chosen == act_start:
            self._set_current_path_as_start()
        elif chosen == act_favorite:
            self._toggle_favorite_path(self.current_path)

    def _breadcrumb_paths(self, path: str):
        norm = normalize_api_path(path)
        crumbs = [("/", ".")]
        if norm in ("", "."):
            return crumbs

        parts = [part for part in norm.split("/") if part]
        cur_parts = []
        for part in parts:
            cur_parts.append(part)
            crumb_path = "/".join(cur_parts)
            crumbs.append(("/" + crumb_path, crumb_path))
        return crumbs

    def _reposition_path_badge(self):
        if hasattr(self, "path_badge") and not self.path_badge.isVisible():
            return
        vp = self.view.viewport().rect()
        self.path_badge.adjustSize()
        w = self.path_badge.width()
        h = self.path_badge.height()
        x = max(0, (vp.width() - w) // 2)
        taskbar_h = self.taskbar.height() + 22 if hasattr(self, "taskbar") else 0
        y = max(0, vp.height() - h - taskbar_h - 14)
        self.path_badge.setGeometry(x, y, w, h)
        self.path_badge.raise_()

    def _reposition_version_badge(self):
        if hasattr(self, "version_badge") and not self.version_badge.isVisible():
            return
        vp = self.view.viewport().rect()
        self.version_badge.adjustSize()
        w = self.version_badge.width()
        h = self.version_badge.height()
        x = max(0, vp.width() - w - 14)
        taskbar_h = self.taskbar.height() + 22 if hasattr(self, "taskbar") else 0
        y = max(0, vp.height() - h - taskbar_h - 14)
        self.version_badge.setGeometry(x, y, w, h)
        self.version_badge.raise_()

    def _show_center_message(self, text: str):
        self._center_message_source = text
        if text == self.DISCONNECTED_MESSAGE:
            content = (
                "<div align='center'>"
                "<span style='color:#8d8982;font-size:9pt;font-weight:700'>REMOTE WORKSPACE</span>"
                "<br><br><span style='color:#f3f1ed;font-size:17pt;font-weight:700'>"
                "No server connected</span>"
                "<br><br><span style='color:#a19e98;font-size:10pt'>"
                "Open <b style='color:#ded8cc'>Remote</b> in the top bar to connect your VPS."
                "</span></div>"
            )
            target_width = 440
        else:
            safe_text = html.escape(text or "").replace("\n", "<br>")
            content = f"<div align='center' style='color:#c7c3bc'>{safe_text}</div>"
            target_width = 380
        self.center_message.setText(content)
        self.center_message.setFixedWidth(target_width)
        self.center_message.adjustSize()
        vp = self.view.viewport().rect()
        w = min(self.center_message.width(), max(320, vp.width() - 80))
        h = self.center_message.height()
        x = max(20, (vp.width() - w) // 2)
        y = max(70, (vp.height() - h) // 2)
        self.center_message.setGeometry(x, y, w, h)
        self.center_message.show()
        self.center_message.raise_()

    def _hide_center_message(self):
        self.center_message.hide()

    # ---------------- About ----------------
    def show_about_dialog(self):
        dlg = QDialog(self)
        dlg.setWindowTitle(f"{APP_NAME} - {self.T['about_title']}")
        dlg.setModal(True)
        dlg.setFixedSize(460, 430)
        dlg.setStyleSheet("""
            QDialog { background: rgb(14,18,26); }
            QLabel { color: #eef3f9; }
            QToolButton {
                color: #eef3f9;
                background: rgba(255,255,255,0.08);
                border: 1px solid rgba(255,255,255,0.12);
                border-radius: 10px;
                padding: 8px 14px;
            }
            QToolButton:hover {
                background: rgba(216,195,154,0.14);
                border: 1px solid rgba(216,195,154,0.32);
            }
        """)
        if os.path.exists(APP_ICON_PATH):
            dlg.setWindowIcon(QIcon(APP_ICON_PATH))

        layout = QVBoxLayout(dlg)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(14)

        logo_lbl = QLabel()
        logo_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        logo_pm = QPixmap(APP_LOGO_PATH) if os.path.exists(APP_LOGO_PATH) else QPixmap()
        if not logo_pm.isNull():
            logo_lbl.setPixmap(
                logo_pm.scaled(132, 132, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            )
        else:
            logo_lbl.setText("X")
            logo_lbl.setStyleSheet("color: rgba(255,255,255,0.5); font-size: 42px;")
            logo_lbl.setFixedHeight(90)
        layout.addWidget(logo_lbl)

        title = QLabel(
            f"<div style='text-align:center'>"
            f"<b style='font-size:22px'>{APP_NAME}</b><br>"
            f"<span style='color:#97aac2;font-size:12px'>Remote Linux file dashboard</span>"
            f"</div>"
        )
        title.setTextFormat(Qt.TextFormat.RichText)
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        info = QLabel(
            f"<div style='color:white; line-height:1.55'>"
            f"<b>Developer:</b> {APP_DEVELOPER}<br>"
            f"<b>Version:</b> {APP_VERSION}<br>"
            f"<b>Contributors:</b> {APP_CONTRIBUTORS}<br>"
            f"<b>Website:</b> SOON...</a>"
            f"</div>"
        )
        info.setOpenExternalLinks(True)
        info.setTextFormat(Qt.TextFormat.RichText)
        info.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(info)

        layout.addStretch()

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_close = QToolButton()
        btn_close.setText(self.T["about_close"])
        btn_close.clicked.connect(dlg.accept)
        btn_row.addWidget(btn_close)
        layout.addLayout(btn_row)

        dlg.exec()

    # ---------------- EMPTY SPACE context menu (Create folder/file) ----------------
    def show_empty_context_menu(self, global_pos):
        menu = QMenu(self)
        act_refresh = menu.addAction(self.T["refresh"])
        act_refresh.setIcon(self._make_icon("fa6s.rotate-right", "#c7c3bc"))
        menu.addSeparator()
        act_copy_path = menu.addAction(self.T["copy_current_path"])
        act_copy_path.setIcon(self._make_icon("fa6s.copy", "#c7c3bc"))
        act_favorite = menu.addAction(self.T["add_favorite"])
        act_favorite.setIcon(self._make_icon("fa6s.star", "#f4c76b"))
        menu.addSeparator()
        act_folder = menu.addAction(self.T["create_folder"])
        act_file = menu.addAction(self.T["create_file"])

        chosen = menu.exec(global_pos)
        if chosen == act_refresh:
            self.refresh_session()
        elif chosen == act_copy_path:
            self._copy_remote_path_to_clipboard(self.current_path)
        elif chosen == act_favorite:
            self._toggle_favorite_path(self.current_path)
        elif chosen == act_folder:
            self._create_folder_dialog()
        elif chosen == act_file:
            self._create_file_dialog()

    def _create_folder_dialog(self):
        name, ok = QInputDialog.getText(self, self.T["create_title"], self.T["name_prompt"])
        if not ok:
            return
        name = (name or "").strip()
        if not is_valid_new_name(name):
            QMessageBox.warning(self, self.T["create_title"], self.T["rename_invalid"])
            return

        remote_path = join_server_path(self.current_path, name)

        try:
            self._backend_mkdir(remote_path)
        except Exception as e:
            QMessageBox.warning(self, self.T["create_title"], f"{self.T['create_failed']}:\n{e}")
            return

        self.load_folder(self.current_path)

    def _create_file_dialog(self):
        name, ok = QInputDialog.getText(self, self.T["create_title"], self.T["name_prompt"])
        if not ok:
            return
        name = (name or "").strip()
        if not is_valid_new_name(name):
            QMessageBox.warning(self, self.T["create_title"], self.T["rename_invalid"])
            return

        remote_path = join_server_path(self.current_path, name)

        try:
            self._backend_write_text(remote_path, "")
        except Exception as e:
            QMessageBox.warning(self, self.T["create_title"], f"{self.T['create_failed']}:\n{e}")
            return

        self.load_folder(self.current_path)
