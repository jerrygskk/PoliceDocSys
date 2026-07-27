import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import bump_version
from main import TAB_CLASSES
from lib.app_profile import ENTRY_PROFILE


def _spec_datas(spec_name: str) -> list[tuple[str, str]]:
    tree = ast.parse((ROOT / spec_name).read_text(encoding="utf-8"))
    analysis = next(
        node.value
        for node in tree.body
        if isinstance(node, ast.Assign)
        and isinstance(node.value, ast.Call)
        and getattr(node.value.func, "id", None) == "Analysis"
    )
    datas = next(keyword.value for keyword in analysis.keywords if keyword.arg == "datas")
    return ast.literal_eval(datas)


def test_full_program_devlog_hidden_imports_cover_all_tab_modules():
    text = (ROOT / "DEVELOPER.md").read_text(encoding="utf-8")
    start = text.index("### 打包指令")
    end = text.index("### 獨立版打包指令", start)
    block = text[start:end]
    for module_path, _class_name in TAB_CLASSES.values():
        assert f"--hidden-import {module_path} ^" in block, (
            f"missing --hidden-import {module_path} in DEVELOPER.md 打包指令"
        )


def _full_build_block() -> str:
    text = (ROOT / "DEVELOPER.md").read_text(encoding="utf-8")
    start = text.index("### 打包指令")
    end = text.index("### 獨立版打包指令", start)
    return text[start:end]


def _entry_build_block() -> str:
    """DEVELOPER.md 的獨立版打包指令區塊。獨立版與大程式一樣 spec 不入庫、
    每次砍掉重建，故**文件裡的這串指令就是唯一建置定義**，測試以它為準。"""
    text = (ROOT / "DEVELOPER.md").read_text(encoding="utf-8")
    start = text.index("### 獨立版打包指令")
    end = text.index("### 注意事項", start)
    return text[start:end]


def test_entry_build_command_covers_entry_profile_tabs():
    block = _entry_build_block()
    for key in ENTRY_PROFILE.tab_keys:
        module_path, _class_name = TAB_CLASSES[key]
        assert f"--hidden-import {module_path} ^" in block, (
            f"獨立版打包指令缺 --hidden-import {module_path}"
        )


def test_entry_build_command_excludes_heavy_print_deps():
    block = _entry_build_block()
    for mod in ("matplotlib", "numpy", "PIL"):
        assert f"--exclude-module {mod} ^" in block, f"獨立版打包指令未排除 {mod}"


def test_entry_build_command_excludes_startup_rescue_module():
    """規格禁止獨立版執行資料庫還原。除了 handleCorruptDb 的 profile guard，
    打包時也不收救援視窗模組，讓「獨立版不可能開啟還原」成為結構性保證。"""
    block = _entry_build_block()
    assert "--exclude-module ui_utils.rescue_dialog ^" in block

    full_start = (ROOT / "DEVELOPER.md").read_text(encoding="utf-8")
    full_block = full_start[full_start.index("### 打包指令"):
                            full_start.index("### 獨立版打包指令")]
    assert "ui_utils.rescue_dialog" not in full_block, "大程式仍須保留開機救援"


def test_entry_build_command_does_not_bundle_full_only_tabs():
    """列印／歸檔等完整版專屬分頁不得出現在獨立版指令：列進去等於把
    matplotlib 一整串拉回來，體積優化直接白做。"""
    block = _entry_build_block()
    entry_modules = {TAB_CLASSES[k][0] for k in ENTRY_PROFILE.tab_keys}
    for module_path, _class_name in TAB_CLASSES.values():
        if module_path not in entry_modules:
            assert f"--hidden-import {module_path} " not in block, (
                f"獨立版打包指令不該含 {module_path}"
            )


def test_entry_build_command_contract():
    block = _entry_build_block()
    assert "--name Police-Entry-Manager standalone_main.py" in block
    assert "--version-file version_info_entry.txt" in block
    assert "--windowed" in block
    assert "--onefile" in block
    assert "police_badge.ico" in block


def test_build_commands_bundle_their_profile_banner():
    full_block = _full_build_block()
    entry_block = _entry_build_block()
    assert '--add-data "res/buttons/banner.png;res/buttons" ^' in full_block
    assert "reward_ticket_banner.png" not in full_block
    assert '--add-data "res/buttons/reward_ticket_banner.png;res/buttons" ^' in entry_block
    assert '--add-data "res/buttons/banner.png;res/buttons" ^' not in entry_block


def test_full_spec_bundles_only_full_profile_banner():
    datas = _spec_datas("Police-Document-Manager.spec")
    assert ("res/buttons/banner.png", "res/buttons") in datas
    assert ("res/buttons/reward_ticket_banner.png", "res/buttons") not in datas


def test_entry_spec_bundles_only_entry_profile_banner():
    datas = _spec_datas("Police-Entry-Manager.spec")
    assert ("res/buttons/reward_ticket_banner.png", "res/buttons") in datas
    assert ("res/buttons/banner.png", "res/buttons") not in datas


def test_entry_version_info_contract():
    text = (ROOT / "version_info_entry.txt").read_text(encoding="utf-8")
    assert "警政快速登錄系統" in text
    assert text.count("Police-Entry-Manager.exe") == 2
    assert "桃園市政府警察局中壢分局" in text


def _extract_field(text: str, field: str) -> str:
    m = re.search(rf"StringStruct\('{field}', '([^']*)'\)", text)
    assert m, f"missing field {field}"
    return m.group(1)


def test_gen_infos_produces_matching_versions(tmp_path, monkeypatch):
    info_txt = tmp_path / "version_info.txt"
    entry_info_txt = tmp_path / "version_info_entry.txt"
    monkeypatch.setattr(bump_version, "INFO_TXT", info_txt)
    monkeypatch.setattr(bump_version, "ENTRY_INFO_TXT", entry_info_txt)

    bump_version.gen_infos("1.2.5")

    full_text = info_txt.read_text(encoding="utf-8")
    entry_text = entry_info_txt.read_text(encoding="utf-8")

    assert _extract_field(full_text, "FileVersion") == _extract_field(entry_text, "FileVersion")
    assert _extract_field(full_text, "ProductVersion") == _extract_field(entry_text, "ProductVersion")


def test_gen_infos_does_not_cross_pollute_product_fields(tmp_path, monkeypatch):
    info_txt = tmp_path / "version_info.txt"
    entry_info_txt = tmp_path / "version_info_entry.txt"
    monkeypatch.setattr(bump_version, "INFO_TXT", info_txt)
    monkeypatch.setattr(bump_version, "ENTRY_INFO_TXT", entry_info_txt)

    bump_version.gen_infos("1.2.5")

    full_text = info_txt.read_text(encoding="utf-8")
    entry_text = entry_info_txt.read_text(encoding="utf-8")

    assert _extract_field(full_text, "ProductName") == bump_version.PRODUCT
    assert _extract_field(full_text, "FileDescription") == bump_version.PRODUCT
    assert _extract_field(full_text, "InternalName") == bump_version.EXE_NAME
    assert _extract_field(full_text, "OriginalFilename") == bump_version.EXE_NAME

    assert _extract_field(entry_text, "ProductName") == bump_version.ENTRY_PRODUCT
    assert _extract_field(entry_text, "FileDescription") == bump_version.ENTRY_PRODUCT
    assert _extract_field(entry_text, "InternalName") == bump_version.ENTRY_EXE
    assert _extract_field(entry_text, "OriginalFilename") == bump_version.ENTRY_EXE
