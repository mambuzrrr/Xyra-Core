from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QFormLayout, QLineEdit, QLabel,
    QDialogButtonBox, QSpinBox, QGraphicsView, QApplication,
    QComboBox, QPushButton, QHBoxLayout,
    QGraphicsRectItem, QGraphicsPixmapItem, QGraphicsTextItem,
    QGraphicsScene, QWidget
)
from PyQt6.QtGui import QPixmap, QPainter, QPen, QColor, QFont, QAction
from PyQt6.QtCore import Qt, QTimer, QSize, QRectF

from app_constants import BOX_H, BOX_W, ICON_RENDER_SIZE, TEXT_TOP_GAP


class SSHLoginDialog(QDialog):
    def __init__(self, cfg: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Connect Server")
        self.setModal(True)
        self.resize(460, 320)
        self.setStyleSheet("""
            QDialog {
                background: rgba(12, 16, 24, 0.98);
                color: #eef3f9;
            }
            QLabel {
                color: #eef3f9;
            }
            QLineEdit, QSpinBox {
                background: rgba(255,255,255,0.07);
                border: 1px solid rgba(255,255,255,0.10);
                border-radius: 10px;
                padding: 7px 10px;
                color: #f6f9fc;
            }
            QLineEdit:focus, QSpinBox:focus {
                border: 1px solid rgba(110,168,255,0.45);
                background: rgba(255,255,255,0.10);
            }
            QDialogButtonBox QPushButton {
                background: rgba(255,255,255,0.08);
                border: 1px solid rgba(255,255,255,0.12);
                border-radius: 10px;
                padding: 8px 14px;
                color: #eef3f9;
                min-width: 90px;
            }
            QDialogButtonBox QPushButton:hover {
                background: rgba(110,168,255,0.16);
                border: 1px solid rgba(110,168,255,0.34);
            }
        """)

        layout = QVBoxLayout(self)
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(10)
        layout.addLayout(form)

        self.profiles = [dict(p) for p in cfg.get("ssh_profiles", []) if isinstance(p, dict)]
        self.profile_combo = QComboBox()
        self.profile_name_edit = QLineEdit(cfg.get("ssh_profile_name", ""))

        self.host_edit = QLineEdit(cfg.get("ssh_host", ""))
        self.port_spin = QSpinBox()
        self.port_spin.setRange(1, 65535)
        self.port_spin.setValue(int(cfg.get("ssh_port", 22) or 22))
        self.user_edit = QLineEdit(cfg.get("ssh_username", ""))
        self.password_edit = QLineEdit(cfg.get("ssh_password", ""))
        self.password_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.key_edit = QLineEdit(cfg.get("ssh_key_path", ""))
        self.root_edit = QLineEdit(cfg.get("ssh_root", "/root"))
        for edit in (self.host_edit, self.user_edit, self.password_edit, self.key_edit, self.root_edit):
            edit.setClearButtonEnabled(True)

        self.profile_combo.addItem("Custom / New profile")
        selected_profile_name = cfg.get("ssh_profile_name", "")
        selected_index = 0
        for idx, profile in enumerate(self.profiles, start=1):
            name = profile.get("profile_name") or f"Profile {idx}"
            self.profile_combo.addItem(name)
            if selected_profile_name and name == selected_profile_name:
                selected_index = idx

        profile_buttons = QHBoxLayout()
        self.save_profile_btn = QPushButton("Save profile")
        self.delete_profile_btn = QPushButton("Delete profile")
        self.save_profile_btn.clicked.connect(self._save_profile_clicked)
        self.delete_profile_btn.clicked.connect(self._delete_profile_clicked)
        profile_buttons.addWidget(self.save_profile_btn)
        profile_buttons.addWidget(self.delete_profile_btn)

        form.addRow("Profile", self.profile_combo)
        form.addRow("Profile name", self.profile_name_edit)
        form.addRow("", self._wrap_layout_widget(profile_buttons))
        form.addRow("Host", self.host_edit)
        form.addRow("Port", self.port_spin)
        form.addRow("Username", self.user_edit)
        form.addRow("Password", self.password_edit)
        form.addRow("Key file (optional)", self.key_edit)
        form.addRow("Remote root", self.root_edit)

        self.profile_combo.currentIndexChanged.connect(self._profile_changed)
        self.profile_combo.setCurrentIndex(selected_index)
        if selected_index > 0:
            self._apply_profile(self.profiles[selected_index - 1])

        hint = QLabel("Use password or key file. The dashboard will browse files via SFTP inside the selected remote root.")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _wrap_layout_widget(self, layout):
        container = QWidget()
        container.setLayout(layout)
        return container

    def _current_profile_data(self) -> dict:
        return {
            "profile_name": self.profile_name_edit.text().strip(),
            "ssh_host": self.host_edit.text().strip(),
            "ssh_port": int(self.port_spin.value()),
            "ssh_username": self.user_edit.text().strip(),
            "ssh_password": self.password_edit.text(),
            "ssh_key_path": self.key_edit.text().strip(),
            "ssh_root": (self.root_edit.text().strip() or "/root"),
        }

    def _apply_profile(self, profile: dict):
        self.profile_name_edit.setText(profile.get("profile_name", ""))
        self.host_edit.setText(profile.get("ssh_host", ""))
        self.port_spin.setValue(int(profile.get("ssh_port", 22) or 22))
        self.user_edit.setText(profile.get("ssh_username", ""))
        self.password_edit.setText(profile.get("ssh_password", ""))
        self.key_edit.setText(profile.get("ssh_key_path", ""))
        self.root_edit.setText(profile.get("ssh_root", "/root"))

    def _profile_changed(self, index: int):
        if index <= 0:
            return
        profile = self.profiles[index - 1]
        self._apply_profile(profile)

    def _save_profile_clicked(self):
        profile = self._current_profile_data()
        name = profile.get("profile_name", "")
        if not name:
            return
        replaced = False
        for idx, existing in enumerate(self.profiles):
            if (existing.get("profile_name") or "") == name:
                self.profiles[idx] = profile
                replaced = True
                break
        if not replaced:
            self.profiles.append(profile)
            self.profile_combo.addItem(name)
        self._refresh_profiles_combo(name)

    def _delete_profile_clicked(self):
        name = self.profile_name_edit.text().strip()
        if not name:
            return
        self.profiles = [p for p in self.profiles if (p.get("profile_name") or "") != name]
        self._refresh_profiles_combo("")

    def _refresh_profiles_combo(self, selected_name: str):
        self.profile_combo.blockSignals(True)
        self.profile_combo.clear()
        self.profile_combo.addItem("Custom / New profile")
        selected_index = 0
        for idx, profile in enumerate(self.profiles, start=1):
            name = profile.get("profile_name") or f"Profile {idx}"
            self.profile_combo.addItem(name)
            if selected_name and name == selected_name:
                selected_index = idx
        self.profile_combo.setCurrentIndex(selected_index)
        self.profile_combo.blockSignals(False)

    def get_data(self) -> dict:
        return {
            "ssh_profile_name": self.profile_name_edit.text().strip(),
            "ssh_profiles": self.profiles,
            "ssh_host": self.host_edit.text().strip(),
            "ssh_port": int(self.port_spin.value()),
            "ssh_username": self.user_edit.text().strip(),
            "ssh_password": self.password_edit.text(),
            "ssh_key_path": self.key_edit.text().strip(),
            "ssh_root": (self.root_edit.text().strip() or "/root"),
            "connection_mode": "ssh",
        }


class ImagePreviewView(QGraphicsView):
    def __init__(self, scene, parent=None):
        super().__init__(scene, parent)
        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        self.setFrameShape(QGraphicsView.Shape.NoFrame)
        self.setStyleSheet("QGraphicsView { background: rgba(5,8,12,0.96); border: none; }")
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self._zoom = 1.0

    def wheelEvent(self, event):
        if event.angleDelta().y() > 0:
            self.scale(1.15, 1.15)
            self._zoom *= 1.15
        else:
            self.scale(1 / 1.15, 1 / 1.15)
            self._zoom /= 1.15


class ImagePreviewDialog(QDialog):
    def __init__(self, image_path: str, display_name: str, open_external_cb=None, parent=None):
        super().__init__(parent)
        self.image_path = image_path
        self.display_name = display_name
        self.open_external_cb = open_external_cb
        self.setWindowTitle(f"Preview - {display_name}")
        self.resize(1100, 780)
        self.setStyleSheet("""
            QDialog {
                background: rgba(10,14,20,0.98);
                color: #eef3f9;
            }
            QLabel {
                color: #eef3f9;
            }
            QPushButton {
                background: rgba(255,255,255,0.08);
                border: 1px solid rgba(255,255,255,0.12);
                border-radius: 10px;
                padding: 8px 14px;
                color: #eef3f9;
                min-width: 90px;
            }
            QPushButton:hover {
                background: rgba(110,168,255,0.16);
                border: 1px solid rgba(110,168,255,0.34);
            }
        """)

        layout = QVBoxLayout(self)
        header = QHBoxLayout()
        self.title_label = QLabel(display_name)
        self.info_label = QLabel("")
        self.info_label.setStyleSheet("color: rgba(255,255,255,0.70);")
        header.addWidget(self.title_label)
        header.addStretch()
        header.addWidget(self.info_label)
        layout.addLayout(header)

        self.scene = QGraphicsScene(self)
        self.view = ImagePreviewView(self.scene, self)
        layout.addWidget(self.view, 1)

        buttons = QHBoxLayout()
        self.fit_btn = QPushButton("Fit")
        self.actual_btn = QPushButton("100%")
        self.external_btn = QPushButton("Open externally")
        self.close_btn = QPushButton("Close")
        self.fit_btn.clicked.connect(self.fit_image)
        self.actual_btn.clicked.connect(self.show_actual_size)
        self.external_btn.clicked.connect(self.open_external)
        self.close_btn.clicked.connect(self.accept)
        buttons.addWidget(self.fit_btn)
        buttons.addWidget(self.actual_btn)
        buttons.addWidget(self.external_btn)
        buttons.addStretch()
        buttons.addWidget(self.close_btn)
        layout.addLayout(buttons)

        self.pixmap = QPixmap(image_path)
        self.pix_item = QGraphicsPixmapItem(self.pixmap)
        self.scene.addItem(self.pix_item)
        self.scene.setSceneRect(QRectF(self.pixmap.rect()))
        self.info_label.setText(f"{self.pixmap.width()} x {self.pixmap.height()}")
        QTimer.singleShot(0, self.fit_image)

    def fit_image(self):
        if self.pixmap.isNull():
            return
        self.view.resetTransform()
        self.view.fitInView(self.pix_item, Qt.AspectRatioMode.KeepAspectRatio)
        self.view._zoom = 1.0

    def show_actual_size(self):
        self.view.resetTransform()
        self.view._zoom = 1.0

    def open_external(self):
        if callable(self.open_external_cb):
            self.open_external_cb(self.image_path)

    def showEvent(self, event):
        super().showEvent(event)
        QTimer.singleShot(0, self.fit_image)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if abs(self.view._zoom - 1.0) < 0.001:
            QTimer.singleShot(0, self.fit_image)


class DropGraphicsView(QGraphicsView):
    def __init__(self, scene, parent):
        super().__init__(scene, parent)
        self.setAcceptDrops(True)
        self.viewport().setAcceptDrops(True)
        self.setStyleSheet("QGraphicsView { background: transparent; border: none; }")
        self.setFrameShape(QGraphicsView.Shape.NoFrame)

    def drawBackground(self, painter: QPainter, rect):
        parent = self.parent()
        pm = getattr(parent, "bg_pixmap", None)
        if isinstance(pm, QPixmap) and not pm.isNull():
            painter.save()
            painter.resetTransform()
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
            painter.drawPixmap(0, 0, self.viewport().width(), self.viewport().height(), pm)
            painter.restore()
        else:
            super().drawBackground(painter, rect)

    def dragEnterEvent(self, event):
        p = self.parent()
        if p and hasattr(p, "_on_drag_enter"):
            p._on_drag_enter(event)
            return
        super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        p = self.parent()
        if p and hasattr(p, "_on_drag_move"):
            p._on_drag_move(event)
            return
        super().dragMoveEvent(event)

    def dragLeaveEvent(self, event):
        p = self.parent()
        if p and hasattr(p, "_on_drag_leave"):
            p._on_drag_leave(event)
            return
        super().dragLeaveEvent(event)

    def dropEvent(self, event):
        p = self.parent()
        if p and hasattr(p, "_on_drop"):
            p._on_drop(event)
            return
        super().dropEvent(event)

    def contextMenuEvent(self, event):
        p = self.parent()
        item = self.itemAt(event.pos())
        icon_item = item if isinstance(item, IconItem) else getattr(item, "parentItem", lambda: None)()

        if icon_item is not None and hasattr(p, "show_item_context_menu"):
            p.show_item_context_menu(icon_item.name, icon_item.is_dir, event.globalPos())
            event.accept()
            return

        if hasattr(p, "show_empty_context_menu"):
            p.show_empty_context_menu(event.globalPos())
            event.accept()
            return

        super().contextMenuEvent(event)


class IconItem(QGraphicsRectItem):
    def __init__(self, pixmap: QPixmap, name: str, is_dir: bool, parent=None):
        super().__init__(parent)

        self.name = name
        self.is_dir = is_dir

        self._base_scale = 1.0
        self._scale_factor = 1.0
        self._target_factor = 1.0

        self.setRect(0, 0, BOX_W, BOX_H)
        self.setPen(QPen(Qt.PenStyle.NoPen))
        self.setBrush(QColor(0, 0, 0, 0))

        self.setFlags(
            QGraphicsRectItem.GraphicsItemFlag.ItemIsMovable |
            QGraphicsRectItem.GraphicsItemFlag.ItemIsSelectable
        )
        self.setAcceptHoverEvents(True)
        self.setAcceptedMouseButtons(Qt.MouseButton.LeftButton | Qt.MouseButton.RightButton)

        pm = pixmap if isinstance(pixmap, QPixmap) else QPixmap()
        if not pm.isNull():
            pm = pm.scaled(
                ICON_RENDER_SIZE, ICON_RENDER_SIZE,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation
            )

        self.pix_item = QGraphicsPixmapItem(pm, self)

        icon_w = self.pix_item.pixmap().width() if not self.pix_item.pixmap().isNull() else ICON_RENDER_SIZE
        icon_h = self.pix_item.pixmap().height() if not self.pix_item.pixmap().isNull() else ICON_RENDER_SIZE

        x_icon = max(0, (BOX_W - icon_w) / 2)
        y_icon = 0
        self.pix_item.setPos(x_icon, y_icon)

        self.text_item = QGraphicsTextItem("", self)
        self.text_item.setTextWidth(BOX_W)
        self.text_item.setDefaultTextColor(Qt.GlobalColor.white)

        self._timer = QTimer()
        self._timer.setInterval(15)
        self._timer.timeout.connect(self._step)

        self._base_font_pt = 9
        self._icon_h_for_text = icon_h
        self._update_label_text(display_name=name, scale_factor=1.0)

    def setBaseScale(self, s: float):
        self._base_scale = max(0.05, float(s))
        self._apply_scale()
        self._update_label_text(display_name=self._display_name, scale_factor=self._base_scale * self._scale_factor)

    def _apply_scale(self):
        super().setScale(self._base_scale * self._scale_factor)

    def _step(self):
        diff = self._target_factor - self._scale_factor
        step = diff * 0.25
        if abs(diff) < 0.001:
            self._scale_factor = self._target_factor
            self._timer.stop()
        else:
            self._scale_factor += step
        self._apply_scale()
        self._update_label_text(display_name=self._display_name, scale_factor=self._base_scale * self._scale_factor)

    def _update_label_text(self, display_name: str, scale_factor: float):
        self._display_name = display_name

        pt = max(8, int(round(self._base_font_pt * max(0.55, scale_factor))))
        f = QFont("Arial", pt)
        self.text_item.setFont(f)

        safe = (display_name or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        self.text_item.setHtml(f"<div align='center' style='line-height:1.05'>{safe}</div>")

        self.text_item.setPos(0, self._icon_h_for_text + TEXT_TOP_GAP)

    def hoverEnterEvent(self, event):
        self._target_factor = 1.10
        if not self._timer.isActive():
            self._timer.start()
        self.setZValue(50)
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event):
        self._target_factor = 1.0
        if not self._timer.isActive():
            self._timer.start()
        self.setZValue(0)
        super().hoverLeaveEvent(event)

    def mouseDoubleClickEvent(self, event):
        modifiers = QApplication.keyboardModifiers()
        shift = bool(modifiers & Qt.KeyboardModifier.ShiftModifier)
        parent = self.scene().parent
        QTimer.singleShot(0, lambda: parent.icon_double_clicked_by_name(self.name, self.is_dir, shift))
        super().mouseDoubleClickEvent(event)

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        parent = self.scene().parent
        if parent and hasattr(parent, "_on_icon_released"):
            QTimer.singleShot(0, lambda: parent._on_icon_released(self))

    def contextMenuEvent(self, event):
        parent = self.scene().parent
        if parent and hasattr(parent, "show_item_context_menu"):
            parent.show_item_context_menu(self.name, self.is_dir, event.screenPos().toPoint())
        event.accept()
