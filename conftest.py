"""專案層 pytest 啟動設定、測試分層與執行證據記錄。"""
from __future__ import annotations

import json
import os
import shutil
import time
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parent
PRIMARY_MARKERS = ("pure", "db", "qt", "shell", "packaging")
MARKER_MODULES = {
    "pure": {
        "test_app_lock.py", "test_app_profile.py", "test_archive_text.py",
        "test_error_msg.py", "test_no_pii.py", "test_pytest_infrastructure.py",
        "test_ref_sort.py", "test_release_documentation_contract.py",
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
        "test_archive_runtime_guards.py", "test_base_tab.py", "test_combo_hint.py",
        "test_date_wheel_guard.py", "test_dbbrowse_sync.py", "test_dialog_smoke.py",
        "test_loading_screen_banner.py", "test_nullable_date.py",
        "test_pytest_qt_runtime.py", "test_report_mode_switch.py",
        "test_reward_browse.py", "test_reward_gui_pilot.py",
        "test_reward_integration.py", "test_reward_print.py",
        "test_reward_recipients.py", "test_reward_refresh.py",
        "test_reward_summary.py", "test_reward_tab.py",
        "test_settle_checkbox_alignment.py", "test_settle_chip_visibility.py",
        "test_standalone_browse.py", "test_standalone_settings.py",
        "test_ticket_browse.py", "test_ticket_runtime_cas.py",
        "test_ticket_tab.py", "test_ui_load.py", "test_window_geometry.py",
    },
    "shell": {
        "test_lazy_tab_loading.py", "test_standalone_shell.py",
        "test_startup_failure.py",
    },
    "packaging": {
        "test_bundle_deps.py", "test_print_baseline.py", "test_pyi_prune.py",
        "test_standalone_packaging.py",
    },
}


# 必須在任何測試模組 collection/import PySide6 或 matplotlib 前完成。
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
_worker = os.environ.get("PYTEST_XDIST_WORKER") or f"master-{os.getpid()}"
_mpl_dir = ROOT / ".tmp" / "mplconfig" / _worker
_mpl_dir.mkdir(parents=True, exist_ok=True)
os.environ["MPLCONFIGDIR"] = str(_mpl_dir)


def classify_test_module(module_name: str) -> str:
    matches = [
        marker for marker, modules in MARKER_MODULES.items()
        if module_name in modules
    ]
    if len(matches) != 1:
        raise pytest.UsageError(
            f"{module_name} 必須恰好屬於一個主層 marker，目前為 {matches!r}；"
            "請更新根目錄 conftest.py 的 MARKER_MODULES")
    return matches[0]


def write_collection_record(items, path):
    node_ids = sorted(item.nodeid for item in items)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "count": len(node_ids),
        "node_ids": node_ids,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def pytest_collection_modifyitems(config, items):
    for item in items:
        marker = classify_test_module(item.path.name)
        existing = [m.name for m in item.iter_markers() if m.name in PRIMARY_MARKERS]
        if existing and existing != [marker]:
            raise pytest.UsageError(
                f"{item.nodeid} 的主層 marker 與模組分類衝突：{existing!r} != {marker}")
        if not existing:
            item.add_marker(getattr(pytest.mark, marker))
    record_path = os.environ.get("PYTEST_COLLECTION_RECORD")
    if record_path and not hasattr(config, "workerinput"):
        write_collection_record(items, record_path)


def pytest_configure(config):
    config._policedoc_executed_nodes = set()
    config._policedoc_durations = {}


def pytest_runtest_logstart(nodeid, location):
    # serial 與 xdist controller 都會收到實際派送/開始執行的 node。
    config = getattr(pytest, "_policedoc_active_config", None)
    if config is not None:
        config._policedoc_executed_nodes.add(nodeid)


@pytest.hookimpl(tryfirst=True)
def pytest_sessionstart(session):
    pytest._policedoc_active_config = session.config
    session.config._policedoc_started_at = time.perf_counter()


def pytest_runtest_logreport(report):
    config = getattr(pytest, "_policedoc_active_config", None)
    if config is None:
        return
    config._policedoc_executed_nodes.add(report.nodeid)
    durations = config._policedoc_durations
    durations[report.nodeid] = durations.get(report.nodeid, 0.0) + report.duration


def pytest_sessionfinish(session, exitstatus):
    config = session.config
    record_path = os.environ.get("PYTEST_RUN_RECORD")
    if record_path and not hasattr(config, "workerinput"):
        path = Path(record_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        durations = sorted(
            (
                {"node_id": nodeid, "seconds": round(seconds, 6)}
                for nodeid, seconds in config._policedoc_durations.items()
            ),
            key=lambda row: (-row["seconds"], row["node_id"]),
        )
        path.write_text(json.dumps({
            "exitstatus": int(exitstatus),
            "elapsed_seconds": round(
                time.perf_counter() - config._policedoc_started_at, 6),
            "node_ids": sorted(config._policedoc_executed_nodes),
            "durations": durations[:20],
        }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if hasattr(pytest, "_policedoc_active_config"):
        del pytest._policedoc_active_config
    shutil.rmtree(_mpl_dir, ignore_errors=True)
