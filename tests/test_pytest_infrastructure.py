import ast
import json
import os
from pathlib import Path

import pytest

from conftest import (
    ISOLATED_MODULES, MARKER_MODULES, PRIMARY_MARKERS, _isolated_child_basetemp,
    classify_test_module, write_collection_record,
)
from tools.pytest_trend import (
    build_trend_record, compare_node_ids, unittest_id_to_pytest,
    write_trend_record,
)


ROOT = Path(__file__).resolve().parents[1]


EXPECTED_MARKER_MODULES = {
    "pure": {
        "test_app_lock.py", "test_app_profile.py", "test_archive_text.py",
        "test_date_guard.py", "test_environment_contract.py",
        "test_error_msg.py",
        "test_no_pii.py", "test_pytest_infrastructure.py",
        "test_ref_sort.py", "test_release_documentation_contract.py",
        "test_row_perm.py",
        "test_status.py",
    },
    "db": {
        "test_audit.py", "test_auth_manager.py", "test_casetype_alias.py",
        "test_db_backup.py", "test_db_schema.py", "test_db_utils.py",
        "test_doc_convert.py", "test_idle_timeouts.py", "test_input_lock.py",
        "test_print_titles.py", "test_report_input_mode.py",
        "test_reward_data.py", "test_reward_lost_update_sql.py",
        "test_reward_status.py", "test_seed_print_baseline.py",
        "test_soft_delete.py", "test_ticket_data.py", "test_ticket_print.py",
        "test_trash.py",
    },
    "qt": {
        "test_archive_gui_pilot.py", "test_archive_runtime_guards.py",
        "test_date_guard_gui_pilot.py",
        "test_base_tab.py", "test_combo_hint.py", "test_context_menu_style.py",
        "test_date_wheel_guard.py", "test_dbbrowse_sync.py",
        "test_table_col_widths.py",
        "test_dialog_disabled_style.py", "test_dialog_smoke.py",
        "test_dispatch_tab.py", "test_edit_dialog_optimistic_lock.py",
        "test_help_content_contract.py",
        "test_idle_timeout_live_apply.py",
        "test_loading_screen_banner.py", "test_nullable_date.py",
        "test_pytest_qt_runtime.py", "test_report_mode_switch.py",
        "test_reset_gui_pilot.py", "test_restore_gui_pilot.py",
        "test_reward_browse.py", "test_reward_gui_pilot.py",
        "test_reward_integration.py", "test_reward_print.py",
        "test_browse_recent.py",
        "test_reward_recipients.py", "test_reward_refresh.py",
        "test_reward_summary.py", "test_reward_tab.py",
        "test_settings_panel_pilot.py", "test_sticky_scroll.py",
        "test_settle_checkbox_alignment.py", "test_settle_chip_visibility.py",
        "test_settle_gui_pilot.py",
        "test_standalone_browse.py", "test_standalone_settings.py",
        "test_ticket_browse.py", "test_ticket_runtime_cas.py",
        "test_trash_gui_pilot.py",
        "test_ticket_tab.py", "test_ui_load.py", "test_window_geometry.py",
    },
    "shell": {
        "test_lazy_tab_loading.py", "test_logout_gui_pilot.py",
        "test_standalone_shell.py", "test_startup_failure.py",
    },
    "packaging": {
        "test_bundle_deps.py", "test_print_baseline.py", "test_pyi_prune.py",
        "test_standalone_packaging.py",
    },
}


def test_marker_classification_covers_every_module_once():
    discovered = {path.name for path in (ROOT / "tests").glob("test_*.py")}
    classified = set().union(*MARKER_MODULES.values())

    assert PRIMARY_MARKERS == tuple(EXPECTED_MARKER_MODULES)
    assert MARKER_MODULES == EXPECTED_MARKER_MODULES
    assert classified == discovered
    assert sum(len(modules) for modules in MARKER_MODULES.values()) == len(discovered)
    for marker, modules in EXPECTED_MARKER_MODULES.items():
        for module in modules:
            assert classify_test_module(module) == marker


def _modules_building_manager_in_process(module_names):
    """回傳「原始碼裡真的呼叫了 DocumentManager(...)」的 shell 層測試檔。

    用 AST 而非字串搜尋：`test_lazy_tab_loading.py` 把建立 manager 的程式碼放在
    要丟給子行程的字串腳本裡，字串搜尋會誤判成同行程建立。"""
    found = set()
    for name in sorted(module_names):
        tree = ast.parse((ROOT / "tests" / name).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            called = getattr(func, "attr", None) or getattr(func, "id", None)
            if called == "DocumentManager":
                found.add(name)
                break
    return found


def test_isolated_modules_stay_inside_shell_layer():
    assert ISOLATED_MODULES <= MARKER_MODULES["shell"]
    assert "test_standalone_shell.py" in ISOLATED_MODULES


def test_every_shell_module_building_managers_runs_isolated():
    """PITFALLS TST-5：在同一行程內反覆建立 `DocumentManager` 會累積長壽掛載，
    到一定量後 native crash。行程隔離是唯一處置，故任何會在行程內建 manager 的
    shell 層測試檔都必須列入 `ISOLATED_MODULES`——漏列的話累積量會重新長回來，
    而症狀是隨機崩在別支測試上，極難回頭查到是這裡漏的。"""
    needs_isolation = _modules_building_manager_in_process(MARKER_MODULES["shell"])
    assert needs_isolation, "掃描結果為空，代表這道防護已失效（可能是掃描條件寫壞）"
    assert needs_isolation <= ISOLATED_MODULES, (
        f"這些 shell 測試會在行程內建立 DocumentManager 卻未隔離："
        f"{sorted(needs_isolation - ISOLATED_MODULES)}；"
        "請補進根 conftest.py 的 ISOLATED_MODULES")


def test_isolated_child_basetemp_is_separate_from_shared_basetemp():
    """子行程不可沿用父行程的 basetemp：pytest 對明確指定的 --basetemp 會在啟動時
    整個清空，沿用會把父行程正在使用的暫存目錄一起刪掉。"""
    one = _isolated_child_basetemp("tests/test_standalone_shell.py::test_a")
    two = _isolated_child_basetemp("tests/test_standalone_shell.py::test_b")
    shared = (ROOT / ".tmp" / "pytest").resolve()

    assert one != two
    assert one.resolve() != shared and shared not in one.resolve().parents
    assert one.parent.is_dir()      # pytest 只建 basetemp 自己那一層


def test_root_pytest_config_uses_project_temp_locations(pytestconfig):
    assert os.environ["QT_QPA_PLATFORM"] == "offscreen"
    assert Path(pytestconfig.getini("cache_dir")) == Path(".tmp/pytest_cache")
    basetemp = Path(pytestconfig.option.basetemp).resolve()
    approved_root = (ROOT / ".tmp/pytest").resolve()
    assert basetemp == approved_root or approved_root in basetemp.parents
    worker = os.environ.get("PYTEST_XDIST_WORKER")
    if worker:
        assert basetemp.name == f"popen-{worker}"
    mpl_dir = Path(os.environ["MPLCONFIGDIR"]).resolve()
    assert mpl_dir.parent == (ROOT / ".tmp/mplconfig").resolve()
    assert mpl_dir.is_dir()


def test_trend_record_keeps_counts_timings_durations_and_delta(tmp_path):
    previous = {
        "collection_count": 3,
        "layers": {"pure_db": {"count": 2, "elapsed_seconds": 1.25}},
    }
    record = build_trend_record(
        collection_node_ids=["a", "b", "c", "d"],
        layers={"pure_db": {"node_ids": ["a", "b", "c"], "elapsed_seconds": 1.5}},
        durations=[{"node_id": "b", "seconds": 0.4}],
        previous=previous,
    )

    assert record["collection_count"] == 4
    assert record["layers"]["pure_db"]["count"] == 3
    assert record["layers"]["pure_db"]["elapsed_seconds"] == 1.5
    assert record["durations"] == [{"node_id": "b", "seconds": 0.4}]
    assert record["delta"] == {
        "collection_count": 1,
        "layers": {"pure_db": {"count": 1, "elapsed_seconds": 0.25}},
    }

    output = tmp_path / "trend.jsonl"
    write_trend_record(output, record)
    assert json.loads(output.read_text(encoding="utf-8").splitlines()[0]) == record


def test_node_comparison_reports_exact_missing_and_extra_ids():
    assert compare_node_ids(["a", "b"], ["b", "c"]) == {
        "matches": False,
        "missing": ["a"],
        "extra": ["c"],
    }


def test_collection_record_preserves_complete_sorted_node_ids(tmp_path):
    output = tmp_path / "collection.json"
    items = [
        type("Item", (), {"nodeid": "tests/test_b.py::test_2"})(),
        type("Item", (), {"nodeid": "tests/test_a.py::test_1"})(),
    ]

    write_collection_record(items, output)

    assert json.loads(output.read_text(encoding="utf-8")) == {
        "count": 2,
        "node_ids": ["tests/test_a.py::test_1", "tests/test_b.py::test_2"],
    }


def test_unittest_ids_are_normalized_to_pytest_node_ids():
    assert unittest_id_to_pytest(
        "test_ticket_data.TestTicketNaturalSort.test_natural_key"
    ) == "tests/test_ticket_data.py::TestTicketNaturalSort::test_natural_key"


# --- 日期防呆遮蔽的單一來源契約（PITFALLS TST-4）--------------------------
# 遮蔽少了任何一條路徑，該路徑的測試就會卡在無人可按的確認框上「不結束」，
# 症狀是掛住而非紅燈，極難判讀（2026-08-06 兩層都踩過）。故用契約釘住。

def test_unittest_path_installs_date_guard_shim():
    """tests/__init__.py 必須在 unittest 跑法安裝遮蔽（conftest 載不到）。"""
    src = (ROOT / "tests" / "__init__.py").read_text(encoding="utf-8")
    assert "installAutoConfirm" in src
    assert "date_guard_shim" in src


def test_pytest_path_shares_the_same_shim():
    """conftest 的 fixture 必須用同一支 shim，不得自己再寫一份遮蔽。"""
    src = (ROOT / "conftest.py").read_text(encoding="utf-8")
    assert "from tests.date_guard_shim import installAutoConfirm" in src
    assert "date_guard.confirmBox" not in src


def test_no_test_module_patches_date_guard_itself():
    """個別測試不得自己 patch 第二份遮蔽——防呆改寫時會漏改那些。"""
    offenders = []
    for path in sorted((ROOT / "tests").glob("test_*.py")):
        src = path.read_text(encoding="utf-8")
        if path.name in ("test_date_guard.py", "test_date_guard_gui_pilot.py",
                         "test_pytest_infrastructure.py"):
            continue        # 防呆自己的專責測試，本來就要動它
        if "date_guard.confirmBox" in src or "confirmDateGap" in src:
            offenders.append(path.name)
    assert offenders == [], (
        f"這些測試自行遮蔽日期防呆，請改用 tests/date_guard_shim：{offenders}")
