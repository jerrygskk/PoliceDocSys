"""GUI pilot：自助取號模式登錄 → 列印頁結算發文（四種流程全走）。

**這支測試的重點是那條接縫**：待結算的判定條件是「發文日期為 NULL 或空字串」，
而登錄端各流程寫進去的哨兵**並不一致**——陳報（刑案／一般）寫 `None`，
敘獎與罰單寫空字串 `''`。兩邊是分開維護的：登錄端在各自分頁裡決定送什麼值，
結算端在 `SETTLE_META` 的 SQL 裡決定撈什麼值。若改用 SQL 直接塞待結算資料，
等於把「登錄端會寫成什麼」這個假設抄進測試，將來有人改了哨兵，兩邊測試都綠、
公文卻會從待結算清單消失。故本檔**一律用真實登錄分頁送出**。

四種流程各有獨立的模式開關（`report_mode_*`），故四種全做，並以 `FLOWS` 表驅動，
新增結算型態時補一列即可。

替身（其餘全用真的）：
- 各式 modal 提示與確認框：離線環境的 modal 會無限等待（PITFALLS TST-4）。
- 結算視窗的 `exec()`：改為就地驅動，理由同上。
- 產生簽收表：只驗一條龍有接上、日期正確；實際繪圖由列印基準網負責
  （PRINTING.md §4），不在此重畫。

只建單一分頁、不建 `DocumentManager`，故留在 qt 層、不需行程隔離（PITFALLS TST-5）。
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

from PySide6.QtCore import QDate
from PySide6.QtWidgets import QTabWidget, QWidget

from lib.auth_manager import AuthManager
from lib.db_schema import applySchema
from lib.db_seed import seedFreshDb
from lib.db_utils import REPORT_MODE_KEYS, setSetting
import ui_utils.settle_dialog as settle_module
from ui_utils.settle_dialog import SettleDialog, count_unissued, load_unissued
import tabs.tab_print as print_module
import tabs.tab_report as report_module
import tabs.tab_reward as reward_module
import tabs.tab_ticket as ticket_module
from tabs.tab_print import TabPrint
from tabs.tab_report import TabReport
from tabs.tab_reward import TabReward
from tabs.tab_ticket import TabTicket


STAFF_ID = "P01"          # 種子既有的假人員（王小明）
ISSUE_DATE = QDate(2026, 8, 20)
ISSUE_DATE_STR = "2026-08-20"

# 四種流程的接縫對照：登錄端寫什麼哨兵、結算端該把哪兩欄補起來。
# ⚠️ 新增結算型態時補一列即可，不要另外複製一段流程。
FLOWS = {
    "crim":   {"table": "Document_Criminal", "date_col": "report_date",
               "sentinel": None, "label": "刑案"},
    "gen":    {"table": "Document_General",  "date_col": "report_date",
               "sentinel": None, "label": "一般"},
    "reward": {"table": "Document_Reward",   "date_col": "register_date",
               "sentinel": "",   "label": "敘獎"},
    "ticket": {"table": "Document_Ticket",   "date_col": "register_date",
               "sentinel": "",   "label": "罰單"},
}


@pytest.fixture
def db_path(tmp_path):
    """暫存 DB：真實 schema ＋ 真實種子（參照表、文號序號、預設設定）。"""
    path = tmp_path / "settle-pilot.db"
    conn = sqlite3.connect(path)
    applySchema(conn)
    seedFreshDb(conn)
    conn.commit()
    conn.close()
    return str(path)


@pytest.fixture(autouse=True)
def _admin_role():
    """登錄與結算都以管理身分進行（唯讀鎖不是本檔要驗的東西）。

    ⚠️ 收尾必須拆掉 `role_changed` 的連線：`AuthManager` 是單例，各分頁在
    `setup()` 時把自己的處理函式掛上去，本檔建立的分頁在測試結束後被回收，
    連線卻留在單例上；之後**別支測試**切換身分就會打到已釋放的 C++ 物件
    （`RuntimeError: Internal C++ object already deleted`），紅在毫不相干的地方。
    作法比照 `tests/test_standalone_shell.py`。"""
    auth = AuthManager.instance()
    auth._role = "admin"
    yield
    try:
        auth.role_changed.disconnect()
    except (RuntimeError, TypeError):
        pass   # 本來就沒有連線
    auth._role = "user"


@pytest.fixture
def quiet_dialogs(monkeypatch):
    """攔掉所有 modal：確認框固定回「確定」，其餘只記標題供斷言。"""
    seen = {"confirm": [], "warning": [], "critical": [], "info": [], "error": []}

    def _install(module):
        for name, bucket in (("msgWarning", "warning"), ("msgCritical", "critical"),
                             ("msgInfo", "info")):
            if hasattr(module, name):
                monkeypatch.setattr(
                    module, name,
                    lambda title, text=None, *a, _b=bucket, **kw: seen[_b].append(title))
        if hasattr(module, "reportError"):
            monkeypatch.setattr(
                module, "reportError",
                lambda title, exc=None, *a, **kw: seen["error"].append(title))
        if hasattr(module, "confirmBox"):
            monkeypatch.setattr(
                module, "confirmBox",
                lambda title, text=None, **kw: (seen["confirm"].append(title), True)[1])

    for module in (settle_module, report_module, reward_module, ticket_module,
                   print_module):
        _install(module)
    return seen


# ── 登錄端：四種流程各自的真實分頁驅動 ──────────────────────────

def _host(qtbot):
    tabs = QTabWidget()
    tabs.addTab(QWidget(), "頁")
    qtbot.addWidget(tabs)
    return tabs


def _pick(combo, data):
    idx = combo.findData(data)
    assert idx != -1, f"下拉選單找不到 {data!r}"
    combo.setCurrentIndex(idx)


def _submit_report(qtbot, db_path, kind, *, subject):
    """陳報頁：kind 為 crim（型態頁 0）或 gen（型態頁 1）。"""
    tab = TabReport(_host(qtbot), db_path)
    tab.setup(0)
    tab.type_tabbar.setCurrentIndex(0 if kind == "crim" else 1)
    if kind == "crim":
        _pick(tab.crim_casetype, "CT01")
        _pick(tab.crim_processor, STAFF_ID)
        tab.crim_subject.setText(subject)
        tab.crim_occdate.setText("2026-08-01")
    else:
        _pick(tab.gen_processor, STAFF_ID)
        tab.gen_subject.setText(subject)
    tab._submit()
    return tab


def _submit_reward(qtbot, db_path, *, subject):
    tab = TabReward(_host(qtbot), db_path)
    tab.setup(0)
    tab.reward_reason.setText(subject)
    tab.reward_recipients.setCurrentText("王小明")
    tab._submit()
    return tab


def _submit_ticket(qtbot, db_path, *, ticket_no):
    tab = TabTicket(_host(qtbot), db_path)
    tab.setup(0)
    _pick(tab.ticket_issuer, STAFF_ID)
    tab.ticket_no.setText(ticket_no)
    tab._submit()
    return tab


def _enable_self_service(db_path, *keys):
    for key in (keys or FLOWS):
        setSetting(db_path, REPORT_MODE_KEYS[key], "1")


def _submit_one(qtbot, db_path, key):
    if key in ("crim", "gen"):
        _submit_report(qtbot, db_path, key, subject=f"{FLOWS[key]['label']}測試案由")
    elif key == "reward":
        _submit_reward(qtbot, db_path, subject="敘獎測試事由")
    else:
        _submit_ticket(qtbot, db_path, ticket_no="TP12345678")


def _rows(db_path, key):
    flow = FLOWS[key]
    conn = sqlite3.connect(db_path)
    try:
        return conn.execute(
            f"SELECT doc_id, {flow['date_col']}, sender_id FROM {flow['table']}"
        ).fetchall()
    finally:
        conn.close()


# ── 結算端 ────────────────────────────────────────────────────

def _open_settle(qtbot, db_path):
    """建真實結算視窗但不 exec()（離線 modal 會卡死）。"""
    dlg = SettleDialog(db_path)
    qtbot.addWidget(dlg)
    return dlg


def _confirm_settle(dlg, *, date=ISSUE_DATE, sender=STAFF_ID):
    dlg.issue_date.setDate(date)
    _pick(dlg.cmb_sender, sender)
    dlg.btn_confirm.click()


def _issue_externally(db_path, key, doc_id):
    """模擬別台電腦搶先發文：單執行緒、一行 SQL，無時序競賽。"""
    flow = FLOWS[key]
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            f"UPDATE {flow['table']} SET {flow['date_col']}=?, sender_id=?"
            " WHERE doc_id=?", ("2026-08-19", STAFF_ID, doc_id))
        conn.commit()
    finally:
        conn.close()


# ── 測試 ──────────────────────────────────────────────────────

@pytest.mark.parametrize("key", list(FLOWS))
def test_self_service_entry_writes_sentinel_that_settle_side_can_find(
        qtbot, db_path, quiet_dialogs, key):
    """登錄端寫下的哨兵，結算端必須撈得到——這就是那條接縫。

    刻意不比對哨兵的字面值以外，還一併確認它出現在結算端**自己的查詢**裡：
    只驗欄位值的話，改了 SQL 條件仍會漏。"""
    _enable_self_service(db_path, key)

    _submit_one(qtbot, db_path, key)

    rows = _rows(db_path, key)
    assert len(rows) == 1, f"{FLOWS[key]['label']}應寫入一筆"
    doc_id, date_val, sender_id = rows[0]
    assert date_val == FLOWS[key]["sentinel"], "自助模式的發文日期哨兵不符"
    assert sender_id is None, "自助模式不得寫入送文者"
    assert count_unissued(db_path).get(key) == 1
    assert [str(r["doc_id"]) for r in load_unissued(db_path).get(key, [])] == [doc_id]
    assert not quiet_dialogs["warning"] and not quiet_dialogs["error"]


def test_settle_fills_issue_date_and_sender_for_all_four_flows(
        qtbot, db_path, quiet_dialogs):
    """四種流程同時待結算 → 一次結算全部補上發文日與送文者。"""
    _enable_self_service(db_path)
    for key in FLOWS:
        _submit_one(qtbot, db_path, key)
    assert sum(count_unissued(db_path).values()) == 4

    dlg = _open_settle(qtbot, db_path)
    _confirm_settle(dlg)

    assert dlg.settled() is True
    assert dlg.settledDate().toString("yyyy-MM-dd") == ISSUE_DATE_STR
    for key in FLOWS:
        _doc_id, date_val, sender_id = _rows(db_path, key)[0]
        assert date_val == ISSUE_DATE_STR, f"{FLOWS[key]['label']}發文日期未補上"
        assert sender_id == STAFF_ID, f"{FLOWS[key]['label']}送文者未補上"
    assert sum(count_unissued(db_path).values()) == 0
    assert quiet_dialogs["confirm"] == ["確認結算"]


def test_unchecked_row_stays_pending(qtbot, db_path, quiet_dialogs):
    """取消勾選的那筆維持未發文（部分結算語意）。"""
    _enable_self_service(db_path, "crim", "reward")
    _submit_one(qtbot, db_path, "crim")
    _submit_one(qtbot, db_path, "reward")

    dlg = _open_settle(qtbot, db_path)
    reward_rows = [r for r in range(dlg._tbl.rowCount())
                   if dlg._tbl._row_key(r) == "reward"]
    assert len(reward_rows) == 1
    dlg._tbl.set_row_checked(reward_rows[0], False)
    _confirm_settle(dlg)

    assert _rows(db_path, "crim")[0][1] == ISSUE_DATE_STR
    assert _rows(db_path, "reward")[0][1] == "", "未勾選的敘獎不得被結算"
    assert count_unissued(db_path).get("reward") == 1


def test_ticket_conflict_rolls_back_every_flow_and_warns(
        qtbot, db_path, quiet_dialogs):
    """罰單是 strict 型態：確認前被別台搶先發文 → 整批取消。

    刑案／敘獎在同一個交易裡已經寫進去了，必須一起退回；視窗要把這個例外
    接住、顯示白話衝突訊息並重載清單，而不是當成程式錯誤寫進 error.log。
    這段接住的程式碼在視窗裡，底層 `settle_selected` 的測試看不到。"""
    _enable_self_service(db_path)
    for key in ("crim", "reward", "ticket"):
        _submit_one(qtbot, db_path, key)

    dlg = _open_settle(qtbot, db_path)          # 清單此刻三筆都還是未發文
    ticket_doc_id = _rows(db_path, "ticket")[0][0]
    _issue_externally(db_path, "ticket", ticket_doc_id)

    _confirm_settle(dlg)

    assert quiet_dialogs["warning"] == ["結算衝突"]
    assert not quiet_dialogs["error"], "併發是正常事件，不得當成程式錯誤"
    assert dlg.settled() is False
    assert dlg.result() != int(dlg.DialogCode.Accepted), "衝突時不得 accept"
    assert _rows(db_path, "crim")[0][1] is None, "刑案必須跟著整批退回"
    assert _rows(db_path, "reward")[0][1] == "", "敘獎必須跟著整批退回"
    # 重載後清單只剩仍未發文的兩筆
    assert count_unissued(db_path).get("ticket") == 0
    assert dlg._tbl.rowCount() == 2


def test_print_tab_shows_settle_entry_and_chains_to_receipt(
        qtbot, db_path, quiet_dialogs, monkeypatch):
    """列印頁：自助模式下結算群組現身，結算成功後接著以結算日產生簽收表。

    只驗一條龍有接上與日期正確；實際繪圖由列印基準網負責，不在此重畫。"""
    _enable_self_service(db_path)
    _submit_one(qtbot, db_path, "crim")

    tab = TabPrint(_host(qtbot), db_path)
    tab.setup(0)
    assert tab._settle_group.isVisibleTo(tab._settle_group.parentWidget()), \
        "自助模式下結算群組應現身"
    assert "刑案" in tab.lbl_unissued.text()

    generated = []
    monkeypatch.setattr(TabPrint, "_on_generate",
                        lambda self: generated.append(
                            self.date_edit.date().toString("yyyy-MM-dd")))

    def _drive(self):
        _confirm_settle(self)
        return int(self.result())

    monkeypatch.setattr(settle_module.SettleDialog, "exec", _drive)

    tab._on_settle()

    assert _rows(db_path, "crim")[0][1] == ISSUE_DATE_STR
    assert generated == [ISSUE_DATE_STR], "應以結算當日的日期產生簽收表"
    assert sum(count_unissued(db_path).values()) == 0


def test_sender_mode_keeps_fields_editable_and_requires_sender(
        qtbot, db_path, quiet_dialogs):
    """未開自助模式（送文者登錄）：發文欄位可填，且沒選發文人員要被擋下。
    這是自助模式的反面，確保反灰與免填不會外溢到送文者模式。"""
    tab = TabReport(_host(qtbot), db_path)
    tab.setup(0)
    assert tab.rpt_date.isEnabled()
    assert tab.rpt_sender.isEnabled()

    tab.type_tabbar.setCurrentIndex(0)
    _pick(tab.crim_casetype, "CT01")
    _pick(tab.crim_processor, STAFF_ID)
    tab.crim_subject.setText("送文者模式測試")
    tab.crim_occdate.setText("2026-08-01")
    tab.rpt_sender.setCurrentIndex(-1)          # 未選發文人員

    tab._submit()

    assert quiet_dialogs["warning"] == ["欄位未填"]
    assert _rows(db_path, "crim") == [], "必填未齊不得寫入"
