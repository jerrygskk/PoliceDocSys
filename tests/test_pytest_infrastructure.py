import json
import os
from pathlib import Path

import pytest

from conftest import (
    MARKER_MODULES, PRIMARY_MARKERS, classify_test_module,
    write_collection_record,
)
from tools.pytest_trend import (
    build_trend_record, compare_node_ids, unittest_id_to_pytest,
    write_trend_record,
)


ROOT = Path(__file__).resolve().parents[1]


EXPECTED_MARKER_MODULES = {
    "pure": {
        "test_app_lock.py", "test_app_profile.py", "test_archive_text.py",
        "test_environment_contract.py", "test_error_msg.py",
        "test_no_pii.py", "test_pytest_infrastructure.py",
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
        "test_help_content_contract.py",
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
