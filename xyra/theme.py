"""Visual language for Xyra's desktop shell."""

BACKGROUND = "#0d0d0f"
SURFACE = "#141416"
SURFACE_RAISED = "#1c1c1f"
BORDER = "#303034"
TEXT = "#f3f1ed"
TEXT_MUTED = "#999793"
ACCENT = "#d8c39a"
ACCENT_SOFT = "#eee2c8"
SUCCESS = "#8bc7a8"
WARNING = "#dfb86d"
DANGER = "#e58f98"


APPLICATION_STYLE = f"""
    QWidget {{
        color: {TEXT};
        font-family: "Segoe UI";
        font-size: 10pt;
    }}
    QDialog, QMessageBox {{
        background-color: {SURFACE};
    }}
    QDialog QLabel, QMessageBox QLabel {{
        color: {TEXT};
    }}
    QPushButton {{
        color: {TEXT};
        background-color: {SURFACE_RAISED};
        border: 1px solid {BORDER};
        border-radius: 9px;
        min-height: 34px;
        padding: 0 14px;
        font-weight: 600;
    }}
    QPushButton:hover {{
        background-color: #252527;
        border-color: #504e49;
    }}
    QPushButton:pressed {{
        background-color: #111113;
    }}
    QLineEdit, QSpinBox, QComboBox, QPlainTextEdit, QListWidget {{
        color: {TEXT};
        background-color: #101012;
        border: 1px solid {BORDER};
        border-radius: 9px;
        padding: 7px 10px;
        selection-background-color: #6f6047;
    }}
    QLineEdit:focus, QSpinBox:focus, QComboBox:focus, QPlainTextEdit:focus, QListWidget:focus {{
        border-color: {ACCENT};
    }}
    QComboBox::drop-down {{
        width: 30px;
        border: none;
    }}
    QComboBox QAbstractItemView {{
        color: {TEXT};
        background-color: {SURFACE};
        border: 1px solid {BORDER};
        selection-background-color: #302c25;
        outline: none;
    }}
    QMenu {{
        color: {TEXT};
        background-color: #171719;
        border: 1px solid {BORDER};
        border-radius: 10px;
        padding: 7px;
    }}
    QMenu::item {{
        border-radius: 7px;
        margin: 2px;
        padding: 8px 28px 8px 12px;
    }}
    QMenu::item:selected {{
        color: #ffffff;
        background-color: #302c25;
    }}
    QMenu::item:disabled {{
        color: #62605d;
    }}
    QMenu::separator {{
        height: 1px;
        margin: 6px 8px;
        background-color: {BORDER};
    }}
    QToolTip {{
        color: {TEXT};
        background-color: #1a1a1c;
        border: 1px solid #3b3a38;
        border-radius: 7px;
        padding: 6px 9px;
    }}
    QScrollBar:vertical {{
        width: 12px;
        margin: 6px 3px;
        border: none;
        background: transparent;
    }}
    QScrollBar::handle:vertical {{
        min-height: 36px;
        border-radius: 4px;
        background: #3b3a3d;
    }}
    QScrollBar::handle:vertical:hover {{
        background: #5a5854;
    }}
    QScrollBar:horizontal {{
        height: 12px;
        margin: 3px 6px;
        border: none;
        background: transparent;
    }}
    QScrollBar::handle:horizontal {{
        min-width: 36px;
        border-radius: 4px;
        background: #3b3a3d;
    }}
    QScrollBar::handle:horizontal:hover {{
        background: #5a5854;
    }}
    QScrollBar::add-line, QScrollBar::sub-line,
    QScrollBar::add-page, QScrollBar::sub-page {{
        width: 0;
        height: 0;
        background: transparent;
    }}
"""


TOOLBAR_STYLE = f"""
    QToolBar {{
        spacing: 8px;
        padding: 9px 14px;
        background-color: #101012;
        border: none;
        border-bottom: 1px solid #29292c;
    }}
    QToolBar::separator {{
        width: 1px;
        margin: 7px 7px;
        background-color: #2c2c2f;
    }}
    QToolBar QToolButton {{
        color: #dedbd5;
        background-color: #19191c;
        border: 1px solid #2c2c30;
        border-radius: 10px;
        padding: 7px 12px;
        font-weight: 600;
    }}
    QToolBar QToolButton:hover {{
        color: #ffffff;
        background-color: #242426;
        border-color: #54514b;
    }}
    QToolBar QToolButton:pressed {{
        background-color: #121214;
        border-color: {ACCENT};
    }}
    QToolBar QToolButton:disabled {{
        color: #65635f;
        background-color: #151517;
        border-color: #242427;
    }}
    QToolBar QToolButton::menu-indicator {{
        image: none;
        width: 0;
    }}
    QToolBar QLineEdit {{
        color: {TEXT};
        background-color: #111113;
        border: 1px solid #303034;
        border-radius: 10px;
        padding: 8px 12px;
        font-weight: 500;
    }}
    QToolBar QLineEdit:hover {{
        border-color: #4a4844;
    }}
    QToolBar QLineEdit:focus {{
        background-color: #171719;
        border-color: {ACCENT};
    }}
"""


SERVER_BAR_STYLE = f"""
    QToolBar#serverBar {{
        spacing: 8px;
        padding: 5px 14px 6px 14px;
        background-color: #0d0d0f;
        border: none;
        border-bottom: 1px solid #242427;
    }}
    QToolBar#serverBar QLabel#serverBarTitle {{
        color: #77746f;
        background: transparent;
        border: none;
        font-size: 8pt;
        font-weight: 700;
        letter-spacing: 1px;
        padding-right: 5px;
    }}
    QToolBar#serverBar QTabBar {{
        background: transparent;
    }}
    QToolBar#serverBar QTabBar::tab {{
        color: #a8a49e;
        background: transparent;
        border: 1px solid transparent;
        border-radius: 8px;
        min-width: 112px;
        max-width: 220px;
        min-height: 28px;
        margin-right: 5px;
        padding: 2px 10px 2px 14px;
        font-weight: 600;
    }}
    QToolBar#serverBar QTabBar::tab:hover {{
        color: {TEXT};
        background: #19191b;
        border-color: #2c2c2f;
    }}
    QToolBar#serverBar QTabBar::tab:selected {{
        color: #f5f0e7;
        background: #25221d;
        border-color: #655943;
    }}
    QToolBar#serverBar QToolButton {{
        color: #b8b4ad;
        background: #171719;
        border: 1px solid #2d2d30;
        border-radius: 8px;
        padding: 5px;
    }}
    QToolBar#serverBar QToolButton:hover {{
        color: #ffffff;
        background: #242426;
        border-color: #575149;
    }}
    QToolBar#serverBar QToolButton#serverTabCloseButton {{
        color: #77736d;
        background: transparent;
        border: none;
        border-radius: 4px;
        padding: 0;
        margin: 0;
        font-size: 10pt;
        font-weight: 600;
    }}
    QToolBar#serverBar QToolButton#serverTabCloseButton:hover {{
        color: #f0c5c0;
        background: #3b292b;
        border: none;
    }}
    QToolBar#serverBar QToolButton#serverTabCloseButton:pressed {{
        color: #ffffff;
        background: #512f32;
        border: none;
    }}
"""


TASKBAR_STYLE = f"""
    QWidget#xyraTaskbar {{
        background-color: rgba(20, 20, 22, 246);
        border: 1px solid #353538;
        border-radius: 18px;
    }}
    QWidget#xyraTaskbar QLabel {{
        color: #dedbd5;
        background: transparent;
    }}
    QWidget#xyraTaskbar QToolButton {{
        color: #dedbd5;
        background-color: #1c1c1f;
        border: 1px solid #303034;
        border-radius: 11px;
        padding: 7px 12px;
        font-weight: 600;
    }}
    QWidget#xyraTaskbar QToolButton:hover {{
        color: #ffffff;
        background-color: #29292c;
        border-color: #57534d;
    }}
    QWidget#xyraTaskbar QToolButton:pressed {{
        background-color: #141416;
        border-color: {ACCENT};
    }}
"""


CENTER_MESSAGE_STYLE = f"""
    QLabel {{
        color: {TEXT};
        background-color: rgba(21, 21, 23, 248);
        border: 1px solid #39383a;
        border-radius: 18px;
        padding: 26px 30px;
    }}
"""

OVERLAY_STYLE = f"""
    QLabel {{
        color: {TEXT};
        background-color: rgba(20, 20, 22, 248);
        border: 1px solid #413f3b;
        border-radius: 16px;
        padding: 18px 24px;
        font-size: 12pt;
        font-weight: 600;
    }}
"""

TOAST_STYLE = f"""
    QWidget {{
        background-color: rgba(24, 24, 26, 252);
        border: 1px solid #403e3a;
        border-radius: 12px;
    }}
    QLabel {{
        color: {TEXT};
        background: transparent;
        border: none;
    }}
"""

CONNECTED_PILL_STYLE = f"""
    QLabel {{
        color: {SUCCESS};
        background-color: #18241f;
        border: 1px solid #344f42;
        border-radius: 10px;
        padding: 7px 12px;
        font-weight: 700;
    }}
"""

OFFLINE_PILL_STYLE = f"""
    QLabel {{
        color: {TEXT_MUTED};
        background-color: #1a1a1c;
        border: 1px solid #343438;
        border-radius: 10px;
        padding: 7px 12px;
        font-weight: 650;
    }}
"""
