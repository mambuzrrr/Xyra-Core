# Dashboard.py
# Main entry point for the Xyra dashboard.

import sys
import os
import tempfile
import subprocess
import threading
import time
from contextlib import nullcontext
from datetime import datetime
from typing import cast

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QGraphicsScene,
    QToolBar, QFileDialog,
    QToolButton, QMenu, QLabel, QMessageBox, QLineEdit,
    QDialog, QGraphicsDropShadowEffect, QGraphicsOpacityEffect, QHBoxLayout, QWidget,
    QSizePolicy, QTabBar,
)
from PyQt6.QtGui import (
    QCloseEvent, QColor, QKeyEvent, QPixmap, QFont, QIcon, QAction, QKeySequence,
    QResizeEvent, QShortcut,
)
from PyQt6.QtCore import (
    Qt, QTimer, QPoint, QRect, QSize, QThread, pyqtSignal,
)

from xyra.app_constants import (
    APP_NAME, APP_VERSION, APP_LOGO_PATH, APP_ICON_PATH,
)
from xyra.storage_utils import (
    load_config, load_icons_pos, save_config, save_favorites, save_recent_paths,
    save_server_workspace,
)
from xyra.path_utils import normalize_api_path
from xyra.ssh_backend import SshRemoteBackend
from xyra.discord_rpc import DiscordRichPresence
from xyra.ui_components import SSHLoginDialog, DropGraphicsView
from xyra.application import apply_window_chrome, create_application
from xyra.dashboard_search import DashboardSearchMixin
from xyra.dashboard_transfers import DashboardTransfersMixin
from xyra.dashboard_visuals import DashboardVisualsMixin
from xyra.dashboard_files import DashboardFilesMixin
from xyra.dashboard_editing import DashboardEditingMixin
from xyra.dashboard_updates import DashboardUpdatesMixin
from xyra.transfer_queue import TransferQueue
from xyra.server_profiles import (
    active_profile_data, clean_workspace, profile_accent, profile_display_name,
    profile_identity,
)
from xyra.theme import (
    CENTER_MESSAGE_STYLE, OFFLINE_PILL_STYLE,
    OVERLAY_STYLE, SERVER_BAR_STYLE, TASKBAR_STYLE, TOAST_STYLE, TOOLBAR_STYLE,
)

try:
    import qtawesome as qta
except Exception:
    qta = None

class RemoteDesktop(
    DashboardUpdatesMixin,
    DashboardSearchMixin,
    DashboardTransfersMixin,
    DashboardVisualsMixin,
    DashboardFilesMixin,
    DashboardEditingMixin,
    QMainWindow,
):
    preview_ready = pyqtSignal(str, str)
    file_open_failed = pyqtSignal(str, str)
    remote_job_done = pyqtSignal(str)
    remote_job_failed = pyqtSignal(str, str, str)
    remote_search_done = pyqtSignal(int, str, list)
    remote_search_failed = pyqtSignal(int, str)
    server_health_done = pyqtSignal(str)
    server_health_failed = pyqtSignal(str)
    checksum_done = pyqtSignal(str, dict)
    checksum_failed = pyqtSignal(str, str)
    folder_load_done = pyqtSignal(int, str, object, object)
    folder_load_failed = pyqtSignal(int, str, str)
    connection_state_changed = pyqtSignal(str, str)
    update_check_done = pyqtSignal(object, bool)
    update_check_failed = pyqtSignal(str, bool)
    update_download_progress = pyqtSignal(int, int)
    update_download_done = pyqtSignal(str, object)
    update_download_failed = pyqtSignal(str)
    ARCHIVE_EXTS = (
        ".zip", ".pk3", ".iwd", ".jar", ".tar", ".tar.gz", ".tgz",
        ".tar.bz2", ".tbz2", ".tar.xz", ".txz", ".rar", ".7z",
    )
    DISCONNECTED_MESSAGE = "Not connected.\n\nUse 'Remote' -> 'Connect\nServer...' to open your VPS."

    def _make_icon(self, name: str, color: str = "#e9eef5"):
        if qta is None:
            return QIcon()
        try:
            return cast(QIcon, qta.icon(name, color=color))
        except Exception:
            return QIcon()

    def _toolbar_gap(self, width: int = 8):
        gap = QWidget()
        gap.setFixedWidth(width)
        return gap

    def _style_toolbar_action_button(self, action: QAction, *, icon_only: bool = True):
        btn = self.toolbar.widgetForAction(action)
        if not isinstance(btn, QToolButton):
            return
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        if icon_only:
            btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
            btn.setFixedSize(46, 40)
        else:
            btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
            btn.setMinimumHeight(40)

    def __init__(self, launch_profile_name: str = ""):
        super().__init__()

        if os.path.exists(APP_ICON_PATH):
            self.setWindowIcon(QIcon(APP_ICON_PATH))

        self.T = self._make_strings()

        self.cfg = load_config()
        if launch_profile_name:
            selected = next(
                (
                    profile for profile in self.cfg.get("ssh_profiles", [])
                    if isinstance(profile, dict)
                    and profile_display_name(profile).casefold() == launch_profile_name.casefold()
                ),
                None,
            )
            if selected:
                self.cfg.update(active_profile_data(selected))
                self.cfg["connection_mode"] = "ssh"
        if self.cfg.pop("_migrate_secret_storage", False) or self.cfg.pop("_migrate_storage_layout", False):
            save_config(self.cfg)
        self.icons_pos = load_icons_pos()
        self.backend: SshRemoteBackend | None = None
        self._exit_shutdown_done = False
        self._server_tab_sessions = []
        self._server_session_serial = 0
        self._active_server_session_id = None
        self._dismissed_server_identities = set()

        self.item_by_name = {}
        self._entry_by_name = {}
        self.current_order = []
        self.current_items = []
        self.selected_names = set()
        self.history = []
        self.future = []
        self.open_editors = []
        self._editor_backup_paths = set()
        self.open_previews = []
        self.external_open_dir = os.path.join(tempfile.gettempdir(), "xyra_open")
        os.makedirs(self.external_open_dir, exist_ok=True)
        self._active_external_opens = set()
        self._remote_job_active = False
        self._remote_search_active = False
        self._remote_search_cancel_requested = False
        self._remote_search_id = 0
        self._checksum_widgets = {}
        self.discord_rpc = DiscordRichPresence()
        self.transfer_queue = TransferQueue(self, max_active=1)
        self.transfer_center = None
        self._setup_updates()

        # Search/filter state
        self.search_query = ""
        self.last_load_error = ""
        self._folder_load_generation = 0
        self._folder_load_lock = threading.Lock()
        self._folder_loading_path = None
        self._reconnect_lock = threading.Lock()
        self._search_timer = QTimer()
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(120)
        self._search_timer.timeout.connect(self._rerender_current_folder)
        self._type_select_buffer = ""
        self._type_select_timer = QTimer()
        self._type_select_timer.setSingleShot(True)
        self._type_select_timer.setInterval(900)
        self._type_select_timer.timeout.connect(self._reset_type_select_buffer)

        self.bg_path = None
        self.bg_pixmap = QPixmap()
        self.bg_movie = None
        self._did_first_show = False

        self._relayout_timer = QTimer()
        self._relayout_timer.setSingleShot(True)
        self._relayout_timer.setInterval(110)
        self._relayout_timer.timeout.connect(self._relayout_current_items)

        self._background_resize_timer = QTimer()
        self._background_resize_timer.setSingleShot(True)
        self._background_resize_timer.setInterval(140)
        self._background_resize_timer.timeout.connect(self._update_background_pixmap)

        self._window_size_save_timer = QTimer()
        self._window_size_save_timer.setSingleShot(True)
        self._window_size_save_timer.setInterval(350)
        self._window_size_save_timer.timeout.connect(self._save_window_size)
        self._window_geometry_ready = False
        self.preview_ready.connect(self._show_image_preview_dialog)
        self.file_open_failed.connect(self._show_file_open_error)
        self.remote_job_done.connect(self._finish_remote_job_success)
        self.remote_job_failed.connect(self._finish_remote_job_error)
        self.remote_search_done.connect(self._show_remote_search_results)
        self.remote_search_failed.connect(self._finish_remote_search_error)
        self.server_health_done.connect(self._show_server_health_dialog)
        self.server_health_failed.connect(self._finish_server_health_error)
        self.checksum_done.connect(self._finish_checksum_success)
        self.checksum_failed.connect(self._finish_checksum_error)
        self.folder_load_done.connect(self._finish_folder_load)
        self.folder_load_failed.connect(self._fail_folder_load)
        self.connection_state_changed.connect(self._handle_connection_state)
        self.transfer_queue.jobs_changed.connect(self._handle_transfer_jobs_changed)
        self.transfer_queue.job_finished.connect(self._handle_transfer_job_finished)

        self.setWindowTitle(APP_NAME)
        apply_window_chrome(self)

        self.scene = QGraphicsScene(self)
        self.scene.dashboard_owner = self
        self.view = DropGraphicsView(self.scene, self)
        self.setCentralWidget(self.view)

        self.drop_overlay = QLabel(self.T["drop_hint"], self.view.viewport())
        self.drop_overlay.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.drop_overlay.setStyleSheet(
            "QLabel { background: rgba(31, 66, 104, 0.92); color: #f4f8ff; "
            "font-size: 17px; font-weight: 700; border: 2px dashed #d8c39a; "
            "border-radius: 20px; padding: 24px; }"
        )
        self.drop_overlay.hide()

        self.upload_overlay = QLabel("", self.view.viewport())
        self.upload_overlay.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.upload_overlay.setStyleSheet(OVERLAY_STYLE)
        self.upload_overlay.hide()

        self.search_cancel_button = QToolButton(self.view.viewport())
        self.search_cancel_button.setText("Cancel")
        self.search_cancel_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.search_cancel_button.setStyleSheet(
            "QToolButton { background: #1c1c1f; color: #dedbd5; border: 1px solid #353538; "
            "border-radius: 10px; padding: 8px 18px; font-weight: 650; } "
            "QToolButton:hover { background: #29292c; border-color: #57534d; } "
            "QToolButton:pressed { background: #141416; }"
        )
        self.search_cancel_button.clicked.connect(self.cancel_remote_search)
        self.search_cancel_button.hide()

        self.center_message = QLabel("", self.view.viewport())
        self.center_message.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.center_message.setWordWrap(True)
        self.center_message.setTextFormat(Qt.TextFormat.RichText)
        self.center_message.setStyleSheet(CENTER_MESSAGE_STYLE)
        center_shadow = QGraphicsDropShadowEffect(self.center_message)
        center_shadow.setBlurRadius(34)
        center_shadow.setOffset(0, 12)
        center_shadow.setColor(QColor(0, 0, 0, 125))
        self.center_message.setGraphicsEffect(center_shadow)
        self._center_message_source = ""
        self.center_message.hide()

        # Legacy floating badges stay available internally, but the taskbar is the visible bottom UI now.
        self.path_badge = QLabel("", self.view.viewport())
        self.path_badge.setStyleSheet(
            "QLabel { background: rgba(0,0,0,0.55); color: white; padding: 7px 14px; "
            "border-radius: 14px; font-size: 12px; }"
        )
        self.path_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.path_badge.setCursor(Qt.CursorShape.PointingHandCursor)
        self.path_badge.mousePressEvent = lambda ev: self._show_path_badge_menu(ev, self.path_badge)
        self.path_badge.hide()

        self.version_badge = QLabel(f"{APP_VERSION}", self.view.viewport())
        self.version_badge.setStyleSheet(
            "QLabel { background: rgba(0,0,0,0.45); color: rgba(255,255,255,0.85); "
            "padding: 6px 10px; border-radius: 12px; font-size: 11px; }"
        )
        self.version_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.version_badge.hide()

        self._setup_taskbar()

        self.toast = QWidget(self)
        self.toast.setStyleSheet(TOAST_STYLE)
        toast_layout = QHBoxLayout(self.toast)
        toast_layout.setContentsMargins(10, 7, 12, 7)
        toast_layout.setSpacing(8)
        self.toast_icon = QLabel("")
        self.toast_icon.setFixedSize(16, 16)
        self.toast_text = QLabel("")
        self.toast_text.setStyleSheet("QLabel { color: #eef3f9; }")
        toast_layout.addWidget(self.toast_icon)
        toast_layout.addWidget(self.toast_text)
        self.toast_opacity = QGraphicsOpacityEffect(self.toast)
        self.toast_opacity.setOpacity(0.0)
        self.toast.setGraphicsEffect(self.toast_opacity)
        self.toast.hide()
        self.toast_anim = None
        self._toast_serial = 0

        self.rename_editor = QLineEdit(self.view.viewport())
        self.rename_editor.hide()
        self.rename_editor.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.rename_editor.setStyleSheet(
            "QLineEdit {"
            " background: rgba(24, 24, 26, 0.94);"
            " color: #f3f1ed;"
            " padding: 2px 7px;"
            " border: 1px solid rgba(216, 195, 154, 0.82);"
            " border-radius: 5px;"
            " selection-background-color: rgba(111, 96, 71, 0.75);"
            " selection-color: #ffffff;"
            "}"
        )
        self.rename_target_item = None
        self.rename_old_name = ""
        self.rename_hidden_text_item = None
        self.rename_editor.returnPressed.connect(self._commit_inline_rename)
        self.rename_editor.editingFinished.connect(self._commit_inline_rename)
        self.rename_editor.installEventFilter(self)

        self.toolbar = QToolBar(self.T["nav"])
        self.toolbar.setMovable(False)
        self.toolbar.setFloatable(False)
        self.toolbar.setFixedHeight(62)
        self.toolbar.setIconSize(QSize(18, 18))
        toolbar_font = QFont("Segoe UI")
        toolbar_font.setPointSizeF(10.5)
        toolbar_font.setWeight(QFont.Weight.DemiBold)
        self.toolbar.setFont(toolbar_font)
        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, self.toolbar)

        self.toolbar.setStyleSheet(TOOLBAR_STYLE)

        self.brand_widget = QWidget()
        self.brand_widget.setMinimumWidth(130)
        brand_layout = QHBoxLayout(self.brand_widget)
        brand_layout.setContentsMargins(3, 0, 10, 0)
        brand_layout.setSpacing(9)
        self.brand_icon = QLabel()
        self.brand_icon.setFixedSize(28, 28)
        if os.path.exists(APP_LOGO_PATH):
            self.brand_icon.setPixmap(
                QPixmap(APP_LOGO_PATH).scaled(
                    28, 28, Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
        self.brand_text = QLabel("<b>XYRA</b><br><span style='color:#8d8982;font-size:8pt'>REMOTE</span>")
        self.brand_text.setStyleSheet("QLabel { color: #f3f1ed; background: transparent; border: none; }")
        brand_layout.addWidget(self.brand_icon)
        brand_layout.addWidget(self.brand_text)
        self.toolbar.addWidget(self.brand_widget)
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
        self.places_tool.setIcon(self._make_icon("fa6s.route", "#d8c39a"))
        self.places_tool.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.places_tool.setCursor(Qt.CursorShape.PointingHandCursor)
        self.places_tool.setMinimumHeight(40)
        self.places_tool.setMinimumWidth(138)
        self.places_menu = QMenu(self.places_tool)
        self.places_menu.aboutToShow.connect(self._rebuild_places_menu)
        self.places_tool.setMenu(self.places_menu)
        self.places_tool.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.toolbar.addWidget(self.places_tool)

        self.toolbar.addSeparator()

        self.display_tool = QToolButton()
        self.display_tool.setFont(toolbar_font)
        self.display_tool.setText(self.T["display"])
        self.display_tool.setIcon(self._make_icon("fa6s.palette", "#c7b7d8"))
        self.display_tool.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.display_tool.setCursor(Qt.CursorShape.PointingHandCursor)
        self.display_tool.setMinimumHeight(40)
        self.display_tool.setMinimumWidth(124)
        display_menu = QMenu(self.display_tool)
        act_bg = display_menu.addAction(self.T["choose_bg"], self.change_background)
        act_bg.setIcon(self._make_icon("fa6s.image", "#c7b7d8"))
        act_icons = display_menu.addAction(self.T["change_icon_pack"], self.change_icon_pack)
        act_icons.setIcon(self._make_icon("fa6s.icons", "#f4c76b"))
        act_reset_icons = display_menu.addAction(self.T["reset_icon_pack"], self.reset_icon_pack)
        act_reset_icons.setIcon(self._make_icon("fa6s.rotate-left", "#ffb86b"))
        self.display_tool.setMenu(display_menu)
        self.display_tool.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.toolbar.addWidget(self.display_tool)

        self.toolbar.addSeparator()

        self.term_tool = QToolButton()
        self.term_tool.setFont(toolbar_font)
        self.term_tool.setText(self.T["terminal"])
        self.term_tool.setIcon(self._make_icon("fa6s.terminal", "#8bc7a8"))
        self.term_tool.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.term_tool.setCursor(Qt.CursorShape.PointingHandCursor)
        self.term_tool.setMinimumHeight(40)
        self.term_tool.setMinimumWidth(148)
        self.term_menu = QMenu(self.term_tool)
        self.term_menu.aboutToShow.connect(self._rebuild_term_menu)
        self._rebuild_term_menu()
        self.term_tool.setMenu(self.term_menu)
        self.term_tool.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.toolbar.addWidget(self.term_tool)

        self.toolbar.addSeparator()
        self.search_box = QLineEdit()
        self.search_box.setFont(toolbar_font)
        self.search_box.setPlaceholderText(self.T["search_placeholder"])
        self.search_box.setClearButtonEnabled(True)
        self.search_box.setMinimumHeight(42)
        self.search_box.setFixedWidth(320)
        self.search_box.textChanged.connect(self._on_search_changed)
        search_action = self.search_box.addAction(self._make_icon("fa6s.magnifying-glass", "#aaa69f"), QLineEdit.ActionPosition.LeadingPosition)
        search_action.setEnabled(False)
        remote_search_action = self.search_box.addAction(self._make_icon("fa6s.server", "#8bc7a8"), QLineEdit.ActionPosition.TrailingPosition)
        remote_search_action.setToolTip("Search server from current folder (Ctrl+Shift+F)")
        remote_search_action.triggered.connect(self.start_remote_search)
        self.toolbar.addWidget(self.search_box)

        self.shortcut_search = QShortcut(QKeySequence("Ctrl+F"), self)
        self.shortcut_search.activated.connect(self._focus_search)
        self.shortcut_remote_search = QShortcut(QKeySequence("Ctrl+Shift+F"), self)
        self.shortcut_remote_search.activated.connect(self.start_remote_search)

        self._was_maximized_before_fullscreen = False
        self.shortcut_fullscreen = QShortcut(QKeySequence("F11"), self)
        self.shortcut_fullscreen.activated.connect(self.toggle_fullscreen)

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
        self.connection_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.connection_label.setMinimumWidth(166)
        self.connection_label.setMinimumHeight(40)
        self.toolbar.addWidget(self.connection_label)

        self.addToolBarBreak(Qt.ToolBarArea.TopToolBarArea)
        self.server_bar = QToolBar("Servers", self)
        self.server_bar.setObjectName("serverBar")
        self.server_bar.setMovable(False)
        self.server_bar.setFloatable(False)
        self.server_bar.setFixedHeight(43)
        self.server_bar.setIconSize(QSize(15, 15))
        self.server_bar.setStyleSheet(SERVER_BAR_STYLE)
        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, self.server_bar)

        server_title = QLabel("SERVERS")
        server_title.setObjectName("serverBarTitle")
        self.server_bar.addWidget(server_title)

        self.add_server_button = QToolButton()
        self.add_server_button.setIcon(self._make_icon("fa6s.plus", "#d8c39a"))
        self.add_server_button.setToolTip("Add or manage server profiles")
        self.add_server_button.setCursor(Qt.CursorShape.ArrowCursor)
        self.add_server_button.setFixedSize(30, 30)
        self.add_server_button.clicked.connect(self.show_ssh_login_dialog)
        self.server_bar.addWidget(self.add_server_button)
        self.server_bar.addWidget(self._toolbar_gap(12))

        self.server_tabs = QTabBar()
        self.server_tabs.setDocumentMode(True)
        self.server_tabs.setDrawBase(False)
        self.server_tabs.setExpanding(False)
        self.server_tabs.setMovable(False)
        self.server_tabs.setTabsClosable(False)
        self.server_tabs.setElideMode(Qt.TextElideMode.ElideRight)
        self.server_tabs.setUsesScrollButtons(True)
        self.server_tabs.setCursor(Qt.CursorShape.ArrowCursor)
        self.server_tabs.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.server_tabs.currentChanged.connect(self._server_tab_changed)
        self.server_bar.addWidget(self.server_tabs)
        self._syncing_server_tabs = False
        self._rebuild_server_tabs()

        self._load_icons()
        self._setup_backend(initial=True)

        bg_path = self.cfg.get("background", None)
        if bg_path and os.path.exists(bg_path):
            self.bg_path = bg_path

        self.discord_rpc.connect()

        self.current_path = self._restore_server_workspace()

        self._apply_initial_window_geometry()

        self.update_path_label()
        self.load_folder(self.current_path)
        self.schedule_automatic_update_check()

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
            "favorite_folders": "Favorite folders",
            "add_favorite": "Add current folder to favorites",
            "add_folder_favorite": "Add folder to favorites",
            "remove_favorite": "Remove from favorites",
            "favorite_added": "Favorite added",
            "favorite_removed": "Favorite removed",
            "no_favorites": "No favorite folders yet",
            "clear_favorites": "Clear favorites",
            "favorites_cleared": "Favorites cleared",
            "recent_paths": "Recent folders",
            "no_recent_paths": "No recent folders yet",
            "clear_recent_paths": "Clear recent folders",
            "recent_paths_cleared": "Recent folders cleared",
            "display": "Display",
            "choose_bg": "Choose background...",
            "change_icon_pack": "Change icon pack...",
            "reset_icon_pack": "Use default icon pack",
            "icon_pack_changed": "Icon pack changed",
            "icon_pack_reset": "Default icon pack restored",
            "icon_pack_missing": "No supported icon files found. Expected names include linux_folder.png, linux_file.png, images.png or linux_archive.png.",
            "icon_pack_custom": "Custom folder...",
            "icon_pack_default": "Xyra Default",
            "terminal": "Remote",
            "ssh_connect": "Connect Server...",
            "ssh_disconnect": "Disconnect Server",
            "ssh_profiles": "Open server in tab",
            "server_health": "Server Health",
            "server_health_title": "Server Health",
            "server_health_checking": "Checking server health...",
            "server_health_failed": "Server health check failed",
            "copy_report": "Copy report",
            "open_putty": "Open PuTTY",
            "open_termius": "Open Termius",
            "drop_hint": "Drag&Drop\nRelease to upload",
            "uploading": "{file} is uploading ({mb:.2f} MB)...",
            "uploaded": "{file} uploaded",
            "upload_failed": "Upload failed",
            "upload_finished": "Upload finished",
            "upload_overwrite_title": "Overwrite existing item?",
            "upload_overwrite_file": "A remote file with the same name already exists:\n\n{path}\n\nOverwrite it?",
            "upload_overwrite_folder": "A remote folder with the same name already exists:\n\n{path}\n\nMerge into it and overwrite matching files?",
            "upload_conflict_type": "A remote item with the same name but a different type already exists:\n\n{path}\n\nXyra will not replace it automatically.",
            "rename": "Rename",
            "delete": "Move to trash",
            "delete_permanently": "Delete permanently",
            "trash_q": "Move to trash?\n\n{path}\n\nThe item will be moved to .xyra-trash instead of being deleted permanently.",
            "permanent_delete_q": "Permanently delete?\n\n{path}\n\nThis cannot be undone by Xyra.",
            "trash_failed": "Move to trash failed",
            "trashed": "Moved to trash",
            "trash_manager": "Trash Manager",
            "trash_empty": "Trash is empty.",
            "trash_restore": "Restore",
            "trash_delete": "Delete permanently",
            "trash_empty_all": "Empty trash",
            "trash_open_original": "Open original folder",
            "trash_loaded_failed": "Could not load trash",
            "trash_restored": "Restored",
            "trash_restore_failed": "Restore failed",
            "trash_deleted": "Trash item deleted",
            "trash_empty_q": "Permanently delete all items in .xyra-trash?\n\nThis cannot be undone by Xyra.",
            "trash_empty_done": "Trash emptied",
            "copy_path": "Copy path",
            "copy_current_path": "Copy current path",
            "path_copied": "Path copied",
            "path_menu": "Path menu",
            "go_to": "Go to",
            "fullscreen_on": "Fullscreen enabled",
            "fullscreen_off": "Fullscreen disabled",
            "copy_to": "Copy to...",
            "move_to": "Move to...",
            "extract_here": "Extract here",
            "extract_to": "Extract to...",
            "compress_zip": "Compress to ZIP...",
            "download": "Download...",
            "downloaded": "Downloaded",
            "download_failed": "Download failed",
            "download_finished": "Download finished",
            "download_overwrite_title": "Overwrite local file?",
            "download_overwrite_q": "A local file with the same name already exists:\n\n{path}\n\nOverwrite it?",
            "sensitive_title": "Sensitive item",
            "sensitive_warning": (
                "This looks like a sensitive file or folder:\n\n"
                "{path}\n\n"
                "It may contain credentials, private keys, tokens or server secrets.\n"
                "Continue with this action?"
            ),
            "sensitive_multi_warning": (
                "Your selection contains sensitive items:\n\n"
                "{items}\n\n"
                "They may contain credentials, private keys, tokens or server secrets.\n"
                "Continue with this action?"
            ),
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
            "launch_failed": (
                "Could not launch {tool}.\n\n"
                "Xyra tried the saved app path, Windows PATH and common install locations.\n\n"
                "Fix:\n"
                "- install {tool_name}, or\n"
                "- add it to Windows PATH, or\n"
                "- set the custom path in Xyra's local settings database."
            ),
            "putty_password_notice": "PuTTY opened without password autofill for security.",
            "create_folder": "Create folder",
            "create_file": "Create file",
            "name_prompt": "Name:",
            "create_title": "Create",
            "create_failed": "Create failed",
            "search_placeholder": "Search (Ctrl+F)...",
            "remote_search_title": "Search server",
            "remote_search_prompt": "Filename contains:",
            "remote_search_depth": "Max folder depth:",
            "remote_searching": "Searching server for \"{query}\"...",
            "remote_search_info": "This can take some minutes on large folders.",
            "remote_search_cancelled": "Search cancelled",
            "remote_search_failed": "Server search failed",
            "remote_search_results": "Search results",
            "remote_search_empty": "No matching files or folders found.",
            "remote_search_hint": "Double-click a result to open its folder.",
            "remote_search_open_folder": "Open folder",
            "remote_search_copy_path": "Copy path",
            "path_change_blocked": "Please wait until the server search is finished or cancelled.",
            "ssh_connect_failed": "Server connection failed",
            "ssh_connected": "Server connected",
            "ssh_disconnected": "Server disconnected",
            "backend_idle": "Offline",
            "backend_ssh": "Remote Connected",
        }

    def _setup_taskbar(self):
        self.taskbar = QWidget(self)
        self.taskbar.setObjectName("xyraTaskbar")
        self.taskbar.setFixedHeight(58)
        self.taskbar.setStyleSheet(TASKBAR_STYLE)
        dock_shadow = QGraphicsDropShadowEffect(self.taskbar)
        dock_shadow.setBlurRadius(30)
        dock_shadow.setOffset(0, 8)
        dock_shadow.setColor(QColor(0, 0, 0, 150))
        self.taskbar.setGraphicsEffect(dock_shadow)

        layout = QHBoxLayout(self.taskbar)
        layout.setContentsMargins(9, 8, 9, 8)
        layout.setSpacing(7)

        self.task_start_button = QToolButton(self.taskbar)
        self.task_start_button.setText("Xyra")
        if os.path.exists(APP_ICON_PATH):
            self.task_start_button.setIcon(QIcon(APP_ICON_PATH))
        elif os.path.exists(APP_LOGO_PATH):
            self.task_start_button.setIcon(QIcon(APP_LOGO_PATH))
        self.task_start_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.task_start_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.task_start_button.setIconSize(QSize(20, 20))
        self.task_start_button.setMinimumWidth(98)
        self.task_start_button.setMinimumHeight(40)
        self.task_start_button.setStyleSheet(
            "QToolButton { color: #f3f1ed; background: #24211d; border: 1px solid #574b38; "
            "border-radius: 11px; padding: 7px 13px; font-weight: 800; } "
            "QToolButton:hover { background: #292724; border-color: #d8c39a; }"
        )
        self.task_start_button.clicked.connect(self._show_taskbar_menu)
        layout.addWidget(self.task_start_button)

        self.task_path_label = QLabel("/", self.taskbar)
        self.task_path_label.setCursor(Qt.CursorShape.PointingHandCursor)
        self.task_path_label.setMinimumHeight(40)
        self.task_path_label.setMinimumWidth(220)
        self.task_path_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.task_path_label.setStyleSheet(
            "QLabel { color: #dedbd5; background: #18181b; border: 1px solid #343438; "
            "border-radius: 11px; padding: 7px 14px; font-weight: 650; } "
            "QLabel:hover { color: #ffffff; background: #222225; border-color: #57534d; }"
        )
        self.task_path_label.mousePressEvent = lambda ev: self._show_path_badge_menu(ev, self.task_path_label)
        layout.addWidget(self.task_path_label, 1)

        self.task_search_button = QToolButton(self.taskbar)
        self.task_search_button.setIcon(self._make_icon("fa6s.magnifying-glass", "#c7c3bc"))
        self.task_search_button.setText("Search")
        self.task_search_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.task_search_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.task_search_button.setMinimumHeight(40)
        self.task_search_button.clicked.connect(self._show_task_search_menu)
        layout.addWidget(self.task_search_button)

        self.task_transfers_button = QToolButton(self.taskbar)
        self.task_transfers_button.setIcon(self._make_icon("fa6s.arrow-right-arrow-left", "#d8c39a"))
        self.task_transfers_button.setText("Transfers")
        self.task_transfers_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.task_transfers_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.task_transfers_button.setMinimumHeight(40)
        self.task_transfers_button.clicked.connect(self._show_transfer_center)
        layout.addWidget(self.task_transfers_button)

        self.task_health_button = QToolButton(self.taskbar)
        self.task_health_button.setIcon(self._make_icon("fa6s.heart-pulse", "#ff9ea5"))
        self.task_health_button.setText("Health")
        self.task_health_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.task_health_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.task_health_button.setMinimumHeight(40)
        self.task_health_button.clicked.connect(self.show_server_health)
        layout.addWidget(self.task_health_button)

        self.task_fullscreen_button = QToolButton(self.taskbar)
        self.task_fullscreen_button.setIcon(self._make_icon("fa6s.up-right-and-down-left-from-center", "#f4c76b"))
        self.task_fullscreen_button.setText("F11")
        self.task_fullscreen_button.setToolTip("Toggle fullscreen (F11)")
        self.task_fullscreen_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.task_fullscreen_button.setMinimumHeight(40)
        self.task_fullscreen_button.clicked.connect(self.toggle_fullscreen)
        layout.addWidget(self.task_fullscreen_button)

        self.task_time_label = QLabel("", self.taskbar)
        self.task_time_label.setMinimumWidth(76)
        self.task_time_label.setMinimumHeight(40)
        self.task_time_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.task_time_label.setStyleSheet(
            "QLabel { color: #aaa69f; background: #19191b; border: 1px solid #303034; "
            "border-radius: 11px; padding: 7px 12px; font-weight: 700; }"
        )
        layout.addWidget(self.task_time_label)

        self.taskbar.show()
        self.task_clock = QTimer(self)
        self.task_clock.timeout.connect(self._update_taskbar_clock)
        self.task_clock.start(30000)
        self._update_taskbar_clock()

    def _update_responsive_toolbar(self):
        """Keep the command bar useful instead of clipping at smaller widths."""
        if not hasattr(self, "search_box"):
            return

        compact = self.width() < 1380
        self.search_box.setFixedWidth(220 if compact else 320)
        self.brand_text.setVisible(not compact)
        self.brand_widget.setMinimumWidth(46 if compact else 130)
        self.brand_widget.setMaximumWidth(52 if compact else 16777215)
        self.connection_label.setMinimumWidth(122 if compact else 166)

        tools = (
            (self.places_tool, 138),
            (self.display_tool, 124),
            (self.term_tool, 148),
        )
        for tool, normal_width in tools:
            tool.setToolButtonStyle(
                Qt.ToolButtonStyle.ToolButtonIconOnly
                if compact else Qt.ToolButtonStyle.ToolButtonTextBesideIcon
            )
            tool.setMinimumWidth(46 if compact else normal_width)
            tool.setMaximumWidth(46 if compact else 16777215)
            tool.setToolTip(tool.text() if compact else "")

        compact_dock = self.width() < 1100
        for button, tooltip in (
            (getattr(self, "task_transfers_button", None), "Transfers"),
            (getattr(self, "task_health_button", None), "Server health"),
        ):
            if button is None:
                continue
            button.setToolButtonStyle(
                Qt.ToolButtonStyle.ToolButtonIconOnly
                if compact_dock else Qt.ToolButtonStyle.ToolButtonTextBesideIcon
            )
            button.setMinimumWidth(42 if compact_dock else 0)
            button.setMaximumWidth(46 if compact_dock else 16777215)
            if compact_dock:
                button.setToolTip(tooltip)

    def _show_taskbar_menu(self):
        menu = QMenu(self)
        act_refresh = menu.addAction(self.T["refresh"])
        act_refresh.setIcon(self._make_icon("fa6s.rotate-right", "#c7c3bc"))
        act_trash = menu.addAction(self.T["trash_manager"])
        act_trash.setIcon(self._make_icon("fa6s.trash-can-arrow-up", "#f4c76b"))
        act_health = menu.addAction(self.T["server_health"])
        act_health.setIcon(self._make_icon("fa6s.heart-pulse", "#ff9ea5"))
        act_fullscreen = menu.addAction(self.T["fullscreen_off"] if self.isFullScreen() else self.T["fullscreen_on"])
        act_fullscreen.setIcon(self._make_icon("fa6s.up-right-and-down-left-from-center", "#f4c76b"))
        update_menu = menu.addMenu("Updates")
        update_menu.setIcon(self._make_icon("fa6s.shield-halved", "#8bc7a8"))
        act_check_updates = update_menu.addAction("Check for updates...")
        act_check_updates.setIcon(self._make_icon("fa6s.arrows-rotate", "#c7c3bc"))
        update_menu.addSeparator()
        act_stable_updates = update_menu.addAction("Stable channel")
        act_stable_updates.setCheckable(True)
        act_preview_updates = update_menu.addAction("Preview channel")
        act_preview_updates.setCheckable(True)
        update_channel = self.cfg.get("update_channel", "stable")
        act_stable_updates.setChecked(update_channel == "stable")
        act_preview_updates.setChecked(update_channel == "prerelease")
        update_menu.addSeparator()
        act_auto_updates = update_menu.addAction("Check automatically on startup")
        act_auto_updates.setCheckable(True)
        act_auto_updates.setChecked(bool(self.cfg.get("automatic_update_checks", True)))
        menu.addSeparator()
        act_about = menu.addAction(self.T["about"])
        act_about.setIcon(self._make_icon("fa6s.circle-info", "#f4c76b"))

        chosen = self._exec_menu_above_widget(menu, self.task_start_button)
        if chosen == act_refresh:
            self.refresh_session()
        elif chosen == act_trash:
            self.show_trash_manager()
        elif chosen == act_health:
            self.show_server_health()
        elif chosen == act_fullscreen:
            self.toggle_fullscreen()
        elif chosen == act_check_updates:
            self.check_for_updates(manual=True)
        elif chosen == act_stable_updates:
            self.set_update_channel("stable")
        elif chosen == act_preview_updates:
            self.set_update_channel("prerelease")
        elif chosen == act_auto_updates:
            self.toggle_automatic_update_checks()
        elif chosen == act_about:
            self.show_about_dialog()

    def _show_task_search_menu(self):
        menu = QMenu(self)
        act_local = menu.addAction("Focus search")
        act_local.setIcon(self._make_icon("fa6s.magnifying-glass", "#c7c3bc"))
        act_remote = menu.addAction(self.T["remote_search_title"])
        act_remote.setIcon(self._make_icon("fa6s.server", "#8bc7a8"))

        chosen = self._exec_menu_above_widget(menu, self.task_search_button)
        if chosen == act_local:
            self._focus_search()
        elif chosen == act_remote:
            self.start_remote_search()

    def _exec_menu_above_widget(self, menu: QMenu, widget: QWidget):
        menu.ensurePolished()
        hint = menu.sizeHint()
        top_left = widget.mapToGlobal(QPoint(0, 0))
        x = top_left.x()
        y = top_left.y() - hint.height() - 10
        return menu.exec(QPoint(x, max(0, y)))

    def _update_taskbar_clock(self):
        if hasattr(self, "task_time_label"):
            self.task_time_label.setText(datetime.now().strftime("%H:%M"))

    def _update_taskbar_connection(self, connected: bool):
        if hasattr(self, "task_start_button"):
            self.task_start_button.setToolTip(self.backend.describe() if connected and self.backend else APP_NAME)

    def _reposition_taskbar(self):
        if not hasattr(self, "taskbar"):
            return
        margin = 18
        h = self.taskbar.height()
        window_w = max(320, self.width())
        window_h = max(220, self.height())
        width = min(max(720, int(window_w * 0.64)), 1120, max(320, window_w - margin * 2))
        x = max(margin, (window_w - width) // 2)
        y = max(margin, window_h - h - margin)
        self.taskbar.setGeometry(x, y, width, h)
        self.taskbar.raise_()

    def _rebuild_places_menu(self):
        menu = self.places_menu
        menu.clear()

        start_path = normalize_api_path(self.cfg.get("start_path", "."))
        current_path = normalize_api_path(getattr(self, "current_path", start_path))

        act_start = menu.addAction(f"{self.T['open_start_path']}: {self._display_server_path(start_path)}")
        act_start.setIcon(self._make_icon("fa6s.house", "#d8c39a"))
        act_start.triggered.connect(lambda checked=False, p=start_path: self._navigate_to_path(p))

        act_set_start = menu.addAction(f"{self.T['set_start_path']}: {self._display_server_path(current_path)}")
        act_set_start.setIcon(self._make_icon("fa6s.location-dot", "#f4c76b"))
        act_set_start.triggered.connect(self._set_current_path_as_start)

        menu.addSeparator()
        favorite_menu = menu.addMenu(self.T["favorite_folders"])
        favorite_menu.setIcon(self._make_icon("fa6s.star", "#f4c76b"))

        favorites = self._clean_saved_paths(self.cfg.get("favorites", []))
        is_current_favorite = current_path in favorites
        act_toggle_current = favorite_menu.addAction(
            self.T["remove_favorite"] if is_current_favorite else self.T["add_favorite"]
        )
        act_toggle_current.setIcon(self._make_icon("fa6s.star", "#f4c76b"))
        act_toggle_current.triggered.connect(lambda checked=False, p=current_path: self._toggle_favorite_path(p))

        favorite_menu.addSeparator()
        if favorites:
            for path in favorites:
                action = favorite_menu.addAction(self._display_server_path(path))
                action.triggered.connect(lambda checked=False, p=path: self._navigate_to_path(p))
            favorite_menu.addSeparator()
            act_clear_favorites = favorite_menu.addAction(self.T["clear_favorites"])
            act_clear_favorites.setIcon(self._make_icon("fa6s.broom", "#ffb86b"))
            act_clear_favorites.triggered.connect(self._clear_favorites)
        else:
            empty_favorites = favorite_menu.addAction(self.T["no_favorites"])
            empty_favorites.setEnabled(False)

        menu.addSeparator()
        recent_menu = menu.addMenu(self.T["recent_paths"])
        recent_menu.setIcon(self._make_icon("fa6s.clock-rotate-left", "#c7b7d8"))

        recent_paths = self._clean_saved_paths(self.cfg.get("recent_paths", []))
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

    def _clean_saved_paths(self, paths, limit: int = 10) -> list[str]:
        cleaned = []
        for path in paths if isinstance(paths, list) else []:
            norm = normalize_api_path(str(path))
            if norm not in cleaned:
                cleaned.append(norm)
        return cleaned[:limit]

    def _record_recent_path(self, path: str):
        norm = normalize_api_path(path)
        recent_paths = self._clean_saved_paths(self.cfg.get("recent_paths", []))
        updated = [norm] + [p for p in recent_paths if p != norm]
        updated = updated[:10]
        if recent_paths == updated:
            return
        self.cfg["recent_paths"] = updated
        save_recent_paths(self.cfg["recent_paths"])
        self._save_current_server_workspace()

    def _current_profile_data(self) -> dict:
        return {
            "profile_name": self.cfg.get("ssh_profile_name") or self.cfg.get("profile_name") or "",
            "ssh_host": self.cfg.get("ssh_host") or "",
            "ssh_port": self.cfg.get("ssh_port", 22),
            "ssh_username": self.cfg.get("ssh_username") or "",
            "ssh_root": self.cfg.get("ssh_root") or ".",
        }

    def _save_current_server_workspace(self):
        if not (self.cfg.get("ssh_host") and self.cfg.get("ssh_username")):
            return
        identity = profile_identity(self._current_profile_data())
        workspaces = self.cfg.get("server_workspaces")
        if not isinstance(workspaces, dict):
            workspaces = {}
            self.cfg["server_workspaces"] = workspaces
        workspaces[identity] = clean_workspace({
            "current_path": getattr(self, "current_path", self.cfg.get("start_path", ".")),
            "start_path": self.cfg.get("start_path", "."),
            "favorites": self.cfg.get("favorites", []),
            "recent_paths": self.cfg.get("recent_paths", []),
        })
        save_server_workspace(identity, workspaces[identity])

    def _restore_server_workspace(self) -> str:
        profile = self._current_profile_data()
        configured = bool(profile.get("ssh_host") and profile.get("ssh_username"))
        identity = profile_identity(profile) if configured else ""
        self._active_server_id = identity
        workspaces = self.cfg.get("server_workspaces")
        if not isinstance(workspaces, dict):
            workspaces = {}
            self.cfg["server_workspaces"] = workspaces
        fallback = {
            "current_path": self.cfg.get("start_path", "."),
            "start_path": self.cfg.get("start_path", "."),
            "favorites": self.cfg.get("favorites", []),
            "recent_paths": self.cfg.get("recent_paths", []),
        }
        workspace = clean_workspace(workspaces.get(identity, fallback))
        self.cfg["start_path"] = workspace["start_path"]
        self.cfg["favorites"] = workspace["favorites"]
        self.cfg["recent_paths"] = workspace["recent_paths"]
        self.history.clear()
        self.future.clear()
        self.search_query = ""
        self.selected_names.clear()
        return workspace["current_path"]

    def _toggle_favorite_path(self, path: str):
        norm = normalize_api_path(path)
        favorites = self._clean_saved_paths(self.cfg.get("favorites", []), limit=50)
        if norm in favorites:
            favorites = [p for p in favorites if p != norm]
            toast_text = self.T["favorite_removed"]
        else:
            favorites.insert(0, norm)
            toast_text = self.T["favorite_added"]
        self.cfg["favorites"] = favorites[:50]
        save_favorites(self.cfg["favorites"])
        self._save_current_server_workspace()
        self.show_toast(toast_text, "fa6s.star", "#f4c76b")

    def _can_change_path(self) -> bool:
        if self._remote_search_active:
            self.show_toast(self.T["path_change_blocked"], "fa6s.magnifying-glass", "#f4c76b")
            return False
        if self._remote_job_active:
            self.show_toast(self.T["remote_job_busy"], "fa6s.hourglass-half", "#f4c76b")
            return False
        return True

    def _navigate_to_path(self, path: str):
        if not self._can_change_path():
            return
        target = normalize_api_path(path)
        if target == normalize_api_path(self.current_path):
            self.refresh_session()
            return
        self._clear_local_search_filter()
        self.load_folder(target, navigation_mode="normal")

    def _set_current_path_as_start(self):
        self.cfg["start_path"] = normalize_api_path(self.current_path)
        save_config(self.cfg)
        self._save_current_server_workspace()
        self.show_toast(self.T["start_path_set"], "fa6s.location-dot", "#53d18b")

    def _clear_recent_paths(self):
        self.cfg["recent_paths"] = []
        save_recent_paths(self.cfg["recent_paths"])
        self._save_current_server_workspace()
        self.show_toast(self.T["recent_paths_cleared"], "fa6s.broom", "#f4c76b")

    def _clear_favorites(self):
        self.cfg["favorites"] = []
        save_favorites(self.cfg["favorites"])
        self._save_current_server_workspace()
        self.show_toast(self.T["favorites_cleared"], "fa6s.broom", "#f4c76b")

    def _saved_server_profiles(self) -> list[dict]:
        return [
            dict(profile) for profile in self.cfg.get("ssh_profiles", [])
            if isinstance(profile, dict)
            and (profile.get("ssh_host") or "").strip()
            and (profile.get("ssh_username") or "").strip()
        ]

    def _backend_is_connected(self) -> bool:
        backend = self.backend
        if backend is None:
            return False
        try:
            return bool(backend.is_connected())
        except Exception:
            return False

    def _current_server_tab_state(self) -> dict:
        return {
            "current_path": normalize_api_path(getattr(self, "current_path", ".")),
            "history": list(self.history),
            "future": list(self.future),
            "search_query": self.search_query,
            "current_items": [dict(item) for item in self.current_items if isinstance(item, dict)],
            "selected_names": list(self.selected_names),
        }

    def _capture_active_server_tab_state(self):
        session_id = self._active_server_session_id
        if session_id is None or not hasattr(self, "current_path"):
            return
        for session in self._server_tab_sessions:
            if session.get("session_id") == session_id:
                session["state"] = self._current_server_tab_state()
                return

    def _restore_server_tab_state(self, session: dict):
        state = session.get("state") if isinstance(session, dict) else None
        if not isinstance(state, dict):
            session["state"] = self._current_server_tab_state()
            return

        self._folder_load_generation += 1
        self.current_path = normalize_api_path(state.get("current_path", "."))
        self.history = list(state.get("history", []))
        self.future = list(state.get("future", []))
        self.search_query = str(state.get("search_query", ""))
        self.current_items = [
            dict(item) for item in state.get("current_items", [])
            if isinstance(item, dict)
        ]
        self.selected_names = set(state.get("selected_names", []))
        self.search_box.blockSignals(True)
        self.search_box.setText(self.search_query)
        self.search_box.blockSignals(False)
        self.update_path_label()
        self._render_folder_items()
        self.load_folder(self.current_path)

    def _add_server_tab_session(self, profile: dict, state: dict | None = None) -> int:
        self._server_session_serial += 1
        session_id = self._server_session_serial
        self._server_tab_sessions.append({
            "session_id": session_id,
            "profile": dict(profile),
            "state": dict(state) if isinstance(state, dict) else None,
        })
        return session_id

    def _sync_server_tab_sessions(self):
        profiles = self._saved_server_profiles()
        saved_by_identity = {
            profile_identity(profile): profile for profile in profiles
            if profile_identity(profile) not in self._dismissed_server_identities
        }
        retained = []

        for session in self._server_tab_sessions:
            profile = session.get("profile") if isinstance(session, dict) else None
            if not isinstance(profile, dict):
                continue
            identity = profile_identity(profile)
            saved = saved_by_identity.get(identity)
            if saved is not None:
                session["profile"] = dict(saved)
            retained.append(session)

        self._server_tab_sessions = retained
        if self._backend_is_connected() and not self._server_tab_sessions:
            active = self._current_profile_data()
            active_identity = profile_identity(active)
            self._add_server_tab_session(saved_by_identity.get(active_identity, active))

    def _select_connected_server_session(
        self,
        profile: dict,
        *,
        force_new: bool,
        capture_current: bool = True,
    ):
        source_state = self._current_server_tab_state()
        if capture_current:
            self._capture_active_server_tab_state()
        identity = profile_identity(profile)
        self._dismissed_server_identities.discard(identity)
        self._sync_server_tab_sessions()
        session_id = None
        if not force_new:
            for session in self._server_tab_sessions:
                if profile_identity(session["profile"]) == identity:
                    session_id = session["session_id"]
                    break
        if session_id is None:
            session_id = self._add_server_tab_session(profile, source_state)
        self._active_server_session_id = session_id
        self._rebuild_server_tabs()

    def _rebuild_server_tabs(self):
        if not hasattr(self, "server_tabs") or self._syncing_server_tabs:
            return

        self._sync_server_tab_sessions()
        sessions = list(self._server_tab_sessions)
        connected = self._backend_is_connected()
        active_identity = ""
        if connected:
            active_identity = getattr(self, "_active_server_id", "")
            if not active_identity:
                active_identity = profile_identity(self._current_profile_data())

        identity_totals = {}
        for session in sessions:
            identity = profile_identity(session["profile"])
            identity_totals[identity] = identity_totals.get(identity, 0) + 1
        identity_occurrence = {}

        self._syncing_server_tabs = True
        self.server_tabs.blockSignals(True)
        try:
            while self.server_tabs.count():
                self.server_tabs.removeTab(0)

            active_index = -1
            fallback_index = -1
            for session in sessions:
                profile = session["profile"]
                identity = profile_identity(profile)
                identity_occurrence[identity] = identity_occurrence.get(identity, 0) + 1
                occurrence = identity_occurrence[identity]
                name = profile_display_name(profile)
                tab_name = f"{name} - {occurrence}" if identity_totals[identity] > 1 else name
                index = self.server_tabs.addTab(
                    self._make_icon("fa6s.server", profile_accent(profile)),
                    tab_name,
                )
                self.server_tabs.setTabData(index, dict(session))
                close_button = QToolButton(self.server_tabs)
                close_button.setObjectName("serverTabCloseButton")
                close_button.setText("×")
                close_button.setToolTip(f"Close {tab_name}")
                close_button.setCursor(Qt.CursorShape.ArrowCursor)
                close_button.setAutoRaise(True)
                close_button.setFixedSize(16, 16)
                close_button.clicked.connect(
                    lambda checked=False, sid=session["session_id"]: self._close_server_session(sid)
                )
                self.server_tabs.setTabButton(
                    index,
                    QTabBar.ButtonPosition.RightSide,
                    close_button,
                )
                self.server_tabs.setTabToolTip(
                    index,
                    f"{name}\n{profile.get('ssh_username')}@{profile.get('ssh_host')}"
                    f":{profile.get('ssh_port', 22)}\nSession {occurrence} - click to switch",
                )
                if connected and identity == active_identity:
                    if fallback_index < 0:
                        fallback_index = index
                    if session["session_id"] == self._active_server_session_id:
                        active_index = index

            if active_index < 0:
                active_index = fallback_index
                if active_index >= 0:
                    active_session = self.server_tabs.tabData(active_index)
                    self._active_server_session_id = active_session["session_id"]

            self.server_tabs.setCurrentIndex(active_index)
            self.server_tabs.setVisible(bool(sessions))
            self.server_bar.setVisible(connected and len(sessions) > 1)
        finally:
            self.server_tabs.blockSignals(False)
            self._syncing_server_tabs = False

    def _server_tab_changed(self, index: int):
        if self._syncing_server_tabs or index < 0:
            return
        session = self.server_tabs.tabData(index)
        if not isinstance(session, dict):
            return
        profile = session.get("profile")
        session_id = session.get("session_id")
        if not isinstance(profile, dict) or not isinstance(session_id, int):
            return
        if self._backend_is_connected() and session_id == self._active_server_session_id:
            return

        self._capture_active_server_tab_state()
        same_server = (
            self._backend_is_connected()
            and profile_identity(profile) == getattr(self, "_active_server_id", "")
        )
        if same_server:
            self._active_server_session_id = session_id
            self._restore_server_tab_state(session)
            self._rebuild_server_tabs()
            self._update_connection_label()
            return

        name = profile_display_name(profile)
        self._syncing_server_tabs = True
        self.connection_label.setText(f"CONNECTING  {name}")
        self.connection_label.setToolTip(f"Connecting to {name}...")
        QApplication.processEvents()
        try:
            if self.connect_ssh_profile(profile):
                self._active_server_session_id = session_id
                self._restore_server_tab_state(session)
        finally:
            self._syncing_server_tabs = False
            self.server_tabs.setCursor(Qt.CursorShape.ArrowCursor)
            self._rebuild_server_tabs()
            self._update_connection_label()

    def _close_server_session(self, session_id: int):
        for index in range(self.server_tabs.count()):
            session = self.server_tabs.tabData(index)
            if isinstance(session, dict) and session.get("session_id") == session_id:
                self._close_server_tab(index)
                return

    def _close_server_tab(self, index: int):
        if self._syncing_server_tabs or index < 0:
            return
        session = self.server_tabs.tabData(index)
        if not isinstance(session, dict):
            return
        session_id = session.get("session_id")
        profile = session.get("profile")
        if not isinstance(session_id, int) or not isinstance(profile, dict):
            return

        was_active = session_id == self._active_server_session_id
        if was_active:
            self._capture_active_server_tab_state()
        old_sessions = list(self._server_tab_sessions)
        self._server_tab_sessions = [
            candidate for candidate in self._server_tab_sessions
            if candidate.get("session_id") != session_id
        ]

        identity = profile_identity(profile)
        if not any(
            profile_identity(candidate["profile"]) == identity
            for candidate in self._server_tab_sessions
        ):
            self._dismissed_server_identities.add(identity)

        if not was_active:
            self._rebuild_server_tabs()
            return
        if not self._server_tab_sessions:
            self._active_server_session_id = None
            self.disconnect_ssh()
            return

        target_index = min(index, len(self._server_tab_sessions) - 1)
        target = self._server_tab_sessions[target_index]
        target_profile = target["profile"]
        same_server = (
            self._backend_is_connected()
            and profile_identity(target_profile) == getattr(self, "_active_server_id", "")
        )
        if same_server or self.connect_ssh_profile(target_profile):
            self._active_server_session_id = target["session_id"]
            self._restore_server_tab_state(target)
            self._rebuild_server_tabs()
            self._update_connection_label()
            return

        self._server_tab_sessions = old_sessions
        self._dismissed_server_identities.discard(identity)
        self._active_server_session_id = session_id
        self._rebuild_server_tabs()

    def _open_profile_session(self, profile: dict) -> bool:
        already_connected = self._backend_is_connected()
        same_server = (
            already_connected
            and profile_identity(profile) == getattr(self, "_active_server_id", "")
        )
        if not self.connect_ssh_profile(profile):
            return False
        self._select_connected_server_session(
            profile,
            force_new=already_connected,
            capture_current=same_server,
        )
        return True

    def _rebuild_term_menu(self):
        term_menu = self.term_menu
        term_menu.clear()

        act_connect = term_menu.addAction(self.T["ssh_connect"], self.show_ssh_login_dialog)
        act_disconnect = term_menu.addAction(self.T["ssh_disconnect"], self.disconnect_ssh)
        act_trash = term_menu.addAction(self.T["trash_manager"], self.show_trash_manager)
        act_health = term_menu.addAction(self.T["server_health"], self.show_server_health)
        term_menu.addSeparator()

        profiles_menu = term_menu.addMenu(self.T["ssh_profiles"])
        profiles_menu.setIcon(self._make_icon("fa6s.server", "#c7c3bc"))

        profiles = self._saved_server_profiles()
        if profiles:
            active_name = (self.cfg.get("ssh_profile_name") or "").strip()
            for profile in profiles:
                profile_name = profile_display_name(profile)
                action = profiles_menu.addAction(profile_name)
                action.setCheckable(True)
                action.setChecked(profile_name == active_name and self.backend is not None)
                action.setIcon(self._make_icon("fa6s.server", profile_accent(profile)))
                action.setStatusTip(f"Open {profile_name} in a Xyra tab")
                action.triggered.connect(lambda checked=False, p=dict(profile): self._open_profile_session(p))
        else:
            empty_action = profiles_menu.addAction("No saved profiles")
            empty_action.setEnabled(False)

        term_menu.addSeparator()
        act_putty = term_menu.addAction(self.T["open_putty"], lambda: self._launch_tool("putty"))
        act_termius = term_menu.addAction(self.T["open_termius"], lambda: self._launch_tool("termius"))

        act_connect.setIcon(self._make_icon("fa6s.plug-circle-bolt", "#8bc7a8"))
        act_disconnect.setIcon(self._make_icon("fa6s.power-off", "#ff9ea5"))
        act_trash.setIcon(self._make_icon("fa6s.trash-can-arrow-up", "#f4c76b"))
        act_health.setIcon(self._make_icon("fa6s.heart-pulse", "#ff9ea5"))
        act_putty.setIcon(self._make_icon("fa6s.window-restore"))
        act_termius.setIcon(self._make_icon("fa6s.square-terminal"))

    def _update_connection_label(self):
        if isinstance(self.backend, SshRemoteBackend) and self.backend.is_connected():
            profile = self._current_profile_data()
            name = profile_display_name(profile)
            accent = profile_accent(profile)
            compact_name = name if len(name) <= 18 else name[:17].rstrip() + "…"
            self.connection_label.setText(f"●  {compact_name}")
            self.connection_label.setToolTip(
                f"{name}\n{self.backend.describe()}\nRoot: {self.cfg.get('ssh_root') or '/'}"
            )
            self.connection_label.setStyleSheet(
                f"QLabel {{ color:{accent}; background-color:#191d1b; border:1px solid {accent}; "
                "border-radius:10px; padding:7px 12px; font-weight:700; }"
            )
            self.setWindowTitle(f"{APP_NAME} - {name}")
            self._update_taskbar_connection(True)
        else:
            self.connection_label.setText("●  OFFLINE")
            self.connection_label.setToolTip("No active remote server connection")
            self.connection_label.setStyleSheet(OFFLINE_PILL_STYLE)
            self.setWindowTitle(APP_NAME)
            self._update_taskbar_connection(False)
        self._rebuild_server_tabs()

    def _handle_connection_state(self, state: str, detail: str = ""):
        if state == "reconnecting":
            self.connection_label.setText("⟳  RECONNECTING")
            self.connection_label.setToolTip(detail or "Restoring the SSH connection…")
            self.connection_label.setStyleSheet(OFFLINE_PILL_STYLE)
            if self.cfg.get("ssh_host") and self.cfg.get("ssh_username"):
                self.setWindowTitle(f"{APP_NAME} - {profile_display_name(self._current_profile_data())} (Offline)")
            else:
                self.setWindowTitle(APP_NAME)
            self._update_taskbar_connection(False)
            return
        self._update_connection_label()
        self._update_discord_presence()
        if state == "connected":
            self.show_toast("SSH connection restored", "fa6s.link", "#8bc7a8")
        elif state == "offline":
            self.show_toast(
                "SSH reconnect failed. Check the server or connect manually.",
                "fa6s.plug-circle-xmark",
                "#e58f98",
            )

    def _update_discord_presence(self):
        if not hasattr(self, "discord_rpc"):
            return
        if isinstance(self.backend, SshRemoteBackend) and self.backend.is_connected():
            profile_name = profile_display_name(self._current_profile_data())
            self.discord_rpc.update(
                "Browsing remote files",
                f"Connected to {profile_name}",
            )
        else:
            self.discord_rpc.update("Idle in dashboard", APP_VERSION)

    def _verify_ssh_host_key(self, hostname: str, algorithm: str, fingerprint: str) -> bool:
        message = (
            "This server has not been trusted by Xyra yet.\n\n"
            f"Server: {hostname}\n"
            f"Key type: {algorithm}\n"
            f"Fingerprint: {fingerprint}\n\n"
            "Compare this fingerprint with the value shown by your hosting provider "
            "or server administrator. Only trust it when it matches exactly."
        )
        answer = QMessageBox.question(
            self,
            "Verify SSH host key",
            message,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return answer == QMessageBox.StandardButton.Yes

    def _create_ssh_backend(self, config: dict | None = None) -> SshRemoteBackend:
        return SshRemoteBackend(
            config or self.cfg,
            host_key_verifier=self._verify_ssh_host_key,
        )

    def _prepare_server_switch(self, target_profile: dict) -> bool:
        target_id = profile_identity(target_profile)
        active_id = getattr(self, "_active_server_id", "")
        switching_server = bool(active_id) and target_id != active_id

        if switching_server and self._active_external_opens:
            self.show_toast(
                "Please wait until files currently opening have finished before switching servers.",
                "fa6s.hourglass-half",
                "#dfb86d",
            )
            return False

        counts = self.transfer_queue.counts()
        has_transfers = counts["active"] + counts["queued"] > 0
        if has_transfers:
            answer = QMessageBox.question(
                self,
                "Switch server",
                "Switching servers will cancel all running and queued transfers.\n\nContinue?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return False

        if switching_server:
            for editor in list(self.open_editors):
                try:
                    if not editor.close():
                        self.show_toast("Server switch cancelled: an editor still has unsaved changes.")
                        return False
                except RuntimeError:
                    self._on_editor_destroyed(editor)

        self._save_current_server_workspace()
        if has_transfers:
            self.transfer_queue.cancel_all()
        return True

    def _activate_connected_backend(self, backend: SshRemoteBackend, data: dict) -> bool:
        if not self._prepare_server_switch(data):
            backend.disconnect()
            return False

        previous_backend = self.backend
        self.cfg.update(data)
        self.cfg["ssh_profile_name"] = data.get("ssh_profile_name") or data.get("profile_name") or ""
        self.cfg["connection_mode"] = "ssh"
        save_config(self.cfg)

        self.backend = backend
        if isinstance(previous_backend, SshRemoteBackend):
            previous_backend.disconnect()

        self._folder_load_generation += 1
        self._editor_backup_paths.clear()
        self._prepare_scene_reset()
        self.current_items = []
        self.item_by_name = {}
        self._entry_by_name = {}
        self.current_order = []
        self.current_path = self._restore_server_workspace()
        self.update_path_label()
        self._update_connection_label()
        self._update_discord_presence()
        self.show_toast(self.T["ssh_connected"], "fa6s.plug-circle-check", "#53d18b")
        self.load_folder(self.current_path)
        return True

    def _launch_profile_window(self, profile_name: str):
        profile_name = (profile_name or "").strip()
        if not profile_name:
            return
        if getattr(sys, "frozen", False):
            command = [sys.executable, "--profile", profile_name]
            workdir = os.path.dirname(sys.executable)
        else:
            command = [sys.executable, os.path.abspath(__file__), "--profile", profile_name]
            workdir = os.path.dirname(os.path.abspath(__file__))
        kwargs = {"cwd": workdir}
        if sys.platform.startswith("win"):
            kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            subprocess.Popen(command, **kwargs)
            self.show_toast(f"Opening {profile_name} in a new Xyra window…")
        except Exception as exc:
            QMessageBox.warning(self, "Open profile", str(exc))

    def _setup_backend(self, initial: bool = False):
        use_ssh = (self.cfg.get("connection_mode") == "ssh" and self.cfg.get("ssh_host") and self.cfg.get("ssh_username"))
        if use_ssh:
            backend = self._create_ssh_backend()
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
        self._update_discord_presence()

    def show_ssh_login_dialog(self):
        dlg = SSHLoginDialog(self.cfg, self)
        accepted = dlg.exec() == QDialog.DialogCode.Accepted
        self._rebuild_server_tabs()
        if not accepted:
            self._update_connection_label()
            return False

        data = dlg.get_data()
        already_connected = self._backend_is_connected()
        active_identity = getattr(self, "_active_server_id", "")
        if already_connected and profile_identity(data) == active_identity:
            self.cfg.update(data)
            save_config(self.cfg)
            self._select_connected_server_session(data, force_new=True)
            self._update_connection_label()
            self.show_toast(
                f"Opened {profile_display_name(data)} in a new tab",
                "fa6s.clone",
                profile_accent(data),
            )
            return True

        backend = self._create_ssh_backend(data)
        try:
            backend.connect()
        except Exception as e:
            QMessageBox.warning(self, self.T["ssh_connect_failed"], str(e))
            return False

        if not self._activate_connected_backend(backend, data):
            return False
        self._select_connected_server_session(
            data,
            force_new=already_connected,
            capture_current=False,
        )
        return True

    def connect_ssh_profile(self, profile: dict) -> bool:
        data = dict(profile or {})
        if not data:
            return False
        if not (data.get("ssh_host") or "").strip() or not (data.get("ssh_username") or "").strip():
            QMessageBox.warning(self, self.T["ssh_connect_failed"], "This saved profile is missing SSH host or username. Please edit and save it again.")
            return False

        if (
            self._backend_is_connected()
            and profile_identity(data) == getattr(self, "_active_server_id", "")
        ):
            return True

        connection_data = dict(data)
        connection_data["ssh_profile_name"] = data.get("profile_name", "")
        connection_data["ssh_profiles"] = self.cfg.get("ssh_profiles", [])
        backend = self._create_ssh_backend(connection_data)
        try:
            backend.connect()
        except Exception as e:
            QMessageBox.warning(self, self.T["ssh_connect_failed"], str(e))
            return False

        return self._activate_connected_backend(backend, connection_data)

    def disconnect_ssh(self):
        self._capture_active_server_tab_state()
        self._save_current_server_workspace()
        if isinstance(self.backend, SshRemoteBackend):
            self.transfer_queue.cancel_all()
            self.backend.disconnect()
        self.cfg["connection_mode"] = "none"
        save_config(self.cfg)
        self.backend = None
        collapsed_by_identity = {}
        for session in self._server_tab_sessions:
            identity = profile_identity(session["profile"])
            if identity in self._dismissed_server_identities:
                continue
            existing = collapsed_by_identity.get(identity)
            if existing is None or session.get("session_id") == self._active_server_session_id:
                collapsed_by_identity[identity] = session
        self._server_tab_sessions = list(collapsed_by_identity.values())
        self._active_server_session_id = None
        self._update_connection_label()
        self._update_discord_presence()
        self.show_toast(self.T["ssh_disconnected"], "fa6s.plug-circle-xmark", "#f4c76b")
        self.refresh_session()

    def _require_backend(self) -> SshRemoteBackend:
        backend = self.backend
        if backend is None:
            raise RuntimeError(self.DISCONNECTED_MESSAGE)
        return backend

    def _reconnect_backend(self, backend: SshRemoteBackend, observed_generation: int) -> bool:
        with self._reconnect_lock:
            if backend is not self.backend:
                return False
            if backend.connection_generation != observed_generation and backend.is_connected():
                return True

            self.connection_state_changed.emit("reconnecting", backend.describe())
            last_error = ""
            for delay in (0.0, 0.4, 1.0):
                if backend is not self.backend:
                    return False
                if delay:
                    time.sleep(delay)
                try:
                    backend.connect(allow_host_key_prompt=False)
                    self.connection_state_changed.emit("connected", backend.describe())
                    return True
                except Exception as exc:
                    last_error = str(exc)

            self.connection_state_changed.emit("offline", last_error)
            return False

    def _schedule_backend_reconnect(self, backend: SshRemoteBackend, observed_generation: int):
        threading.Thread(
            target=self._reconnect_backend,
            args=(backend, observed_generation),
            name="xyra-ssh-reconnect",
            daemon=True,
        ).start()

    def _backend_read_call(self, operation, *, backend: SshRemoteBackend | None = None):
        active = backend or self._require_backend()
        observed_generation = active.connection_generation
        try:
            with getattr(active, "operation_lock", nullcontext()):
                return operation(active)
        except Exception as exc:
            if not active.is_connection_error(exc):
                raise

            if QThread.currentThread() == self.thread():
                self._schedule_backend_reconnect(active, observed_generation)
                raise RuntimeError(
                    "The SSH connection was interrupted. Xyra is reconnecting; try again shortly."
                ) from exc

            if not self._reconnect_backend(active, observed_generation):
                raise RuntimeError("The SSH connection was lost and could not be restored.") from exc
            try:
                with getattr(active, "operation_lock", nullcontext()):
                    return operation(active)
            except Exception as retry_error:
                if active.is_connection_error(retry_error):
                    self.connection_state_changed.emit("offline", str(retry_error))
                raise

    def _backend_write_call(self, operation):
        active = self._require_backend()
        observed_generation = active.connection_generation
        try:
            with getattr(active, "operation_lock", nullcontext()):
                return operation(active)
        except Exception as exc:
            if not active.is_connection_error(exc):
                raise
            if QThread.currentThread() == self.thread():
                self._schedule_backend_reconnect(active, observed_generation)
            else:
                self._reconnect_backend(active, observed_generation)
            raise RuntimeError(
                "The SSH connection was interrupted. For safety, Xyra did not retry this change automatically."
            ) from exc

    def _backend_list_dir(self, path: str):
        return self._backend_read_call(lambda backend: backend.list_dir(path))

    def _backend_read_bytes(self, remote_path: str) -> bytes:
        return self._backend_read_call(lambda backend: backend.read_bytes(remote_path))

    def _backend_write_text(self, remote_path: str, content: str):
        self._backend_write_call(lambda backend: backend.write_text(remote_path, content))

    def _backend_backup_file(self, remote_path: str):
        return self._backend_write_call(lambda backend: backend.backup_file(remote_path))

    def _backend_mkdir(self, remote_path: str):
        self._backend_write_call(lambda backend: backend.mkdir(remote_path))

    def _backend_delete(self, remote_path: str):
        self._backend_write_call(lambda backend: backend.delete_path(remote_path))

    def _backend_trash(self, remote_path: str):
        return self._backend_write_call(lambda backend: backend.trash_path(remote_path))

    def _backend_list_trash(self):
        return self._backend_read_call(lambda backend: backend.list_trash_items())

    def _backend_restore_trash(self, trash_path: str, original_path: str, *, overwrite: bool = False):
        self._backend_write_call(
            lambda backend: backend.restore_trash_item(trash_path, original_path, overwrite=True)
            if overwrite else backend.restore_trash_item(trash_path, original_path)
        )

    def _backend_delete_trash(self, trash_path: str):
        self._backend_write_call(lambda backend: backend.delete_trash_item(trash_path))

    def _backend_empty_trash(self):
        self._backend_write_call(lambda backend: backend.empty_trash())

    def _backend_rename(self, old_path: str, new_path: str, *, overwrite: bool = False):
        self._backend_write_call(
            lambda backend: backend.rename(old_path, new_path, overwrite=True)
            if overwrite else backend.rename(old_path, new_path)
        )

    def _backend_upload_file(self, local_path: str, remote_dir: str):
        self._backend_write_call(lambda backend: backend.upload_file(local_path, remote_dir))

    def _backend_upload_path(self, local_path: str, remote_dir: str):
        self._backend_write_call(lambda backend: backend.upload_path(local_path, remote_dir))

    def _backend_upload_path_with_options(self, local_path: str, remote_dir: str, *, overwrite: bool = False, progress_callback=None, cancel_callback=None):
        self._backend_write_call(lambda backend: backend.upload_path(remote_dir=remote_dir, local_path=local_path, overwrite=overwrite, progress_callback=progress_callback, cancel_callback=cancel_callback))

    def _backend_download_file(self, remote_path: str, local_path: str, *, overwrite: bool = False, progress_callback=None, cancel_callback=None):
        return self._backend_read_call(
            lambda backend: backend.download_file(
                remote_path, local_path, overwrite=True,
                progress_callback=progress_callback, cancel_callback=cancel_callback,
            ) if overwrite else backend.download_file(
                remote_path, local_path,
                progress_callback=progress_callback, cancel_callback=cancel_callback,
            )
        )

    def _backend_copy(self, source_path: str, dest_path: str, *, overwrite: bool = False):
        self._backend_write_call(
            lambda backend: backend.copy_path(source_path, dest_path, overwrite=True)
            if overwrite else backend.copy_path(source_path, dest_path)
        )

    def _backend_move(self, source_path: str, dest_path: str, *, overwrite: bool = False):
        self._backend_write_call(
            lambda backend: backend.move_path(source_path, dest_path, overwrite=True)
            if overwrite else backend.move_path(source_path, dest_path)
        )

    def _backend_extract_archive(self, archive_path: str, dest_dir: str):
        self._backend_write_call(lambda backend: backend.extract_archive(archive_path, dest_dir))

    def _backend_compress_zip(self, source_path: str, archive_path: str):
        self._backend_write_call(lambda backend: backend.compress_to_zip(source_path, archive_path))

    def _backend_get_path_info(self, remote_path: str):
        return self._backend_read_call(lambda backend: backend.get_path_info(remote_path))

    def _backend_chmod(self, remote_path: str, mode_text: str):
        self._backend_write_call(lambda backend: backend.chmod_path(remote_path, mode_text))

    def _backend_change_permissions(
        self,
        remote_path: str,
        mode_text: str,
        *,
        owner: str = "",
        group: str = "",
        recursive: bool = False,
        file_mode_text: str = "",
    ):
        return self._backend_write_call(
            lambda backend: backend.change_permissions(
                remote_path,
                mode_text,
                owner=owner,
                group=group,
                recursive=recursive,
                file_mode_text=file_mode_text,
            )
        )

    def _backend_compute_checksums(self, remote_path: str):
        return self._backend_read_call(lambda backend: backend.compute_checksums(remote_path))

    def _backend_search_files(self, start_path: str, query: str, max_depth: int, cancel_callback=None):
        return self._backend_read_call(lambda backend: backend.search_files(start_path, query, max_depth=max_depth, cancel_callback=cancel_callback))

    def _backend_path_info_or_none(self, remote_path: str):
        try:
            return self._backend_get_path_info(remote_path)
        except FileNotFoundError:
            return None
        except OSError as exc:
            if getattr(exc, "errno", None) == 2 or "no such file" in str(exc).lower():
                return None
            raise

    def _backend_server_health(self):
        return self._backend_read_call(lambda backend: backend.get_server_health(self.current_path))


    # ---------------- Drag & Drop Upload (FIXED) ----------------

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
            tool_name = "PuTTY" if tool == "putty" else "Termius"
            QMessageBox.warning(
                self,
                "Launch",
                self.T["launch_failed"].format(tool=tool_name, tool_name=tool_name),
            )

    # ---------------- icons ----------------

    # ---------------- context menu: rename/delete/download ----------------

    # ---------------- inline rename ----------------

    # ---------------- navigation ----------------
    def go_back(self):
        if not self._can_change_path():
            return
        if self.history:
            self.load_folder(self.history[-1], navigation_mode="back")

    def go_forward(self):
        if not self._can_change_path():
            return
        if self.future:
            self.load_folder(self.future[-1], navigation_mode="forward")

    # ---------------- UI helpers ----------------
    def change_background(self):
        fname, _ = QFileDialog.getOpenFileName(
            self, self.T["choose_bg"], os.path.expanduser("~"),
            "Images (*.png *.jpg *.jpeg *.png *.gif *.webp *.bmp *.ico)"
        )
        if not fname:
            return

        self.bg_path = fname
        self.cfg["background"] = self.bg_path
        save_config(self.cfg)

        self._update_background_pixmap()
        self.view.viewport().update()

    @staticmethod
    def _centered_window_rect(available: QRect, saved_size) -> QRect:
        try:
            saved_width = int(saved_size[0])
            saved_height = int(saved_size[1])
        except (TypeError, ValueError, IndexError):
            saved_width = 1600
            saved_height = 900

        max_width = max(320, available.width() - 64)
        max_height = max(280, available.height() - 64)
        min_width = min(900, max_width)
        min_height = min(600, max_height)
        width = max(min_width, min(saved_width, max_width))
        height = max(min_height, min(saved_height, max_height))
        x = available.x() + (available.width() - width) // 2
        y = available.y() + (available.height() - height) // 2
        return QRect(x, y, width, height)

    def _apply_initial_window_geometry(self):
        screen = QApplication.primaryScreen() or self.screen()
        if screen is None:
            self.resize(1600, 900)
            return
        target = self._centered_window_rect(
            screen.availableGeometry(),
            self.cfg.get("window_size"),
        )
        self.resize(target.size())
        self.move(target.topLeft())

    def _enable_window_geometry_saving(self):
        self._window_geometry_ready = True

    def resizeEvent(self, a0: QResizeEvent | None):
        super().resizeEvent(a0)

        # Resizing can produce dozens of events per second. Keep the lightweight
        # overlays responsive and defer expensive scaling/layout/disk work until
        # the user pauses dragging the window edge.
        self._background_resize_timer.start()

        if self.drop_overlay.isVisible():
            self.drop_overlay.setGeometry(self.view.viewport().rect())
        if self.upload_overlay.isVisible():
            if self.search_cancel_button.isVisible():
                lines = self.upload_overlay.text().split("\n", 1)
                self._show_search_overlay(lines[0], lines[1] if len(lines) > 1 else "")
            else:
                self._show_upload_overlay(self.upload_overlay.text())

        self._reposition_path_badge()
        self._reposition_version_badge()
        self._reposition_taskbar()
        self._update_responsive_toolbar()
        if self.center_message.isVisible():
            self._show_center_message(self._center_message_source)

        if (
            self._window_geometry_ready
            and self.isVisible()
            and not self.isMaximized()
            and not self.isFullScreen()
            and not self.isMinimized()
        ):
            self._window_size_save_timer.start()

        self._relayout_timer.start()

    def _save_window_size(self):
        try:
            if not self._window_geometry_ready:
                return
            if not self.isMaximized() and not self.isFullScreen() and not self.isMinimized():
                size = self.size()
                if size.width() >= 200 and size.height() >= 200:
                    self.cfg["window_size"] = [int(size.width()), int(size.height())]
            save_config(self.cfg)
        except Exception:
            pass

    def keyPressEvent(self, a0: QKeyEvent | None):
        if a0 is None:
            return
        event = a0
        selected_name = self._primary_selected_name()

        if event.matches(QKeySequence.StandardKey.SelectAll):
            self._select_all_icons()
        elif event.key() == Qt.Key.Key_F11:
            self.toggle_fullscreen()
        elif event.key() == Qt.Key.Key_Escape and self.isFullScreen():
            self.toggle_fullscreen()
        elif event.key() == Qt.Key.Key_Escape and self.selected_names:
            self._clear_icon_selection()
        elif event.key() == Qt.Key.Key_Return or event.key() == Qt.Key.Key_Enter:
            if selected_name:
                item = self.item_by_name.get(selected_name)
                if item:
                    self.icon_double_clicked_by_name(selected_name, item.is_dir, False)
            else:
                super().keyPressEvent(event)
        elif event.key() == Qt.Key.Key_F2:
            if selected_name:
                self._start_inline_rename(selected_name)
            else:
                super().keyPressEvent(event)
        elif event.key() == Qt.Key.Key_Delete:
            if self.selected_names:
                permanent = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
                self._delete_selected_items(permanent=permanent)
            else:
                super().keyPressEvent(event)
        elif event.key() == Qt.Key.Key_Escape:
            self.go_back()
        elif self._handle_type_select_key(event):
            return
        else:
            super().keyPressEvent(event)

    def closeEvent(self, a0: QCloseEvent | None):
        if self._exit_shutdown_done:
            super().closeEvent(a0)
            return
        self._exit_shutdown_done = True
        self._folder_load_generation += 1
        self._capture_active_server_tab_state()
        self._save_current_server_workspace()
        self._save_window_size()
        self.transfer_queue.shutdown()
        backend = self.backend
        self.backend = None
        self.cfg["connection_mode"] = "none"
        save_config(self.cfg)
        if backend is not None:
            try:
                backend.disconnect()
            except Exception:
                pass
        try:
            self.discord_rpc.close()
        except Exception:
            pass
        super().closeEvent(a0)


# ------------------- Run -------------------
if __name__ == "__main__":
    app = create_application(sys.argv)
    launch_profile = ""
    if "--profile" in sys.argv:
        try:
            launch_profile = sys.argv[sys.argv.index("--profile") + 1]
        except (IndexError, ValueError):
            launch_profile = ""
    window = RemoteDesktop(launch_profile_name=launch_profile)
    window.show()
    sys.exit(app.exec())
