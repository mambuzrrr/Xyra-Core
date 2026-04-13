from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QFormLayout, QLineEdit, QLabel,
    QDialogButtonBox, QSpinBox, QGraphicsView, QApplication,
    QGraphicsRectItem, QGraphicsPixmapItem, QGraphicsTextItem
)
from PyQt6.QtGui import QPixmap, QPainter, QPen, QColor, QFont
from PyQt6.QtCore import Qt, QTimer

from app_constants import BOX_H, BOX_W, ICON_RENDER_SIZE, TEXT_TOP_GAP


class SSHLoginDialog(QDialog):
    def __init__(self, cfg: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("SSH Login")
        self.setModal(True)
        self.resize(440, 220)
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

        form.addRow("Host", self.host_edit)
        form.addRow("Port", self.port_spin)
        form.addRow("Username", self.user_edit)
        form.addRow("Password", self.password_edit)
        form.addRow("Key file (optional)", self.key_edit)
        form.addRow("Remote root", self.root_edit)

        hint = QLabel("Use password or key file. The dashboard will browse files via SFTP inside the selected remote root.")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def get_data(self) -> dict:
        return {
            "ssh_host": self.host_edit.text().strip(),
            "ssh_port": int(self.port_spin.value()),
            "ssh_username": self.user_edit.text().strip(),
            "ssh_password": self.password_edit.text(),
            "ssh_key_path": self.key_edit.text().strip(),
            "ssh_root": (self.root_edit.text().strip() or "/root"),
            "connection_mode": "ssh",
        }


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
