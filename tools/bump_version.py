"""
進版工具：一次完成「改版號 + 產出 version_info.txt」。

用法：
    python tools/bump_version.py 1.0.4   # 版號一律自帶（從專案根目錄執行）

會做三件事：
  1. 改寫 lib/version.py 的 __version__
  2. 產出 version_info.txt（exe 右鍵→內容→詳細資料的版本資訊，打包 --version-file 用）
  3. 同步 README 門面兩處「目前版本」版號

⚠️ 進版一律用本工具，不要手改 lib/version.py，否則 version_info.txt 會與版號不同步。
（README §8 補版本記錄、git tag v{版本} 仍須手動。）
"""
import re
import sys
from pathlib import Path

# 顯示字串（要改公司/產品名改這裡）
COMPANY     = "桃園市政府警察局中壢分局"
PRODUCT     = "公文管理系統"
DESCRIPTION = "公文管理系統"
COPYRIGHT   = "© 2026 桃園市政府警察局中壢分局龍興派出所"
EXE_NAME    = "Police-Document-Manager.exe"

# 錨定 repo 根（本檔在 tools/ 之下），與當前工作目錄脫鉤
ROOT        = Path(__file__).resolve().parent.parent
VERSION_PY  = ROOT / "lib" / "version.py"
INFO_TXT    = ROOT / "version_info.txt"
README_MD   = ROOT / "README.md"
_VER_RE     = re.compile(r'__version__\s*=\s*"([^"]*)"')
# README 門面顯示的版號（兩處），進版時一併同步，免得每次手動忘記
_README_RES = (
    re.compile(r'(目前版本\s*\*\*v)\d+(?:\.\d+){1,3}(\*\*)'),
    re.compile(r'(\*\*目前版本\*\*：v)\d+(?:\.\d+){1,3}'),
)


def read_current() -> str:
    m = _VER_RE.search(VERSION_PY.read_text(encoding="utf-8"))
    if not m:
        sys.exit("錯誤：無法於 lib/version.py 讀取版本號碼（__version__）。")
    return m.group(1)


def write_version(new: str) -> None:
    text = VERSION_PY.read_text(encoding="utf-8")
    text = _VER_RE.sub(f'__version__ = "{new}"', text, count=1)
    VERSION_PY.write_text(text, encoding="utf-8")


def update_readme(new: str) -> bool:
    """同步 README 門面顯示的版號（兩處）。回傳是否有改到。"""
    if not README_MD.exists():
        return False
    text = README_MD.read_text(encoding="utf-8")
    orig = text
    text = _README_RES[0].sub(rf'\g<1>{new}\g<2>', text)
    text = _README_RES[1].sub(rf'\g<1>{new}', text)
    if text != orig:
        README_MD.write_text(text, encoding="utf-8")
        return True
    return False


def gen_info(version: str) -> None:
    parts = [int(x) for x in version.split(".")]
    while len(parts) < 4:
        parts.append(0)
    vers = tuple(parts[:4])
    INFO_TXT.write_text(f"""# UTF-8
# 由 bump_version.py 自動產生，請勿手改（用 bump_version.py 進版即可）
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers={vers},
    prodvers={vers},
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo([
      StringTable(
        '040404b0',
        [
          StringStruct('CompanyName', '{COMPANY}'),
          StringStruct('FileDescription', '{DESCRIPTION}'),
          StringStruct('FileVersion', '{version}'),
          StringStruct('InternalName', '{EXE_NAME}'),
          StringStruct('LegalCopyright', '{COPYRIGHT}'),
          StringStruct('OriginalFilename', '{EXE_NAME}'),
          StringStruct('ProductName', '{PRODUCT}'),
          StringStruct('ProductVersion', '{version}')
        ])
    ]),
    VarFileInfo([VarStruct('Translation', [1028, 1200])])
  ]
)
""", encoding="utf-8")


if __name__ == "__main__":
    current = read_current()
    print(f"目前版本號碼：v{current}")

    if len(sys.argv) < 2:
        sys.exit("請指定欲進版之版本號碼，如：python bump_version.py 1.0.4")
    new = sys.argv[1].lstrip("v")
    if not re.fullmatch(r"\d+(\.\d+){1,3}", new):
        sys.exit(f"版本號碼格式不正確：{new}（如：1.0.4）")

    write_version(new)
    gen_info(new)
    readme_done = update_readme(new)
    suffix = "、README 版號" if readme_done else ""
    print(f"已完成進版：v{current} → v{new}（已更新 lib/version.py 與 version_info.txt{suffix}）")
    if not readme_done:
        print("⚠️ README 版號未變動（找不到對應字樣或已是新版），請手動確認。")
