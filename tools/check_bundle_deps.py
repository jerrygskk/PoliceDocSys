# -*- coding: utf-8 -*-
"""打包後相依檢查：確認每個被收進 exe 的 DLL／pyd，其**連結期**相依都還在包裡。

用途：`tools/pyi_prune.py` 會剔除用不到的 binary，但「程式沒 import 某模組」
不等於「那支 DLL 可以砍」——Qt 有不少連結期硬相依（踩過：`Qt6UiTools.dll`
連結期就要 `Qt6OpenGLWidgets.dll`，砍掉後打包版一開機就
`ImportError: DLL load failed while importing QtUiTools`）。

這類問題**打包成功、原始碼跑測試也抓不到**，只有實際執行打包版才會炸，
所以每次調整排除清單後都要跑這支。

用法（專案根目錄，build 之後）：

    python tools/check_bundle_deps.py

有缺項時印出「誰缺了什麼」並以非 0 結束。
"""

import os
import re
import struct
import sys

_VALID_DLL_NAME = re.compile(r"^[A-Za-z0-9_.+\-]+\.(?:dll|DLL)$")

_SYSTEM_DIRS = (
    os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32"),
    os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "SysWOW64"),
)


def pe_imports(path):
    """回傳 PE 檔的 import DLL 名稱清單（連結期相依）。非 PE 檔回傳空 list。"""
    try:
        with open(path, "rb") as f:
            data = f.read()
        if data[:2] != b"MZ":
            return []
        e_lfanew = struct.unpack_from("<I", data, 0x3C)[0]
        if data[e_lfanew:e_lfanew + 4] != b"PE\0\0":
            return []
        coff = e_lfanew + 4
        nsec = struct.unpack_from("<H", data, coff + 2)[0]
        optsz = struct.unpack_from("<H", data, coff + 16)[0]
        opt = coff + 20
        magic = struct.unpack_from("<H", data, opt)[0]
        ddoff = opt + (112 if magic == 0x20B else 96)
        imp_rva = struct.unpack_from("<I", data, ddoff + 8)[0]
        if not imp_rva:
            return []
        secs = []
        so = opt + optsz
        for i in range(nsec):
            s = so + 40 * i
            secs.append((
                struct.unpack_from("<I", data, s + 12)[0],   # VirtualAddress
                struct.unpack_from("<I", data, s + 8)[0],    # VirtualSize
                struct.unpack_from("<I", data, s + 20)[0],   # PointerToRawData
            ))

        def to_offset(rva):
            for va, vs, praw in secs:
                if va <= rva < va + max(vs, 1) + 0x2000:
                    return praw + (rva - va)
            return None

        out = []
        off = to_offset(imp_rva)
        while off is not None:
            chunk = data[off:off + 20]
            if len(chunk) < 20 or chunk == b"\0" * 20:
                break
            name_rva = struct.unpack_from("<I", chunk, 12)[0]
            if not name_rva:
                break
            no = to_offset(name_rva)
            if no is None:
                break
            name = data[no:data.index(b"\0", no)].decode("ascii", "replace")
            # 少數 PE 的 section 對應會讓偏移落在區段外，讀到亂碼；只收像 DLL 名的
            if not _VALID_DLL_NAME.match(name):
                break
            out.append(name)
            off += 20
        return out
    except Exception as exc:                                    # noqa: BLE001
        print(f"  ! 無法解析 {path}: {exc}")
        return []


#: api-set 名稱（api-ms-win-crt-heap-l1-1-0.dll）在少數 PE 會被切成尾段，非真缺項
_APISET_TAIL = re.compile(r"^l\d+-\d+-\d+\.dll$", re.I)


def _is_system_dll(name):
    low = name.lower()
    if low.startswith("api-ms-win-") or low.startswith("ext-ms-win-"):
        return True
    if _APISET_TAIL.match(low):
        return True
    return any(os.path.isfile(os.path.join(d, name)) for d in _SYSTEM_DIRS)


def check(app):
    toc = os.path.join("build", app, "PKG-00.toc")
    if not os.path.isfile(toc):
        print(f"[{app}] 找不到 {toc}，請先 build")
        return None

    import ast
    entries = ast.literal_eval(open(toc, encoding="utf-8").read())[2]

    bundled = {}
    for dest, src, _typ in entries:
        bundled[os.path.basename(dest).lower()] = src

    problems = []
    for dest, src, _typ in entries:
        if os.path.splitext(dest)[1].lower() not in (".dll", ".pyd", ".exe"):
            continue
        if not src or not os.path.isfile(src):
            continue
        for dep in pe_imports(src):
            if dep.lower() in bundled or _is_system_dll(dep):
                continue
            problems.append((dest, dep))

    if problems:
        print(f"[{app}] 缺少 {len(problems)} 筆連結期相依：")
        for owner, dep in sorted(set(problems)):
            print(f"    {owner}  ->  {dep}   <-- 不在包裡，也不是系統 DLL")
    else:
        print(f"[{app}] OK：{len(bundled)} 個檔案的連結期相依全部齊全")
    return not problems


def main():
    apps = sys.argv[1:] or ["Police-Document-Manager", "Police-Entry-Manager"]
    results = [check(a) for a in apps]
    if any(r is False for r in results):
        sys.exit(1)
    if all(r is None for r in results):
        sys.exit(2)


if __name__ == "__main__":
    main()
