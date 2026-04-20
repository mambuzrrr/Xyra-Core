# -*- mode: python ; coding: utf-8 -*-

from PyInstaller.utils.hooks import collect_all

qtawesome_datas, qtawesome_binaries, qtawesome_hiddenimports = collect_all("qtawesome")

datas = []
datas += qtawesome_datas
datas += [
    ("assets", "assets"),
    ("icons", "icons"),
]

binaries = []
binaries += qtawesome_binaries

hiddenimports = []
hiddenimports += qtawesome_hiddenimports
hiddenimports += [
    "keyring.backends.Windows",
    "keyring.backends.fail",
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
    upx=True,
    upx_exclude=[],
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=["assets/app.ico"],
    onefile=True,
)
