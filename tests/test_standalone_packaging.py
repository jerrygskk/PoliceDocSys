import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import bump_version
from main import TAB_CLASSES
from lib.app_profile import ENTRY_PROFILE


def test_full_program_devlog_hidden_imports_cover_all_tab_modules():
    text = (ROOT / "DEVELOPER.md").read_text(encoding="utf-8")
    start = text.index("### 打包指令")
    end = text.index("### 獨立版打包指令", start)
    block = text[start:end]
    for module_path, _class_name in TAB_CLASSES.values():
        assert f"--hidden-import {module_path} ^" in block, (
            f"missing --hidden-import {module_path} in DEVELOPER.md 打包指令"
        )


def test_entry_spec_hiddenimports_cover_entry_profile_tabs():
    text = (ROOT / "Police-Entry-Manager.spec").read_text(encoding="utf-8")
    for key in ENTRY_PROFILE.tab_keys:
        module_path, _class_name = TAB_CLASSES[key]
        assert f"'{module_path}'" in text, f"missing hiddenimports entry for {module_path}"


def test_entry_spec_excludes_heavy_print_deps():
    text = (ROOT / "Police-Entry-Manager.spec").read_text(encoding="utf-8")
    assert "'matplotlib'" in text
    assert "'numpy'" in text


def test_entry_spec_contract():
    text = (ROOT / "Police-Entry-Manager.spec").read_text(encoding="utf-8")
    assert "['standalone_main.py']" in text
    assert "name='Police-Entry-Manager'" in text
    assert "console=False" in text
    assert "version='version_info_entry.txt'" in text
    assert "police_badge.ico" in text


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
