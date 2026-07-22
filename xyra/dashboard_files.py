"""Remote file actions, properties, permissions and archive operations."""

import os
import threading
from datetime import datetime

from PyQt6.QtCore import QPoint, Qt
from PyQt6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QFileDialog, QFormLayout, QGridLayout,
    QHBoxLayout, QInputDialog, QLabel, QLineEdit, QMenu, QMessageBox,
    QPlainTextEdit, QTabWidget, QToolButton, QVBoxLayout, QWidget,
)

from xyra.path_utils import join_server_path, normalize_api_path, split_ext
from xyra.permissions import (
    normalize_octal_mode, permission_presets, permission_risks,
    permission_summary, suggested_file_mode, symbolic_mode,
)


class DashboardFilesMixin:
    def show_item_context_menu(self, name: str, is_dir: bool, screen_pos: QPoint):
        if name not in self.selected_names:
            self._select_icon_by_name(name)

        menu = QMenu(self)
        act_properties = menu.addAction(self.T["properties"])
        act_properties.setIcon(self._make_icon("fa6s.circle-info", "#c7c3bc"))
        act_copy_path = menu.addAction(self.T["copy_path"])
        act_copy_path.setIcon(self._make_icon("fa6s.copy", "#c7c3bc"))
        act_favorite = None
        if is_dir:
            folder_path = join_server_path(self.current_path, name)
            folder_favorites = self._clean_saved_paths(self.cfg.get("favorites", []), limit=50)
            act_favorite = menu.addAction(
                self.T["remove_favorite"] if normalize_api_path(folder_path) in folder_favorites else self.T["add_folder_favorite"]
            )
            act_favorite.setIcon(self._make_icon("fa6s.star", "#f4c76b"))
        menu.addSeparator()
        act_rename = menu.addAction(self.T["rename"])
        act_rename.setIcon(self._make_icon("fa6s.pen", "#f4c76b"))
        act_delete = menu.addAction(self.T["delete"])
        act_delete.setIcon(self._make_icon("fa6s.trash-can-arrow-up", "#f4c76b"))
        act_delete_permanent = menu.addAction(self.T["delete_permanently"])
        act_delete_permanent.setIcon(self._make_icon("fa6s.trash", "#ff7b7b"))
        menu.addSeparator()
        act_copy = menu.addAction(self.T["copy_to"])
        act_copy.setIcon(self._make_icon("fa6s.copy", "#c7c3bc"))
        act_move = menu.addAction(self.T["move_to"])
        act_move.setIcon(self._make_icon("fa6s.arrows-right-left", "#d8c39a"))
        act_compress = menu.addAction(self.T["compress_zip"])
        act_compress.setIcon(self._make_icon("fa6s.file-zipper", "#53d18b"))

        act_download = None
        act_extract = None
        act_extract_to = None
        if not is_dir:
            if self._is_archive_name(name):
                menu.addSeparator()
                act_extract = menu.addAction(self.T["extract_here"])
                act_extract.setIcon(self._make_icon("fa6s.box-open", "#53d18b"))
                act_extract_to = menu.addAction(self.T["extract_to"])
                act_extract_to.setIcon(self._make_icon("fa6s.folder-open", "#53d18b"))
            menu.addSeparator()
            act_download = menu.addAction(self.T["download"])
            act_download.setIcon(self._make_icon("fa6s.download", "#c7b7d8"))

        chosen = menu.exec(screen_pos)
        if chosen == act_properties:
            self._show_item_properties(name)
        elif chosen == act_copy_path:
            self._copy_remote_path_to_clipboard(join_server_path(self.current_path, name))
        elif act_favorite is not None and chosen == act_favorite:
            self._toggle_favorite_path(join_server_path(self.current_path, name))
        elif chosen == act_rename:
            self._start_inline_rename(name)
        elif chosen == act_delete:
            self._delete_item(name)
        elif chosen == act_delete_permanent:
            self._delete_item(name, permanent=True)
        elif chosen == act_copy:
            self._copy_item_to(name)
        elif chosen == act_move:
            self._move_item_to(name)
        elif chosen == act_compress:
            self._compress_item_to_zip(name)
        elif act_extract is not None and chosen == act_extract:
            self._extract_item_here(name)
        elif act_extract_to is not None and chosen == act_extract_to:
            self._extract_item_to(name)
        elif act_download is not None and chosen == act_download:
            self._download_item(name)

    def _is_sensitive_remote_name(self, name: str) -> bool:
        base = os.path.basename(str(name or "")).lower()
        if not base:
            return False
        sensitive_names = {
            ".env", ".env.local", ".env.production", ".env.development",
            ".npmrc", ".pypirc", ".netrc", ".ssh", "id_rsa", "id_dsa",
            "id_ecdsa", "id_ed25519", "authorized_keys", "known_hosts",
            "config.php", "wp-config.php", "credentials", "credentials.json",
            "secrets.json", "secret.json", "private.key",
        }
        sensitive_exts = {
            ".pem", ".key", ".p12", ".pfx", ".crt", ".cer", ".csr",
            ".kdbx", ".ovpn", ".pgpass",
        }
        if base in sensitive_names:
            return True
        if base.startswith(".env."):
            return True
        return split_ext(base) in sensitive_exts

    def _confirm_sensitive_action(self, path: str) -> bool:
        if not self._is_sensitive_remote_name(path):
            return True
        res = QMessageBox.warning(
            self,
            self.T["sensitive_title"],
            self.T["sensitive_warning"].format(path=self._display_server_path(path)),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        return res == QMessageBox.StandardButton.Yes

    def _confirm_sensitive_selection(self, names: list[str]) -> bool:
        sensitive_paths = [
            join_server_path(self.current_path, name)
            for name in names
            if self._is_sensitive_remote_name(name)
        ]
        if not sensitive_paths:
            return True
        preview = "\n".join(f"- {self._display_server_path(path)}" for path in sensitive_paths[:8])
        if len(sensitive_paths) > 8:
            preview += f"\n... and {len(sensitive_paths) - 8} more"
        res = QMessageBox.warning(
            self,
            self.T["sensitive_title"],
            self.T["sensitive_multi_warning"].format(items=preview),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        return res == QMessageBox.StandardButton.Yes

    def _download_item(self, name: str):
        remote_path = join_server_path(self.current_path, name)
        if not self._confirm_sensitive_action(remote_path):
            return
        if self._remote_job_active or self._remote_search_active:
            self.show_toast(self.T["remote_job_busy"], "fa6s.hourglass-half", "#f4c76b")
            return

        suggested = os.path.basename(name) if name else "download.bin"
        save_path, _ = QFileDialog.getSaveFileName(self, self.T["download"], suggested, "All Files (*.*)")
        if not save_path:
            return
        proceed, overwrite = self._confirm_local_download_overwrite(remote_path, save_path)
        if not proceed:
            return

        download_name = os.path.basename(name) or name

        def runner(progress, cancel_event):
            self._backend_download_file(
                remote_path,
                save_path,
                overwrite=overwrite,
                progress_callback=progress,
                cancel_callback=cancel_event.is_set,
            )

        self.transfer_queue.enqueue(
            direction="download",
            name=download_name,
            source=remote_path,
            target=save_path,
            runner=runner,
        )
        self.show_toast(
            f"Download added to Transfers: {download_name}",
            "fa6s.arrow-down",
            "#d8c39a",
        )
        self._show_transfer_center()

    def _show_item_properties(self, name: str):
        remote_path = join_server_path(self.current_path, name)
        try:
            info = self._backend_get_path_info(remote_path)
        except Exception as e:
            QMessageBox.warning(self, self.T["properties_title"], f"{self.T['properties_failed']}:\n{e}")
            return

        dlg = QDialog(self)
        dlg.setWindowTitle(f"{self.T['properties_title']} - {name}")
        dlg.setMinimumWidth(500)
        dlg.setStyleSheet("""
            QDialog { background: rgba(14,18,26,0.98); }
            QLabel { color: #eef3f9; }
            QTabWidget::pane {
                border: 1px solid rgba(255,255,255,0.10);
                border-radius: 12px;
                top: 0px;
                background: rgba(255,255,255,0.025);
            }
            QTabBar::tab {
                color: #b9c8d8;
                background: rgba(255,255,255,0.040);
                border: 1px solid rgba(255,255,255,0.08);
                border-bottom: 1px solid rgba(255,255,255,0.08);
                border-radius: 8px;
                padding: 8px 14px;
                margin-right: 5px;
                margin-bottom: 6px;
            }
            QTabBar::tab:selected {
                color: #f6f9ff;
                background: rgba(216,195,154,0.12);
                border-color: rgba(216,195,154,0.30);
            }
            QCheckBox { color: #eef3f9; spacing: 6px; }
            QCheckBox::indicator {
                width: 22px;
                height: 22px;
                border-radius: 7px;
                border: 1px solid rgba(255,255,255,0.18);
                background: rgba(255,255,255,0.055);
            }
            QCheckBox::indicator:hover {
                border: 1px solid rgba(216,195,154,0.44);
                background: rgba(216,195,154,0.09);
            }
            QCheckBox::indicator:checked {
                image: url(assets/icons/ui_checkmark.svg);
                background: rgba(255,255,255,0.055);
                border: 1px solid rgba(125,240,193,0.70);
            }
            QCheckBox::indicator:checked:hover {
                background: rgba(125,240,193,0.08);
                border: 1px solid rgba(125,240,193,0.95);
            }
            QLineEdit, QComboBox {
                color: #f3f7fc;
                background: rgba(255,255,255,0.08);
                border: 1px solid rgba(255,255,255,0.12);
                border-radius: 10px;
                padding: 8px 10px;
            }
            QLabel#permissionHint {
                color: #aaa69f;
                background: rgba(255,255,255,0.025);
                border: 1px solid rgba(255,255,255,0.07);
                border-radius: 9px;
                padding: 9px 11px;
            }
            QLabel#permissionWarning {
                color: #f0c9a0;
                background: rgba(94,65,35,0.28);
                border: 1px solid rgba(201,151,91,0.38);
                border-radius: 9px;
                padding: 9px 11px;
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
                border: 1px solid rgba(216,195,154,0.32);
            }
            QPlainTextEdit {
                color: #dbe7f5;
                background: rgba(255,255,255,0.045);
                border: 1px solid rgba(255,255,255,0.10);
                border-radius: 12px;
                padding: 10px;
                font-family: "Cascadia Mono", "Consolas";
                font-size: 12px;
            }
        """)

        layout = QVBoxLayout(dlg)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(14)

        header = QHBoxLayout()
        icon_label = QLabel()
        icon_pm = self._pick_icon_for_entry(name, bool(info.get("isDir")))
        if not icon_pm.isNull():
            icon_label.setPixmap(icon_pm.scaled(42, 42, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        title_box = QVBoxLayout()
        title_name = QLabel(f"<b>{name}</b>")
        title_name.setTextFormat(Qt.TextFormat.RichText)
        title_path = QLabel(self._display_server_path(info.get("path", ".")))
        title_path.setStyleSheet("color: #9fb1c6;")
        title_path.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        title_box.addWidget(title_name)
        title_box.addWidget(title_path)
        header.addWidget(icon_label)
        header.addLayout(title_box, 1)
        layout.addLayout(header)

        tabs = QTabWidget()
        general_tab = QWidget()
        general_layout = QVBoxLayout(general_tab)
        general_layout.setContentsMargins(14, 14, 14, 14)
        general_layout.setSpacing(12)
        tabs.addTab(general_tab, "General")
        layout.addWidget(tabs, 1)

        form = QFormLayout()
        form.setSpacing(10)

        modified_text = "-"
        try:
            modified_text = datetime.fromtimestamp(int(info.get("modTime", 0))).strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            pass

        details = [
            (self.T["type"], self.T["folder"] if info.get("isDir") else self.T["file"]),
            (self.T["size"], self._format_remote_size(info.get("size", 0))),
            (self.T["modified"], modified_text),
        ]

        for label_text, value_text in details:
            value = QLabel(str(value_text))
            value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            value.setWordWrap(True)
            form.addRow(f"{label_text}:", value)

        symbolic_preview = QLabel(str(info.get("permissions", "---------")))
        symbolic_preview.setObjectName("symbolicPermissionPreview")
        symbolic_preview.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        form.addRow(f"{self.T['symbolic_mode']}:", symbolic_preview)

        original_owner = str(
            info.get("owner")
            or (info.get("uid") if info.get("uid") is not None else "")
        )
        original_group = str(
            info.get("group")
            or (info.get("gid") if info.get("gid") is not None else "")
        )
        owner_edit = QLineEdit(original_owner)
        group_edit = QLineEdit(original_group)
        owner_edit.setObjectName("permissionOwnerEdit")
        group_edit.setObjectName("permissionGroupEdit")
        owner_edit.setPlaceholderText("Account name or numeric UID")
        group_edit.setPlaceholderText("Group name or numeric GID")
        owner_edit.setToolTip("Changing the owner usually requires elevated server permissions.")
        group_edit.setToolTip("Changing the group requires membership or elevated server permissions.")
        form.addRow("Owner:", owner_edit)
        form.addRow("Group:", group_edit)
        general_layout.addLayout(form)

        rights_grid = QGridLayout()
        rights_grid.setHorizontalSpacing(14)
        rights_grid.setVerticalSpacing(8)
        rights_grid.addWidget(QLabel(f"<b>{self.T['permissions_label']}</b>"), 0, 0)
        for col, text in enumerate(("R", "W", "X"), start=1):
            lbl = QLabel(text)
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            rights_grid.addWidget(lbl, 0, col)
        special_label = QLabel("Special")
        special_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        rights_grid.addWidget(special_label, 0, 4)

        mode = int(str(info.get("octal", "755") or "755"), 8)
        checks = {}
        rows = [
            ("Owner", 6, "setuid", 0o4000, "Set UID"),
            ("Group", 3, "setgid", 0o2000, "Set GID"),
            ("Other", 0, "sticky", 0o1000, "Sticky"),
        ]
        for row, (label, shift, special_key, special_bit, special_text) in enumerate(rows, start=1):
            rights_grid.addWidget(QLabel(label), row, 0)
            for col, (flag, bit) in enumerate((("r", 4), ("w", 2), ("x", 1)), start=1):
                cb = QCheckBox()
                cb.setChecked(bool(mode & (bit << shift)))
                checks[(label, flag)] = cb
                rights_grid.addWidget(cb, row, col, Qt.AlignmentFlag.AlignCenter)
            special_cb = QCheckBox(special_text)
            special_cb.setChecked(bool(mode & special_bit))
            checks[(label, special_key)] = special_cb
            rights_grid.addWidget(special_cb, row, 4)

        octal_row = QHBoxLayout()
        octal_row.addWidget(QLabel(f"{self.T['octal_mode']}:"))
        perm_edit = QLineEdit(format(mode, "04o"))
        perm_edit.setObjectName("permissionModeEdit")
        perm_edit.setMaxLength(4)
        perm_edit.setFixedWidth(92)
        octal_row.addWidget(perm_edit)
        octal_row.addStretch()

        general_layout.addLayout(rights_grid)
        general_layout.addLayout(octal_row)

        preset_row = QHBoxLayout()
        preset_row.addWidget(QLabel("Preset:"))
        preset_combo = QComboBox()
        preset_combo.setObjectName("permissionPresetCombo")
        preset_combo.addItem("Custom / current", "")
        for preset_name, preset_mode in permission_presets(is_dir=bool(info.get("isDir"))):
            preset_combo.addItem(f"{preset_name} ({preset_mode})", preset_mode)
        preset_row.addWidget(preset_combo, 1)
        general_layout.addLayout(preset_row)

        recursive_check = QCheckBox("Apply to everything inside this folder")
        recursive_check.setObjectName("recursivePermissionCheck")
        recursive_check.setVisible(bool(info.get("isDir")))
        recursive_check.setToolTip("Symbolic links are skipped and never followed.")
        general_layout.addWidget(recursive_check)

        recursive_file_row = QWidget()
        recursive_file_row.setObjectName("recursiveFileModeRow")
        recursive_file_layout = QHBoxLayout(recursive_file_row)
        recursive_file_layout.setContentsMargins(0, 0, 0, 0)
        recursive_file_layout.addWidget(QLabel("Files inside:"))
        recursive_file_edit = QLineEdit(suggested_file_mode(mode))
        recursive_file_edit.setObjectName("recursiveFileModeEdit")
        recursive_file_edit.setMaxLength(4)
        recursive_file_edit.setFixedWidth(92)
        recursive_file_edit.setToolTip(
            "Files normally should not receive directory execute permissions."
        )
        recursive_file_layout.addWidget(recursive_file_edit)
        recursive_file_layout.addWidget(QLabel("Folders use the main mode above."))
        recursive_file_layout.addStretch()
        recursive_file_row.hide()
        general_layout.addWidget(recursive_file_row)

        permission_hint = QLabel("")
        permission_hint.setObjectName("permissionHint")
        permission_hint.setWordWrap(True)
        general_layout.addWidget(permission_hint)

        permission_warning = QLabel("")
        permission_warning.setObjectName("permissionWarning")
        permission_warning.setWordWrap(True)
        permission_warning.hide()
        general_layout.addWidget(permission_warning)

        if not info.get("isDir"):
            checksum_key = normalize_api_path(remote_path)
            checksum_tab = QWidget()
            checksum_layout = QVBoxLayout(checksum_tab)
            checksum_layout.setContentsMargins(14, 14, 14, 14)
            checksum_layout.setSpacing(10)
            checksum_status = QLabel("Calculating checksums...")
            checksum_status.setStyleSheet("color: #9fb1c6;")
            checksum_box = QPlainTextEdit()
            checksum_box.setReadOnly(True)
            checksum_box.setPlainText("MD5:    calculating...\nSHA1:   calculating...\nSHA256: calculating...")
            checksum_layout.addWidget(checksum_status)
            checksum_layout.addWidget(checksum_box, 1)
            tabs.addTab(checksum_tab, "Checksums")
            self._checksum_widgets[checksum_key] = {
                "status": checksum_status,
                "box": checksum_box,
                "dialog": dlg,
            }
            dlg.finished.connect(lambda _result, key=checksum_key: self._checksum_widgets.pop(key, None))
            self._start_checksum_worker(remote_path)

        btn_apply = QToolButton()
        btn_apply.setObjectName("applyPermissionsButton")
        btn_apply.setText(self.T["permissions_apply"])
        btn_apply.setMinimumWidth(92)

        btn_close_row = QHBoxLayout()
        btn_close_row.addStretch()
        btn_close_row.addWidget(btn_apply)
        btn_close = QToolButton()
        btn_close.setText(self.T["about_close"])
        btn_close.clicked.connect(dlg.accept)
        btn_close_row.addWidget(btn_close)
        layout.addLayout(btn_close_row)

        sync_guard = {"active": False}

        def mode_from_checks() -> int:
            value = 0
            for label, shift, special_key, special_bit, _special_text in rows:
                for flag, bit in (("r", 4), ("w", 2), ("x", 1)):
                    if checks[(label, flag)].isChecked():
                        value |= bit << shift
                if checks[(label, special_key)].isChecked():
                    value |= special_bit
            return value

        def sync_octal_from_checks():
            if sync_guard["active"]:
                return
            sync_guard["active"] = True
            updated_mode = format(mode_from_checks(), "04o")
            perm_edit.setText(updated_mode)
            recursive_file_edit.setText(suggested_file_mode(updated_mode))
            preset_combo.setCurrentIndex(0)
            sync_guard["active"] = False
            update_permission_guidance()

        def sync_checks_from_octal(text: str):
            if sync_guard["active"]:
                return
            text = (text or "").strip()
            if len(text) not in (3, 4) or any(ch not in "01234567" for ch in text):
                return
            value = int(text, 8)
            sync_guard["active"] = True
            for label, shift, special_key, special_bit, _special_text in rows:
                for flag, bit in (("r", 4), ("w", 2), ("x", 1)):
                    checks[(label, flag)].setChecked(bool(value & (bit << shift)))
                checks[(label, special_key)].setChecked(bool(value & special_bit))
            sync_guard["active"] = False
            update_permission_guidance()

        def update_permission_guidance():
            try:
                normalized = normalize_octal_mode(perm_edit.text())
            except ValueError:
                symbolic_preview.setText("Invalid octal mode")
                permission_hint.setText("Enter 3 or 4 digits using only 0 through 7.")
                permission_warning.hide()
                return
            symbolic_preview.setText(symbolic_mode(normalized, is_dir=bool(info.get("isDir"))))
            summaries = [permission_summary(normalized)]
            risks = permission_risks(normalized, recursive=recursive_check.isChecked())
            if recursive_check.isChecked():
                try:
                    file_mode = normalize_octal_mode(recursive_file_edit.text())
                except ValueError:
                    permission_hint.setText("Enter a valid octal mode for files inside the folder.")
                    permission_warning.hide()
                    return
                summaries.append(f"Files inside: {file_mode} - {permission_summary(file_mode)}")
                risks.extend(permission_risks(file_mode))
            permission_hint.setText("\n".join(summaries))
            if (owner_edit.text() or "").strip() != original_owner:
                risks.append("The owner will be changed.")
            if (group_edit.text() or "").strip() != original_group:
                risks.append("The group will be changed.")
            permission_warning.setText("\n".join(f"- {risk}" for risk in risks))
            permission_warning.setVisible(bool(risks))

        def apply_preset(index: int):
            preset_mode = preset_combo.itemData(index)
            if preset_mode:
                perm_edit.setText(str(preset_mode))
                recursive_file_edit.setText(suggested_file_mode(str(preset_mode)))

        def recursive_changed(checked: bool):
            recursive_file_row.setVisible(checked)
            update_permission_guidance()

        for checkbox in checks.values():
            checkbox.toggled.connect(sync_octal_from_checks)
        perm_edit.textChanged.connect(sync_checks_from_octal)
        recursive_file_edit.textChanged.connect(update_permission_guidance)
        preset_combo.currentIndexChanged.connect(apply_preset)
        recursive_check.toggled.connect(recursive_changed)
        owner_edit.textChanged.connect(update_permission_guidance)
        group_edit.textChanged.connect(update_permission_guidance)
        update_permission_guidance()

        def apply_permissions():
            try:
                mode_text = normalize_octal_mode(perm_edit.text())
            except ValueError as exc:
                QMessageBox.warning(dlg, self.T["properties_title"], str(exc))
                return
            owner = (owner_edit.text() or "").strip()
            group = (group_edit.text() or "").strip()
            if not owner or not group:
                QMessageBox.warning(
                    dlg,
                    self.T["properties_title"],
                    "Owner and group cannot be empty. Use an account name or numeric ID.",
                )
                return
            owner_change = owner if owner != original_owner else ""
            group_change = group if group != original_group else ""
            recursive = bool(info.get("isDir") and recursive_check.isChecked())
            file_mode_text = ""
            if recursive:
                try:
                    file_mode_text = normalize_octal_mode(recursive_file_edit.text())
                except ValueError as exc:
                    QMessageBox.warning(dlg, self.T["properties_title"], f"Files inside: {exc}")
                    return
            risks = permission_risks(mode_text, recursive=recursive)
            if file_mode_text:
                risks.extend(permission_risks(file_mode_text))
            if owner_change:
                risks.append(f"Owner will change from '{original_owner or 'unknown'}' to '{owner}'.")
            if group_change:
                risks.append(f"Group will change from '{original_group or 'unknown'}' to '{group}'.")

            if risks:
                details_text = "\n".join(f"- {risk}" for risk in risks)
                answer = QMessageBox.warning(
                    dlg,
                    "Confirm permission change",
                    f"Target: {self._display_server_path(remote_path)}\n"
                    f"New mode: {mode_text} ({symbolic_mode(mode_text, is_dir=bool(info.get('isDir')))})\n\n"
                    + (f"Files inside: {file_mode_text}\n\n" if file_mode_text else "")
                    + f"{details_text}\n\nApply this change?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No,
                )
                if answer != QMessageBox.StandardButton.Yes:
                    return

            started = self._run_remote_job(
                title=self.T["properties_title"],
                busy_text=f"Updating permissions for {name}...",
                success_toast=self.T["permissions_changed"],
                failure_label=self.T["permissions_failed"],
                worker=lambda: self._backend_change_permissions(
                    remote_path,
                    mode_text,
                    owner=owner_change,
                    group=group_change,
                    recursive=recursive,
                    file_mode_text=file_mode_text,
                ),
            )
            if started:
                dlg.accept()

        btn_apply.clicked.connect(apply_permissions)
        dlg.exec()

    def _start_checksum_worker(self, remote_path: str):
        checksum_key = normalize_api_path(remote_path)

        def worker():
            try:
                checksums = self._backend_compute_checksums(remote_path)
                self.checksum_done.emit(checksum_key, checksums)
            except Exception as e:
                self.checksum_failed.emit(checksum_key, str(e))

        threading.Thread(target=worker, daemon=True).start()

    def _finish_checksum_success(self, remote_path: str, checksums: dict):
        widgets = self._checksum_widgets.get(normalize_api_path(remote_path))
        if not widgets:
            return
        status = widgets.get("status")
        box = widgets.get("box")
        if status:
            status.setText("Checksums ready")
        if box:
            box.setPlainText(
                "MD5:    {md5}\nSHA1:   {sha1}\nSHA256: {sha256}".format(
                    md5=checksums.get("MD5", ""),
                    sha1=checksums.get("SHA1", ""),
                    sha256=checksums.get("SHA256", ""),
                )
            )

    def _finish_checksum_error(self, remote_path: str, error_text: str):
        widgets = self._checksum_widgets.get(normalize_api_path(remote_path))
        if not widgets:
            return
        status = widgets.get("status")
        box = widgets.get("box")
        if status:
            status.setText("Checksum calculation failed")
        if box:
            box.setPlainText(error_text or "Unknown checksum error.")

    def _delete_item(self, name: str, *, permanent: bool = False):
        remote_path = join_server_path(self.current_path, name)
        pretty = "/" if normalize_api_path(remote_path) == "." else ("/" + normalize_api_path(remote_path))

        if not self._confirm_sensitive_action(remote_path):
            return

        res = QMessageBox.question(
            self,
            self.T["delete_title"],
            (self.T["permanent_delete_q"] if permanent else self.T["trash_q"]).format(path=pretty),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if res != QMessageBox.StandardButton.Yes:
            return

        try:
            trash_path = "" if permanent else self._backend_trash(remote_path)
            if permanent:
                self._backend_delete(remote_path)
        except Exception as e:
            failure_text = self.T["delete_failed"] if permanent else self.T["trash_failed"]
            QMessageBox.warning(self, self.T["delete_title"], f"{failure_text}:\n{e}")
            return

        if name in self.current_order:
            self.current_order = [n for n in self.current_order if n != name]
            self._save_order_for_current_folder(self.current_order)

        if not permanent:
            self.show_toast(f"{self.T['trashed']}: {self._display_server_path(trash_path)}", "fa6s.trash-can-arrow-up", "#f4c76b")

        self.load_folder(self.current_path)

    def _delete_selected_items(self, *, permanent: bool = False):
        names = self._selected_existing_names()
        if not names:
            return
        if len(names) == 1:
            self._delete_item(names[0], permanent=permanent)
            return

        if not self._confirm_sensitive_selection(names):
            return

        preview = "\n".join(f"- {name}" for name in names[:12])
        if len(names) > 12:
            preview += f"\n... and {len(names) - 12} more"
        action_text = "permanently delete" if permanent else "move to .xyra-trash"
        res = QMessageBox.question(
            self,
            self.T["delete_title"],
            f"{action_text.capitalize()} {len(names)} selected items?\n\n{preview}",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if res != QMessageBox.StandardButton.Yes:
            return

        errors = []
        for name in names:
            remote_path = join_server_path(self.current_path, name)
            try:
                if permanent:
                    self._backend_delete(remote_path)
                else:
                    self._backend_trash(remote_path)
            except Exception as e:
                errors.append(f"{name}: {e}")

        self.selected_names.difference_update(names)
        self.current_order = [n for n in self.current_order if n not in names]
        self._save_order_for_current_folder(self.current_order)
        self.load_folder(self.current_path)

        if errors:
            QMessageBox.warning(self, self.T["delete_failed"], "\n".join(errors[:8]))
        else:
            self.show_toast(f"{len(names)} items updated", "fa6s.trash-can-arrow-up", "#f4c76b")

    def _display_server_path(self, path: str) -> str:
        norm = normalize_api_path(path)
        if norm in ("", "."):
            return "/"
        return "/" + norm

    def _copy_remote_path_to_clipboard(self, path: str):
        QApplication.clipboard().setText(self._display_server_path(path))
        self.show_toast(self.T["path_copied"], "fa6s.copy", "#53d18b")

    def _format_remote_size(self, size_value) -> str:
        try:
            size_int = int(size_value or 0)
        except Exception:
            size_int = 0

        units = ["bytes", "KB", "MB", "GB", "TB"]
        size_float = float(size_int)
        unit_index = 0
        while size_float >= 1024.0 and unit_index < len(units) - 1:
            size_float /= 1024.0
            unit_index += 1

        if unit_index == 0:
            return f"{size_int:,} bytes"

        return f"{size_float:.2f} {units[unit_index]} ({size_int:,} bytes)"

    def _is_archive_name(self, name: str) -> bool:
        lower = (name or "").lower()
        return any(lower.endswith(ext) for ext in self.ARCHIVE_EXTS)

    def _target_folder_choices(self):
        choices = ["/"]

        current_display = self._display_server_path(self.current_path)
        if current_display not in choices:
            choices.append(current_display)

        if self.backend:
            try:
                root_entries = self.backend.list_dir(".")
                root_dirs = sorted(
                    [
                        self._display_server_path(entry.get("name", ""))
                        for entry in root_entries
                        if entry.get("isDir") and entry.get("name")
                    ],
                    key=str.lower,
                )
                for item in root_dirs:
                    if item not in choices:
                        choices.append(item)
            except Exception:
                pass

        return choices

    def _choose_target_folder(self, title: str, current_name: str):
        choices = self._target_folder_choices()
        target_dir, ok = QInputDialog.getItem(
            self,
            title,
            self.T["target_folder_prompt"],
            choices,
            0,
            True,
        )
        if not ok:
            return None
        target_dir = normalize_api_path((target_dir or "").strip())
        if not target_dir:
            QMessageBox.warning(self, title, self.T["target_invalid"])
            return None
        source_path = join_server_path(self.current_path, current_name)
        dest_path = join_server_path(target_dir, current_name)
        if normalize_api_path(source_path) == normalize_api_path(dest_path):
            return None
        return source_path, dest_path

    def _copy_item_to(self, name: str):
        chosen = self._choose_target_folder(self.T["copy_title"], name)
        if not chosen:
            return
        source_path, dest_path = chosen
        proceed, overwrite = self._confirm_remote_destination("Copy", source_path, dest_path)
        if not proceed:
            return
        self._run_remote_job(
            title=self.T["copy_title"],
            busy_text=self.T["copying"].format(name=os.path.basename(name) or name),
            success_toast=self.T["copy_done"],
            failure_label=self.T["copy_failed"],
            worker=lambda: self._backend_copy(source_path, dest_path, overwrite=overwrite),
        )

    def _move_item_to(self, name: str):
        chosen = self._choose_target_folder(self.T["move_title"], name)
        if not chosen:
            return
        source_path, dest_path = chosen
        proceed, overwrite = self._confirm_remote_destination("Move", source_path, dest_path)
        if not proceed:
            return
        self._run_remote_job(
            title=self.T["move_title"],
            busy_text=self.T["moving"].format(name=os.path.basename(name) or name),
            success_toast=self.T["move_done"],
            failure_label=self.T["move_failed"],
            worker=lambda: self._backend_move(source_path, dest_path, overwrite=overwrite),
        )

    def _extract_item_here(self, name: str):
        archive_path = join_server_path(self.current_path, name)
        self._run_remote_job(
            title=self.T["extract_title"],
            busy_text=self.T["extracting"].format(name=os.path.basename(name) or name),
            success_toast=self.T["extract_done"],
            failure_label=self.T["extract_failed"],
            worker=lambda: self._backend_extract_archive(archive_path, self.current_path),
        )

    def _extract_item_to(self, name: str):
        chosen = self._choose_target_folder(self.T["extract_title"], name)
        if not chosen:
            return
        archive_path, dest_path = chosen
        self._run_remote_job(
            title=self.T["extract_title"],
            busy_text=self.T["extracting"].format(name=os.path.basename(name) or name),
            success_toast=self.T["extract_done"],
            failure_label=self.T["extract_failed"],
            worker=lambda: self._backend_extract_archive(archive_path, dest_path),
        )

    def _compress_item_to_zip(self, name: str):
        base_name = name
        if "." in name:
            split_base = os.path.splitext(name)[0]
            if split_base:
                base_name = split_base
        default_name = f"{base_name}.zip"
        archive_name, ok = QInputDialog.getText(
            self,
            self.T["compress_title"],
            self.T["archive_name_prompt"],
            text=default_name,
        )
        if not ok:
            return
        archive_name = (archive_name or "").strip()
        if not archive_name:
            QMessageBox.warning(self, self.T["compress_title"], self.T["archive_name_invalid"])
            return
        if "/" in archive_name or "\\" in archive_name:
            QMessageBox.warning(self, self.T["compress_title"], self.T["rename_invalid"])
            return
        if not archive_name.lower().endswith(".zip"):
            archive_name += ".zip"

        source_path = join_server_path(self.current_path, name)
        archive_path = join_server_path(self.current_path, archive_name)
        self._run_remote_job(
            title=self.T["compress_title"],
            busy_text=self.T["compressing"].format(name=os.path.basename(name) or name),
            success_toast=self.T["compress_done"],
            failure_label=self.T["compress_failed"],
            worker=lambda: self._backend_compress_zip(source_path, archive_path),
        )

    def _run_remote_job(self, *, title: str, busy_text: str, success_toast: str, failure_label: str, worker):
        if self._remote_job_active:
            self.show_toast(self.T["remote_job_busy"], "fa6s.hourglass-half", "#f4c76b")
            return False

        self._remote_job_active = True
        self._show_upload_overlay(busy_text)

        def job():
            try:
                worker()
                self.remote_job_done.emit(success_toast)
            except Exception as e:
                self.remote_job_failed.emit(title, failure_label, str(e))

        threading.Thread(target=job, daemon=True).start()
        return True

    def _finish_remote_job_success(self, success_toast: str):
        self._remote_job_active = False
        self._hide_upload_overlay()
        self.show_toast(success_toast, "fa6s.circle-check", "#53d18b")
        self.load_folder(self.current_path)

    def _finish_remote_job_error(self, title: str, failure_label: str, error_text: str):
        self._remote_job_active = False
        self._hide_upload_overlay()
        QMessageBox.warning(self, title, f"{failure_label}:\n{error_text}")
