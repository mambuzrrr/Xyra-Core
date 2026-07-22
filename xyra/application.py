"""Qt application setup shared by the source entry point and packaged build."""

import os
import sys

from PyQt6.QtGui import QFont, QIcon
from PyQt6.QtWidgets import QApplication

from xyra.app_constants import APP_ICON_PATH
from xyra.theme import APPLICATION_STYLE


def _set_windows_app_id() -> None:
    if not sys.platform.startswith("win"):
        return
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            "Brejax.Xyra.Core"
        )
    except Exception:
        pass


def apply_window_chrome(window) -> None:
    """Use native Windows controls with Xyra's dark caption colors."""
    if not sys.platform.startswith("win"):
        return
    try:
        import ctypes

        hwnd = int(window.winId())
        dark_mode = ctypes.c_int(1)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(
            hwnd, 20, ctypes.byref(dark_mode), ctypes.sizeof(dark_mode)
        )

        def colorref(hex_color: str):
            value = hex_color.lstrip("#")
            red, green, blue = (int(value[index:index + 2], 16) for index in (0, 2, 4))
            return ctypes.c_int(red | (green << 8) | (blue << 16))

        for attribute, color in ((34, "#303034"), (35, "#101012"), (36, "#f3f1ed")):
            value = colorref(color)
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, attribute, ctypes.byref(value), ctypes.sizeof(value)
            )
    except Exception:
        pass


def create_application(argv=None) -> QApplication:
    """Create and consistently configure the single Qt application instance."""
    _set_windows_app_id()
    application = QApplication.instance() or QApplication(argv or sys.argv)

    font = QFont("Segoe UI")
    font.setPointSizeF(10.5)
    application.setFont(font)

    if os.path.exists(APP_ICON_PATH):
        application.setWindowIcon(QIcon(APP_ICON_PATH))

    application.setStyleSheet(APPLICATION_STYLE)
    return application
