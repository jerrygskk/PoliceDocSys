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

# PE 的 import 名稱不是只有 .dll：Windows 模組合法副檔名還有 .drv／.sys／.exe／
# .ocx／.cpl（Qt6PrintSupport 匯入的 `WINSPOOL.DRV` 就是實例，踩過）。這裡只判斷
# 「名稱格式像不像模組」，是否真的存在仍由 _is_system_dll／bundle 比對把關，
# 故放寬副檔名不會削弱 fail-closed。
_VALID_DLL_NAME = re.compile(
    r"^[A-Za-z0-9_.+\-]+\.(?:dll|drv|sys|exe|ocx|cpl)$", re.I)

_SYSTEM_DIRS = (
    os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32"),
    os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "SysWOW64"),
)


def pe_imports(path):
    """回傳 PE 檔的 import DLL 名稱清單；格式無效時丟出解析錯誤。"""
    try:
        with open(path, "rb") as f:
            data = f.read()
        if len(data) < 0x40:
            raise ValueError("DOS header 截斷")
        if data[:2] != b"MZ":
            raise ValueError("DOS header 無效")
        e_lfanew = struct.unpack_from("<I", data, 0x3C)[0]
        if e_lfanew + 24 > len(data):
            raise ValueError("PE/COFF header 截斷")
        if data[e_lfanew:e_lfanew + 4] != b"PE\0\0":
            raise ValueError("PE header 無效")
        coff = e_lfanew + 4
        nsec = struct.unpack_from("<H", data, coff + 2)[0]
        optsz = struct.unpack_from("<H", data, coff + 16)[0]
        opt = coff + 20
        if opt + optsz > len(data):
            raise ValueError("optional header 截斷")
        magic = struct.unpack_from("<H", data, opt)[0]
        if magic == 0x10B:
            data_directory_offset = 96
        elif magic == 0x20B:
            data_directory_offset = 112
        else:
            raise ValueError(f"不支援的 optional header magic 0x{magic:04x}")
        if optsz < data_directory_offset + 16:
            raise ValueError("optional header data directory 截斷")
        ddoff = opt + data_directory_offset
        imp_rva = struct.unpack_from("<I", data, ddoff + 8)[0]
        if not imp_rva:
            return []
        secs = []
        so = opt + optsz
        for i in range(nsec):
            s = so + 40 * i
            if s + 40 > len(data):
                raise ValueError("section header 截斷")
            raw_size = struct.unpack_from("<I", data, s + 16)[0]
            raw_offset = struct.unpack_from("<I", data, s + 20)[0]
            if raw_size and raw_offset + raw_size > len(data):
                raise ValueError("section raw data 截斷")
            secs.append((
                struct.unpack_from("<I", data, s + 12)[0],   # VirtualAddress
                struct.unpack_from("<I", data, s + 8)[0],    # VirtualSize
                raw_size,
                raw_offset,
            ))

        def to_offset(rva):
            for va, vs, raw_size, raw_offset in secs:
                delta = rva - va
                if 0 <= delta < max(vs, raw_size) and delta < raw_size:
                    return raw_offset + delta, raw_offset + raw_size
            return None

        out = []
        mapped = to_offset(imp_rva)
        if mapped is None:
            raise ValueError("import RVA 無法映射到 section raw data")
        off, descriptor_end = mapped
        while True:
            if off + 20 > descriptor_end:
                raise ValueError("import descriptor 截斷")
            chunk = data[off:off + 20]
            if chunk == b"\0" * 20:
                return out
            name_rva = struct.unpack_from("<I", chunk, 12)[0]
            if not name_rva:
                raise ValueError("import descriptor 的 name RVA 無效")
            name_mapping = to_offset(name_rva)
            if name_mapping is None:
                raise ValueError("import name RVA 無法映射到 section raw data")
            no, name_end = name_mapping
            nul = data.find(b"\0", no, name_end)
            if nul < 0:
                raise ValueError("import name 截斷")
            name = data[no:nul].decode("ascii")
            if not _VALID_DLL_NAME.match(name):
                raise ValueError(f"import name 無效: {name!r}")
            out.append(name)
            off += 20
    except Exception as exc:                                    # noqa: BLE001
        raise RuntimeError(f"無法解析 {path}: {exc}") from exc


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
        return False

    import ast
    entries = ast.literal_eval(open(toc, encoding="utf-8").read())[2]

    bundled = {}
    for dest, src, _typ in entries:
        bundled[os.path.basename(dest).lower()] = src

    problems = []
    parse_failed = False
    source_missing = False
    for dest, src, _typ in entries:
        if os.path.splitext(dest)[1].lower() not in (".dll", ".pyd", ".exe"):
            continue
        if not src or not os.path.isfile(src):
            print(f"  ! 找不到候選 PE 來源檔案 {src or '<empty>'} ({dest})")
            source_missing = True
            continue
        try:
            imports = pe_imports(src)
        except Exception as exc:  # noqa: BLE001
            print(f"  ! 無法解析 {src}: {exc}")
            parse_failed = True
            continue
        for dep in imports:
            if dep.lower() in bundled or _is_system_dll(dep):
                continue
            problems.append((dest, dep))

    if problems:
        print(f"[{app}] 缺少 {len(problems)} 筆連結期相依：")
        for owner, dep in sorted(set(problems)):
            print(f"    {owner}  ->  {dep}   <-- 不在包裡，也不是系統 DLL")
    if parse_failed:
        print(f"[{app}] PE 解析失敗，無法確認連結期相依完整")
    if source_missing:
        print(f"[{app}] 候選 PE 來源檔案缺失，無法確認連結期相依完整")
    elif not parse_failed and not problems:
        print(f"[{app}] OK：{len(bundled)} 個檔案的連結期相依全部齊全")
    return not problems and not parse_failed and not source_missing


def main():
    apps = sys.argv[1:] or ["Police-Document-Manager", "Police-Entry-Manager"]
    results = [check(a) for a in apps]
    if any(r is False for r in results):
        sys.exit(1)


if __name__ == "__main__":
    main()
