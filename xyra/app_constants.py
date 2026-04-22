import os
import sys


PACKAGE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(PACKAGE_DIR)
RESOURCE_DIR = getattr(sys, "_MEIPASS", PROJECT_ROOT)
USER_DATA_DIR = os.path.join(os.getenv("APPDATA") or os.path.expanduser("~"), "Xyra") if getattr(sys, "frozen", False) else PROJECT_ROOT
os.makedirs(USER_DATA_DIR, exist_ok=True)


def resource_path(*parts):
    return os.path.join(RESOURCE_DIR, *parts)


def data_path(*parts):
    return os.path.join(USER_DATA_DIR, *parts)

APP_NAME = "Xyra"
APP_VERSION = "Xyra Core 1.6"
APP_WEBSITE = "[SOON...]"
APP_DEVELOPER = "Brejax (Rico)"
APP_CONTRIBUTORS = "-"
APP_LOGO_PATH = resource_path("assets", "xyra_512x512.png")
APP_ICON_PATH = resource_path("assets", "xyra.ico")

CONFIG_FILE = data_path("config.json")
GUI_CONFIG_FILE = data_path("gui.ini")
ICONS_POS_FILE = data_path("icons_pos.json")
STATE_DB_FILE = data_path("xyra_state.db")

TEXT_EXTS = {".txt", ".py", ".js", ".json", ".md", ".html", ".css", ".ini", ".cfg"}

ICON_RENDER_SIZE = 48
BOX_W = 158
BOX_H = 122
TEXT_TOP_GAP = 8
