import os
import sys


PACKAGE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(PACKAGE_DIR)
RESOURCE_DIR = getattr(sys, "_MEIPASS", PROJECT_ROOT)
USER_DATA_DIR = os.path.join(os.getenv("APPDATA") or os.path.expanduser("~"), "Xyra") if getattr(sys, "frozen", False) else PROJECT_ROOT
os.makedirs(USER_DATA_DIR, exist_ok=True)
SECURE_DATA_DIR = os.path.join(os.getenv("APPDATA") or os.path.expanduser("~"), "Xyra")
os.makedirs(SECURE_DATA_DIR, exist_ok=True)


def resource_path(*parts):
    return os.path.join(RESOURCE_DIR, *parts)


def data_path(*parts):
    return os.path.join(USER_DATA_DIR, *parts)

APP_NAME = "Xyra"
APP_VERSION = "Xyra Core 1.7.3"
APP_WEBSITE = "[SOON...]"
APP_REPOSITORY_URL = "https://github.com/mambuzrrr/Xyra-Core"
UPDATE_MANIFEST_URLS = {
    "stable": "https://raw.githubusercontent.com/mambuzrrr/Xyra-Core/main/updates/stable.json",
    "prerelease": "https://raw.githubusercontent.com/mambuzrrr/Xyra-Core/main/updates/prerelease.json",
}
APP_DEVELOPER = "Brejax (Rico)"
APP_CONTRIBUTORS = "-"
DISCORD_APP_ID = "1294445522811097189"
DISCORD_LARGE_IMAGE_KEY = "xyra_512x512"
DISCORD_SMALL_IMAGE_KEY = "linux_mascott"
APP_LOGO_PATH = resource_path("assets", "xyra_512x512.png")
APP_ICON_PATH = resource_path("assets", "xyra.ico")

CONFIG_FILE = data_path("config.json")
GUI_CONFIG_FILE = data_path("gui.ini")
ICONS_POS_FILE = data_path("icons_pos.json")
STATE_DB_FILE = data_path("xyra_state.db")
KNOWN_HOSTS_FILE = os.path.join(SECURE_DATA_DIR, "known_hosts")

TEXT_EXTS = {".txt",".log",".dat",".md",".rst",".py",".pyw",".js",".mjs",".cjs",".ts",".tsx",".jsx",".java",".c",".cpp",".h",".hpp",".cs",".go",".rs",".rb",".php",".swift",".kt",".kts",".scala",".dart",".lua",".sh",".bat",".ps1",".html",".htm",".xhtml",".css",".scss",".sass",".less",".xml",".svg",".json",".jsonc",".yaml",".yml",".ini",".cfg",".conf",".toml",".env",".properties",".lock",".gitignore",".gitattributes",".editorconfig",".csv",".tsv",".tex",".bib",".rtf",".gradle",".cmake",".make",".mk",".dockerfile",".dockerignore",".arena",".menu",".shader",".script",".gsc",".nfo",".srt",".vtt",".mod"}

DANGEROUS_OPEN_EXTS = {
    ".appref-ms", ".application", ".appx", ".appxbundle", ".chm", ".cmd",
    ".com", ".cpl", ".diagcab", ".dll", ".exe", ".gadget", ".hta",
    ".inf", ".ins", ".iso", ".jar", ".jnlp", ".js", ".jse", ".lnk",
    ".msc", ".msi", ".msp", ".msu", ".pif", ".ps1", ".ps1xml",
    ".ps2", ".ps2xml", ".psc1", ".psc2", ".reg", ".scf", ".scr",
    ".sct", ".shb", ".sys", ".url", ".vb", ".vbe", ".vbs", ".ws",
    ".wsc", ".wsf", ".wsh",
}

ICON_RENDER_SIZE = 50
BOX_W = 124
BOX_H = 108
TEXT_TOP_GAP = 7
