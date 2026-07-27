# -*- mode: python ; coding: utf-8 -*-
"""獨立版（警政快速登錄系統）打包設定。

與完整版的差異：進入點、名稱、版本資訊檔、只收 ENTRY_PROFILE 的四個分頁，
並整包排除 matplotlib／numpy／PIL（獨立版無簽收單列印）。
`ui_utils.rescue_dialog` 也刻意不收：規格禁止獨立版執行資料庫還原，
`main.handleCorruptDb()` 已依 profile 擋住，排除模組是第二層保險。
排除清單的說明見 tools/pyi_prune.py 與 DEVELOPER.md §7。
"""

import os
import sys

sys.path.insert(0, os.path.join(SPECPATH, 'tools'))
from pyi_prune import prune, force_qt_binaries


a = Analysis(
    ['standalone_main.py'],
    pathex=[],
    binaries=force_qt_binaries(),
    datas=[('layouts/*.ui', 'layouts'), ('res/buttons/police_badge.svg', 'res/buttons'), ('res/buttons/reward_ticket_banner.png', 'res/buttons')],
    hiddenimports=['lib.db_utils', 'lib.base_tab', 'lib.auth_manager', 'lib.app_lock', 'lib.db_backup', 'lib.db_schema', 'lib.theme', 'lib.loading_screen', 'lib.version', 'lib.archive_text', 'tabs.tab_reward', 'tabs.tab_ticket', 'tabs.tab_dbbrowse', 'tabs.tab_settings', 'res.resources_rc'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['matplotlib', 'numpy', 'PIL', 'contourpy', 'fontTools', 'kiwisolver', 'cycler', 'dateutil', 'pyparsing', 'tkinter', 'ui_utils.rescue_dialog',
                 # 純 QWidget 程式，從未 import QtQuick／QML／OpenGL
                 'PySide6.QtQuick', 'PySide6.QtQuickWidgets', 'PySide6.QtQml',
                 'PySide6.QtOpenGL', 'PySide6.QtOpenGLWidgets'],
    noarchive=False,
    optimize=0,
)
prune(a)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='Police-Entry-Manager',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,  # 刻意不用 UPX：壓縮後的 exe 容易被防毒誤判，警用單位不宜
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    version='version_info_entry.txt',
    icon=['res\\buttons\\police_badge.ico'],
)
