# -*- coding: utf-8 -*-
"""排除清單驗證：確認 spec 的 `excludes` 沒有砍掉執行期真的會用到的 Python 模組。

做法：讀出 spec 自己的 `excludes` 與 `hiddenimports`（單一來源，不另外抄一份），
安裝一個會對 `excludes` 內模組丟 `ModuleNotFoundError` 的攔截器，然後逐一 import
所有 `hiddenimports`。只要有任何一個是「表面上沒用到、實際上被間接 import」的模組，
這裡就會當場失敗。

踩過的雷：`--exclude-module PIL` 看起來安全（程式沒 import PIL），但
`matplotlib/colors.py` 在 module 層就 `from PIL import Image`，
打包版一點到列印頁就 `ModuleNotFoundError: No module named 'PIL'`。

與 `tools/check_bundle_deps.py` 分工：那支驗 DLL 層的連結期相依，這支驗 Python
層的 import 相依，兩類都攔不到才算安全。**兩支都不需要 build，改完 spec 就能跑。**

用法（專案根目錄）：

    python tools/check_excludes.py
"""

import ast
import importlib
import os
import subprocess
import sys

_SPECS = ("Police-Document-Manager.spec", "Police-Entry-Manager.spec")


def spec_lists(path):
    """從 spec 取出 (excludes, hiddenimports)。只讀 Analysis 的字面值 list。"""
    # utf-8-sig：容忍 PowerShell 寫出的 BOM
    tree = ast.parse(open(path, encoding="utf-8-sig").read())
    found = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not (isinstance(node.func, ast.Name) and node.func.id == "Analysis"):
            continue
        for kw in node.keywords:
            if kw.arg in ("excludes", "hiddenimports"):
                try:
                    found[kw.arg] = ast.literal_eval(kw.value)
                except ValueError:
                    found[kw.arg] = []
    return found.get("excludes", []), found.get("hiddenimports", [])


_CHILD = r'''
import sys, importlib

BLOCKED = set(sys.argv[1].split(",")) if sys.argv[1] else set()
TARGETS = sys.argv[2].split(",") if sys.argv[2] else []


class _Blocker:
    """模擬打包後「這些模組不存在」的狀態。"""

    def find_module(self, name, path=None):
        return self.find_spec(name, path)

    def find_spec(self, name, path=None, target=None):
        parts = name.split(".")
        for i in range(len(parts)):
            if ".".join(parts[:i + 1]) in BLOCKED:
                raise ModuleNotFoundError(f"No module named {name!r}", name=name)
        return None


sys.meta_path.insert(0, _Blocker())

failures = []
for mod in TARGETS:
    try:
        importlib.import_module(mod)
    except Exception as exc:
        failures.append(f"{mod}: {type(exc).__name__}: {exc}")

for f in failures:
    print("FAIL " + f)
sys.exit(1 if failures else 0)
'''


def check(spec):
    excludes, hidden = spec_lists(spec)
    # 只驗本專案自己的模組；PySide6.QtPrintSupport 之類第三方 hiddenimport 由 Qt 自己保證
    targets = [m for m in hidden if m.split(".")[0] in ("lib", "tabs", "ui_utils", "res")]
    if not targets:
        print(f"[{spec}] 沒有可驗證的 hiddenimports，略過")
        return True

    env = dict(os.environ, QT_QPA_PLATFORM="offscreen", PYTHONIOENCODING="utf-8")
    proc = subprocess.run(
        [sys.executable, "-c", _CHILD, ",".join(excludes), ",".join(targets)],
        capture_output=True, text=True, encoding="utf-8", errors="replace", env=env,
    )
    out = (proc.stdout or "").strip()
    if proc.returncode == 0:
        print(f"[{spec}] OK：{len(targets)} 個模組在 {len(excludes)} 項排除下都 import 得起來")
        return True

    print(f"[{spec}] 排除清單砍到了執行期需要的模組：")
    for line in out.splitlines():
        print("    " + line)
    if proc.stderr.strip():
        print("    (stderr) " + proc.stderr.strip().splitlines()[-1])
    return False


def main():
    specs = sys.argv[1:] or [s for s in _SPECS if os.path.isfile(s)]
    if not specs:
        print("找不到 spec 檔，請先產生")
        sys.exit(2)
    if not all([check(s) for s in specs]):
        sys.exit(1)


if __name__ == "__main__":
    main()
