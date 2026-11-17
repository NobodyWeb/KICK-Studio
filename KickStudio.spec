# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller build definition for Kick Studio (Windows, one-folder)."""

import os

from PyInstaller.utils.hooks import collect_all

ROOT = os.path.abspath(os.getcwd())

datas = [
    (os.path.join(ROOT, "web"), "web"),
    (os.path.join(ROOT, "assets"), "assets"),
]
binaries = []
hiddenimports = []

# pywebview ships platform backends and assets that are imported dynamically.
for package in ("webview",):
    package_datas, package_binaries, package_hidden = collect_all(package)
    datas += package_datas
    binaries += package_binaries
    hiddenimports += package_hidden

hiddenimports += [
    "clr_loader",
    "pythonnet",
    "webview.platforms.edgechromium",
    "webview.platforms.winforms",
]

a = Analysis(
    ["app.py"],
    pathex=[ROOT],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "PIL"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="KickStudio",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    icon=os.path.join(ROOT, "assets", "icon.ico"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="KickStudio",
)
