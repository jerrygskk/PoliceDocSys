# -*- mode: python ; coding: utf-8 -*-
"""完整版打包設定。排除清單的說明見 tools/pyi_prune.py 與 DEVELOPER.md §7。"""

import os
import sys

sys.path.insert(0, os.path.join(SPECPATH, 'tools'))
from pyi_prune import prune, force_qt_binaries


a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=force_qt_binaries(),
    datas=[('layouts/*.ui', 'layouts'), ('res/buttons/police_badge.svg', 'res/buttons'), ('res/buttons/banner.png', 'res/buttons')],
    hiddenimports=['PySide6.QtPrintSupport', 'lib.db_utils', 'lib.base_tab', 'lib.auth_manager', 'lib.app_lock', 'lib.db_backup', 'lib.db_schema', 'lib.theme', 'lib.loading_screen', 'lib.version', 'lib.archive_text', 'res.resources_rc', 'tabs.tab_dispatch', 'tabs.tab_receive', 'tabs.tab_report', 'tabs.tab_reward', 'tabs.tab_reward_issue', 'tabs.tab_ticket', 'tabs.tab_print', 'tabs.tab_dbbrowse', 'tabs.tab_archive', 'tabs.tab_settings', 'tabs.tab_audit'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['matplotlib.backends.backend_cairo', 'matplotlib.backends.backend_gtk3', 'matplotlib.backends.backend_gtk3agg', 'matplotlib.backends.backend_gtk3cairo', 'matplotlib.backends.backend_gtk4', 'matplotlib.backends.backend_gtk4agg', 'matplotlib.backends.backend_gtk4cairo', 'matplotlib.backends.backend_macosx', 'matplotlib.backends.backend_nbagg', 'matplotlib.backends.backend_pgf', 'matplotlib.backends.backend_ps', 'matplotlib.backends.backend_qt', 'matplotlib.backends.backend_qt5', 'matplotlib.backends.backend_qt5agg', 'matplotlib.backends.backend_qt5cairo', 'matplotlib.backends.backend_qtagg', 'matplotlib.backends.backend_qtcairo', 'matplotlib.backends.backend_svg', 'matplotlib.backends.backend_template', 'matplotlib.backends.backend_tkagg', 'matplotlib.backends.backend_tkcairo', 'matplotlib.backends.backend_webagg', 'matplotlib.backends.backend_webagg_core', 'matplotlib.backends.backend_wx', 'matplotlib.backends.backend_wxagg', 'matplotlib.backends.backend_wxcairo', 'tkinter',
             # 純 QWidget 程式，從未 import QtQuick／QML／OpenGL
             'PySide6.QtQuick', 'PySide6.QtQuickWidgets', 'PySide6.QtQml',
             'PySide6.QtOpenGL', 'PySide6.QtOpenGLWidgets',
             # AVIF 影像格式支援（_avif.pyd 未壓縮 7.5MB，比 PIL 核心的 _imaging 還大）。
             # 本專案影像只有 PNG／SVG，用不到；PIL 的外掛載入本來就允許缺席——
             # AvifImagePlugin 自己 try/except 後設 SUPPORTED=False，Image.init() 也
             # 對每個外掛 import 包 try/except ImportError，缺了不會炸。
             'PIL._avif'],
    # ⚠️ PIL 整包不可排除：matplotlib/colors.py 在 module 層就 from PIL import Image，
    #    排掉會在載入列印頁時 ModuleNotFoundError（踩過）
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
    name='Police-Document-Manager',
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
    version='version_info.txt',
    icon=['res\\buttons\\police_badge.ico'],
)
