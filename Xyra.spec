# -*- mode: python ; coding: utf-8 -*-

from PyInstaller.utils.hooks import collect_all

qtawesome_datas, qtawesome_binaries, qtawesome_hiddenimports = collect_all("qtawesome")

datas = []
datas += qtawesome_datas
datas += [
    ("assets", "assets"),
]

binaries = []
binaries += qtawesome_binaries

hiddenimports = []
hiddenimports += qtawesome_hiddenimports
hiddenimports += [
    "keyring.backends.Windows",
    "keyring.backends.fail",
    "pypresence",
]

a = Analysis(
    ["Dashboard.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    name="Xyra",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    # UPX-packed executables trigger more heuristic antivirus detections and
    # make release output harder to reproduce and inspect.
    upx=False,
    upx_exclude=[],
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=["assets/xyra.ico"],
    version="version_info.txt",
    manifest="app.manifest",
    onefile=True,
)
