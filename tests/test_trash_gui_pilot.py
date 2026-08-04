"""GUI pilot：回收筒還原一條龍（列清單 → 過濾 → 選一筆 → 還原回原文號）。

刪除是清空式的（欄位清空、保留 `doc_id`），刪除前的整列快照存進回收筒；還原就是
把快照寫回那個空殼列。既有 `tests/test_trash.py` 測的是底層三支函式
（`snapshotRow`／`writeTrash`／`restoreFromTrash`）的 round-trip，**面板那層沒有
測試**——清單怎麼列、過濾、權限保底、確認框、還原後寫稽核與通知相鄰分頁重載，
全部沒人看過。

值得看住的兩點：
- **還原後必須通知瀏覽／歸檔頁重載**：沒通知的話資料明明回來了，畫面上卻還是空的，
  使用者會以為還原失敗而重複操作。
- **已被還原過或不存在的紀錄**要給明確提示，且**不得**觸發重載通知。

替身（其餘全用真的）：確認框與提示框（離線 modal 會無限等待，PITFALLS TST-4）。

只建面板一個控制器、不建 `DocumentManager`，故留在 qt 層、不需行程隔離
（PITFALLS TST-5）。
"""

import os
import shutil
import sqlite3

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    import pytest
except ModuleNotFoundError as exc:  # 讓 unittest discover 在缺 pytest 時記為「跳過」而非 ImportError
    if exc.name != "pytest":
        raise
    import unittest

    raise unittest.SkipTest("需 pytest/pytest-qt，請以 pytest 執行此檔")

from PySide6.QtWidgets import (
    QLabel, QLineEdit, QPushButton, QTableWidget, QWidget)

from lib.auth_manager import AuthManager
from lib.db_schema import applySchema
from lib.db_seed import seedFreshDb
from lib.db_utils import getConn, snapshotRow, writeTrash
import ui_utils.trash_panel as trash_module
from ui_utils.trash_panel import TrashPanel


CRIM_SUBJECT = "誤刪的竊盜案"
GEN_SUBJECT = "誤刪的一般陳報"

# 清空式刪除（比照瀏覽頁：清空業務欄、保留 doc_id）
_CLEAR_CRIM = (
    "UPDATE Document_Criminal SET create_date=NULL, report_date=NULL,"
    " sender_id=NULL, subject_summary=NULL, processor_id=NULL,"
    " is_reported=0, is_electronic='' WHERE doc_id=?")
_CLEAR_GEN = (
    "UPDATE Document_General SET create_date=NULL, report_date=NULL,"
    " sender_id=NULL, subject=NULL, processor_id=NULL WHERE doc_id=?")


@pytest.fixture(scope="session")
def _db_template(tmp_path_factory):
    """套完 schema 與種子的空殼；各測試複製取用，省下重建 schema 的固定成本。"""
    path = tmp_path_factory.mktemp("trash-template") / "template.db"
    conn = sqlite3.connect(path)
    applySchema(conn)
    seedFreshDb(conn)
    conn.commit()
    conn.close()
    return str(path)


@pytest.fixture
def db_path(tmp_path, _db_template):
    """兩筆已軟刪除的公文（刑案、一般），走真正的「快照 → 寫回收筒 → 清空」流程。"""
    path = tmp_path / "trash-pilot.db"
    shutil.copy2(_db_template, path)
    conn = sqlite3.connect(path)
    conn.execute(
        "INSERT INTO Document_Criminal"
        "(doc_id,create_date,report_date,processor_id,subject_summary,"
        " reporter_name,is_reported) VALUES(?,?,?,?,?,?,?)",
        ("1", "2026-08-01", "2026-08-02", "P01", CRIM_SUBJECT, "陳小美", 1))
    conn.execute(
        "INSERT INTO Document_General"
        "(doc_id,create_date,report_date,processor_id,subject)"
        " VALUES(?,?,?,?,?)",
        ("2", "2026-08-01", "2026-08-02", "P01", GEN_SUBJECT))
    conn.commit()

    for table, doc_id, subject, person, clear_sql in (
            ("Document_Criminal", "1", CRIM_SUBJECT, "王小明", _CLEAR_CRIM),
            ("Document_General", "2", GEN_SUBJECT, "李大同", _CLEAR_GEN)):
        payload = snapshotRow(conn, table, doc_id)
        writeTrash(conn, table_name=table, doc_id=doc_id, payload=payload,
                   subject=subject, doc_person=person, deleted_role="admin")
        conn.execute(clear_sql, (doc_id,))
    conn.commit()
    conn.close()
    return str(path)


@pytest.fixture(autouse=True)
def _admin_role():
    """還原僅管理身分可為。"""
    AuthManager.instance()._role = "admin"
    yield
    AuthManager.instance()._role = "user"


@pytest.fixture
def quiet_dialogs(monkeypatch):
    """攔掉所有 modal：確認框固定回「確定」，其餘只記標題供斷言。"""
    seen = {"confirm": [], "warning": [], "critical": []}
    monkeypatch.setattr(
        trash_module, "confirmBox",
        lambda title, text=None, **kw: (seen["confirm"].append(title), True)[1])
    for name, bucket in (("msgWarning", "warning"), ("msgCritical", "critical")):
        monkeypatch.setattr(
            trash_module, name,
            lambda title, text=None, *a, _b=bucket, **kw: seen[_b].append(title))
    return seen


def _make_panel(qtbot, db_path):
    """面板持有 .ui 元件參照（非 QWidget 子類），故此處自備等價元件。"""
    parent = QWidget()
    qtbot.addWidget(parent)
    table = QTableWidget(0, 6, parent)
    reloaded = []
    panel = TrashPanel(
        db_path=db_path, table=table,
        filter_edit=QLineEdit(parent), restore_btn=QPushButton(parent),
        reload_btn=QPushButton(parent), count_label=QLabel(parent),
        hint_label=QLabel(parent), parent=parent,
        sibling_reload=lambda key: reloaded.append(key))
    panel.load()
    return panel, reloaded


def _row_of(panel, subject):
    for row in range(panel.table.rowCount()):
        if panel.table.item(row, 3).text() == subject:
            return row
    raise AssertionError(f"清單中找不到主旨為 {subject!r} 的列")


def _crim(db_path):
    conn = sqlite3.connect(db_path)
    try:
        return conn.execute(
            "SELECT subject_summary, report_date, is_reported"
            " FROM Document_Criminal WHERE doc_id='1'").fetchone()
    finally:
        conn.close()


def _trash_count(db_path):
    conn = sqlite3.connect(db_path)
    try:
        return conn.execute("SELECT COUNT(*) FROM Trash_Documents").fetchone()[0]
    finally:
        conn.close()


def _audit_details(db_path):
    conn = sqlite3.connect(db_path)
    try:
        return [r[0] for r in conn.execute(
            "SELECT detail FROM Audit_Log WHERE action='還原'").fetchall()]
    finally:
        conn.close()


# ── 測試 ──────────────────────────────────────────────────────

def test_list_shows_deleted_rows_newest_first_with_readable_fields(
        qtbot, db_path):
    """清單依刪除順序新到舊，類別與刪除身分要顯示成中文，計數標籤同步。"""
    panel, _ = _make_panel(qtbot, db_path)

    assert panel.table.rowCount() == 2
    assert panel.table.item(0, 3).text() == GEN_SUBJECT, "最新刪除的應排最前"
    assert panel.table.item(1, 3).text() == CRIM_SUBJECT
    assert panel.table.item(1, 1).text() == "1", "文號要列出來（還原會回填原文號）"
    assert panel.table.item(1, 2).text() == "刑案"
    assert panel.table.item(1, 4).text() == "王小明"
    assert panel.table.item(1, 5).text() == "管理者", "刪除身分應中文化"
    assert panel.count_label.text() == "顯示 2／共 2 筆"


def test_filter_matches_subject_and_person(qtbot, db_path):
    """過濾同時吃主旨與對象人，計數標籤顯示「顯示 N／共 M 筆」。"""
    panel, _ = _make_panel(qtbot, db_path)

    panel.filter_edit.setText("竊盜")
    assert panel.table.rowCount() == 1
    assert panel.table.item(0, 3).text() == CRIM_SUBJECT
    assert panel.count_label.text() == "顯示 1／共 2 筆"

    panel.filter_edit.setText("李大同")          # 改用對象人
    assert panel.table.rowCount() == 1
    assert panel.table.item(0, 3).text() == GEN_SUBJECT

    panel.filter_edit.setText("查無此物")
    assert panel.table.rowCount() == 0
    assert panel.count_label.text() == "顯示 0／共 2 筆"


def test_restore_writes_data_back_audits_and_notifies_sibling_tab(
        qtbot, db_path, quiet_dialogs):
    """還原：資料回填原文號、回收筒少一筆、寫稽核、通知相鄰分頁重載、清單刷新。

    通知那步特別要緊——沒通知的話資料明明回來了，瀏覽頁畫面上卻還是空的，
    使用者會以為還原失敗而重複操作。"""
    panel, reloaded = _make_panel(qtbot, db_path)
    assert _crim(db_path) == (None, None, 0), "前置：該列已被清空成空殼"

    panel.table.setCurrentCell(_row_of(panel, CRIM_SUBJECT), 0)
    panel.restore_btn.click()

    assert _crim(db_path) == (CRIM_SUBJECT, "2026-08-02", 1), "整列應原樣回填"
    assert _trash_count(db_path) == 1
    assert any(CRIM_SUBJECT in d for d in _audit_details(db_path))
    assert reloaded == ["crim"], "應通知瀏覽／歸檔頁重載刑案那張表"
    assert quiet_dialogs["confirm"] == ["還原誤刪"]
    assert panel.table.rowCount() == 1, "還原後清單應刷新"


def test_restore_without_selection_warns_and_does_nothing(
        qtbot, db_path, quiet_dialogs):
    """沒選取就按還原 → 提示請先選取，不動資料。"""
    panel, reloaded = _make_panel(qtbot, db_path)
    panel.table.setCurrentCell(-1, -1)

    panel.restore_btn.click()

    assert quiet_dialogs["warning"] == ["請選擇項目"]
    assert not quiet_dialogs["confirm"]
    assert _trash_count(db_path) == 2
    assert reloaded == []


def test_cancelling_confirm_does_nothing(qtbot, db_path, quiet_dialogs, monkeypatch):
    """確認框取消 → 不還原、不寫稽核、不通知。"""
    monkeypatch.setattr(trash_module, "confirmBox",
                        lambda title, text=None, **kw: False)
    panel, reloaded = _make_panel(qtbot, db_path)
    panel.table.setCurrentCell(_row_of(panel, CRIM_SUBJECT), 0)

    panel.restore_btn.click()

    assert _crim(db_path) == (None, None, 0)
    assert _trash_count(db_path) == 2
    assert _audit_details(db_path) == []
    assert reloaded == []


def test_non_admin_restore_has_no_side_effect(qtbot, db_path, quiet_dialogs):
    """回收筒頁僅管理身分可見，但仍要有保底：非管理身分直接觸發完全無副作用。"""
    panel, reloaded = _make_panel(qtbot, db_path)
    panel.table.setCurrentCell(_row_of(panel, CRIM_SUBJECT), 0)
    AuthManager.instance()._role = "archive"

    panel.restore_btn.click()

    assert _crim(db_path) == (None, None, 0)
    assert _trash_count(db_path) == 2
    assert not quiet_dialogs["confirm"] and not quiet_dialogs["warning"]
    assert reloaded == []


def test_already_restored_entry_reports_failure_without_notifying(
        qtbot, db_path, quiet_dialogs):
    """別台已先還原（回收筒那列不在了）→ 明確提示無法還原，且**不得**通知重載。
    通知了會讓使用者看到「更新中」卻什麼也沒變，誤以為系統壞掉。"""
    panel, reloaded = _make_panel(qtbot, db_path)
    row = _row_of(panel, CRIM_SUBJECT)
    panel.table.setCurrentCell(row, 0)
    conn = getConn(db_path)                       # 模擬他機搶先還原
    conn.execute("DELETE FROM Trash_Documents WHERE doc_id='1'")
    conn.commit()
    conn.close()

    panel.restore_btn.click()

    assert quiet_dialogs["warning"] == ["無法還原"]
    assert _crim(db_path) == (None, None, 0)
    assert reloaded == []
    assert panel.table.rowCount() == 1, "清單仍應刷新成最新狀態"


def test_missing_trash_table_shows_empty_list_without_crashing(
        qtbot, db_path):
    """缺 `Trash_Documents` 的舊資料庫 → 空清單，不得拋例外。"""
    conn = sqlite3.connect(db_path)
    conn.execute("DROP TABLE Trash_Documents")
    conn.commit()
    conn.close()

    panel, _ = _make_panel(qtbot, db_path)

    assert panel.table.rowCount() == 0
    assert panel.count_label.text() == "顯示 0／共 0 筆"
