# -*- mode: python ; coding: utf-8 -*-

import sys

from PyInstaller.utils.hooks import (
    collect_data_files,
    collect_dynamic_libs,
    collect_submodules,
)

# Web Terminal feature uses pywinpty on Windows. The import lives inside
# PtySession._spawn_windows (deferred), so PyInstaller's static analysis
# may miss the C++ winpty.dll / winpty-agent.exe assets the package
# ships with. Force-collect them on Windows builds; on POSIX the import
# never executes and the helpers safely return empty lists.
_winpty_binaries = []
_winpty_datas = []
_winpty_hidden = []
if sys.platform == "win32":
    _winpty_binaries = collect_dynamic_libs("winpty")
    _winpty_datas = collect_data_files("winpty")
    _winpty_hidden = ["winpty"] + collect_submodules("winpty")


a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=_winpty_binaries,
    datas=_winpty_datas,
    hiddenimports=_winpty_hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='mcp-workspace-agent',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
