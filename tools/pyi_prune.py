# -*- coding: utf-8 -*-
"""PyInstaller 打包瘦身：把 Analysis 收進來、但本專案用不到的 binary／data 剔除。

由兩份 spec（`Police-Document-Manager.spec`／`Police-Entry-Manager.spec`）共用，
避免兩邊各維護一份排除清單而走鐘。spec 內用法：

    import sys, os
    sys.path.insert(0, os.path.join(SPECPATH, "tools"))
    from pyi_prune import prune
    prune(a)

⚠️ `--exclude-module` 只砍得掉 Python 模組，砍不掉 hook 以「binary」身分收進來的
DLL（`opengl32sw.dll`、`.qm` 語系檔等），那些只能在 spec 裡對 `a.binaries`／
`a.datas` 過濾，這支模組就是做這件事的唯一地方。
"""

import os

# 打包機器 PATH 上若有 Git for Windows，PyInstaller 會撿到 mingw64 的 OpenSSL
# （libcrypto-3-x64.dll／libssl-3-x64.dll，未壓縮約 6.5MB）混進來。Python 自己
# 的 libcrypto-3.dll 才是 ssl 模組要用的那份，不受影響。
_BAD_SOURCE_DIRS = (
    r"\program files\git",
    r"\program files (x86)\git",
)

# 純 QWidget 程式用不到的 Qt 模組。QtQuick／QML 從未被 import；
# opengl32sw.dll 是 Qt 的軟體 OpenGL 後備，只有 QtQuick／QOpenGLWidget
# 或無顯示驅動的遠端桌面情境才會用到，本專案（實體桌機＋SMB 共用 DB）不需要。
#
# ⚠️ 這裡刻意**不含** Qt6OpenGL.dll／Qt6OpenGLWidgets.dll：
# `QtUiTools.pyd`（loadUi 的 QUiLoader）→ `Qt6UiTools.dll` → `Qt6OpenGLWidgets.dll`
# → `Qt6OpenGL.dll` 是**連結期**相依，跟程式有沒有用到 OpenGL 無關，砍掉會在
# 開機 import ui_utils 時就 `ImportError: DLL load failed while importing QtUiTools`
# （踩過）。Python 綁定層 `QtOpenGL.pyd`（8.3MB）沒人 import，仍由 excludes 排除。
_DROP_BASENAMES = {
    "opengl32sw.dll",
    "qt6quick.dll",
    "qt6quickwidgets.dll",
    "qt6qml.dll",
    "qt6qmlmodels.dll",
    "qt6qmlmeta.dll",
    "qt6qmlworkerscript.dll",
    "qt6virtualkeyboard.dll",
    # 用不到的影像格式（本專案圖檔只有 PNG／SVG；qjpeg 刻意保留當安全網、
    # qico 保留給視窗圖示，qsvg／qsvgicon 是本專案 icon 的命脈，都不可砍）
    "qtiff.dll",
    "qwebp.dll",
    "qicns.dll",
    "qtga.dll",
    "qwbmp.dll",
    "qgif.dll",
    # PDF：`qpdf.dll` 是「把 PDF 當圖檔讀」的 imageformats plugin，全專案沒人用，
    # 而它是 `Qt6Pdf.dll`（4.6MB）唯一的連結期使用者；Qt6Pdf 又是 Qt6Network 的
    # 使用者之一。兩支一起砍才收得到效果，缺一則另一支仍被留下。
    # ⚠️ 與列印無關：列印走 QPrinter／QPdfWriter（在 Qt6Gui／Qt6PrintSupport 內），
    # 不經 Qt6Pdf.dll——完整版有列印頁，一樣不需要它。
    "qpdf.dll",
    "qt6pdf.dll",
    # 網路：本專案是純本機 SQLite 程式，原始碼零網路使用。逆向查證 Qt6Network 的
    # 連結期使用者只有 Qt6Pdf 與下面幾個 plugin（tls／networkinformation／
    # tuiotouch），全部一起砍才不會留下缺相依。QtNetwork 的 Python 綁定層
    # （QtNetwork.pyd）由兩份 spec 的 excludes 排除。
    "qt6network.dll",
    "qtuiotouchplugin.dll",
    # 備用平台外掛：正式執行一律走 qwindows.dll。qoffscreen 只有離線測試會用，
    # 而測試跑的是原始碼、不是這包 exe。
    "qdirect2d.dll",
    "qoffscreen.dll",
    "qminimal.dll",
}

#: OpenSSL：唯一使用者是 `_hashlib.pyd`（見 `drop_openssl` 說明），預設不砍
_OPENSSL_BASENAMES = {
    "libcrypto-3.dll",
    "libssl-3.dll",
}

# 整個資料夾剔除（dest 路徑前綴，比對時統一小寫 + 正斜線）
_DROP_DEST_PREFIXES = (
    "pyside6/qml/",
    "pyside6/plugins/qmltooling/",
    "pyside6/plugins/virtualkeyboard/",
    "pyside6/plugins/platforminputcontexts/",
    # 皆為 Qt6Network 的使用者，隨 Qt6Network 一起砍（見上方說明）
    "pyside6/plugins/tls/",
    "pyside6/plugins/networkinformation/",
    "pyside6/plugins/generic/",
)

# Qt 內建對話框的語系檔，只留繁中；其餘數十國語系未壓縮約 6.2MB
_KEEP_LOCALES = ("zh_tw",)


#: 被 `excludes` 排除掉 Python 綁定層、但仍是連結期相依、必須手動補回的 Qt DLL
_FORCE_QT_DLLS = ("Qt6OpenGL.dll", "Qt6OpenGLWidgets.dll")


def force_qt_binaries():
    """回傳必須強制收進打包的 Qt DLL（給 spec 的 `Analysis(binaries=...)`）。

    這些 DLL 不能靠 PySide6 hook 自動收——對應的 Python 模組已被 `excludes`
    排除，hook 就不會帶它們進來，但 `Qt6UiTools.dll` 連結期仍要求它們存在。
    """
    import PySide6

    root = os.path.dirname(PySide6.__file__)
    out = []
    for name in _FORCE_QT_DLLS:
        path = os.path.join(root, name)
        if not os.path.isfile(path):
            raise SystemExit(f"pyi_prune: 找不到必要的 Qt DLL：{path}")
        out.append((path, "PySide6"))
    return out


def _norm(dest):
    return dest.replace("\\", "/").lower()


def _drop(dest, src, drop_openssl=False):
    d = _norm(dest)
    s = (src or "").lower()

    if any(bad in s for bad in _BAD_SOURCE_DIRS):
        return "git-openssl"
    if drop_openssl and os.path.basename(d) in _OPENSSL_BASENAMES:
        return "openssl"
    if os.path.basename(d) in _DROP_BASENAMES:
        return "unused-qt"
    if d.startswith(_DROP_DEST_PREFIXES):
        return "unused-qt"
    if "/translations/" in d and d.endswith(".qm"):
        if not any(loc in d for loc in _KEEP_LOCALES):
            return "locale"
    return None


def prune(a, verbose=True, drop_openssl=False):
    """就地過濾 Analysis 的 binaries／datas，回傳 {原因: 剔除數}。

    `drop_openssl=True` 另外剔除 `libcrypto-3.dll`／`libssl-3.dll`（未壓縮約 5.2MB）。
    **只有獨立版能開**：那包裡 libcrypto 的唯一使用者是 `_hashlib.pyd`，而本專案只用
    `hashlib.sha256`（密碼雜湊），`_hashlib` 缺席時 Python 會自動退回內建 `_sha2`
    實作，結果完全相同。完整版則另有 `_ssl.pyd`／`libssl-3.dll` 也吃 libcrypto，
    故維持預設 False——要開之前先重跑逆向相依確認沒有第二個使用者。
    搭配 spec 的 `excludes=['_hashlib']` 使用（單砍 DLL 會留下缺相依的 pyd）。
    """
    stats = {}
    for attr in ("binaries", "datas"):
        kept = []
        for entry in getattr(a, attr):
            dest, src = entry[0], entry[1]
            reason = _drop(dest, src, drop_openssl=drop_openssl)
            if reason:
                stats[reason] = stats.get(reason, 0) + 1
                if verbose:
                    print(f"pyi_prune: drop [{reason}] {dest}")
            else:
                kept.append(entry)
        setattr(a, attr, kept)

    if verbose:
        total = sum(stats.values())
        detail = ", ".join(f"{k}={v}" for k, v in sorted(stats.items())) or "none"
        print(f"pyi_prune: removed {total} entries ({detail})")
    return stats
