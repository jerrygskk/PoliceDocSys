# -*- coding: utf-8 -*-
"""階段 3 驗收工具（本階段最重要的一關）：證明 matplotlib／numpy／PIL
確實離開產品路徑。

兩道關卡並存，缺一不可：

1. **靜態掃描**（`ast`）：逐檔走 `main.py`／`standalone_main.py`／`lib/`／
   `tabs/`／`ui_utils/` 底下所有 `.py`，抓出所有 `Import`／`ImportFrom`
   節點中指向 `matplotlib`／`numpy`／`PIL`／`pylab`／`mpl_toolkits` 的
   import，**不管有沒有被 `try/except ImportError` 包住**。這是為了
   堵住 runtime hook 的盲點：`try: import matplotlib / except ImportError:
   pass` 這種寫法會被 hook 攔下、但例外被自己吞掉，hook 完全偵測不到；
   階段 4 把這三個套件加進 PyInstaller 排除清單後，這種降級路徑會在
   打包版裡靜默走 fallback，行為與開發環境不同、極難查。

2. **runtime import hook**：在 `sys.meta_path` 插入一個 finder，一旦有人
   試圖 import `matplotlib`／`numpy`／`PIL`（或其任何子模組），立刻拋
   `ImportError`——不是「事後檢查 sys.modules 有沒有這些名字」，是**主動
   擋下**，第一次嘗試就當場失敗，訊息直接點出是哪個 import 觸發的。

   裝上這個 hook 之後才 `import main`，並逐一 import `tabs/` 底下**所有**
   分頁模組與 `ui_utils/` 底下所有模組（`tabs/__init__.py` 是延遲載入，
   只 import `main` 測不到未被存取的分頁；PITFALLS 記載過的既有雷：排除
   清單一上，沒被跑到的分頁會在使用者第一次點開該分頁時才炸），並實際跑
   一次 `tabs.tab_print.generate_pages()` 取得預覽 PNG 與 PDF bytes——因為
   `_set_text_measurer('qt')` 這類「切換到 matplotlib」的路徑只有真的被
   呼叫到才會觸發 import，光 import 模組測不到。

全程若有任何一次 import 被攔到或靜態掃描找到，直接印出並回傳非 0；全部跑完
都沒攔到，最後再檢查一次 `sys.modules` 保底（雙重確認 hook 沒有漏放行）。

用法：
    python tools/check_no_matplotlib.py
"""

import ast
import importlib
import os
import pkgutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

BLOCKED_ROOTS = ("matplotlib", "numpy", "PIL", "pylab", "mpl_toolkits")

# 靜態掃描涵蓋的產品路徑：single files ＋ package 目錄。
STATIC_SCAN_FILES = ("main.py", "standalone_main.py")
STATIC_SCAN_PACKAGES = ("lib", "tabs", "ui_utils")


class _BlockedImportError(ImportError):
    pass


class _ProductPathGuard:
    """`sys.meta_path` finder：擋下任何 `matplotlib`／`numpy`／`PIL`
    （含子模組，例如 `matplotlib.pyplot`）的 import，改拋例外中止。"""

    def find_spec(self, fullname, path, target=None):
        root = fullname.split(".")[0]
        if root in BLOCKED_ROOTS:
            raise _BlockedImportError(
                f"[check_no_matplotlib] 產品路徑觸發了禁止的 import："
                f"{fullname}")
        return None   # 交給後續 finder（標準 import 機制）正常處理


def _install_guard():
    sys.meta_path.insert(0, _ProductPathGuard())


# ── 關卡 1：靜態 AST 掃描 ────────────────────────────────
def _iter_py_files():
    for name in STATIC_SCAN_FILES:
        path = os.path.join(ROOT, name)
        if os.path.exists(path):
            yield path
    for pkg in STATIC_SCAN_PACKAGES:
        pkg_dir = os.path.join(ROOT, pkg)
        for dirpath, _dirnames, filenames in os.walk(pkg_dir):
            for fn in filenames:
                if fn.endswith(".py"):
                    yield os.path.join(dirpath, fn)


def _blocked_root_of(module_name):
    if not module_name:
        return None
    root = module_name.split(".")[0]
    return root if root in BLOCKED_ROOTS else None


def static_scan():
    """回傳違規清單：`[(檔案, 行號, 說明), ...]`。不管有沒有被
    `try/except` 包住，只要原始碼裡出現指向 BLOCKED_ROOTS 的 import
    節點就算違規。"""
    violations = []
    for path in _iter_py_files():
        with open(path, encoding="utf-8") as f:
            src = f.read()
        try:
            tree = ast.parse(src, filename=path)
        except SyntaxError as e:
            violations.append((path, e.lineno or 0, f"檔案無法解析：{e}"))
            continue

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root = _blocked_root_of(alias.name)
                    if root:
                        violations.append(
                            (path, node.lineno, f"import {alias.name}"))
            elif isinstance(node, ast.ImportFrom):
                # `from . import x` 之類 module 為 None，與本檢查無關。
                root = _blocked_root_of(node.module)
                if root:
                    violations.append(
                        (path, node.lineno,
                         f"from {node.module} import ..."))
    return violations


# ── 關卡 2：runtime import hook ─────────────────────────
def _iter_submodule_names(package_name):
    """回傳某個套件底下所有子模組的完整名稱（不含套件本身）。"""
    pkg = importlib.import_module(package_name)
    names = []
    if hasattr(pkg, "__path__"):
        for _finder, name, _ispkg in pkgutil.iter_modules(pkg.__path__, package_name + "."):
            names.append(name)
    return names


def runtime_scan():
    """裝好 hook 後，import 產品路徑上的所有模組並實跑一次
    `generate_pages()`。回傳 (ok, message)。"""
    try:
        import main as _app_main            # noqa: F401  (只驗證不觸發 matplotlib)

        # tabs/__init__.py 是延遲載入（PEP 562），只 import 套件本身測不到
        # 個別分頁模組；逐一 import 每個子模組才涵蓋全部分頁。
        for mod_name in _iter_submodule_names("tabs"):
            importlib.import_module(mod_name)
        for mod_name in _iter_submodule_names("ui_utils"):
            importlib.import_module(mod_name)

        import tabs.tab_print as tp

        from PySide6.QtGui import QGuiApplication
        app = QGuiApplication.instance() or QGuiApplication([])  # noqa: F841

        db_path, date_str = "dbfile.db", "2026-05-11"
        if not os.path.exists(db_path):
            return False, f"[X] 找不到測試資料庫：{db_path}（需在專案根目錄執行）"

        png_list, pdf_bytes, page_specs = tp.generate_pages(db_path, date_str)
    except _BlockedImportError as e:
        return False, f"[X] {e}"

    if not png_list:
        return False, "[X] generate_pages() 沒有回傳任何預覽 PNG（案例可能已失效）"
    if not pdf_bytes:
        return False, "[X] generate_pages() 沒有回傳 PDF bytes"

    leaked = [m for m in BLOCKED_ROOTS if m in sys.modules]
    if leaked:
        return False, f"[X] sys.modules 混入了禁止的模組（hook 未攔到）：{leaked}"

    return True, (
        f"[OK] import main／全部 tabs／全部 ui_utils／generate_pages() 全程"
        f"未 import matplotlib／numpy／PIL。"
        f"（預覽 {len(png_list)} 張、PDF {len(pdf_bytes)} bytes、"
        f"{len(page_specs)} 個頁面規格）")


def main():
    ok_all = True

    # 關卡 1：靜態掃描（先跑，不需要 QApplication／DB）。
    violations = static_scan()
    if violations:
        ok_all = False
        print(f"[X] 靜態掃描發現 {len(violations)} 處禁止的 import"
              f"（不論是否被 try/except 包住）：")
        for path, lineno, desc in violations:
            rel = os.path.relpath(path, ROOT)
            print(f"  {rel}:{lineno}  {desc}")
    else:
        print("[OK] 靜態掃描：main.py／standalone_main.py／lib／tabs／"
              "ui_utils 全部原始碼中沒有任何 matplotlib／numpy／PIL 的"
              "import 節點（含被 try/except 包住的）。")

    # 關卡 2：runtime hook（即使關卡 1 已失敗也照跑，累積回報全部問題）。
    _install_guard()
    ok, msg = runtime_scan()
    print(msg)
    ok_all = ok_all and ok

    return 0 if ok_all else 1


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    sys.exit(main())
