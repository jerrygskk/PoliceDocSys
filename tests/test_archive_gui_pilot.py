"""GUI pilot：檔案歸檔一條龍（選公文 → 比對 PDF → 歸檔預覽 → 執行歸檔）。

既有的 `test_archive_runtime_guards.py` 用假物件直接驅動處理函式，驗的是
「權限與檔名／DB 一致性」那一段；本檔補的是**沒有人測過的前半段**——真實版面
有沒有把候選 PDF 列出來、歸檔預覽有沒有把四格填對、按鈕按下去會不會真的走到
那些處理函式。歸檔是全系統最難善後的流程（同時動實體檔案與 DB），值得先被
自動化看住。

只建 `TabArchive` 一個分頁、不建 `DocumentManager`，故留在 qt 層、不需行程隔離
（判準見 PITFALLS TST-5）。

兩個必要的替身，其餘全用真的：
- **選資料夾的原生視窗**：`QFileDialog` 關不掉也點不了，直接餵路徑給
  `_loadFolder`（`_pickFolder` 唯一的工作就是拿到路徑後呼叫它）。
- **確認框／錯誤框**：離線環境的 modal 會無限等待（PITFALLS TST-4）。
"""

import os
import sqlite3

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    import pytest
except ModuleNotFoundError as exc:  # 讓 unittest discover 在缺 pytest 時記為「跳過」而非 ImportError
    if exc.name != "pytest":
        raise
    import unittest

    raise unittest.SkipTest("需 pytest/pytest-qt，請以 pytest 執行此檔")

from PySide6.QtWidgets import QPushButton, QStackedWidget, QTabWidget, QWidget

from lib.auth_manager import AuthManager
from lib.db_schema import applySchema
import tabs.tab_archive as archive_module
from tabs.tab_archive import TabArchive


DOC_ID = "1"
SUBJECT = "竊盜案嫌疑人陳大明"
PDF_NAME = "1140801-竊盜案嫌疑人陳大明-掃描檔.pdf"


@pytest.fixture
def archive_env(tmp_path):
    """暫存 DB（真實 schema，含 View）＋暫存 PDF 資料夾；絕不碰真實 dbfile.db。"""
    db_path = tmp_path / "archive-pilot.db"
    conn = sqlite3.connect(db_path)
    applySchema(conn)
    conn.execute(
        "INSERT INTO Ref_Personnel(staff_id,staff_name,is_active,sort_order)"
        " VALUES(?,?,?,?)",
        ("P01", "王小明", 1, 1),
    )
    conn.execute(
        "INSERT INTO Document_Criminal"
        "(doc_id,create_date,report_date,processor_id,subject_summary,"
        " reporter_name,is_reported,is_electronic)"
        " VALUES(?,?,?,?,?,?,?,?)",
        (DOC_ID, "2026-08-01", "2026-08-01", "P01", SUBJECT, "李小華", 0, None),
    )
    conn.commit()
    conn.close()

    pdf_dir = tmp_path / "scans"
    pdf_dir.mkdir()
    pdf = pdf_dir / PDF_NAME
    pdf.write_bytes(b"%PDF-1.4\n%%EOF\n")
    return {"db": str(db_path), "folder": str(pdf_dir), "pdf": pdf}


@pytest.fixture(autouse=True)
def _reset_role():
    """AuthManager 是單例；每支測試前後都回到最低權限，避免互相汙染。"""
    AuthManager.instance()._role = "user"
    yield
    AuthManager.instance()._role = "user"


@pytest.fixture
def quiet_dialogs(monkeypatch):
    """攔掉所有 modal：確認框固定回「確定」，錯誤／提示只記錄標題供斷言。"""
    recorded = {"confirm": [], "critical": [], "info": [], "error": []}
    monkeypatch.setattr(
        archive_module, "confirmBox",
        lambda title, text, **kw: (recorded["confirm"].append(title), True)[1])
    monkeypatch.setattr(
        archive_module, "msgCritical",
        lambda title, text, *a, **kw: recorded["critical"].append(title))
    monkeypatch.setattr(
        archive_module, "msgInfo",
        lambda title, text, *a, **kw: recorded["info"].append(title))
    monkeypatch.setattr(
        archive_module, "reportError",
        lambda title, exc, *a, **kw: recorded["error"].append(title))
    return recorded


def _build_tab(qtbot, db_path, *, role="admin"):
    AuthManager.instance()._role = role
    tabs = QTabWidget()
    tabs.addTab(QWidget(), "檔案歸檔")
    qtbot.addWidget(tabs)
    tab = TabArchive(tabs, db_path)
    tab.setup(0)
    tabs.show()
    return tab


def _pdf_row_buttons(tab, key, row):
    """候選清單「操作」欄的兩顆鈕：0=開啟 PDF、1=歸檔預覽。"""
    cell = tab._ui[key]["pdf"].cellWidget(row, 0)
    return cell.findChildren(QPushButton)


def _fetch(db_path):
    conn = sqlite3.connect(db_path)
    try:
        return conn.execute(
            "SELECT is_electronic, is_reported FROM Document_Criminal"
            " WHERE doc_id=?", (DOC_ID,)).fetchone()
    finally:
        conn.close()


def _drive_to_preview(qtbot, archive_env):
    """共用前半段：建頁 → 選待歸檔公文 → 餵資料夾 → 點「歸檔預覽」。"""
    tab = _build_tab(qtbot, archive_env["db"])
    doc_table = tab._ui["crim"]["doc"]
    assert doc_table.rowCount() == 1, "待歸檔清單應有那筆未歸檔刑案"

    doc_table.selectRow(0)                       # 觸發 itemSelectionChanged → 鎖定該筆
    assert tab._selected["crim"] == DOC_ID

    tab._loadFolder("crim", archive_env["folder"])   # 代替原生選資料夾視窗
    pdf_table = tab._ui["crim"]["pdf"]
    assert pdf_table.rowCount() == 1, "資料夾內的 PDF 應出現在候選清單"
    assert pdf_table.item(0, 2).text() == PDF_NAME

    _pdf_row_buttons(tab, "crim", 0)[1].click()      # 歸檔預覽
    return tab


def _preview_values(tab, key="crim"):
    u = tab._ui[key]
    return {f: u[f].text() for f in ("h_pk", "h_date", "h_subj", "h_proc")}


def test_archive_full_flow_renames_pdf_and_updates_db(
        qtbot, archive_env, quiet_dialogs):
    """一條龍：預覽四格自動填好 → 執行歸檔 → 實體檔改名、DB 同步、清單少一筆。"""
    tab = _drive_to_preview(qtbot, archive_env)

    preview = _preview_values(tab)
    assert preview["h_pk"] == DOC_ID
    assert all(preview[f] for f in ("h_date", "h_subj", "h_proc")), \
        f"四格預覽不得有空欄（空欄會被 _doArchive 擋下）：{preview}"
    expected_name = "-".join(
        preview[f] for f in ("h_pk", "h_date", "h_subj", "h_proc")) + ".pdf"
    assert expected_name in tab._ui["crim"]["final"].text()

    tab._ui["crim"]["archive"].click()

    new_path = os.path.join(archive_env["folder"], expected_name)
    assert os.path.exists(new_path), "實體 PDF 應已改名"
    assert not archive_env["pdf"].exists(), "原檔名不應殘留"
    assert _fetch(archive_env["db"]) == (expected_name, 1), \
        "電子檔欄位應寫入新檔名，且紙本一併標記已歸"
    assert not quiet_dialogs["critical"] and not quiet_dialogs["error"]
    assert quiet_dialogs["confirm"] == ["確認歸檔"]

    # 歸檔後：待歸檔清單清空、預覽四格清空
    assert tab._ui["crim"]["doc"].rowCount() == 0
    assert all(v == "" for v in _preview_values(tab).values())


def test_restricted_role_sees_permission_wall_instead_of_content(
        qtbot, archive_env):
    """受限身分進歸檔頁只能看到權限提示頁；升為管理身分後才切到內容頁。

    既有 guard 測試驗的是「直接呼叫處理函式會被擋」，這裡驗的是使用者根本
    看不到那些按鈕——兩道防線都要在。"""
    tab = _build_tab(qtbot, archive_env["db"], role="user")
    stack = tab._inner.findChild(QStackedWidget, "outer_stack")
    gate_index = stack.indexOf(stack.findChild(QWidget, "page_gate"))
    content_index = stack.indexOf(stack.findChild(QWidget, "page_content"))
    assert gate_index != -1 and content_index != -1
    assert stack.currentIndex() == gate_index

    auth = AuthManager.instance()
    auth._role = "admin"
    auth.role_changed.emit("admin")
    assert stack.currentIndex() == content_index


def test_archive_blocked_when_subject_cleared(
        qtbot, archive_env, quiet_dialogs):
    """主旨被清空 → 擋下並提示，檔案不改名、DB 不動。
    只剩系統號碼的檔名毫無識別度，寧可擋在前面。"""
    tab = _drive_to_preview(qtbot, archive_env)
    tab._ui["crim"]["h_subj"].setText("")

    tab._ui["crim"]["archive"].click()

    assert quiet_dialogs["critical"] == ["資料不完整"]
    assert not quiet_dialogs["confirm"], "資料不齊時不該走到確認框"
    assert archive_env["pdf"].exists()
    assert _fetch(archive_env["db"]) == (None, 0)


def test_archive_blocked_when_target_filename_exists(
        qtbot, archive_env, quiet_dialogs):
    """目標檔名已存在 → 擋下，兩個檔案都原封不動（不得覆蓋既有歸檔）。"""
    tab = _drive_to_preview(qtbot, archive_env)
    preview = _preview_values(tab)
    clash = os.path.join(archive_env["folder"], "-".join(
        preview[f] for f in ("h_pk", "h_date", "h_subj", "h_proc")) + ".pdf")
    with open(clash, "wb") as fh:
        fh.write(b"%PDF-1.4\nplaceholder\n%%EOF\n")

    tab._ui["crim"]["archive"].click()

    assert quiet_dialogs["critical"] == ["歸檔失敗"]
    assert archive_env["pdf"].exists(), "原始 PDF 應留在原地"
    assert os.path.getsize(clash) > 0, "既有同名檔不得被覆蓋"
    assert _fetch(archive_env["db"]) == (None, 0)
