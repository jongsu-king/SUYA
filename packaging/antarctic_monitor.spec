# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller build. Run from the repository root:  pyinstaller packaging/antarctic_monitor.spec"""

import sys
from pathlib import Path

ROOT = Path(SPECPATH).resolve().parent
ICONS = ROOT / "packaging" / "icons"
APP_NAME = "SUYA"
EXE_NAME = "suya" if sys.platform != "win32" else "SUYA"
icon = {
    "win32": ICONS / "icon.ico",
    "darwin": ICONS / "icon.icns",
}.get(sys.platform, ICONS / "icon.png")

block_cipher = None

a = Analysis(
    [str(ROOT / "packaging" / "entry.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=[(str(ROOT / "antarctic_monitor" / "data"), "antarctic_monitor/data")],
    hiddenimports=[
        "antarctic_monitor.collectors.argo",
        "antarctic_monitor.collectors.erddap",
        "antarctic_monitor.collectors.gosud",
        "antarctic_monitor.collectors.hycom",
        "antarctic_monitor.collectors.metar",
        "antarctic_monitor.collectors.openmeteo",
        "antarctic_monitor.collectors.windy",
        "antarctic_monitor.collectors.woa",
        "matplotlib.backends.backend_qtagg",
        "xlsxwriter",
    ],
    hookspath=[],
    hooksconfig={"matplotlib": {"backends": ["QtAgg", "Agg"]}},
    runtime_hooks=[],
    excludes=[
        "tkinter", "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtQml", "PySide6.QtQuick",
        "PySide6.Qt3DCore", "PySide6.QtMultimedia", "PySide6.QtCharts", "PySide6.QtDataVisualization",
        "PySide6.QtPdf", "PySide6.QtBluetooth", "PySide6.QtNfc", "PySide6.QtRemoteObjects", "PySide6.QtSensors",
        "PySide6.QtSerialPort", "PySide6.QtTest", "PySide6.QtWebSockets", "PySide6.QtWebChannel", "PySide6.QtDesigner",
        "PySide6.QtHelp", "PySide6.QtUiTools", "PySide6.QtXml", "PySide6.QtSql", "PySide6.QtPositioning",
        "PySide6.QtLocation", "PySide6.QtTextToSpeech", "PySide6.QtSpatialAudio", "PySide6.QtQuick3D",
        "pytest", "openpyxl", "IPython",
    ],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=EXE_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(icon) if icon.exists() else None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name=EXE_NAME,
)

if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name=f"{APP_NAME}.app",
        icon=str(icon) if icon.exists() else None,
        bundle_identifier="io.github.jongsu-king.suya",
        info_plist={
            "CFBundleDisplayName": APP_NAME,
            "CFBundleShortVersionString": "0.1.0",
            "CFBundleVersion": "0.1.0",
            "NSHighResolutionCapable": True,
            "NSHumanReadableCopyright": "Copyright © 2026 Jongsu Lim and Suyeon Park. MIT License.",
            "LSMinimumSystemVersion": "12.0",
        },
    )
