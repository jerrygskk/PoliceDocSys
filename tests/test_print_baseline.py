# -*- coding: utf-8 -*-
"""列印基準工具的 manifest 與診斷行為測試。"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "print_baseline.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("print_baseline_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_manifest_is_written_to_tracked_tests_path():
    baseline = _load_module()

    assert Path(baseline.MANIFEST).resolve() == (
        ROOT / "tests" / "print_baseline_manifest.json"
    )
    assert Path(baseline.BASE_DIR).resolve() == ROOT / "docs" / "print_baseline"


def test_generated_database_directory_is_applied_to_all_ten_cases(tmp_path):
    baseline = _load_module()

    cases = baseline.resolve_cases(tmp_path)

    assert len(cases) == 10
    assert {Path(db) for db, _date, _desc in cases} == {
        tmp_path / "dbfile.db",
        tmp_path / "dbfile_multiline_title.db",
    }
    assert [date for _db, date, _desc in cases] == [
        "2026-05-11",
        "2026-02-23",
        "2026-06-22",
        "2026-07-26",
        "2026-07-25",
        "2026-01-01",
        "2026-08-10",
        "2026-08-11",
        "2026-08-10",
        "2026-08-11",
    ]


def test_environment_metadata_records_portable_render_dependencies():
    baseline = _load_module()

    metadata = baseline.environment_metadata()

    assert set(metadata) == {
        "fonts",
        "qt_version",
        "pyside6_version",
        "windows_scaling_percent",
    }
    assert set(metadata["fonts"]) == {"regular", "bold"}
    for font in metadata["fonts"].values():
        assert set(font) == {"file", "version"}
        assert Path(font["file"]).name == font["file"]
        assert font["version"]
    assert metadata["qt_version"]
    assert metadata["pyside6_version"]
    assert isinstance(metadata["windows_scaling_percent"], int)
    assert metadata["windows_scaling_percent"] > 0


def test_check_prints_recorded_and_current_environment_side_by_side(
    tmp_path, monkeypatch, capsys
):
    baseline = _load_module()
    base_dir = tmp_path / "images"
    base_dir.mkdir()
    manifest = tmp_path / "manifest.json"
    recorded = {
        "fonts": {
            "regular": {"file": "old-regular.ttc", "version": "1.0"},
            "bold": {"file": "old-bold.ttc", "version": "1.0"},
        },
        "qt_version": "6.old",
        "pyside6_version": "6.old",
        "windows_scaling_percent": 125,
    }
    current = {
        "fonts": {
            "regular": {"file": "new-regular.ttc", "version": "2.0"},
            "bold": {"file": "new-bold.ttc", "version": "2.0"},
        },
        "qt_version": "6.new",
        "pyside6_version": "6.new",
        "windows_scaling_percent": 100,
    }
    manifest.write_text(
        json.dumps(
            {
                "environment": recorded,
                "cases": {"2026-01-01": {"__empty__": "EMPTY"}},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(baseline, "BASE_DIR", str(base_dir))
    monkeypatch.setattr(baseline, "MANIFEST", str(manifest))
    monkeypatch.setattr(baseline, "DIFF_DIR", str(base_dir / "diff"))
    monkeypatch.setattr(
        baseline,
        "CASES",
        [("dbfile.db", "2026-01-01", "empty")],
    )
    monkeypatch.setattr(
        baseline,
        "collect",
        lambda _db_dir: {"2026-01-01": {"__empty__": ("EMPTY", b"")}},
    )
    monkeypatch.setattr(baseline, "environment_metadata", lambda: current)

    result = baseline.cmd_check(tmp_path)

    output = capsys.readouterr().out
    assert result == 1
    assert "記錄值" in output and "目前值" in output
    assert "old-regular.ttc" in output and "new-regular.ttc" in output
    assert "125" in output and "100" in output


def test_missing_baseline_prints_complete_rebuild_commands(
    tmp_path, monkeypatch, capsys
):
    baseline = _load_module()
    db_dir = tmp_path / "generated-db"
    monkeypatch.setattr(baseline, "BASE_DIR", str(tmp_path / "missing-images"))
    monkeypatch.setattr(baseline, "MANIFEST", str(tmp_path / "missing.json"))

    result = baseline.cmd_check(db_dir)

    output = capsys.readouterr().out
    assert result == 2
    assert f"python tools/seed_print_baseline.py {db_dir}" in output
    assert (
        f"python tools/print_baseline.py --db-dir {db_dir} --save --force"
        in output
    )
