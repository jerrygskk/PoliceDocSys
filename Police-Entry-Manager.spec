# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['standalone_main.py'],
    pathex=[],
    binaries=[],
    datas=[('layouts/*.ui', 'layouts'), ('res/buttons/police_badge.svg', 'res/buttons'), ('res/buttons/banner.png', 'res/buttons')],
    hiddenimports=['PySide6.QtPrintSupport', 'lib.db_utils', 'lib.base_tab', 'lib.auth_manager', 'lib.app_lock', 'lib.db_backup', 'lib.db_schema', 'lib.theme', 'lib.loading_screen', 'lib.version', 'lib.archive_text', 'res.resources_rc'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['matplotlib.backends.backend_cairo', 'matplotlib.backends.backend_gtk3', 'matplotlib.backends.backend_gtk3agg', 'matplotlib.backends.backend_gtk3cairo', 'matplotlib.backends.backend_gtk4', 'matplotlib.backends.backend_gtk4agg', 'matplotlib.backends.backend_gtk4cairo', 'matplotlib.backends.backend_macosx', 'matplotlib.backends.backend_nbagg', 'matplotlib.backends.backend_pgf', 'matplotlib.backends.backend_ps', 'matplotlib.backends.backend_qt', 'matplotlib.backends.backend_qt5', 'matplotlib.backends.backend_qt5agg', 'matplotlib.backends.backend_qt5cairo', 'matplotlib.backends.backend_qtagg', 'matplotlib.backends.backend_qtcairo', 'matplotlib.backends.backend_svg', 'matplotlib.backends.backend_template', 'matplotlib.backends.backend_tkagg', 'matplotlib.backends.backend_tkcairo', 'matplotlib.backends.backend_webagg', 'matplotlib.backends.backend_webagg_core', 'matplotlib.backends.backend_wx', 'matplotlib.backends.backend_wxagg', 'matplotlib.backends.backend_wxcairo', 'tkinter'],
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
    name='Police-Entry-Manager',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
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
