# tests/test_release_documentation_contract.py
"""入庫技術文件（DEVELOPER.md）的內容契約：發布流程 gate、陳報模式與結算、
跨功能影響對照表、設定 key 名、資料庫結構。

原本一半在本檔、一半散在 `test_reward_integration.py`（那支同時檢查敘獎程式、
HELP、速查卡與本文件四件事，紅燈看不出哪裡出事）。**斷言內容一字未改**，
只是集中到名副其實的檔案裡。HELP／速查卡的部分在
`test_help_content_contract.py`。

⚠️ 這些斷言刻意逐字比對文件敘述：改了文案就會紅，這是「文件與程式要一起改」
的提醒機制。紅了就照著改斷言，不要為了讓它不紅而把比對放寬。
"""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _developer():
    return (ROOT / "DEVELOPER.md").read_text(encoding="utf-8")


def _release_steps():
    developer = _developer()
    release_section = developer.split("### 發布流程", 1)[1].split(
        "### 打包（spec 檔", 1
    )[0]
    gate_start = release_section.index("**推送前完整 gate**")
    push_start = release_section.index("**版號進版並推上去**")
    return release_section, gate_start, push_start


# ── 發布流程 ───────────────────────────────────────────────────

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
    developer = _developer()
    test_section = developer.split("### 單元測試（tests/）", 1)[1].split(
        "---", 1
    )[0]

    assert "無 pytest 環境備援" in test_section
    assert "python -m unittest discover -s tests" in test_section


def test_fresh_build_must_precede_the_bundle_dependency_check():
    release_section, _, _ = _release_steps()

    assert "刪除既有 `build/`／`dist/`" in release_section
    fresh_build_pos = release_section.index("**兩支 exe 都要重建**")
    checker_pos = release_section.index(
        "兩支 fresh build 完成後立即於同次執行")
    assert fresh_build_pos < checker_pos
    assert "兩支 fresh build 完成後立即於同次執行" in release_section
    assert "不得沿用舊 `build/` 或 `PKG-00.toc`" in release_section
    assert (
        "python tools/check_bundle_deps.py Police-Document-Manager Police-Entry-Manager"
        in release_section[checker_pos:])


def test_bundle_checker_is_documented_as_fail_closed():
    assert "候選 PE 只要來源缺失或無法解析即 **fail-closed**" in _developer()


# ── 陳報模式／結算 ─────────────────────────────────────────────

def test_new_tab_checklist_points_at_per_flow_report_mode():
    developer = _developer()

    assert "新 Tab 若有日期／發文欄位要接發文結算模式" not in developer
    assert ("會發文的輸入頁才依需求接陳報模式（`REPORT_MODE_KEYS` 逐流程一把"
            in developer)


def test_settle_meta_covers_four_document_kinds_with_strict_ticket():
    developer = _developer()

    assert "成員為刑案／一般／敘獎／罰單" in developer
    assert "罰單 meta 帶 `strict=True`，任一衝突即整批 rollback" in developer


def test_ticket_print_attribution_always_follows_register_date():
    assert "唯一依 `Document_Ticket.register_date`" in _developer()


# ── 跨功能影響對照表與設定 key ─────────────────────────────────

def test_ticket_row_in_cross_impact_table_lists_every_touchpoint():
    developer = _developer()

    assert "| **罰單登錄**（`Document_Ticket`／`print_title_ticket`）" in developer
    assert ("所有 CRUD 寫入唯一走 `lib/ticket_utils.py`；"
            "結算發文由 `SETTLE_META` 在共用 transaction 更新" in developer)


def test_settings_keys_for_reward_and_ticket_are_documented():
    developer = _developer()

    assert "`input_lock_reward`／`input_lock_ticket`" in developer
    assert "`report_mode_reward`" in developer
    assert "`print_title_ticket`" in developer
    # 敘獎發文頁已整頁移除，文件不得殘留其入口
    assert "`tab_reward_issue.handleIssue`" not in developer


# ── 資料庫結構 ─────────────────────────────────────────────────

def test_five_document_tables_and_four_views_are_documented():
    developer = _developer()

    assert "五張公文主表" in developer
    views_section = developer.split("### Views", 1)[1].split("\n---\n", 1)[0]
    for view_name in ("View_Task_Full", "View_Criminal_Full",
                      "View_General_Full", "Document_Ticket_Full"):
        assert view_name in views_section
    assert "`idx_task/crim/gen/reward/ticket_lastmod`" in developer
