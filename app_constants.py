import os
import sys


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
RESOURCE_DIR = getattr(sys, "_MEIPASS", BASE_DIR)
USER_DATA_DIR = os.path.join(os.getenv("APPDATA") or os.path.expanduser("~"), "Xyra") if getattr(sys, "frozen", False) else BASE_DIR
os.makedirs(USER_DATA_DIR, exist_ok=True)


def resource_path(*parts):
    return os.path.join(RESOURCE_DIR, *parts)


def data_path(*parts):
    return os.path.join(USER_DATA_DIR, *parts)

APP_NAME = "Xyra"
APP_VERSION = "Xyra Core beta-v1.4"
APP_WEBSITE = "[SOON...]"
APP_DEVELOPER = "Brejax (Rico)"
APP_CONTRIBUTORS = "-"
APP_LOGO_PATH = resource_path("assets", "xyra_logo.png")
APP_ICON_PATH = resource_path("assets", "app.ico")

CONFIG_FILE = data_path("config.json")
GUI_CONFIG_FILE = data_path("gui.ini")
ICONS_POS_FILE = data_path("icons_pos.json")
STATE_DB_FILE = data_path("xyra_state.db")

TEXT_EXTS = {".txt", ".py", ".js", ".json", ".md", ".html", ".css", ".ini", ".cfg"}

ICON_RENDER_SIZE = 64
BOX_W = 150
BOX_H = 112
TEXT_TOP_GAP = 6
