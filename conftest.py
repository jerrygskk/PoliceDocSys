"""專案層 pytest 啟動設定、測試分層、行程隔離與執行證據記錄。"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest
from _pytest.reports import TestReport


ROOT = Path(__file__).resolve().parent
PRIMARY_MARKERS = ("pure", "db", "qt", "shell", "packaging")
MARKER_MODULES = {
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
        "test_base_tab.py", "test_combo_hint.py",
        "test_date_wheel_guard.py", "test_dbbrowse_sync.py",
        "test_dialog_disabled_style.py", "test_dialog_smoke.py",
        "test_dispatch_tab.py", "test_edit_dialog_optimistic_lock.py",
        "test_help_content_contract.py",
        "test_loading_screen_banner.py", "test_nullable_date.py",
        "test_pytest_qt_runtime.py", "test_report_mode_switch.py",
        "test_reset_gui_pilot.py", "test_restore_gui_pilot.py",
        "test_reward_browse.py", "test_reward_gui_pilot.py",
        "test_reward_integration.py", "test_reward_print.py",
        "test_reward_recipients.py", "test_reward_refresh.py",
        "test_reward_summary.py", "test_reward_tab.py",
        "test_settings_panel_pilot.py",
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


# 必須在任何測試模組 collection/import PySide6 或 matplotlib 前完成。
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
_worker = os.environ.get("PYTEST_XDIST_WORKER") or f"master-{os.getpid()}"
_mpl_dir = ROOT / ".tmp" / "mplconfig" / _worker
_mpl_dir.mkdir(parents=True, exist_ok=True)
os.environ["MPLCONFIGDIR"] = str(_mpl_dir)


# --- 行程隔離（PITFALLS TST-5 的處置）-------------------------------------
# test_standalone_shell.py 每支測試都自己建一個完整的 DocumentManager，一個
# 行程累積下來約 28 個。manager 底下有部分東西掛在比它長壽的宿主上（AuthManager
# 單例的 signal、QApplication 層的滾輪 guard／hover filter、各 combo 的 completer
# model 與 viewport event filter），回收時機不確定，累積到一定量後會在「下一次
# 大量配置 Qt 物件」的隨機位置 native crash（access violation）。崩點與測試身分
# 無關、只與累積量有關。
#
# 故本層改由父行程逐一派給子行程執行：一個子行程只建一個 manager，累積量從 28
# 降為 1，觸發條件在結構上不成立。這是隔離、不是修復——長壽掛載本身沒有被拆掉
# （方案 B，2026-08-01 實測兩條修法皆無效，見 PITFALLS TST-5）。
#
# ⚠️ 一次一支、序列執行，不是平行。正式 gate 仍不得加 -n（xdist 對 shell 層已
# 裁決退回 serial）。
ISOLATED_MODULES = {"test_logout_gui_pilot.py", "test_standalone_shell.py"}
ISOLATION_CHILD_ENV = "POLICEDOC_ISOLATED_CHILD"
ISOLATION_TIMEOUT_SEC = 300


def _isolated_child_basetemp(nodeid: str) -> Path:
    """子行程要有自己的 basetemp：pytest 對明確指定的 --basetemp 會在啟動時整個
    清空，沿用父行程那個會把父行程正在使用的暫存目錄一起刪掉。"""
    slug = re.sub(r"[^0-9A-Za-z]+", "_", nodeid).strip("_")[-60:].strip("_")
    base = ROOT / ".tmp" / "pytest-isolated" / (slug or "node")
    # pytest 只會建 basetemp 自己那一層，上層不存在會 FileNotFoundError。
    base.parent.mkdir(parents=True, exist_ok=True)
    return base


def _run_isolated(item) -> TestReport:
    cmd = [
        sys.executable, "-m", "pytest", item.nodeid,
        "-q", "--no-header", "-p", "no:cacheprovider",
        "--basetemp", str(_isolated_child_basetemp(item.nodeid)),
    ]
    env = dict(os.environ)
    env[ISOLATION_CHILD_ENV] = "1"
    env["QT_QPA_PLATFORM"] = "offscreen"
    # 子行程自己會記錄執行證據會覆蓋父行程的檔案，故一律移除。
    env.pop("PYTEST_RUN_RECORD", None)
    env.pop("PYTEST_COLLECTION_RECORD", None)
    # 子行程的訊息含中文；不指定就會用系統 codepage（本機 cp950）解讀而丟
    # UnicodeDecodeError，症狀是每支測試都莫名紅燈。
    env["PYTHONIOENCODING"] = "utf-8"

    started = time.perf_counter()
    try:
        result = subprocess.run(
            cmd, cwd=str(ROOT), env=env, capture_output=True, text=True,
            encoding="utf-8", errors="replace",
            timeout=ISOLATION_TIMEOUT_SEC,
        )
        returncode, stdout, stderr = result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired as exc:
        returncode = -1
        stdout = exc.stdout or ""
        stderr = (exc.stderr or "") + (
            f"\n子行程逾時（{ISOLATION_TIMEOUT_SEC} 秒）未結束，已終止。")
        if isinstance(stdout, bytes):
            stdout = stdout.decode("utf-8", "replace")
        if isinstance(stderr, bytes):
            stderr = stderr.decode("utf-8", "replace")
    duration = time.perf_counter() - started

    if returncode == 0:
        return TestReport(
            nodeid=item.nodeid, location=item.location, keywords={},
            outcome="passed", longrepr=None, when="call", duration=duration,
        )

    # 結束碼 !=0：可能是斷言失敗（1）、收集不到（5），也可能是 native crash
    # （Windows access violation 為 0xC0000005，回傳負值或大數）。三者都當失敗，
    # 並把子行程輸出原樣帶回，讓紅燈訊息足以直接行動。
    detail = (
        f"隔離子行程失敗（exit={returncode}）\n"
        f"指令：{' '.join(cmd)}\n"
        f"--- stdout ---\n{stdout}\n--- stderr ---\n{stderr}"
    )
    return TestReport(
        nodeid=item.nodeid, location=item.location, keywords={},
        outcome="failed", longrepr=detail, when="call", duration=duration,
    )


def pytest_runtest_protocol(item, nextitem):
    """隔離清單內的測試改派給子行程；其餘一律走 pytest 預設流程。

    子行程自己也會載入本檔，靠 ISOLATION_CHILD_ENV 認出身分並停用隔離，
    否則會無限遞迴地一直開子行程。"""
    if item.path.name not in ISOLATED_MODULES:
        return None
    if os.environ.get(ISOLATION_CHILD_ENV):
        return None

    ihook = item.ihook
    ihook.pytest_runtest_logstart(nodeid=item.nodeid, location=item.location)
    # setup／teardown 實際都在子行程內完成，父行程只補形式上的報告讓終端輸出
    # 與計數正常。
    ihook.pytest_runtest_logreport(report=TestReport(
        nodeid=item.nodeid, location=item.location, keywords={},
        outcome="passed", longrepr=None, when="setup", duration=0.0,
    ))
    ihook.pytest_runtest_logreport(report=_run_isolated(item))
    ihook.pytest_runtest_logreport(report=TestReport(
        nodeid=item.nodeid, location=item.location, keywords={},
        outcome="passed", longrepr=None, when="teardown", duration=0.0,
    ))
    ihook.pytest_runtest_logfinish(nodeid=item.nodeid, location=item.location)
    return True


# --- 日期防呆的測試處置（PITFALLS TST-4）---------------------------------
# 實作在 tests/date_guard_shim.py，是 pytest 與 unittest 共用的唯一一份；
# unittest 跑法載不到本檔，由 tests/__init__.py 匯入同一支安裝。
from tests.date_guard_shim import OWN_TESTS as DATE_GUARD_OWN_TESTS   # noqa: E402
from tests.date_guard_shim import installAutoConfirm                  # noqa: E402


@pytest.fixture(autouse=True)
def _auto_confirm_date_guard(request, monkeypatch):
    if request.path.name in DATE_GUARD_OWN_TESTS:
        return
    installAutoConfirm(monkeypatch)


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
