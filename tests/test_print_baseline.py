# -*- coding: utf-8 -*-
"""列印基準工具的 manifest 與診斷行為測試。"""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "print_baseline.py"


def test_declared_matplotlib_pin_matches_manifest_and_runtime():
    requirements = (ROOT / "requirements-dev.txt").read_text(encoding="utf-8")
    match = re.search(r"(?m)^matplotlib==([^\s]+)$", requirements)
    assert match is not None
    declared_version = match.group(1)
    manifest = json.loads(
        (ROOT / "tests" / "print_baseline_manifest.json").read_text(
            encoding="utf-8"
        )
    )

    import matplotlib

    assert declared_version == manifest["environment"]["matplotlib_version"]
    assert declared_version == matplotlib.__version__


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
        "matplotlib_version",
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
    assert metadata["matplotlib_version"]
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
    rendered = []

    def _collect(_db_dir):
        rendered.append(_db_dir)
        return {"2026-01-01": {"__empty__": ("EMPTY", b"")}}

    monkeypatch.setattr(baseline, "_collect_with_mpl_config", _collect)
    monkeypatch.setattr(baseline, "environment_metadata", lambda: current)

    result = baseline.cmd_check(tmp_path)

    output = capsys.readouterr().out
    # 環境先行：不符就停在算圖之前。算完 101 張才說「環境不同」既浪費 90 秒，
    # 又會讓人把上百處差異誤判成程式回歸（實際發生過）。
    assert result == 3
    assert rendered == [], "環境不符時不得算圖"
    assert "停止比對" in output
    assert "記錄值" in output and "目前值" in output
    assert "old-regular.ttc" in output and "new-regular.ttc" in output
    assert "125" in output and "100" in output


def test_environment_drift_can_be_overridden_to_still_compare(
    tmp_path, monkeypatch, capsys
):
    """逃生口：明知環境不同、就是想看差異圖時仍要跑得動。"""
    baseline = _load_module()
    base_dir = tmp_path / "images"
    base_dir.mkdir()
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "environment": {"qt_version": "6.old"},
                "cases": {"2026-01-01": {"__empty__": "EMPTY"}},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(baseline, "BASE_DIR", str(base_dir))
    monkeypatch.setattr(baseline, "MANIFEST", str(manifest))
    monkeypatch.setattr(baseline, "DIFF_DIR", str(base_dir / "diff"))
    monkeypatch.setattr(baseline, "CASES", [("dbfile.db", "2026-01-01", "empty")])
    rendered = []

    def _collect(_db_dir):
        rendered.append(_db_dir)
        return {"2026-01-01": {"__empty__": ("EMPTY", b"")}}

    monkeypatch.setattr(baseline, "_collect_with_mpl_config", _collect)
    monkeypatch.setattr(baseline, "environment_metadata",
                        lambda: {"qt_version": "6.new"})

    result = baseline.cmd_check(tmp_path, allow_environment_drift=True)

    output = capsys.readouterr().out
    assert rendered == [tmp_path], "指定逃生口時仍要實際算圖比對"
    assert result == 1          # 影像雖相同，環境不同本身仍記為一處差異
    assert "allow-environment-drift" in output


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


def test_check_uses_manifest_when_candidate_image_directory_is_absent(
    tmp_path, monkeypatch
):
    baseline = _load_module()
    base_dir = tmp_path / "candidate-images"
    manifest = tmp_path / "manifest.json"
    environment = {
        "fonts": {},
        "matplotlib_version": "test",
        "qt_version": "test",
        "pyside6_version": "test",
        "windows_scaling_percent": 125,
    }
    manifest.write_text(
        json.dumps(
            {
                "environment": environment,
                "cases": {"2026-01-01": {"__empty__": "EMPTY"}},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(baseline, "BASE_DIR", str(base_dir))
    monkeypatch.setattr(baseline, "MANIFEST", str(manifest))
    monkeypatch.setattr(baseline, "DIFF_DIR", str(base_dir / "diff"))
    monkeypatch.setattr(
        baseline, "CASES", [("dbfile.db", "2026-01-01", "empty")]
    )
    monkeypatch.setattr(
        baseline,
        "_collect_with_mpl_config",
        lambda _db_dir: {"2026-01-01": {"__empty__": ("EMPTY", b"")}},
    )
    monkeypatch.setattr(baseline, "environment_metadata", lambda: environment)

    assert baseline.cmd_check(tmp_path) == 0
    assert not base_dir.exists()


def test_each_collect_run_uses_a_distinct_cleaned_mpl_config_directory(
    tmp_path, monkeypatch
):
    baseline = _load_module()
    seen = []

    def capture(_db_dir):
        path = Path(os.environ["MPLCONFIGDIR"])
        assert path.is_dir()
        seen.append(path)
        return {}

    monkeypatch.setattr(baseline, "_collect_with_mpl_config", capture)
    monkeypatch.setenv("MPLCONFIGDIR", str(tmp_path / "caller-config"))

    assert baseline.collect(tmp_path) == {}
    assert baseline.collect(tmp_path) == {}

    assert len(set(seen)) == 2
    assert all(not path.exists() for path in seen)
    assert os.environ["MPLCONFIGDIR"] == str(tmp_path / "caller-config")


def test_check_enters_one_mpl_config_before_metadata_and_render(tmp_path):
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps({"environment": {}, "cases": {}}), encoding="utf-8"
    )
    caller_config = tmp_path / "caller-mpl-config"
    caller_config.mkdir()
    probe = r'''
import json
import os
from pathlib import Path
import sys

import tools.print_baseline as baseline

baseline.MANIFEST = sys.argv[1]
baseline.BASE_DIR = sys.argv[2]
baseline.DIFF_DIR = str(Path(sys.argv[2]) / "diff")
baseline.CASES = []
seen = []
real_metadata = baseline.environment_metadata

def metadata():
    result = real_metadata()
    import matplotlib
    seen.append(["metadata", os.environ["MPLCONFIGDIR"], matplotlib.get_configdir()])
    return result

def render(_db_dir):
    import matplotlib
    seen.append(["render", os.environ["MPLCONFIGDIR"], matplotlib.get_configdir()])
    return {}

baseline.environment_metadata = metadata
baseline._collect_with_mpl_config = render
# 這支驗的是「metadata 與 render 共用同一個暫存 MPLCONFIGDIR」；探針的 manifest
# 環境是空的、必然與實際環境不符，故要開逃生口讓兩步都真的跑到。
result = baseline.cmd_check(Path.cwd(), allow_environment_drift=True)
paths = [entry[1] for entry in seen]
print(json.dumps({
    "result": result,
    "seen": seen,
    "paths_exist_after": [Path(path).exists() for path in paths],
    "restored_env": os.environ.get("MPLCONFIGDIR"),
}, ensure_ascii=False))
'''
    env = os.environ.copy()
    env["MPLCONFIGDIR"] = str(caller_config)
    env["PYTHONIOENCODING"] = "utf-8"
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            probe,
            str(manifest),
            str(tmp_path / "missing-candidate-images"),
        ],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert result.returncode == 0, result.stdout + result.stderr
    observed = json.loads(result.stdout.strip().splitlines()[-1])

    assert [entry[0] for entry in observed["seen"]] == ["metadata", "render"]
    mpl_paths = [entry[1] for entry in observed["seen"]]
    real_config_paths = [entry[2] for entry in observed["seen"]]
    assert len(set(mpl_paths)) == 1
    assert real_config_paths == mpl_paths
    assert mpl_paths[0] != str(caller_config)
    assert observed["paths_exist_after"] == [False, False]
    assert observed["restored_env"] == str(caller_config)
