from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _release_steps():
    developer = (ROOT / "DEVELOPER.md").read_text(encoding="utf-8")
    release_section = developer.split("### 發布流程", 1)[1].split(
        "### 打包（spec 檔", 1
    )[0]
    gate_start = release_section.index("**推送前完整 gate**")
    push_start = release_section.index("**版號進版並推上去**")
    return release_section, gate_start, push_start


def test_release_gate_cannot_be_moved_after_version_push():
    _, gate_start, push_start = _release_steps()

    assert gate_start < push_start


def test_all_required_commands_must_remain_inside_release_gate():
    release_section, gate_start, push_start = _release_steps()
    gate_section = release_section[gate_start:push_start]
    required_commands = (
        'python -m pytest tests -q -m "not shell" --ignore=tests/test_no_pii.py',
        'python -m pytest tests -q -m shell --ignore=tests/test_no_pii.py',
        "python -m unittest tests.test_no_pii",
    )

    for command in required_commands:
        assert command in gate_section


def test_unittest_discover_is_documented_only_as_a_pytest_fallback():
    developer = (ROOT / "DEVELOPER.md").read_text(encoding="utf-8")
    test_section = developer.split("### 單元測試（tests/）", 1)[1].split(
        "---", 1
    )[0]

    assert "無 pytest 環境備援" in test_section
    assert "python -m unittest discover -s tests" in test_section
