# Dashboard.py
# Main entry point for the Xyra dashboard.

import sys
import os
import tempfile
import math
import subprocess
import threading
import hashlib
from datetime import datetime

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QGraphicsScene,
    QToolBar, QFileDialog,
    QToolButton, QMenu, QLabel, QMessageBox, QLineEdit,
    QDialog, QVBoxLayout, QHBoxLayout, QWidget, QSizePolicy,
    QInputDialog, QFormLayout, QDialogButtonBox, QSpinBox
)
from PyQt6.QtGui import (
    QPixmap, QFont, QIcon, QAction, QKeySequence, QShortcut, QPainter,
    QPen, QColor
)
from PyQt6.QtCore import (
    Qt, QTimer, QRectF, QPoint, QPointF,
    QEasingCurve, QPropertyAnimation, QSize, pyqtSignal
)

from editor import TextEditorWindow
from app_constants import (
    APP_NAME, APP_VERSION, APP_WEBSITE, APP_DEVELOPER, APP_CONTRIBUTORS,
    APP_LOGO_PATH, APP_ICON_PATH, TEXT_EXTS, resource_path
)
from storage_utils import load_config, save_config, save_recent_paths, load_icons_pos, save_icons_pos
from path_utils import (
    split_ext, mb_size, normalize_api_path,
    join_server_path, join_remote_path, is_valid_new_name
)
from ssh_backend import SshRemoteBackend
from ui_components import SSHLoginDialog, DropGraphicsView, IconItem, ImagePreviewDialog

try:
    import qtawesome as qta
except Exception:
    qta = None

app = QApplication(sys.argv)

if os.path.exists(APP_ICON_PATH):
    app.setWindowIcon(QIcon(APP_ICON_PATH))

app.setStyleSheet("""
    QToolTip {
        background: rgba(18,22,30,0.96);
        color: #f2f6fb;
        border: 1px solid rgba(255,255,255,0.10);
        padding: 6px 8px;
    }
    QScrollBar:vertical {
        background: rgba(8,10,14,0.18);
        width: 14px;
        margin: 8px 4px 8px 0px;
        border: none;
        border-radius: 7px;
    }
    QScrollBar::handle:vertical {
        background: rgba(170, 190, 215, 0.42);
        min-height: 36px;
        border-radius: 7px;
    }
    QScrollBar::handle:vertical:hover {
        background: rgba(110,168,255,0.62);
    }
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical,
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
        background: transparent;
        height: 0px;
    }
    QScrollBar:horizontal {
        background: rgba(8,10,14,0.18);
        height: 14px;
        margin: 0px 8px 4px 8px;
        border: none;
        border-radius: 7px;
    }
    QScrollBar::handle:horizontal {
        background: rgba(170, 190, 215, 0.42);
        min-width: 36px;
        border-radius: 7px;
    }
    QScrollBar::handle:horizontal:hover {
        background: rgba(110,168,255,0.62);
    }
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal,
    QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {
        background: transparent;
        width: 0px;
    }
""")

class RemoteDesktop(QMainWindow):
    preview_ready = pyqtSignal(str, str)
    remote_job_done = pyqtSignal(str)
    remote_job_failed = pyqtSignal(str, str, str)
    ARCHIVE_EXTS = (
        ".zip", ".pk3", ".iwd", ".jar", ".tar", ".tar.gz", ".tgz",
        ".tar.bz2", ".tbz2", ".tar.xz", ".txz", ".rar", ".7z",
    )
    DISCONNECTED_MESSAGE = "Not connected.\n\nUse 'Remote' -> 'Connect\nServer...' to open your VPS."

    def _make_icon(self, name: str, color: str = "#e9eef5"):
        if qta is None:
            return QIcon()
        try:
            return qta.icon(name, color=color)
        except Exception:
            return QIcon()

    def _toolbar_gap(self, width: int = 8):
        gap = QWidget()
        gap.setFixedWidth(width)
        return gap

    def _style_toolbar_action_button(self, action: QAction, *, icon_only: bool = True):
        btn = self.toolbar.widgetForAction(action)
        if btn is None:
            return
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        if icon_only:
            btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
            btn.setFixedSize(44, 38)
        else:
            btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
            btn.setMinimumHeight(38)

    def __init__(self):
        super().__init__()

        if os.path.exists(APP_ICON_PATH):
            self.setWindowIcon(QIcon(APP_ICON_PATH))

        self.T = self._make_strings()

        self.cfg = load_config()
        if self.cfg.pop("_migrate_secret_storage", False) or self.cfg.pop("_migrate_storage_layout", False):
            save_config(self.cfg)
        self.icons_pos = load_icons_pos()
        self.backend = None

        self.item_by_name = {}
        self.current_order = []
        self.current_items = []
        self.history = []
        self.future = []
        self.open_editors = []
        self.open_previews = []
        self.external_open_dir = os.path.join(tempfile.gettempdir(), "xyra_open")
        os.makedirs(self.external_open_dir, exist_ok=True)
        self._active_external_opens = set()
        self._remote_job_active = False

        # Search/filter state
        self.search_query = ""
        self.last_load_error = ""
        self._search_timer = QTimer()
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(120)
        self._search_timer.timeout.connect(self._rerender_current_folder)

        self.bg_path = None
        self.bg_pixmap = QPixmap()
        self._did_first_show = False

        self._relayout_timer = QTimer()
        self._relayout_timer.setSingleShot(True)
        self._relayout_timer.setInterval(80)
        self._relayout_timer.timeout.connect(self._rerender_current_folder)
        self.preview_ready.connect(self._show_image_preview_dialog)
        self.remote_job_done.connect(self._finish_remote_job_success)
        self.remote_job_failed.connect(self._finish_remote_job_error)

        self.setWindowTitle(APP_NAME)

        self.scene = QGraphicsScene()
        self.scene.parent = self
        self.view = DropGraphicsView(self.scene, self)
        self.setCentralWidget(self.view)

        self.drop_overlay = QLabel(self.T["drop_hint"], self.view.viewport())
        self.drop_overlay.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.drop_overlay.setStyleSheet(
            "QLabel { background: rgba(0,0,0,0.65); color: white; font-size: 24px; "
            "border-radius: 18px; padding: 18px; }"
        )
        self.drop_overlay.hide()

        self.upload_overlay = QLabel("", self.view.viewport())
        self.upload_overlay.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.upload_overlay.setStyleSheet(
            "QLabel { background: rgba(20,20,20,0.78); color: white; font-size: 18px; "
            "border-radius: 16px; padding: 16px 22px; }"
        )
        self.upload_overlay.hide()

        self.center_message = QLabel("", self.view.viewport())
        self.center_message.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.center_message.setWordWrap(True)
        self.center_message.setStyleSheet(
            "QLabel { background: rgba(8,12,18,0.76); color: #f5f7fb; font-size: 18px; "
            "border: 1px solid rgba(255,255,255,0.10); border-radius: 20px; padding: 18px 24px; }"
        )
        self.center_message.hide()

        # Path badge bottom center
        self.path_badge = QLabel("", self.view.viewport())
        self.path_badge.setStyleSheet(
            "QLabel { background: rgba(0,0,0,0.55); color: white; padding: 7px 14px; "
            "border-radius: 14px; font-size: 12px; }"
        )
        self.path_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.path_badge.show()

        self.version_badge = QLabel(f"{APP_VERSION}", self.view.viewport())
        self.version_badge.setStyleSheet(
            "QLabel { background: rgba(0,0,0,0.45); color: rgba(255,255,255,0.85); "
            "padding: 6px 10px; border-radius: 12px; font-size: 11px; }"
        )
        self.version_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.version_badge.show()

        self.toast = QWidget(self)
        self.toast.setStyleSheet(
            "QWidget { background: rgba(8,12,18,0.92); border: 1px solid rgba(255,255,255,0.10); border-radius: 12px; }"
            "QLabel { background: transparent; color: white; }"
        )
        toast_layout = QHBoxLayout(self.toast)
        toast_layout.setContentsMargins(10, 7, 12, 7)
        toast_layout.setSpacing(8)
        self.toast_icon = QLabel("")
        self.toast_icon.setFixedSize(16, 16)
        self.toast_text = QLabel("")
        self.toast_text.setStyleSheet("QLabel { color: #eef3f9; }")
        toast_layout.addWidget(self.toast_icon)
        toast_layout.addWidget(self.toast_text)
        self.toast.hide()
        self.toast_anim = None

        self.rename_editor = QLineEdit(self.view.viewport())
        self.rename_editor.hide()
        self.rename_editor.setStyleSheet(
            "QLineEdit { background: rgba(0,0,0,0.75); color: white; padding: 3px 6px; "
            "border: 1px solid rgba(255,255,255,0.35); border-radius: 7px; }"
        )
        self.rename_target_item = None
        self.rename_old_name = ""
        self.rename_editor.returnPressed.connect(self._commit_inline_rename)
        self.rename_editor.editingFinished.connect(self._commit_inline_rename)
        self.rename_editor.installEventFilter(self)

        self.toolbar = QToolBar(self.T["nav"])
        self.toolbar.setMovable(False)
        self.toolbar.setFloatable(False)
        self.toolbar.setIconSize(QSize(18, 18))
        toolbar_font = QFont(self.font())
        if toolbar_font.pointSize() <= 0:
            toolbar_font.setPointSize(10)
        self.toolbar.setFont(toolbar_font)
        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, self.toolbar)

        self.toolbar.setStyleSheet("""
            QToolBar {
                spacing: 12px;
                padding: 9px 12px;
                background: rgba(15,18,25,0.88);
                border: none;
                border-bottom: 1px solid rgba(255,255,255,0.06);
            }
            QToolBar::separator {
                background: rgba(255,255,255,0.10);
                width: 1px;
                margin: 5px 10px;
            }
            QToolButton, QToolBar QLabel {
                color: #eef3f9;
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 rgba(255,255,255,0.10),
                    stop:1 rgba(255,255,255,0.05));
                border: 1px solid rgba(255,255,255,0.12);
                border-radius: 14px;
                padding: 8px 13px;
            }
            QToolButton:hover {
                background: rgba(110,168,255,0.16);
                border: 1px solid rgba(110,168,255,0.34);
            }
            QToolButton:pressed {
                background: rgba(110,168,255,0.22);
            }
            QToolButton::menu-indicator { image: none; width: 0px; }
            QLineEdit {
                color: #f3f7fc;
                background: rgba(255,255,255,0.07);
                border: 1px solid rgba(255,255,255,0.10);
                border-radius: 14px;
                padding: 9px 13px;
                selection-background-color: rgba(110,168,255,0.30);
            }
            QLineEdit:focus {
                border: 1px solid rgba(110,168,255,0.45);
                background: rgba(255,255,255,0.10);
            }
            QMenu {
                background: rgba(16,20,28,0.96);
                color: #eef3f9;
                border: 1px solid rgba(255,255,255,0.08);
                border-radius: 12px;
                padding: 8px;
            }
            QMenu::item {
                padding: 8px 12px;
                border-radius: 8px;
                margin: 2px 0px;
            }
            QMenu::item:selected {
                background: rgba(110,168,255,0.18);
            }
            QMenu::separator {
                height: 1px;
                background: rgba(255,255,255,0.08);
                margin: 6px 6px;
            }
        """)

        self.brand_label = QLabel("Xyra")
        self.brand_label.setFont(toolbar_font)
        self.brand_label.setStyleSheet(
            "QLabel { color: #f7fbff; background: transparent; border: none; font-weight: 700; padding: 0 6px 0 2px; }"
        )
        self.toolbar.addWidget(self.brand_label)
        self.toolbar.addSeparator()

        self.back_action = QAction(self._make_icon("fa6s.arrow-left"), self.T["back"], self)
        self.back_action.triggered.connect(self.go_back)
        self.toolbar.addAction(self.back_action)
        self._style_toolbar_action_button(self.back_action, icon_only=True)
        self.toolbar.addWidget(self._toolbar_gap(6))

        self.forward_action = QAction(self._make_icon("fa6s.arrow-right"), self.T["forward"], self)
        self.forward_action.triggered.connect(self.go_forward)
        self.toolbar.addAction(self.forward_action)
        self._style_toolbar_action_button(self.forward_action, icon_only=True)
        self.toolbar.addWidget(self._toolbar_gap(10))

        self.refresh_action = QAction(self._make_icon("fa6s.rotate-right"), self.T["refresh"], self)
        self.refresh_action.triggered.connect(self.refresh_session)
        self.toolbar.addAction(self.refresh_action)
        self._style_toolbar_action_button(self.refresh_action, icon_only=True)

        self.shortcut_refresh = QShortcut(QKeySequence("Ctrl+R"), self)
        self.shortcut_refresh.activated.connect(self.refresh_session)

        self.toolbar.addWidget(self._toolbar_gap(10))
        self.places_tool = QToolButton()
        self.places_tool.setFont(toolbar_font)
        self.places_tool.setText(self.T["quick_paths"])
        self.places_tool.setIcon(self._make_icon("fa6s.route", "#f4c76b"))
        self.places_tool.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.places_tool.setCursor(Qt.CursorShape.PointingHandCursor)
        self.places_tool.setMinimumHeight(38)
        self.places_tool.setMinimumWidth(132)
        self.places_menu = QMenu(self.places_tool)
        self.places_menu.aboutToShow.connect(self._rebuild_places_menu)
        self.places_tool.setMenu(self.places_menu)
        self.places_tool.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.toolbar.addWidget(self.places_tool)

        self.toolbar.addSeparator()

        self.display_tool = QToolButton()
        self.display_tool.setFont(toolbar_font)
        self.display_tool.setText(self.T["display"])
        self.display_tool.setIcon(self._make_icon("fa6s.palette", "#8bd3ff"))
        self.display_tool.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.display_tool.setCursor(Qt.CursorShape.PointingHandCursor)
        self.display_tool.setMinimumHeight(38)
        self.display_tool.setMinimumWidth(112)
        display_menu = QMenu(self.display_tool)
        display_menu.addAction(self.T["choose_bg"], self.change_background)
        display_menu.actions()[0].setIcon(self._make_icon("fa6s.image", "#8bd3ff"))
        self.display_tool.setMenu(display_menu)
        self.display_tool.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.toolbar.addWidget(self.display_tool)

        self.toolbar.addSeparator()

        self.term_tool = QToolButton()
        self.term_tool.setFont(toolbar_font)
        self.term_tool.setText(self.T["terminal"])
        self.term_tool.setIcon(self._make_icon("fa6s.terminal", "#7df0c1"))
        self.term_tool.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.term_tool.setCursor(Qt.CursorShape.PointingHandCursor)
        self.term_tool.setMinimumHeight(38)
        self.term_tool.setMinimumWidth(154)
        self.term_menu = QMenu(self.term_tool)
        self.term_menu.aboutToShow.connect(self._rebuild_term_menu)
        self._rebuild_term_menu()
        self.term_tool.setMenu(self.term_menu)
        self.term_tool.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.toolbar.addWidget(self.term_tool)

        # Search box smaller
        self.toolbar.addSeparator()
        self.search_box = QLineEdit()
        self.search_box.setFont(toolbar_font)
        self.search_box.setPlaceholderText(self.T["search_placeholder"])
        self.search_box.setClearButtonEnabled(True)
        self.search_box.setMinimumHeight(40)
        self.search_box.setFixedWidth(250)
        self.search_box.textChanged.connect(self._on_search_changed)
        search_action = self.search_box.addAction(self._make_icon("fa6s.magnifying-glass", "#9fb5ca"), QLineEdit.ActionPosition.LeadingPosition)
        search_action.setEnabled(False)
        self.toolbar.addWidget(self.search_box)

        self.shortcut_search = QShortcut(QKeySequence("Ctrl+F"), self)
        self.shortcut_search.activated.connect(self._focus_search)

        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.toolbar.addWidget(spacer)

        self.about_action = QAction(self._make_icon("fa6s.circle-info", "#f4c76b"), self.T["about"], self)
        self.about_action.triggered.connect(self.show_about_dialog)
        self.toolbar.addAction(self.about_action)
        self._style_toolbar_action_button(self.about_action, icon_only=True)
        self.toolbar.addWidget(self._toolbar_gap(10))

        self.connection_label = QLabel("")
        self.connection_label.setFont(toolbar_font)
        self.connection_label.setMinimumWidth(220)
        self.connection_label.setMinimumHeight(38)
        self.toolbar.addWidget(self.connection_label)

        self._load_icons()
        self._setup_backend(initial=True)

        bg_path = self.cfg.get("background", None)
        if bg_path and os.path.exists(bg_path):
            self.bg_path = bg_path

        self.current_path = normalize_api_path(self.cfg.get("start_path", "."))

        ws = self.cfg.get("window_size", None)
        if isinstance(ws, list) and len(ws) == 2:
            try:
                self.resize(int(ws[0]), int(ws[1]))
            except Exception:
                self.showMaximized()
        else:
            self.showMaximized()

        self.update_path_label()
        self.load_folder(self.current_path)

    def _make_strings(self) -> dict:
        return {
            "nav": "Navigation",
            "back": "Back",
            "forward": "Forward",
            "refresh": "Refresh",
            "refreshed": "Session refreshed",
            "quick_paths": "Quick Paths",
            "open_start_path": "Open start path",
            "set_start_path": "Use current folder on launch",
            "start_path_set": "Start folder updated",
            "recent_paths": "Recent folders",
            "no_recent_paths": "No recent folders yet",
            "clear_recent_paths": "Clear recent folders",
            "recent_paths_cleared": "Recent folders cleared",
            "display": "Display",
            "choose_bg": "Choose background...",
            "terminal": "Remote",
            "ssh_connect": "Connect Server...",
            "ssh_disconnect": "Disconnect Server",
            "ssh_profiles": "Quick servers",
            "open_putty": "Open PuTTY",
            "open_termius": "Open Termius",
            "drop_hint": "Drag&Drop\nRelease to upload",
            "uploading": "{file} is uploading ({mb:.2f} MB)...",
            "uploaded": "{file} uploaded",
            "upload_failed": "Upload failed",
            "rename": "Rename",
            "delete": "Delete",
            "copy_path": "Copy path",
            "copy_current_path": "Copy current path",
            "path_copied": "Path copied",
            "copy_to": "Copy to...",
            "move_to": "Move to...",
            "extract_here": "Extract here",
            "extract_to": "Extract to...",
            "compress_zip": "Compress to ZIP...",
            "download": "Download...",
            "downloaded": "Downloaded",
            "download_failed": "Download failed",
            "copy_title": "Copy",
            "move_title": "Move",
            "extract_title": "Extract",
            "compress_title": "Compress",
            "target_folder_prompt": "Target folder path",
            "copy_failed": "Copy failed",
            "move_failed": "Move failed",
            "extract_failed": "Extraction failed",
            "compress_failed": "Compression failed",
            "copy_done": "Copied",
            "move_done": "Moved",
            "extract_done": "Extracted",
            "compress_done": "Archive created",
            "target_invalid": "Target folder path cannot be empty.",
            "copying": "Copying {name}...",
            "moving": "Moving {name}...",
            "extracting": "Extracting {name}...",
            "compressing": "Compressing {name}...",
            "remote_job_busy": "Another remote file action is already running.",
            "archive_name_prompt": "Archive file name",
            "archive_name_invalid": "Archive name cannot be empty.",
            "properties": "Properties...",
            "properties_title": "Properties",
            "permissions_label": "Permissions",
            "permissions_apply": "Apply",
            "permissions_changed": "Permissions updated",
            "permissions_failed": "Permission update failed",
            "properties_failed": "Could not load item properties",
            "type": "Type",
            "folder": "Folder",
            "file": "File",
            "path": "Path",
            "size": "Size",
            "modified": "Modified",
            "octal_mode": "Octal mode",
            "symbolic_mode": "Symbolic mode",
            "delete_q": "Really delete?\n\n{path}",
            "delete_title": "Delete",
            "rename_invalid": "Invalid name (no slashes allowed).",
            "rename_failed": "Rename failed",
            "delete_failed": "Delete failed",
            "about": "About",
            "about_title": "About",
            "about_close": "Close",
            "launch_failed": "Could not launch:\n{tool}\n\nTip: set putty_path / termius_path in config.json",
            "putty_password_notice": "PuTTY opened without password autofill for security.",
            "create_folder": "Create folder",
            "create_file": "Create file",
            "name_prompt": "Name:",
            "create_title": "Create",
            "create_failed": "Create failed",
            "search_placeholder": "Search (Ctrl+F)...",
            "ssh_connect_failed": "Server connection failed",
            "ssh_connected": "Server connected",
            "ssh_disconnected": "Server disconnected",
            "backend_idle": "Offline",
            "backend_ssh": "Remote Connected",
        }

    def _rebuild_places_menu(self):
        menu = self.places_menu
        menu.clear()

        start_path = normalize_api_path(self.cfg.get("start_path", "."))
        current_path = normalize_api_path(getattr(self, "current_path", start_path))

        act_start = menu.addAction(f"{self.T['open_start_path']}: {self._display_server_path(start_path)}")
        act_start.setIcon(self._make_icon("fa6s.house", "#8bd3ff"))
        act_start.triggered.connect(lambda checked=False, p=start_path: self._navigate_to_path(p))

        act_set_start = menu.addAction(f"{self.T['set_start_path']}: {self._display_server_path(current_path)}")
        act_set_start.setIcon(self._make_icon("fa6s.location-dot", "#f4c76b"))
        act_set_start.triggered.connect(self._set_current_path_as_start)

        menu.addSeparator()
        recent_menu = menu.addMenu(self.T["recent_paths"])
        recent_menu.setIcon(self._make_icon("fa6s.clock-rotate-left", "#7df0c1"))

        recent_paths = self._clean_recent_paths(self.cfg.get("recent_paths", []))
        if recent_paths:
            for path in recent_paths:
                action = recent_menu.addAction(self._display_server_path(path))
                action.triggered.connect(lambda checked=False, p=path: self._navigate_to_path(p))
            recent_menu.addSeparator()
            act_clear = recent_menu.addAction(self.T["clear_recent_paths"])
            act_clear.setIcon(self._make_icon("fa6s.broom", "#ffb86b"))
            act_clear.triggered.connect(self._clear_recent_paths)
        else:
            empty_action = recent_menu.addAction(self.T["no_recent_paths"])
            empty_action.setEnabled(False)

    def _clean_recent_paths(self, paths) -> list[str]:
        cleaned = []
        for path in paths if isinstance(paths, list) else []:
            norm = normalize_api_path(str(path))
            if norm not in cleaned:
                cleaned.append(norm)
        return cleaned[:10]

    def _record_recent_path(self, path: str):
        norm = normalize_api_path(path)
        recent_paths = self._clean_recent_paths(self.cfg.get("recent_paths", []))
        recent_paths = [p for p in recent_paths if p != norm]
        recent_paths.insert(0, norm)
        self.cfg["recent_paths"] = recent_paths[:10]
        save_recent_paths(self.cfg["recent_paths"])

    def _navigate_to_path(self, path: str):
        target = normalize_api_path(path)
        if target == normalize_api_path(self.current_path):
            self.refresh_session()
            return
        self.history.append(self.current_path)
        self.future.clear()
        self.current_path = target
        self.update_path_label()
        self.load_folder(self.current_path)

    def _set_current_path_as_start(self):
        self.cfg["start_path"] = normalize_api_path(self.current_path)
        save_config(self.cfg)
        self.show_toast(self.T["start_path_set"], "fa6s.location-dot", "#53d18b")

    def _clear_recent_paths(self):
        self.cfg["recent_paths"] = []
        save_recent_paths(self.cfg["recent_paths"])
        self.show_toast(self.T["recent_paths_cleared"], "fa6s.broom", "#f4c76b")

    def _rebuild_term_menu(self):
        term_menu = self.term_menu
        term_menu.clear()

        act_connect = term_menu.addAction(self.T["ssh_connect"], self.show_ssh_login_dialog)
        act_disconnect = term_menu.addAction(self.T["ssh_disconnect"], self.disconnect_ssh)
        term_menu.addSeparator()

        profiles_menu = term_menu.addMenu(self.T["ssh_profiles"])
        profiles_menu.setIcon(self._make_icon("fa6s.server", "#8bd3ff"))

        profiles = [p for p in self.cfg.get("ssh_profiles", []) if isinstance(p, dict)]
        if profiles:
            for profile in profiles:
                profile_name = (profile.get("profile_name") or profile.get("ssh_host") or "Unnamed profile").strip()
                action = profiles_menu.addAction(profile_name)
                action.triggered.connect(lambda checked=False, p=dict(profile): self.connect_ssh_profile(p))
        else:
            empty_action = profiles_menu.addAction("No saved profiles")
            empty_action.setEnabled(False)

        term_menu.addSeparator()
        act_putty = term_menu.addAction(self.T["open_putty"], lambda: self._launch_tool("putty"))
        act_termius = term_menu.addAction(self.T["open_termius"], lambda: self._launch_tool("termius"))

        act_connect.setIcon(self._make_icon("fa6s.plug-circle-bolt", "#7df0c1"))
        act_disconnect.setIcon(self._make_icon("fa6s.power-off", "#ff9ea5"))
        act_putty.setIcon(self._make_icon("fa6s.window-restore"))
        act_termius.setIcon(self._make_icon("fa6s.square-terminal"))

    def _update_connection_label(self):
        if isinstance(self.backend, SshRemoteBackend) and self.backend.is_connected():
            self.connection_label.setText(self.T["backend_ssh"])
            self.connection_label.setToolTip(self.backend.describe())
            self.connection_label.setStyleSheet(
                "QLabel { color: #dff9ef; background: rgba(39,174,96,0.16); "
                "border: 1px solid rgba(39,174,96,0.34); border-radius: 12px; padding: 7px 12px; }"
            )
        else:
            self.connection_label.setText(self.T["backend_idle"])
            self.connection_label.setToolTip("No active remote server connection")
            self.connection_label.setStyleSheet(
                "QLabel { color: #f7e7b3; background: rgba(244,199,107,0.12); "
                "border: 1px solid rgba(244,199,107,0.26); border-radius: 12px; padding: 7px 12px; }"
            )

    def _setup_backend(self, initial: bool = False):
        use_ssh = (self.cfg.get("connection_mode") == "ssh" and self.cfg.get("ssh_host") and self.cfg.get("ssh_username"))
        if use_ssh:
            backend = SshRemoteBackend(self.cfg)
            try:
                backend.connect()
                self.backend = backend
            except Exception as e:
                self.backend = None
                if not initial:
                    QMessageBox.warning(self, self.T["ssh_connect_failed"], str(e))
        else:
            self.backend = None
        self._update_connection_label()

    def show_ssh_login_dialog(self):
        dlg = SSHLoginDialog(self.cfg, self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        data = dlg.get_data()
        self.cfg.update(data)
        save_config(self.cfg)

        backend = SshRemoteBackend(self.cfg)
        try:
            backend.connect()
        except Exception as e:
            QMessageBox.warning(self, self.T["ssh_connect_failed"], str(e))
            return

        if isinstance(self.backend, SshRemoteBackend):
            self.backend.disconnect()

        self.backend = backend
        self._update_connection_label()
        self.show_toast(self.T["ssh_connected"], "fa6s.plug-circle-check", "#53d18b")
        self.refresh_session()

    def connect_ssh_profile(self, profile: dict):
        data = dict(profile or {})
        if not data:
            return

        self.cfg.update(data)
        self.cfg["ssh_profile_name"] = data.get("profile_name", "")
        self.cfg["connection_mode"] = "ssh"
        save_config(self.cfg)

        backend = SshRemoteBackend(self.cfg)
        try:
            backend.connect()
        except Exception as e:
            QMessageBox.warning(self, self.T["ssh_connect_failed"], str(e))
            return

        if isinstance(self.backend, SshRemoteBackend):
            self.backend.disconnect()

        self.backend = backend
        self._update_connection_label()
        self.show_toast(self.T["ssh_connected"], "fa6s.plug-circle-check", "#53d18b")
        self.refresh_session()

    def disconnect_ssh(self):
        if isinstance(self.backend, SshRemoteBackend):
            self.backend.disconnect()
        self.cfg["connection_mode"] = "none"
        save_config(self.cfg)
        self.backend = None
        self._update_connection_label()
        self.show_toast(self.T["ssh_disconnected"], "fa6s.plug-circle-xmark", "#f4c76b")
        self.refresh_session()

    def _backend_list_dir(self, path: str):
        if self.backend is None:
            raise RuntimeError("Not connected. Use 'Remote' -> 'Connect Server...'.")
        return self.backend.list_dir(path)

    def _backend_read_bytes(self, remote_path: str) -> bytes:
        return self.backend.read_bytes(remote_path)

    def _backend_write_text(self, remote_path: str, content: str):
        self.backend.write_text(remote_path, content)

    def _backend_mkdir(self, remote_path: str):
        self.backend.mkdir(remote_path)

    def _backend_delete(self, remote_path: str):
        self.backend.delete_path(remote_path)

    def _backend_rename(self, old_path: str, new_path: str):
        self.backend.rename(old_path, new_path)

    def _backend_upload_file(self, local_path: str, remote_dir: str):
        self.backend.upload_file(local_path, remote_dir)

    def _backend_download_file(self, remote_path: str, local_path: str):
        self.backend.download_file(remote_path, local_path)

    def _backend_copy(self, source_path: str, dest_path: str):
        self.backend.copy_path(source_path, dest_path)

    def _backend_move(self, source_path: str, dest_path: str):
        self.backend.move_path(source_path, dest_path)

    def _backend_extract_archive(self, archive_path: str, dest_dir: str):
        self.backend.extract_archive(archive_path, dest_dir)

    def _backend_compress_zip(self, source_path: str, archive_path: str):
        self.backend.compress_to_zip(source_path, archive_path)

    def _backend_get_path_info(self, remote_path: str):
        return self.backend.get_path_info(remote_path)

    def _backend_chmod(self, remote_path: str, mode_text: str):
        self.backend.chmod_path(remote_path, mode_text)

    # ---------------- Search ----------------
    def _focus_search(self):
        self.search_box.setFocus()
        self.search_box.selectAll()

    def _on_search_changed(self, text: str):
        self.search_query = (text or "").strip()
        self._search_timer.start()

    # ---------------- Path badge ----------------
    def update_path_label(self):
        p = normalize_api_path(self.current_path)
        text = "/" if p in (".", "") else ("/" + p)
        self.path_badge.setText(text)
        self._reposition_path_badge()

    def _reposition_path_badge(self):
        vp = self.view.viewport().rect()
        self.path_badge.adjustSize()
        w = self.path_badge.width()
        h = self.path_badge.height()
        x = max(0, (vp.width() - w) // 2)
        y = max(0, vp.height() - h - 14)
        self.path_badge.setGeometry(x, y, w, h)
        self.path_badge.raise_()

    def _reposition_version_badge(self):
        vp = self.view.viewport().rect()
        self.version_badge.adjustSize()
        w = self.version_badge.width()
        h = self.version_badge.height()
        x = max(0, vp.width() - w - 14)
        y = max(0, vp.height() - h - 14)
        self.version_badge.setGeometry(x, y, w, h)
        self.version_badge.raise_()

    def _show_center_message(self, text: str):
        self.center_message.setText(text)
        self.center_message.adjustSize()
        vp = self.view.viewport().rect()
        w = min(max(self.center_message.width(), 320), max(320, vp.width() - 80))
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
        dlg.setFixedSize(420, 330)
        dlg.setStyleSheet("""
            QDialog { background: rgba(14,18,26,0.98); }
            QLabel { color: #eef3f9; }
            QToolButton {
                color: #eef3f9;
                background: rgba(255,255,255,0.08);
                border: 1px solid rgba(255,255,255,0.12);
                border-radius: 10px;
                padding: 8px 14px;
            }
            QToolButton:hover {
                background: rgba(110,168,255,0.16);
                border: 1px solid rgba(110,168,255,0.34);
            }
        """)
        if os.path.exists(APP_ICON_PATH):
            dlg.setWindowIcon(QIcon(APP_ICON_PATH))

        layout = QVBoxLayout(dlg)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        title = QLabel(f"<b style='font-size:18px'>{APP_NAME}</b><br><span style='color:#97aac2;font-size:11px'>Remote Linux file dashboard</span>")
        title.setTextFormat(Qt.TextFormat.RichText)
        title.setStyleSheet("color: white;")
        layout.addWidget(title)

        info = QLabel(
            f"<div style='color:white; line-height:1.4'>"
            f"<b>Developer:</b> {APP_DEVELOPER}<br>"
            f"<b>Version:</b> {APP_VERSION}<br>"
            f"<b>Contributors:</b> {APP_CONTRIBUTORS}<br>"
            f"<b>Website:</b> SOON...</a>"
            f"</div>"
        )
        info.setOpenExternalLinks(True)
        info.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(info)

        layout.addStretch()

        logo_row = QHBoxLayout()
        logo_row.addStretch()

        logo_lbl = QLabel()
        logo_pm = QPixmap(APP_LOGO_PATH) if os.path.exists(APP_LOGO_PATH) else QPixmap()
        if not logo_pm.isNull():
            logo_lbl.setPixmap(
                logo_pm.scaled(256, 256, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            )
        else:
            logo_lbl.setText("■")
            logo_lbl.setStyleSheet("color: rgba(255,255,255,0.5); font-size: 42px;")
            logo_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            logo_lbl.setFixedSize(64, 64)

        logo_row.addWidget(logo_lbl)
        logo_row.addStretch()
        layout.addLayout(logo_row)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_close = QToolButton()
        btn_close.setText(self.T["about_close"])
        btn_close.clicked.connect(dlg.accept)
        btn_row.addWidget(btn_close)
        layout.addLayout(btn_row)

        dlg.setStyleSheet("QDialog { background: rgb(20,20,20); }")
        dlg.exec()

    # ---------------- EMPTY SPACE context menu (Create folder/file) ----------------
    def show_empty_context_menu(self, global_pos):
        menu = QMenu(self)
        act_copy_path = menu.addAction(self.T["copy_current_path"])
        act_copy_path.setIcon(self._make_icon("fa6s.copy", "#8bd3ff"))
        menu.addSeparator()
        act_folder = menu.addAction(self.T["create_folder"])
        act_file = menu.addAction(self.T["create_file"])

        chosen = menu.exec(global_pos)
        if chosen == act_copy_path:
            self._copy_remote_path_to_clipboard(self.current_path)
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

    # ---------------- Drag & Drop Upload (FIXED) ----------------
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

    def _upload_single_file(self, local_path: str) -> tuple[bool, str]:
        try:
            self._backend_upload_file(local_path, self.current_path)
        except Exception as e:
            return False, str(e)
        return True, ""

    def _on_drop(self, event):
        self.drop_overlay.hide()

        md = event.mimeData()
        if not md or not md.hasUrls():
            event.ignore()
            return

        local_files = []
        for u in md.urls():
            if u.isLocalFile():
                p = u.toLocalFile()
                if p and os.path.isfile(p):
                    local_files.append(p)

        if not local_files:
            event.ignore()
            return

        event.setDropAction(Qt.DropAction.CopyAction)
        event.accept()

        for p in local_files:
            self._show_upload_overlay(self.T["uploading"].format(file=os.path.basename(p), mb=mb_size(p)))
            ok, err = self._upload_single_file(p)
            if ok:
                self.show_toast(self.T["uploaded"].format(file=os.path.basename(p)), "fa6s.cloud-arrow-up", "#53d18b")
            else:
                QMessageBox.warning(self, "Upload", f"{self.T['upload_failed']}:\n{os.path.basename(p)}\n\n{err}")

        self._hide_upload_overlay()
        self.load_folder(self.current_path)

    # ---------------- tool launching ----------------
    def _launch_tool(self, tool: str):
        putty_path = self.cfg.get("putty_path")
        termius_path = self.cfg.get("termius_path")
        ssh_host = (self.cfg.get("ssh_host") or "").strip()
        ssh_port = int(self.cfg.get("ssh_port", 22) or 22)
        ssh_user = (self.cfg.get("ssh_username") or "").strip()
        has_ssh_password = bool(self.cfg.get("ssh_password"))
        ssh_key_path = (self.cfg.get("ssh_key_path") or "").strip()

        def try_start(command) -> bool:
            try:
                if not command:
                    return False
                if isinstance(command, str) and os.path.exists(command):
                    os.startfile(command)
                    return True
                if isinstance(command, (list, tuple)):
                    subprocess.Popen(list(command), shell=False)
                else:
                    subprocess.Popen([command], shell=False)
                return True
            except Exception:
                return False

        ok = False
        if tool == "putty":
            putty_args = []
            if ssh_host:
                target = ssh_host
                if ssh_user:
                    target = f"{ssh_user}@{ssh_host}"
                putty_args = ["-ssh", target, "-P", str(ssh_port)]
                if ssh_key_path:
                    putty_args += ["-i", ssh_key_path]

            if putty_path:
                ok = try_start([putty_path] + putty_args if putty_args else putty_path)
            if not ok:
                ok = try_start(["putty.exe"] + putty_args if putty_args else "putty.exe") or try_start(["putty"] + putty_args if putty_args else "putty")
            if not ok:
                for c in [r"C:\Program Files\PuTTY\putty.exe", r"C:\Program Files (x86)\PuTTY\putty.exe"]:
                    if os.path.exists(c):
                        ok = try_start([c] + putty_args if putty_args else c)
                        break
            if ok and has_ssh_password and not ssh_key_path:
                self.show_toast(self.T["putty_password_notice"], "fa6s.shield-halved", "#f4c76b")
        elif tool == "termius":
            if termius_path:
                ok = try_start(termius_path)
            if not ok:
                ok = try_start("termius.exe") or try_start("termius")
            if not ok:
                for c in [
                    os.path.expandvars(r"%LOCALAPPDATA%\Programs\Termius\Termius.exe"),
                    os.path.expandvars(r"%LOCALAPPDATA%\Termius\Termius.exe"),
                ]:
                    if os.path.exists(c):
                        ok = try_start(c)
                        break

        if not ok:
            QMessageBox.warning(self, "Launch", self.T["launch_failed"].format(tool=tool))

    # ---------------- icons ----------------
    def _load_icons(self):
        def pm(p):
            return QPixmap(p) if p and os.path.exists(p) else QPixmap()

        self.pm_folder = pm(resource_path("icons", "linux_folder.png"))
        if self.pm_folder.isNull():
            self.pm_folder = pm(resource_path("icons", "folder.png"))

        self.pm_file = pm(resource_path("icons", "linux_file.png"))
        if self.pm_file.isNull():
            self.pm_file = pm(resource_path("icons", "file.png"))

        self.pm_images = pm(resource_path("icons", "images.png"))

        if self.pm_folder.isNull() and not self.pm_file.isNull():
            self.pm_folder = self.pm_file

    def _pick_icon_for_entry(self, name: str, is_dir: bool) -> QPixmap:
        if is_dir:
            return self.pm_folder if not self.pm_folder.isNull() else self.pm_file
        ext = split_ext(name)
        if ext in {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".tga"}:
            return self.pm_images if not self.pm_images.isNull() else self.pm_file
        return self.pm_file

    # ---------------- background ----------------
    def _update_background_pixmap(self):
        if not self.bg_path or not os.path.exists(self.bg_path):
            self.bg_pixmap = QPixmap()
            self.view.viewport().update()
            return

        vw = max(1, self.view.viewport().width())
        vh = max(1, self.view.viewport().height())

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

    def showEvent(self, event):
        super().showEvent(event)
        if self._did_first_show:
            return
        self._did_first_show = True
        QTimer.singleShot(0, self._post_first_show_fix)

    def _post_first_show_fix(self):
        self._update_background_pixmap()
        self._reposition_path_badge()
        self._reposition_version_badge()
        self._relayout_timer.start()

    # ---------------- toast ----------------
    def show_toast(self, text: str, icon_name: str = "fa6s.circle-info", color: str = "#8bd3ff"):
        self.toast_text.setText(text)
        icon = self._make_icon(icon_name, color)
        pixmap = icon.pixmap(QSize(16, 16))
        self.toast_icon.setPixmap(pixmap)
        self.toast.adjustSize()

        x_start = -self.toast.width()
        y = self.toolbar.height() + 8
        x_end = 10

        self.toast.move(x_start, y)
        self.toast.show()
        self.toast.raise_()

        anim = QPropertyAnimation(self.toast, b"pos", self)
        anim.setDuration(380)
        anim.setStartValue(QPoint(x_start, y))
        anim.setEndValue(QPoint(x_end, y))
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim.start()

        self.toast_anim = anim
        QTimer.singleShot(1400, self._hide_toast)

    def _hide_toast(self):
        if not self.toast.isVisible():
            return
        x_end = -self.toast.width()
        y = self.toast.y()
        x_start = self.toast.x()

        anim = QPropertyAnimation(self.toast, b"pos", self)
        anim.setDuration(320)
        anim.setStartValue(QPoint(x_start, y))
        anim.setEndValue(QPoint(x_end, y))
        anim.setEasingCurve(QEasingCurve.Type.InCubic)
        anim.finished.connect(self.toast.hide)
        anim.start()
        self.toast_anim = anim

    def refresh_session(self):
        self._save_order_for_current_folder()
        self.load_folder(self.current_path)
        self.show_toast(self.T["refreshed"])

    # ---------------- folder order persistence ----------------
    def _folder_key(self) -> str:
        return normalize_api_path(self.current_path)

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
        key = self._folder_key()
        if not isinstance(self.icons_pos, dict):
            self.icons_pos = {}
        self.icons_pos.setdefault(key, {})
        if not isinstance(self.icons_pos[key], dict):
            self.icons_pos[key] = {}
        self.icons_pos[key]["order"] = order
        save_icons_pos(self.icons_pos)

    # ---------------- grid logic ----------------
    def _grid_params(self, n_items: int) -> dict:
        spacing_x = 160
        spacing_y = 125
        margin_x = 40
        margin_y = 40
        bottom_pad = 70

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

    def _nearest_slot_index(self, pos: QPointF, gp: dict) -> int:
        x = pos.x()
        y = pos.y()

        col = int(round((x - gp["margin_x"]) / gp["spacing_x"]))
        row = int(round((y - gp["margin_y"]) / gp["spacing_y"]))

        col = max(0, min(gp["cols"] - 1, col))
        row = max(0, row)

        idx = row * gp["cols"] + col
        return max(0, idx)

    def _relayout_to_order(self, gp: dict):
        for i, name in enumerate(self.current_order):
            it = self.item_by_name.get(name)
            if not it:
                continue
            it.setBaseScale(gp["icon_scale"])
            it.setPos(self._slot_pos(i, gp))

        self.scene.setSceneRect(QRectF(0, 0, gp["vw"], gp["scene_h"]))
        self.view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.view.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

    def _on_icon_released(self, item: IconItem):
        if item.name not in self.current_order:
            return

        gp = self._grid_params(len(self.current_order))
        idx = self._nearest_slot_index(item.pos(), gp)

        old_idx = self.current_order.index(item.name)
        if idx != old_idx:
            self.current_order.pop(old_idx)
            idx = min(idx, len(self.current_order))
            self.current_order.insert(idx, item.name)

        # enforce grouping after drag too (folders first)
        self._enforce_folder_first_grouping()

        self._relayout_to_order(gp)
        self._save_order_for_current_folder()

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
            self.scene.clear()
            self.item_by_name = {}
            self.current_order = []
            self.scene.setSceneRect(QRectF(0, 0, self.view.viewport().width(), self.view.viewport().height()))
            self._show_center_message(self.DISCONNECTED_MESSAGE)
            return

        items = list(self.current_items or [])

        self.scene.clear()
        self.item_by_name = {}
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

        self._relayout_to_order(gp)
        self._reposition_path_badge()
        self._reposition_version_badge()
        self._save_order_for_current_folder()

        if not names_default:
            self._show_center_message("This folder is empty.")
        else:
            self._hide_center_message()

    # ---------------- folder listing ----------------
    def load_folder(self, path):
        path = normalize_api_path(path)

        if self.backend is None:
            self.last_load_error = ""
            self.current_path = path
            self.update_path_label()
            self.scene.clear()
            self.current_items = []
            self.item_by_name = {}
            self.current_order = []
            self.scene.setSceneRect(QRectF(0, 0, self.view.viewport().width(), self.view.viewport().height()))
            self._show_center_message(self.DISCONNECTED_MESSAGE)
            self.view.viewport().update()
            return

        try:
            items = self._backend_list_dir(path)
        except Exception as e:
            error_text = str(e)
            if error_text != self.last_load_error:
                print("SSH Error:", e)
                self.last_load_error = error_text
            self.current_path = path
            self.update_path_label()
            self.scene.clear()
            self.current_items = []
            self.item_by_name = {}
            self.current_order = []
            self.scene.setSceneRect(QRectF(0, 0, self.view.viewport().width(), self.view.viewport().height()))
            self._show_center_message(self.DISCONNECTED_MESSAGE)
            self.view.viewport().update()
            return

        if items is None:
            items = []

        self.last_load_error = ""
        self.current_path = path
        self.current_items = items
        self.update_path_label()
        self._record_recent_path(path)
        self._render_folder_items()

    # ---------------- context menu: rename/delete/download ----------------
    def show_item_context_menu(self, name: str, is_dir: bool, screen_pos: QPoint):
        menu = QMenu(self)
        act_properties = menu.addAction(self.T["properties"])
        act_properties.setIcon(self._make_icon("fa6s.circle-info", "#8bd3ff"))
        act_copy_path = menu.addAction(self.T["copy_path"])
        act_copy_path.setIcon(self._make_icon("fa6s.copy", "#8bd3ff"))
        menu.addSeparator()
        act_rename = menu.addAction(self.T["rename"])
        act_rename.setIcon(self._make_icon("fa6s.pen", "#f4c76b"))
        act_delete = menu.addAction(self.T["delete"])
        act_delete.setIcon(self._make_icon("fa6s.trash", "#ff7b7b"))
        menu.addSeparator()
        act_copy = menu.addAction(self.T["copy_to"])
        act_copy.setIcon(self._make_icon("fa6s.copy", "#8bd3ff"))
        act_move = menu.addAction(self.T["move_to"])
        act_move.setIcon(self._make_icon("fa6s.arrows-right-left", "#8bd3ff"))
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
            act_download.setIcon(self._make_icon("fa6s.download", "#8bd3ff"))

        chosen = menu.exec(screen_pos)
        if chosen == act_properties:
            self._show_item_properties(name)
        elif chosen == act_copy_path:
            self._copy_remote_path_to_clipboard(join_server_path(self.current_path, name))
        elif chosen == act_rename:
            self._start_inline_rename(name)
        elif chosen == act_delete:
            self._delete_item(name)
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

    def _download_item(self, name: str):
        remote_path = join_server_path(self.current_path, name)

        suggested = os.path.basename(name) if name else "download.bin"
        save_path, _ = QFileDialog.getSaveFileName(self, self.T["download"], suggested, "All Files (*.*)")
        if not save_path:
            return

        try:
            self._backend_download_file(remote_path, save_path)
        except Exception as e:
            QMessageBox.warning(self, self.T["download"], f"{self.T['download_failed']}:\n{e}")
            return

        self.show_toast(self.T["downloaded"], "fa6s.cloud-arrow-down", "#53d18b")

    def _show_item_properties(self, name: str):
        remote_path = join_server_path(self.current_path, name)
        try:
            info = self._backend_get_path_info(remote_path)
        except Exception as e:
            QMessageBox.warning(self, self.T["properties_title"], f"{self.T['properties_failed']}:\n{e}")
            return

        dlg = QDialog(self)
        dlg.setWindowTitle(f"{self.T['properties_title']} - {name}")
        dlg.setMinimumWidth(460)
        dlg.setStyleSheet("""
            QDialog { background: rgba(14,18,26,0.98); }
            QLabel { color: #eef3f9; }
            QLineEdit {
                color: #f3f7fc;
                background: rgba(255,255,255,0.08);
                border: 1px solid rgba(255,255,255,0.12);
                border-radius: 10px;
                padding: 8px 10px;
            }
            QToolButton {
                color: #eef3f9;
                background: rgba(255,255,255,0.08);
                border: 1px solid rgba(255,255,255,0.12);
                border-radius: 10px;
                padding: 8px 14px;
            }
            QToolButton:hover {
                background: rgba(110,168,255,0.16);
                border: 1px solid rgba(110,168,255,0.34);
            }
        """)

        layout = QVBoxLayout(dlg)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(14)

        form = QFormLayout()
        form.setSpacing(10)

        modified_text = "-"
        try:
            modified_text = datetime.fromtimestamp(int(info.get("modTime", 0))).strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            pass

        details = [
            (self.T["type"], self.T["folder"] if info.get("isDir") else self.T["file"]),
            (self.T["path"], self._display_server_path(info.get("path", "."))),
            (self.T["size"], self._format_remote_size(info.get("size", 0))),
            (self.T["modified"], modified_text),
            (self.T["octal_mode"], info.get("octal", "---")),
            (self.T["symbolic_mode"], info.get("permissions", "---------")),
        ]

        for label_text, value_text in details:
            value = QLabel(str(value_text))
            value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            value.setWordWrap(True)
            form.addRow(f"{label_text}:", value)

        layout.addLayout(form)

        perm_row = QHBoxLayout()
        perm_label = QLabel(f"{self.T['permissions_label']}:")
        perm_edit = QLineEdit(info.get("octal", "755"))
        perm_edit.setMaxLength(4)
        perm_edit.setFixedWidth(100)
        btn_apply = QToolButton()
        btn_apply.setText(self.T["permissions_apply"])
        perm_row.addWidget(perm_label)
        perm_row.addWidget(perm_edit)
        perm_row.addWidget(btn_apply)
        perm_row.addStretch()
        layout.addLayout(perm_row)

        btn_close_row = QHBoxLayout()
        btn_close_row.addStretch()
        btn_close = QToolButton()
        btn_close.setText(self.T["about_close"])
        btn_close.clicked.connect(dlg.accept)
        btn_close_row.addWidget(btn_close)
        layout.addLayout(btn_close_row)

        def apply_permissions():
            mode_text = (perm_edit.text() or "").strip()
            try:
                self._backend_chmod(remote_path, mode_text)
            except Exception as e:
                QMessageBox.warning(dlg, self.T["properties_title"], f"{self.T['permissions_failed']}:\n{e}")
                return
            self.show_toast(self.T["permissions_changed"], "fa6s.shield-halved", "#53d18b")
            dlg.accept()
            self.load_folder(self.current_path)

        btn_apply.clicked.connect(apply_permissions)
        dlg.exec()

    def _delete_item(self, name: str):
        remote_path = join_server_path(self.current_path, name)
        pretty = "/" if normalize_api_path(remote_path) == "." else ("/" + normalize_api_path(remote_path))

        res = QMessageBox.question(
            self,
            self.T["delete_title"],
            self.T["delete_q"].format(path=pretty),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if res != QMessageBox.StandardButton.Yes:
            return

        try:
            self._backend_delete(remote_path)
        except Exception as e:
            QMessageBox.warning(self, self.T["delete_title"], f"{self.T['delete_failed']}:\n{e}")
            return

        if name in self.current_order:
            self.current_order = [n for n in self.current_order if n != name]
            self._save_order_for_current_folder(self.current_order)

        self.load_folder(self.current_path)

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
        self._run_remote_job(
            title=self.T["copy_title"],
            busy_text=self.T["copying"].format(name=os.path.basename(name) or name),
            success_toast=self.T["copy_done"],
            failure_label=self.T["copy_failed"],
            worker=lambda: self._backend_copy(source_path, dest_path),
        )

    def _move_item_to(self, name: str):
        chosen = self._choose_target_folder(self.T["move_title"], name)
        if not chosen:
            return
        source_path, dest_path = chosen
        self._run_remote_job(
            title=self.T["move_title"],
            busy_text=self.T["moving"].format(name=os.path.basename(name) or name),
            success_toast=self.T["move_done"],
            failure_label=self.T["move_failed"],
            worker=lambda: self._backend_move(source_path, dest_path),
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
            return

        self._remote_job_active = True
        self._show_upload_overlay(busy_text)

        def job():
            try:
                worker()
                self.remote_job_done.emit(success_toast)
            except Exception as e:
                self.remote_job_failed.emit(title, failure_label, str(e))

        threading.Thread(target=job, daemon=True).start()

    def _finish_remote_job_success(self, success_toast: str):
        self._remote_job_active = False
        self._hide_upload_overlay()
        self.show_toast(success_toast, "fa6s.circle-check", "#53d18b")
        self.load_folder(self.current_path)

    def _finish_remote_job_error(self, title: str, failure_label: str, error_text: str):
        self._remote_job_active = False
        self._hide_upload_overlay()
        QMessageBox.warning(self, title, f"{failure_label}:\n{error_text}")

    # ---------------- inline rename ----------------
    def _start_inline_rename(self, name: str):
        it = self.item_by_name.get(name)
        if not it or not it.text_item:
            return

        label_scene_pos = it.text_item.scenePos()
        label_scene_rect = it.text_item.boundingRect()
        label_scene_rect = QRectF(label_scene_pos.x(), label_scene_pos.y(), label_scene_rect.width(), label_scene_rect.height())

        vp_top_left = self.view.mapFromScene(QPointF(label_scene_rect.left(), label_scene_rect.top()))
        vp_bot_right = self.view.mapFromScene(QPointF(label_scene_rect.right(), label_scene_rect.bottom()))

        x = int(vp_top_left.x())
        y = int(vp_top_left.y())
        w = max(120, int(vp_bot_right.x() - vp_top_left.x()) + 18)
        h = max(24, int(vp_bot_right.y() - vp_top_left.y()) + 12)

        self.rename_target_item = it
        self.rename_old_name = name

        self.rename_editor.setGeometry(x - 8, y - 6, w + 16, h)
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

    def eventFilter(self, obj, event):
        if obj is self.rename_editor:
            if event.type() == event.Type.KeyPress:
                if event.key() == Qt.Key.Key_Escape:
                    self._cancel_inline_rename()
                    return True
        return super().eventFilter(obj, event)

    def _cancel_inline_rename(self):
        self.rename_editor.hide()
        self.rename_target_item = None
        self.rename_old_name = ""

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

        try:
            self._backend_rename(old_path, new_path)
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
    def icon_double_clicked_by_name(self, name: str, is_dir: bool, shift_open: bool):
        new_path = join_server_path(self.current_path, name)

        if is_dir:
            self.history.append(self.current_path)
            self.future.clear()
            self.current_path = normalize_api_path(new_path)
            self.update_path_label()
            self.load_folder(self.current_path)
            return

        ext = split_ext(name)
        if shift_open:
            self._download_and_open_external(new_path, name)
            return

        if ext in {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".tga", ".ico"}:
            self._download_and_open_image_preview(new_path, name)
            return

        if ext in TEXT_EXTS:
            try:
                data = self._backend_read_bytes(new_path)
            except Exception as e:
                print("Download error:", e)
                return
            try:
                text = data.decode("utf-8")
            except Exception:
                text = data.decode("utf-8", errors="replace")

            try:
                editor = TextEditorWindow(new_path, text, self.save_file_to_server)
                self.open_editors.append(editor)
                editor.destroyed.connect(lambda _, e=editor: self._on_editor_destroyed(e))
                editor.show()
                editor.raise_()
                editor.activateWindow()
            except Exception as e:
                print("Failed to open editor:", e)
            return

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

    def _download_and_open_image_preview(self, remote_path: str, name: str):
        task_key = normalize_api_path(remote_path)
        if task_key in self._active_external_opens:
            return

        self._active_external_opens.add(task_key)
        self.show_toast(f"Loading preview for {os.path.basename(name) or name}...", "fa6s.image", "#8bd3ff")

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
                print("Open preview failed:", e)
            finally:
                self._active_external_opens.discard(task_key)

        threading.Thread(target=worker, daemon=True).start()

    def _download_and_open_external(self, remote_path: str, name: str):
        task_key = normalize_api_path(remote_path)
        if task_key in self._active_external_opens:
            return

        self._active_external_opens.add(task_key)
        self.show_toast(f"Opening {os.path.basename(name) or name}...", "fa6s.up-right-from-square", "#8bd3ff")

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
                print("Open external failed:", e)
            finally:
                self._active_external_opens.discard(task_key)

        threading.Thread(target=worker, daemon=True).start()

    def save_file_to_server(self, remote_path, content) -> tuple:
        try:
            self._backend_write_text(remote_path, content)
        except Exception as e:
            return False, str(e)
        return True, ""

    # ---------------- navigation ----------------
    def go_back(self):
        if self.history:
            self.future.append(self.current_path)
            self.current_path = self.history.pop()
            self.update_path_label()
            self.load_folder(self.current_path)

    def go_forward(self):
        if self.future:
            self.history.append(self.current_path)
            self.current_path = self.future.pop()
            self.update_path_label()
            self.load_folder(self.current_path)

    # ---------------- UI helpers ----------------
    def change_background(self):
        fname, _ = QFileDialog.getOpenFileName(
            self, self.T["choose_bg"], os.path.expanduser("~"),
            "Images (*.png *.jpg *.jpeg *.png *.webp *.bmp *.ico)"
        )
        if not fname:
            return

        self.bg_path = fname
        self.cfg["background"] = self.bg_path
        save_config(self.cfg)

        self._update_background_pixmap()
        self.view.viewport().update()

    def resizeEvent(self, event):
        super().resizeEvent(event)

        self._update_background_pixmap()

        if self.drop_overlay.isVisible():
            self.drop_overlay.setGeometry(self.view.viewport().rect())
        if self.upload_overlay.isVisible():
            self.upload_overlay.adjustSize()

        self._reposition_path_badge()
        self._reposition_version_badge()
        if self.center_message.isVisible():
            self._show_center_message(self.center_message.text())

        try:
            if not self.isMaximized():
                s = self.size()
                if s.width() >= 200 and s.height() >= 200:
                    self.cfg["window_size"] = [int(s.width()), int(s.height())]
                    save_config(self.cfg)
        except Exception:
            pass

        self._relayout_timer.start()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.go_back()
        else:
            super().keyPressEvent(event)


# ------------------- Run -------------------
if __name__ == "__main__":
    window = RemoteDesktop()
    window.show()
    sys.exit(app.exec())
