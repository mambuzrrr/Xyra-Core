"""Desktop layout, icon packs, backgrounds and visual feedback."""

import math
import os
import threading

from PyQt6.QtCore import (
    QEasingCurve, QPoint, QPointF, QParallelAnimationGroup,
    QPropertyAnimation, QRectF, QSize, Qt, QVariantAnimation,
    QTimer,
)
from PyQt6.QtGui import QBrush, QColor, QMovie, QPen, QPixmap, QShowEvent
from PyQt6.QtWidgets import (
    QApplication, QFileDialog, QInputDialog, QLineEdit, QMessageBox,
    QGraphicsRectItem, QPlainTextEdit, QSpinBox,
)

from xyra.app_constants import BOX_H, BOX_W, resource_path
from xyra.path_utils import normalize_api_path, split_ext
from xyra.storage_utils import save_config, save_icons_pos
from xyra.ui_components import IconItem


class DashboardVisualsMixin:
    def _load_icons(self):
        def pm(p):
            return QPixmap(p) if p and os.path.exists(p) else QPixmap()

        def icon_path(name: str) -> str:
            pack_path = self._active_icon_pack_path()
            if pack_path:
                candidate = os.path.join(pack_path, name)
                if os.path.exists(candidate):
                    return candidate
            return resource_path("assets", "icons", name)

        self.pm_folder = pm(icon_path("linux_folder.png"))
        if self.pm_folder.isNull():
            self.pm_folder = pm(icon_path("folder.png"))

        self.pm_file = pm(icon_path("linux_file.png"))
        if self.pm_file.isNull():
            self.pm_file = pm(icon_path("file.png"))

        self.pm_images = pm(icon_path("images.png"))
        self.pm_archive = pm(icon_path("linux_archive.png"))

        if self.pm_folder.isNull() and not self.pm_file.isNull():
            self.pm_folder = self.pm_file

    def _supported_icon_pack_files(self) -> set[str]:
        return {
            "linux_folder.png", "folder.png",
            "linux_file.png", "file.png",
            "images.png", "linux_archive.png",
        }

    def _builtin_icon_packs(self) -> list[tuple[str, str, str]]:
        base = resource_path("assets", "icons")
        packs = [
            ("builtin:numix-default", "Numix Default", "numix-default"),
            ("builtin:numix-blue", "Numix Blue", "numix-blue"),
            ("builtin:numix-green", "Numix Green", "numix-green"),
            ("builtin:numix-orange", "Numix Orange", "numix-orange"),
            ("builtin:numix-red", "Numix Red", "numix-red"),
            ("builtin:numix-purple", "Numix Purple", "numix-purple"),
            ("builtin:numix-grey", "Numix Grey", "numix-grey"),
            ("builtin:numix-yellow", "Numix Yellow", "numix-yellow"),
        ]
        return [(key, label, os.path.join(base, folder)) for key, label, folder in packs]

    def _active_icon_pack_path(self) -> str:
        pack_key = (self.cfg.get("icon_pack_key") or "").strip()
        for key, _label, path in self._builtin_icon_packs():
            if pack_key == key and os.path.isdir(path):
                return path

        pack_path = (self.cfg.get("icon_pack_path") or "").strip()
        if os.path.isdir(pack_path):
            return pack_path

        default_pack = resource_path("assets", "icons", "numix-grey")
        return default_pack if os.path.isdir(default_pack) else ""

    def _icon_pack_has_supported_files(self, folder: str) -> bool:
        if not folder or not os.path.isdir(folder):
            return False

        supported = self._supported_icon_pack_files()
        return bool({
            name.lower()
            for name in os.listdir(folder)
            if os.path.isfile(os.path.join(folder, name)) and name.lower() in supported
        })

    def change_icon_pack(self):
        options = [self.T["icon_pack_default"]]
        builtin_packs = [(key, label, path) for key, label, path in self._builtin_icon_packs() if self._icon_pack_has_supported_files(path)]
        options.extend(label for _key, label, _path in builtin_packs)
        options.append(self.T["icon_pack_custom"])

        current_key = (self.cfg.get("icon_pack_key") or "").strip()
        current_label = self.T["icon_pack_default"]
        for key, label, _path in builtin_packs:
            if current_key == key:
                current_label = label
                break
        if self.cfg.get("icon_pack_path"):
            current_label = self.T["icon_pack_custom"]

        current_index = options.index(current_label) if current_label in options else 0
        choice, ok = QInputDialog.getItem(
            self,
            self.T["change_icon_pack"],
            "Icon pack",
            options,
            current_index,
            False,
        )
        if not ok or not choice:
            return

        if choice == self.T["icon_pack_default"]:
            self.cfg["icon_pack_key"] = ""
            self.cfg["icon_pack_path"] = ""
        elif choice == self.T["icon_pack_custom"]:
            start_dir = self.cfg.get("icon_pack_path") or resource_path("assets", "icons") or os.path.expanduser("~")
            folder = QFileDialog.getExistingDirectory(self, self.T["change_icon_pack"], start_dir)
            if not folder:
                return
            if not self._icon_pack_has_supported_files(folder):
                QMessageBox.warning(self, self.T["change_icon_pack"], self.T["icon_pack_missing"])
                return
            self.cfg["icon_pack_key"] = ""
            self.cfg["icon_pack_path"] = folder
        else:
            selected = next(((key, path) for key, label, path in builtin_packs if label == choice), None)
            if not selected:
                return
            key, path = selected
            if not self._icon_pack_has_supported_files(path):
                QMessageBox.warning(self, self.T["change_icon_pack"], self.T["icon_pack_missing"])
                return
            self.cfg["icon_pack_key"] = key
            self.cfg["icon_pack_path"] = ""

        save_config(self.cfg)
        self._load_icons()
        self._render_folder_items()
        self.show_toast(self.T["icon_pack_changed"], "fa6s.icons", "#f4c76b")

    def reset_icon_pack(self):
        if not self.cfg.get("icon_pack_path") and not self.cfg.get("icon_pack_key"):
            return
        self.cfg["icon_pack_path"] = ""
        self.cfg["icon_pack_key"] = ""
        save_config(self.cfg)
        self._load_icons()
        self._render_folder_items()
        self.show_toast(self.T["icon_pack_reset"], "fa6s.rotate-left", "#f4c76b")

    def _pick_icon_for_entry(self, name: str, is_dir: bool) -> QPixmap:
        if is_dir:
            return self.pm_folder if not self.pm_folder.isNull() else self.pm_file
        ext = split_ext(name)
        if ext in {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".tga"}:
            return self.pm_images if not self.pm_images.isNull() else self.pm_file
        if self._is_archive_name(name):
            return self.pm_archive if not self.pm_archive.isNull() else self.pm_file
        return self.pm_file

    # ---------------- background ----------------
    def _stop_background_movie(self):
        if self.bg_movie is not None:
            try:
                self.bg_movie.frameChanged.disconnect(self._update_animated_background_frame)
            except Exception:
                pass
            self.bg_movie.stop()
            self.bg_movie = None

    def _update_animated_background_frame(self):
        if self.bg_movie is None:
            return
        pm = self.bg_movie.currentPixmap()
        if pm.isNull():
            return

        vw = max(1, self.view.viewport().width())
        vh = max(1, self.view.viewport().height())
        self.bg_pixmap = pm.scaled(
            vw, vh,
            Qt.AspectRatioMode.IgnoreAspectRatio,
            Qt.TransformationMode.SmoothTransformation
        )
        self.view.viewport().update()

    def _update_background_pixmap(self):
        if not self.bg_path or not os.path.exists(self.bg_path):
            self._stop_background_movie()
            self.bg_pixmap = QPixmap()
            self.view.viewport().update()
            return

        vw = max(1, self.view.viewport().width())
        vh = max(1, self.view.viewport().height())

        if self.bg_path.lower().endswith(".gif"):
            if self.bg_movie is None or self.bg_movie.fileName() != self.bg_path:
                self._stop_background_movie()
                self.bg_movie = QMovie(self.bg_path)
                self.bg_movie.frameChanged.connect(self._update_animated_background_frame)
                self.bg_movie.start()
            self._update_animated_background_frame()
            return

        self._stop_background_movie()
        pm = QPixmap(self.bg_path)
        if pm.isNull():
            self.bg_pixmap = QPixmap()
            self.view.viewport().update()
            return

        self.bg_pixmap = pm.scaled(
            vw, vh,
            Qt.AspectRatioMode.IgnoreAspectRatio,
            Qt.TransformationMode.SmoothTransformation
        )
        self.view.viewport().update()

    def showEvent(self, a0: QShowEvent | None):
        super().showEvent(a0)
        if self.center_message.isVisible():
            self._show_center_message(self._center_message_source)
        if self._did_first_show:
            return
        self._did_first_show = True
        QTimer.singleShot(0, self._post_first_show_fix)
        QTimer.singleShot(400, self._enable_window_geometry_saving)

    def _post_first_show_fix(self):
        self._update_background_pixmap()
        self._reposition_path_badge()
        self._reposition_version_badge()
        self._reposition_taskbar()
        if self.center_message.isVisible():
            self._show_center_message(self._center_message_source)
        self._relayout_timer.start()

    # ---------------- toast ----------------
    def show_toast(self, text: str, icon_name: str = "fa6s.circle-info", color: str = "#d8c39a"):
        self._toast_serial += 1
        serial = self._toast_serial
        self.toast_text.setText(text)
        icon = self._make_icon(icon_name, color)
        pixmap = icon.pixmap(QSize(16, 16))
        self.toast_icon.setPixmap(pixmap)
        self.toast.adjustSize()

        x_start = self.width() + 8
        y = self.toolbar.height() + 14
        x_end = max(18, self.width() - self.toast.width() - 18)

        self.toast.move(x_start, y)
        self.toast_opacity.setOpacity(0.0)
        self.toast.show()
        self.toast.raise_()

        move_anim = QPropertyAnimation(self.toast, b"pos", self)
        move_anim.setDuration(280)
        move_anim.setStartValue(QPoint(x_start, y))
        move_anim.setEndValue(QPoint(x_end, y))
        move_anim.setEasingCurve(QEasingCurve.Type.OutQuart)
        fade_anim = QPropertyAnimation(self.toast_opacity, b"opacity", self)
        fade_anim.setDuration(180)
        fade_anim.setStartValue(0.0)
        fade_anim.setEndValue(1.0)
        fade_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim = QParallelAnimationGroup(self)
        anim.addAnimation(move_anim)
        anim.addAnimation(fade_anim)
        anim.start()

        self.toast_anim = anim
        visible_ms = min(4200, 2200 + len(text) * 18)
        QTimer.singleShot(visible_ms, lambda: self._hide_toast(serial))

    def _hide_toast(self, serial=None):
        if serial is not None and serial != self._toast_serial:
            return
        if not self.toast.isVisible():
            return
        x_end = self.width() + 8
        y = self.toast.y()
        x_start = self.toast.x()

        move_anim = QPropertyAnimation(self.toast, b"pos", self)
        move_anim.setDuration(220)
        move_anim.setStartValue(QPoint(x_start, y))
        move_anim.setEndValue(QPoint(x_end, y))
        move_anim.setEasingCurve(QEasingCurve.Type.InCubic)
        fade_anim = QPropertyAnimation(self.toast_opacity, b"opacity", self)
        fade_anim.setDuration(160)
        fade_anim.setStartValue(self.toast_opacity.opacity())
        fade_anim.setEndValue(0.0)
        anim = QParallelAnimationGroup(self)
        anim.addAnimation(move_anim)
        anim.addAnimation(fade_anim)
        anim.finished.connect(self.toast.hide)
        anim.start()
        self.toast_anim = anim

    def refresh_session(self):
        self._save_order_for_current_folder()
        self.load_folder(self.current_path)
        self.show_toast(self.T["refreshed"])

    def toggle_fullscreen(self):
        if self.isFullScreen():
            if self._was_maximized_before_fullscreen:
                self.showMaximized()
            else:
                self.showNormal()
            self.show_toast(self.T["fullscreen_off"], "fa6s.down-left-and-up-right-to-center", "#f4c76b")
            return

        self._was_maximized_before_fullscreen = self.isMaximized()
        self.showFullScreen()
        self.show_toast(self.T["fullscreen_on"], "fa6s.up-right-and-down-left-from-center", "#53d18b")

    # ---------------- folder order persistence ----------------
    def _folder_key(self) -> str:
        path = normalize_api_path(self.current_path)
        server_id = getattr(self, "_active_server_id", "")
        return f"{server_id}:{path}" if server_id else path

    def _get_saved_order(self, names: list[str]) -> list[str]:
        key = self._folder_key()
        bucket = self.icons_pos.get(key, {}) if isinstance(self.icons_pos, dict) else {}

        if isinstance(bucket, dict) and isinstance(bucket.get("order"), list):
            order = [n for n in bucket["order"] if n in names]
            for n in names:
                if n not in order:
                    order.append(n)
            return order

        return names[:]

    def _save_order_for_current_folder(self, order: list[str] | None = None):
        # If searching/filtering, don't overwrite saved layout with a partial list
        if (self.search_query or "").strip():
            return

        if order is None:
            order = self.current_order[:]
        else:
            order = list(order)
        key = self._folder_key()
        if not isinstance(self.icons_pos, dict):
            self.icons_pos = {}
        self.icons_pos.setdefault(key, {})
        if not isinstance(self.icons_pos[key], dict):
            self.icons_pos[key] = {}
        if self.icons_pos[key].get("order") == order:
            return
        self.icons_pos[key]["order"] = order
        save_icons_pos(self.icons_pos)

    # ---------------- grid logic ----------------
    def _grid_params(self, n_items: int) -> dict:
        spacing_x = 130
        spacing_y = 116
        margin_x = 18
        margin_y = 26
        bottom_pad = 108

        vw = max(220, self.view.viewport().width())
        vh = max(220, self.view.viewport().height())

        available_w = max(1, vw - 2 * margin_x)
        cols = max(1, int(available_w // spacing_x))

        rows = max(1, math.ceil(n_items / cols)) if cols > 0 else n_items
        needed_h = rows * spacing_y + 2 * margin_y
        scene_h = max(vh, needed_h + bottom_pad)

        icon_scale = 1.0
        if available_w < spacing_x:
            icon_scale = max(0.82, available_w / float(spacing_x))

        return dict(
            vw=vw, vh=vh,
            spacing_x=spacing_x, spacing_y=spacing_y,
            margin_x=margin_x, margin_y=margin_y,
            cols=cols, rows=rows,
            icon_scale=icon_scale,
            scene_h=scene_h
        )

    def _slot_pos(self, idx: int, gp: dict) -> QPointF:
        col = idx % gp["cols"]
        row = idx // gp["cols"]
        x = gp["margin_x"] + col * gp["spacing_x"]
        y = gp["margin_y"] + row * gp["spacing_y"]
        return QPointF(float(x), float(y))

    def _nearest_slot_index(self, pos: QPointF, gp: dict, *, use_center: bool = False) -> int:
        x = pos.x()
        y = pos.y()
        if use_center:
            x -= (BOX_W * gp["icon_scale"]) / 2
            y -= (BOX_H * gp["icon_scale"]) / 2

        col = int(round((x - gp["margin_x"]) / gp["spacing_x"]))
        row = int(round((y - gp["margin_y"]) / gp["spacing_y"]))

        col = max(0, min(gp["cols"] - 1, col))
        row = max(0, row)

        idx = row * gp["cols"] + col
        return max(0, idx)

    def _stop_layout_animations(self):
        animations = getattr(self, "_layout_animations", {})
        for animation in list(animations.values()):
            animation.stop()
        animations.clear()
        self._layout_animations = animations

    def _animate_icon_to(self, item: IconItem, target: QPointF, duration: int = 140):
        if not hasattr(self, "_layout_animations"):
            self._layout_animations = {}

        previous = self._layout_animations.pop(item.name, None)
        if previous is not None:
            previous.stop()

        if (item.pos() - target).manhattanLength() < 0.75:
            item.setPos(target)
            return

        animation = QVariantAnimation(self)
        animation.setDuration(duration)
        animation.setStartValue(item.pos())
        animation.setEndValue(target)
        animation.setEasingCurve(QEasingCurve.Type.OutCubic)

        def update_position(value, moving_item=item):
            try:
                moving_item.setPos(value)
            except RuntimeError:
                animation.stop()

        def forget_animation(name=item.name, current=animation):
            if self._layout_animations.get(name) is current:
                self._layout_animations.pop(name, None)

        animation.valueChanged.connect(update_position)
        animation.finished.connect(forget_animation)
        self._layout_animations[item.name] = animation
        animation.start()

    def _clear_drag_slot_indicator(self):
        indicator = getattr(self, "_drag_slot_indicator", None)
        if indicator is not None:
            try:
                if indicator.scene() is self.scene:
                    self.scene.removeItem(indicator)
            except RuntimeError:
                pass
        self._drag_slot_indicator = None

    def _show_drag_slot_indicator(self, idx: int, gp: dict):
        indicator = getattr(self, "_drag_slot_indicator", None)
        if indicator is None:
            indicator = QGraphicsRectItem(0, 0, BOX_W - 18, BOX_H - 12)
            pen = QPen(QColor(216, 195, 154, 120), 1.25, Qt.PenStyle.DashLine)
            pen.setDashPattern([4.0, 4.0])
            indicator.setPen(pen)
            indicator.setBrush(QBrush(QColor(216, 195, 154, 12)))
            indicator.setZValue(-1)
            self.scene.addItem(indicator)
            self._drag_slot_indicator = indicator

        slot = self._slot_pos(idx, gp)
        indicator.setPos(slot + QPointF(9, 4))
        indicator.show()

    def _prepare_scene_reset(self):
        self._stop_layout_animations()
        self._clear_drag_slot_indicator()
        self.scene.clear()

    def _relayout_to_order(self, gp: dict, *, animate: bool = False, skip_name: str | None = None):
        for i, name in enumerate(self.current_order):
            it = self.item_by_name.get(name)
            if not it:
                continue
            it.setBaseScale(gp["icon_scale"])
            if name == skip_name:
                continue
            target = self._slot_pos(i, gp)
            if animate:
                self._animate_icon_to(it, target)
            else:
                previous = getattr(self, "_layout_animations", {}).pop(name, None)
                if previous is not None:
                    previous.stop()
                it.setPos(target)

        self.scene.setSceneRect(QRectF(0, 0, gp["vw"], gp["scene_h"]))
        self.view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.view.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

    def _relayout_current_items(self):
        """Reflow existing graphics without rebuilding the entire scene."""
        if not getattr(self, "item_by_name", None):
            self.scene.setSceneRect(QRectF(
                0, 0, self.view.viewport().width(), self.view.viewport().height()
            ))
            return

        gp = self._grid_params(len(self.current_order))
        self.view.setUpdatesEnabled(False)
        try:
            self._relayout_to_order(gp)
        finally:
            self.view.setUpdatesEnabled(True)
        self.view.viewport().update()

    def _on_icon_drag_started(self, item: IconItem):
        previous = getattr(self, "_layout_animations", {}).pop(item.name, None)
        if previous is not None:
            previous.stop()

    def _on_icon_dragged(self, item: IconItem):
        if item.name not in self.current_order or (self.search_query or "").strip():
            return

        gp = self._grid_params(len(self.current_order))
        idx = self._nearest_slot_index(item.sceneBoundingRect().center(), gp, use_center=True)
        idx = min(idx, len(self.current_order) - 1)
        old_idx = self.current_order.index(item.name)
        if idx != old_idx:
            self.current_order.pop(old_idx)
            self.current_order.insert(idx, item.name)
            self._relayout_to_order(gp, animate=True, skip_name=item.name)

        self._show_drag_slot_indicator(idx, gp)

    def _on_icon_released(self, item: IconItem):
        if item.name not in self.current_order:
            self._clear_drag_slot_indicator()
            return

        gp = self._grid_params(len(self.current_order))
        if not (self.search_query or "").strip():
            idx = self._nearest_slot_index(item.sceneBoundingRect().center(), gp, use_center=True)
            idx = min(idx, len(self.current_order) - 1)
            old_idx = self.current_order.index(item.name)
            if idx != old_idx:
                self.current_order.pop(old_idx)
                self.current_order.insert(idx, item.name)

        self._clear_drag_slot_indicator()
        self._relayout_to_order(gp, animate=True)
        self._save_order_for_current_folder()

    def _selected_existing_names(self) -> list[str]:
        return [name for name in self.current_order if name in self.selected_names and name in self.item_by_name]

    def _sync_icon_selection(self):
        existing = set(self.item_by_name.keys())
        self.selected_names = {name for name in self.selected_names if name in existing}
        for name, item in self.item_by_name.items():
            item.setSelected(name in self.selected_names)
            item.update()

    def _select_icon_by_name(self, name: str, *, additive: bool = False):
        if name not in self.item_by_name:
            return
        if additive:
            if name in self.selected_names:
                self.selected_names.remove(name)
            else:
                self.selected_names.add(name)
        else:
            self.selected_names = {name}
        self._sync_icon_selection()

    def _clear_icon_selection(self):
        if not self.selected_names:
            return
        self.selected_names.clear()
        self._sync_icon_selection()

    def _select_all_icons(self):
        self.selected_names = set(self.current_order)
        self._sync_icon_selection()

    def _primary_selected_name(self) -> str | None:
        selected = self._selected_existing_names()
        return selected[0] if selected else None

    def _reset_type_select_buffer(self):
        self._type_select_buffer = ""

    def _handle_type_select_key(self, event) -> bool:
        if self.rename_editor.isVisible():
            return False
        focus = QApplication.focusWidget()
        if isinstance(focus, (QLineEdit, QPlainTextEdit, QSpinBox)):
            return False
        if event.modifiers() & (
            Qt.KeyboardModifier.ControlModifier |
            Qt.KeyboardModifier.AltModifier |
            Qt.KeyboardModifier.MetaModifier
        ):
            return False

        text = event.text() or ""
        if len(text) != 1 or not text.isprintable() or text.isspace():
            return False
        if not self.current_order:
            return False

        char = text.lower()
        buffer_text = (self._type_select_buffer + char).lower()
        self._type_select_timer.start()

        selected = self._primary_selected_name()
        start_idx = self.current_order.index(selected) + 1 if selected in self.current_order else 0

        # Repeating the same key cycles through items that start with that letter.
        effective_query = char if buffer_text and len(set(buffer_text)) == 1 else buffer_text

        ordered = self.current_order[start_idx:] + self.current_order[:start_idx]
        matches = [name for name in ordered if name.lower().startswith(effective_query)]
        if not matches:
            matches = [name for name in ordered if effective_query in name.lower()]
        if not matches and effective_query != char:
            matches = [name for name in ordered if name.lower().startswith(char)]
            effective_query = char

        self._type_select_buffer = buffer_text if matches and effective_query != char else effective_query
        if not matches:
            return True

        target_name = matches[0]
        self._select_icon_by_name(target_name)
        item = self.item_by_name.get(target_name)
        if item:
            self.view.ensureVisible(item, 24, 24)
        return True

    # ---------------- grouping helper (folders always first) ----------------
    def _enforce_folder_first_grouping(self):
        # uses current view's is_dir mapping
        if not hasattr(self, "_is_dir_map") or not isinstance(self._is_dir_map, dict):
            return
        dirs = [n for n in self.current_order if self._is_dir_map.get(n, False)]
        files = [n for n in self.current_order if not self._is_dir_map.get(n, False)]
        self.current_order = dirs + files

    def _rerender_current_folder(self):
        self._render_folder_items()

    def _render_folder_items(self):
        if self.backend is None:
            self._prepare_scene_reset()
            self.item_by_name = {}
            self._entry_by_name = {}
            self.current_order = []
            self.selected_names.clear()
            self.scene.setSceneRect(QRectF(0, 0, self.view.viewport().width(), self.view.viewport().height()))
            self._show_center_message(self.DISCONNECTED_MESSAGE)
            return

        items = list(self.current_items or [])

        self._prepare_scene_reset()
        self.item_by_name = {}
        self._entry_by_name = {}
        self.current_order = []

        q = (self.search_query or "").strip().lower()
        if q:
            filtered = []
            for e in items:
                name = str(e.get("name", ""))
                desc = str(e.get("desc", ""))
                if q in name.lower() or q in desc.lower():
                    filtered.append(e)
            items = filtered

        dirs_entries = [e for e in items if bool(e.get("isDir", False))]
        file_entries = [e for e in items if not bool(e.get("isDir", False))]
        item_entries = dirs_entries + file_entries

        names_default = []
        is_dir_map = {}
        for e in item_entries:
            n = str(e.get("name", "")).strip()
            if not n:
                continue
            names_default.append(n)
            is_dir_map[n] = bool(e.get("isDir", False))
            self._entry_by_name[n] = e

        self._is_dir_map = is_dir_map

        gp = self._grid_params(len(names_default))
        saved = self._get_saved_order(names_default)
        self.current_order = saved[:]
        self._enforce_folder_first_grouping()

        for entry in item_entries:
            name = str(entry.get("name", "")).strip()
            if not name:
                continue

            is_dir = bool(entry.get("isDir", False))
            pix = self._pick_icon_for_entry(name, is_dir)

            it = IconItem(pix, name, is_dir)
            it.setBaseScale(gp["icon_scale"])
            it.setToolTip(name)
            it._update_label_text(display_name=name, scale_factor=gp["icon_scale"])

            self.scene.addItem(it)
            self.item_by_name[name] = it

        self._sync_icon_selection()
        self._relayout_to_order(gp)
        self._reposition_path_badge()
        self._reposition_version_badge()
        self._reposition_taskbar()
        self._save_order_for_current_folder()

        if not names_default:
            self._show_center_message("This folder is empty.")
        else:
            self._hide_center_message()

    # ---------------- folder listing ----------------
    def _show_folder_loading(self, path: str):
        self._folder_loading_path = path
        display = "/" if path in ("", ".") else f"/{path}"
        if hasattr(self, "task_path_label"):
            self.task_path_label.setText(f"⟳  {display}")
            self.task_path_label.setToolTip(f"Loading {display} from the server…")

    def _apply_folder_navigation(self, path: str, navigation: dict):
        mode = navigation.get("mode")
        source = normalize_api_path(navigation.get("source", self.current_path))

        if mode == "normal" and source != path:
            self.history.append(source)
            self.future.clear()
        elif mode == "back" and self.history and normalize_api_path(self.history[-1]) == path:
            self.history.pop()
            self.future.append(source)
        elif mode == "forward" and self.future and normalize_api_path(self.future[-1]) == path:
            self.future.pop()
            self.history.append(source)

    def _finish_folder_load(self, generation: int, path: str, items, navigation):
        if generation != self._folder_load_generation:
            return

        self._folder_loading_path = None
        self.last_load_error = ""
        self._apply_folder_navigation(path, navigation or {})
        self.current_path = path
        self.current_items = list(items or [])
        self.update_path_label()
        self._record_recent_path(path)
        self._render_folder_items()
        self._update_discord_presence()

    def _fail_folder_load(self, generation: int, path: str, error_text: str):
        if generation != self._folder_load_generation:
            return

        self._folder_loading_path = None
        self.update_path_label()
        if error_text != self.last_load_error:
            self._show_file_open_error(os.path.basename(path) or path, error_text)
            self.last_load_error = error_text

    def load_folder(self, path, *, navigation_mode: str | None = None):
        path = normalize_api_path(path)

        if self.backend is None:
            self._folder_load_generation += 1
            self._folder_loading_path = None
            self.last_load_error = ""
            self.current_path = path
            self.update_path_label()
            self._prepare_scene_reset()
            self.current_items = []
            self.item_by_name = {}
            self._entry_by_name = {}
            self.current_order = []
            self.selected_names.clear()
            self.scene.setSceneRect(QRectF(0, 0, self.view.viewport().width(), self.view.viewport().height()))
            self._show_center_message(self.DISCONNECTED_MESSAGE)
            self.view.viewport().update()
            return False

        self._folder_load_generation += 1
        generation = self._folder_load_generation
        backend = self.backend
        navigation = {
            "mode": navigation_mode,
            "source": normalize_api_path(self.current_path),
        }
        self._show_folder_loading(path)

        def worker():
            # Paramiko SFTP clients are not safe for concurrent directory reads.
            # Serialize access, then discard queued requests superseded meanwhile.
            with self._folder_load_lock:
                if generation != self._folder_load_generation or backend is not self.backend:
                    return
                try:
                    items = self._backend_read_call(
                        lambda active: active.list_dir(path),
                        backend=backend,
                    )
                except Exception as exc:
                    self.folder_load_failed.emit(generation, path, str(exc))
                    return
            self.folder_load_done.emit(generation, path, list(items or []), navigation)

        threading.Thread(
            target=worker,
            name=f"xyra-folder-{generation}",
            daemon=True,
        ).start()
        return True
