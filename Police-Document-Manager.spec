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
    hiddenimports=['PySide6.QtPrintSupport', 'lib.db_utils', 'lib.base_tab', 'lib.auth_manager', 'lib.app_lock', 'lib.db_backup', 'lib.db_schema', 'lib.theme', 'lib.loading_screen', 'lib.version', 'lib.archive_text', 'res.resources_rc', 'tabs.tab_dispatch', 'tabs.tab_receive', 'tabs.tab_report', 'tabs.tab_reward', 'tabs.tab_ticket', 'tabs.tab_print', 'tabs.tab_dbbrowse', 'tabs.tab_archive', 'tabs.tab_settings', 'tabs.tab_audit'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # 簽收單列印頁自 v1.2.9 起改用 Qt 原生繪圖（QPainter／QPdfWriter），
    # 產品路徑已無 matplotlib，故整包排除 matplotlib／numpy／PIL 及其相依
    # （未壓縮合計約 72MB，實測 onefile 可省約 25MB）。比照獨立版 spec 的清單。
    # ⚠️ 舊註解「PIL 整包不可排除（matplotlib/colors.py 在 module 層 from PIL
    #    import Image）」已不適用——那條相依隨 matplotlib 一起消失。
    #    matplotlib 仍留在開發環境，是 tools/ 底下比對基準用的（不進打包）。
    #    產品路徑無 matplotlib 由 tools/check_no_matplotlib.py 把關（靜態掃描
    #    ＋執行期攔截雙軌，後者涵蓋全部 tabs／ui_utils）。
    excludes=['matplotlib', 'numpy', 'PIL', 'pylab', 'mpl_toolkits',
             'contourpy', 'fontTools', 'kiwisolver', 'cycler', 'dateutil',
             'pyparsing', 'tkinter',
             # 純 QWidget 程式，從未 import QtQuick／QML／OpenGL
             'PySide6.QtQuick', 'PySide6.QtQuickWidgets', 'PySide6.QtQml',
             'PySide6.QtOpenGL', 'PySide6.QtOpenGLWidgets',
             # 純本機 SQLite 程式，原始碼零網路使用；QtNetwork 綁定層（1.0MB）沒人
             # import，Qt6Network.dll 及其 tls／networkinformation 外掛由 pyi_prune 砍
             'PySide6.QtNetwork'],
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
