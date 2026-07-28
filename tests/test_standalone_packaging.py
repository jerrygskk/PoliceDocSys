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


def _analysis_keyword(spec_name: str, keyword: str):
    tree = ast.parse((ROOT / spec_name).read_text(encoding="utf-8"))
    analysis = next(
        node.value
        for node in tree.body
        if isinstance(node, ast.Assign)
        and isinstance(node.value, ast.Call)
        and getattr(node.value.func, "id", None) == "Analysis"
    )
    return next(value.value for value in analysis.keywords if value.arg == keyword)


def _spec_list(spec_name: str, keyword: str) -> list:
    return ast.literal_eval(_analysis_keyword(spec_name, keyword))


def _spec_datas(spec_name: str) -> list[tuple[str, str]]:
    return _spec_list(spec_name, "datas")


def _spec_exe_keywords(spec_name: str) -> dict[str, object]:
    tree = ast.parse((ROOT / spec_name).read_text(encoding="utf-8"))
    exe = next(
        node.value
        for node in tree.body
        if isinstance(node, ast.Assign)
        and isinstance(node.value, ast.Call)
        and getattr(node.value.func, "id", None) == "EXE"
    )
    return {keyword.arg: ast.literal_eval(keyword.value) for keyword in exe.keywords}


def test_full_spec_hidden_imports_cover_all_tab_modules():
    hiddenimports = _spec_list("Police-Document-Manager.spec", "hiddenimports")
    for module_path, _class_name in TAB_CLASSES.values():
        assert module_path in hiddenimports


def test_entry_spec_hidden_imports_cover_entry_profile_tabs():
    hiddenimports = _spec_list("Police-Entry-Manager.spec", "hiddenimports")
    for key in ENTRY_PROFILE.tab_keys:
        module_path, _class_name = TAB_CLASSES[key]
        assert module_path in hiddenimports


def test_entry_spec_excludes_heavy_print_deps():
    excludes = _spec_list("Police-Entry-Manager.spec", "excludes")
    for mod in ("matplotlib", "numpy", "PIL"):
        assert mod in excludes


def test_entry_spec_excludes_startup_rescue_module():
    assert "ui_utils.rescue_dialog" in _spec_list("Police-Entry-Manager.spec", "excludes")
    assert "ui_utils.rescue_dialog" not in _spec_list("Police-Document-Manager.spec", "excludes")


def test_entry_spec_does_not_bundle_full_only_tabs():
    entry_modules = {TAB_CLASSES[k][0] for k in ENTRY_PROFILE.tab_keys}
    hiddenimports = _spec_list("Police-Entry-Manager.spec", "hiddenimports")
    for module_path, _class_name in TAB_CLASSES.values():
        if module_path not in entry_modules:
            assert module_path not in hiddenimports


def test_entry_spec_contract():
    keywords = _spec_exe_keywords("Police-Entry-Manager.spec")
    assert keywords["name"] == "Police-Entry-Manager"
    assert keywords["version"] == "version_info_entry.txt"
    assert keywords["console"] is False
    assert keywords["icon"] == ["res\\buttons\\police_badge.ico"]


def test_specs_bundle_their_profile_banner():
    full_datas = _spec_datas("Police-Document-Manager.spec")
    entry_datas = _spec_datas("Police-Entry-Manager.spec")
    assert ("res/buttons/banner.png", "res/buttons") in full_datas
    assert ("res/buttons/reward_ticket_banner.png", "res/buttons") not in full_datas
    assert ("res/buttons/reward_ticket_banner.png", "res/buttons") in entry_datas
    assert ("res/buttons/banner.png", "res/buttons") not in entry_datas


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
    assert bump_version.ENTRY_PRODUCT in text
    assert text.count("Police-Entry-Manager.exe") == 2
    assert "\u6843\u5712\u5e02\u653f\u5e9c\u8b66\u5bdf\u5c40\u4e2d\u58e2\u5206\u5c40" in text


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
