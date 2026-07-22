import html

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QFormLayout, QLineEdit, QLabel,
    QDialogButtonBox, QSpinBox, QGraphicsView, QApplication,
    QComboBox, QPushButton, QHBoxLayout,
    QGraphicsRectItem, QGraphicsPixmapItem, QGraphicsTextItem,
    QGraphicsScene, QWidget, QMessageBox, QToolTip
)
from PyQt6.QtGui import (
    QAction, QBrush, QColor, QFont, QFontMetrics, QLinearGradient, QPainter,
    QPen, QPixmap, QRadialGradient, QTextOption,
)
from PyQt6.QtCore import QPointF, Qt, QTimer, QSize, QRectF

from xyra.app_constants import BOX_H, BOX_W, ICON_RENDER_SIZE, TEXT_TOP_GAP
from xyra.application import apply_window_chrome
from xyra.storage_utils import save_config


class SSHLoginDialog(QDialog):
    def __init__(self, cfg: dict, parent=None):
        super().__init__(parent)
        self.cfg = cfg
        self._loaded_profile_name = ""
        self.setWindowTitle("Connect Server")
        self.setModal(True)
        self.resize(520, 560)
        apply_window_chrome(self)
        self.setStyleSheet("""
            QDialog {
                background: #141416;
                color: #f3f1ed;
            }
            QLabel#dialogEyebrow {
                color: #d8c39a;
                font-size: 9pt;
                font-weight: 700;
            }
            QLabel#dialogTitle {
                color: #f3f1ed;
                font-size: 20pt;
                font-weight: 700;
            }
            QLabel#dialogSubtitle, QLabel#dialogHint {
                color: #999793;
            }
            QLabel {
                color: #c7c3bc;
            }
            QLineEdit, QSpinBox, QComboBox {
                background: #101012;
                border: 1px solid #303034;
                border-radius: 9px;
                padding: 8px 10px;
                color: #f3f1ed;
                min-height: 20px;
            }
            QLineEdit:focus, QSpinBox:focus, QComboBox:focus {
                border-color: #d8c39a;
                background: #171719;
            }
            QPushButton {
                background: #1c1c1f;
                border: 1px solid #303034;
                border-radius: 9px;
                color: #f3f1ed;
                min-width: 90px;
                min-height: 36px;
                padding: 0 14px;
                font-weight: 600;
            }
            QPushButton:hover {
                background: #29292c;
                border-color: #57534d;
            }
            QPushButton#primaryButton {
                color: #19160f;
                background: #d8c39a;
                border-color: #d8c39a;
            }
            QPushButton#primaryButton:hover {
                background: #ead8b4;
            }
            QPushButton#deleteProfileButton {
                color: #ff9cab;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(26, 24, 26, 22)
        layout.setSpacing(12)

        eyebrow = QLabel("SECURE REMOTE ACCESS")
        eyebrow.setObjectName("dialogEyebrow")
        title = QLabel("Connect a server")
        title.setObjectName("dialogTitle")
        subtitle = QLabel("Choose a saved profile or enter the SSH details for your VPS.")
        subtitle.setObjectName("dialogSubtitle")
        subtitle.setWordWrap(True)
        layout.addWidget(eyebrow)
        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addSpacing(8)

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
        self.delete_profile_btn.setObjectName("deleteProfileButton")
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
        hint.setObjectName("dialogHint")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        connect_button = buttons.button(QDialogButtonBox.StandardButton.Ok)
        if connect_button is not None:
            connect_button.setText("Connect")
            connect_button.setObjectName("primaryButton")
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
            self._loaded_profile_name = ""
            return
        profile = self.profiles[index - 1]
        self._loaded_profile_name = (profile.get("profile_name") or "").strip()
        self._apply_profile(profile)

    def _save_profile_clicked(self):
        profile = self._current_profile_data()
        name = profile.get("profile_name", "")
        if not name:
            QMessageBox.warning(self, "Save profile", "Please enter a profile name first.")
            return
        if not profile.get("ssh_host") or not profile.get("ssh_username"):
            QMessageBox.warning(self, "Save profile", "Host and username are required before saving a profile.")
            return
        if self._loaded_profile_name and self._loaded_profile_name != name:
            self.profiles = [
                existing for existing in self.profiles
                if (existing.get("profile_name") or "").strip() != self._loaded_profile_name
            ]
        self._upsert_profile(profile)
        self._persist_profiles(selected_name=name)
        self._loaded_profile_name = name
        self._refresh_profiles_combo(name)

    def _delete_profile_clicked(self):
        name = self.profile_name_edit.text().strip()
        if not name:
            return
        answer = QMessageBox.question(
            self,
            "Delete profile",
            f"Delete the saved profile '{name}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.profiles = [p for p in self.profiles if (p.get("profile_name") or "") != name]
        self._persist_profiles(selected_name="")
        self._loaded_profile_name = ""
        self._refresh_profiles_combo("")
        self.profile_name_edit.clear()

    def _persist_profiles(self, *, selected_name: str):
        self.cfg["ssh_profiles"] = [dict(profile) for profile in self.profiles]
        if selected_name:
            self.cfg["ssh_profile_name"] = selected_name
        elif (self.cfg.get("ssh_profile_name") or "").strip() not in {
            (profile.get("profile_name") or "").strip() for profile in self.profiles
        }:
            self.cfg["ssh_profile_name"] = ""
        save_config(self.cfg)

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

    def _upsert_profile(self, profile: dict):
        name = (profile.get("profile_name") or "").strip()
        if not name:
            return
        for idx, existing in enumerate(self.profiles):
            if (existing.get("profile_name") or "") == name:
                self.profiles[idx] = profile
                return
        self.profiles.append(profile)

    def accept(self):
        profile = self._current_profile_data()
        if not profile.get("ssh_host") or not profile.get("ssh_username"):
            QMessageBox.warning(self, "Connect Server", "SSH host and username are required.")
            return
        if profile.get("profile_name"):
            self._upsert_profile(profile)
        super().accept()

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
                background: rgba(216,195,154,0.14);
                border: 1px solid rgba(216,195,154,0.32);
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
            painter.save()
            painter.resetTransform()
            width = self.viewport().width()
            height = self.viewport().height()

            base = QLinearGradient(0, 0, 0, max(1, height))
            base.setColorAt(0.0, QColor("#121214"))
            base.setColorAt(0.55, QColor("#0e0e10"))
            base.setColorAt(1.0, QColor("#0b0b0d"))
            painter.fillRect(0, 0, width, height, QBrush(base))

            glow = QRadialGradient(QPointF(width * 0.18, 0), max(320, width * 0.55))
            glow.setColorAt(0.0, QColor(178, 145, 88, 22))
            glow.setColorAt(0.55, QColor(100, 78, 46, 8))
            glow.setColorAt(1.0, QColor(11, 11, 13, 0))
            painter.fillRect(0, 0, width, height, QBrush(glow))

            painter.setPen(QPen(QColor(221, 215, 203, 12), 1))
            step = 32
            for x in range(step, width, step):
                for y in range(step, height, step):
                    painter.drawPoint(x, y)
            painter.restore()

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

    def mousePressEvent(self, event):
        p = self.parent()
        if event.button() == Qt.MouseButton.XButton1:
            if p and hasattr(p, "go_back"):
                p.go_back()
            event.accept()
            return
        if event.button() == Qt.MouseButton.XButton2:
            if p and hasattr(p, "go_forward"):
                p.go_forward()
            event.accept()
            return

        item = self.itemAt(event.pos())
        icon_item = item if isinstance(item, IconItem) else getattr(item, "parentItem", lambda: None)()

        if icon_item is None and event.button() == Qt.MouseButton.LeftButton:
            if p and hasattr(p, "_clear_icon_selection"):
                p._clear_icon_selection()

        super().mousePressEvent(event)


class IconItem(QGraphicsRectItem):
    def __init__(self, pixmap: QPixmap, name: str, is_dir: bool, parent=None):
        super().__init__(parent)

        self.name = name
        self.is_dir = is_dir

        self._base_scale = 1.0
        self._scale_factor = 1.0
        self._target_factor = 1.0
        self._hovered = False

        self.setRect(0, 0, BOX_W, BOX_H)
        self.setPen(QPen(Qt.PenStyle.NoPen))
        self.setBrush(QColor(0, 0, 0, 0))

        self.setFlags(
            QGraphicsRectItem.GraphicsItemFlag.ItemIsMovable |
            QGraphicsRectItem.GraphicsItemFlag.ItemIsSelectable
        )
        self.setAcceptHoverEvents(True)
        self.setAcceptedMouseButtons(Qt.MouseButton.LeftButton | Qt.MouseButton.RightButton)
        self.setTransformOriginPoint(BOX_W / 2, BOX_H / 2)

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
        text_options = self.text_item.document().defaultTextOption()
        text_options.setWrapMode(QTextOption.WrapMode.NoWrap)
        self.text_item.document().setDefaultTextOption(text_options)

        self._timer = QTimer()
        self._timer.setInterval(15)
        self._timer.timeout.connect(self._step)

        self._base_font_pt = 10
        self._label_truncated = False
        self._rendered_label_lines = []
        self._icon_h_for_text = icon_h
        self._highlight_rect = QRectF(18, 4, BOX_W - 36, BOX_H - 12)
        self._update_label_text(display_name=name, scale_factor=1.0)

    def _calculate_highlight_rect(self) -> QRectF:
        pix_rect = self.pix_item.mapRectToParent(self.pix_item.boundingRect())
        text_rect = self.text_item.mapRectToParent(self.text_item.boundingRect())
        combined = pix_rect.united(text_rect)

        pad_x = 12
        pad_y = 8
        width = min(BOX_W - 12, max(76, combined.width() + pad_x * 2))
        height = min(BOX_H - 8, max(74, combined.height() + pad_y * 2))
        x = max(6, (BOX_W - width) / 2)
        y = max(3, combined.top() - pad_y)
        if y + height > BOX_H - 4:
            y = max(3, BOX_H - height - 4)
        return QRectF(x, y, width, height)

    def paint(self, painter, option, widget=None):
        option.state &= ~option.state.State_Selected
        option.state &= ~option.state.State_HasFocus

        if self.isSelected() or self._hovered:
            painter.save()
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            bg = QColor(216, 195, 154, 38) if self.isSelected() else QColor(255, 255, 255, 10)
            border = QColor(216, 195, 154, 160) if self.isSelected() else QColor(255, 255, 255, 38)
            painter.setBrush(QBrush(bg))
            painter.setPen(QPen(border, 1.5 if self.isSelected() else 1.0))
            painter.drawRoundedRect(self._highlight_rect, 14, 14)
            painter.restore()

        super().paint(painter, option, widget)

    def setBaseScale(self, s: float):
        new_scale = max(0.05, float(s))
        if abs(new_scale - self._base_scale) < 0.001:
            return
        self._base_scale = new_scale
        self._apply_scale()
        self._update_label_text(display_name=self._display_name, scale_factor=self._base_scale * self._scale_factor)

    def _apply_scale(self):
        super().setScale(self._base_scale * self._scale_factor)

    def _step(self):
        diff = self._target_factor - self._scale_factor
        step = diff * 0.20
        if abs(diff) < 0.001:
            self._scale_factor = self._target_factor
            self._timer.stop()
        else:
            self._scale_factor += step
        self._apply_scale()

    def _update_label_text(self, display_name: str, scale_factor: float):
        self._display_name = display_name

        pt = max(9, int(round(self._base_font_pt * max(0.62, scale_factor))))
        f = QFont("Segoe UI", pt)
        f.setWeight(QFont.Weight.Medium)
        self.text_item.setFont(f)

        lines, truncated = self._compact_label_lines(display_name or "", f)
        self._label_truncated = truncated
        self._rendered_label_lines = lines
        safe_lines = [html.escape(line) for line in lines]
        safe = "<br>".join(
            f"<span style='white-space:nowrap'>{line}</span>"
            for line in safe_lines
        )
        self.text_item.setHtml(
            f"<div align='center' style='line-height:1.15; font-weight:550; color:#e4e1db'>{safe}</div>"
        )

        self.text_item.setPos(0, self._icon_h_for_text + TEXT_TOP_GAP)
        self._highlight_rect = self._calculate_highlight_rect()

    @staticmethod
    def _compact_label_lines(display_name: str, font: QFont) -> tuple[list[str], bool]:
        """Fit a desktop label into two measured lines while keeping both ends useful."""
        name = display_name or ""
        metrics = QFontMetrics(font)
        line_width = max(48, BOX_W - 14)
        if metrics.horizontalAdvance(name) <= line_width:
            return [name], False

        compact = metrics.elidedText(
            name,
            Qt.TextElideMode.ElideMiddle,
            line_width * 2,
        )
        candidates = []
        for index in range(1, len(compact)):
            left = compact[:index].rstrip()
            right = compact[index:].lstrip()
            if not left or not right:
                continue
            left_width = metrics.horizontalAdvance(left)
            right_width = metrics.horizontalAdvance(right)
            if left_width > line_width or right_width > line_width:
                continue
            delimiter_bonus = line_width * 0.12 if left[-1:] in "-_. " else 0
            score = abs(left_width - right_width) - delimiter_bonus
            candidates.append((score, left, right))

        if not candidates:
            fallback = metrics.elidedText(
                name,
                Qt.TextElideMode.ElideMiddle,
                line_width,
            )
            return [fallback], fallback != name

        _score, first, second = min(candidates, key=lambda entry: entry[0])
        return [first, second], compact != name

    def hoverEnterEvent(self, event):
        self._hovered = True
        self._target_factor = 1.025
        self._timer.start()
        self.update()
        self.setZValue(50)
        if self._label_truncated:
            QToolTip.showText(event.screenPos(), self.name)
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event):
        self._hovered = False
        self._target_factor = 1.0
        self._timer.start()
        self.update()
        self.setZValue(0)
        if self._label_truncated:
            QToolTip.hideText()
        super().hoverLeaveEvent(event)

    def mousePressEvent(self, event):
        modifiers = event.modifiers()
        parent = getattr(self.scene(), "dashboard_owner", None)
        super().mousePressEvent(event)
        self.setZValue(100)
        if parent and hasattr(parent, "_on_icon_drag_started"):
            parent._on_icon_drag_started(self)
        if parent and hasattr(parent, "_select_icon_by_name"):
            additive = bool(modifiers & Qt.KeyboardModifier.ControlModifier)
            QTimer.singleShot(0, lambda: parent._select_icon_by_name(self.name, additive=additive))

    def mouseMoveEvent(self, event):
        super().mouseMoveEvent(event)
        parent = getattr(self.scene(), "dashboard_owner", None)
        if parent and hasattr(parent, "_on_icon_dragged"):
            parent._on_icon_dragged(self)

    def mouseDoubleClickEvent(self, event):
        modifiers = QApplication.keyboardModifiers()
        shift = bool(modifiers & Qt.KeyboardModifier.ShiftModifier)
        parent = getattr(self.scene(), "dashboard_owner", None)
        QTimer.singleShot(0, lambda: parent.icon_double_clicked_by_name(self.name, self.is_dir, shift))
        super().mouseDoubleClickEvent(event)

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        self.setZValue(50 if self._hovered else 0)
        parent = getattr(self.scene(), "dashboard_owner", None)
        if parent and hasattr(parent, "_on_icon_released"):
            QTimer.singleShot(0, lambda: parent._on_icon_released(self))

    def contextMenuEvent(self, event):
        parent = getattr(self.scene(), "dashboard_owner", None)
        if parent and hasattr(parent, "show_item_context_menu"):
            parent.show_item_context_menu(self.name, self.is_dir, event.screenPos().toPoint())
        event.accept()
