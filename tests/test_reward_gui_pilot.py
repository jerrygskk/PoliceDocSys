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
from PySide6.QtCore import QDate, QEvent, QTimer, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QApplication, QLabel, QPushButton, QTableWidget, QTabWidget, QWidget,
)

from lib.db_schema import applySchema
from tabs.tab_reward import TabReward
from ui_utils.reward_dialog import RewardEditDialog
from ui_utils.table import setupPreviewTable
from ui_utils.widgets import LinkCursorFilter


SELECTORS = {
    "entry_date": "reward_date",
    "entry_sender": "reward_sender",
    "entry_reason": "reward_reason",
    "entry_recipients": "reward_recipients",
    "entry_table": "reward_table",
    "entry_table_object": "reward_tableWidget",
    "entry_submit": "btn_submit",
    "entry_submit_object": "btn_reward_submit",
    "edit_reason": "w_reason",
    "edit_recipients": "w_recipients",
    "edit_save": "btn_save",
}


@pytest.fixture
def reward_db(tmp_path):
    db_path = tmp_path / "reward-pilot.db"
    conn = sqlite3.connect(db_path)
    applySchema(conn)
    conn.execute(
        "INSERT INTO Ref_Personnel"
        "(staff_id,staff_name,is_active,sort_order) VALUES(?,?,?,?)",
        ("P01", "王小明", 1, 1),
    )
    conn.commit()
    conn.close()
    return str(db_path)


def fetch_reward(db_path, doc_id):
    conn = sqlite3.connect(db_path)
    try:
        return conn.execute(
            "SELECT create_date,register_date,sender_id,reason,recipients "
            "FROM Document_Reward WHERE doc_id=?",
            (doc_id,),
        ).fetchone()
    finally:
        conn.close()


def test_reward_lifecycle_pilot(qtbot, reward_db):
    """登錄頁送文者模式一條龍：登錄即發文 → 編號連結開修改視窗 → 儲存。

    未設定 report_mode_reward 即預設送文者輸入模式（reward 不吃舊
    report_input_mode 全域 fallback），故本測試不必寫任何設定。
    """
    tabs = QTabWidget()
    tabs.addTab(QWidget(), "登錄")
    qtbot.addWidget(tabs)
    entry = TabReward(tabs, reward_db)
    entry.setup(0)
    tabs.show()

    entry_date = getattr(entry, SELECTORS["entry_date"])
    entry_sender = getattr(entry, SELECTORS["entry_sender"])
    entry_reason = getattr(entry, SELECTORS["entry_reason"])
    entry_recipients = getattr(entry, SELECTORS["entry_recipients"])
    entry_table = getattr(entry, SELECTORS["entry_table"])
    entry_submit = getattr(entry, SELECTORS["entry_submit"])
    assert entry_table.objectName() == SELECTORS["entry_table_object"], "登錄: 表格 selector"
    assert entry_submit.objectName() == SELECTORS["entry_submit_object"], "登錄: 送出 selector"
    assert entry_date.isEnabled(), "登錄: 送文者模式發文日期應可填"
    assert entry_sender.isEnabled(), "登錄: 送文者模式發文人員應可填"

    # 登錄即發文
    entry_date.setDate(QDate(2026, 7, 24))
    sender_index = entry_sender.findData("P01")
    assert sender_index >= 0, "登錄: 找不到 P01"
    entry_sender.setCurrentIndex(sender_index)
    entry_reason.setText("協助查緝")
    entry_recipients.setCurrentText("王小明")
    qtbot.mouseClick(entry_submit, Qt.LeftButton)
    conn = sqlite3.connect(reward_db)
    try:
        created_row = conn.execute("SELECT doc_id FROM Document_Reward").fetchone()
    finally:
        conn.close()
    assert created_row is not None, "登錄: DB 應新增一列"
    doc_id = created_row[0]
    registered = fetch_reward(reward_db, doc_id)
    assert registered[0] == QDate.currentDate().toString("yyyy-MM-dd"), "登錄: create_date"
    assert registered[1] == "2026-07-24", "登錄: register_date 應為所填發文日期"
    assert registered[2] == "P01", "登錄: sender_id 應為所選發文人員"
    assert registered[3:] == ("協助查緝", "王小明"), "登錄: 事由或人員"
    assert entry_table.rowCount() == 1, "登錄: 預覽表應有一列"
    assert entry_table.item(0, 2).text() == "2026-07-24", "登錄: 預覽發文日期"

    # 編輯：由實際 QLabel.linkActivated 開啟實際 dialog，再按實際儲存鈕。
    label = entry_table.cellWidget(0, 1)
    assert isinstance(label, QLabel), "編輯: 編號 cell 應直接是 QLabel"

    def edit_visible_dialog():
        dialogs = [
            widget for widget in QApplication.topLevelWidgets()
            if isinstance(widget, RewardEditDialog) and widget.isVisible()
        ]
        assert len(dialogs) == 1, "編輯: 應只有一個可見 RewardEditDialog"
        dialog = dialogs[0]
        getattr(dialog, SELECTORS["edit_reason"]).setText("更新後事由")
        getattr(dialog, SELECTORS["edit_recipients"]).setCurrentText("王小明,名單外甲")
        qtbot.mouseClick(getattr(dialog, SELECTORS["edit_save"]), Qt.LeftButton)

    QTimer.singleShot(0, edit_visible_dialog)
    timed_out = {"value": False}
    edit_watchdog = QTimer()
    edit_watchdog.setSingleShot(True)

    def close_stuck_edit_dialogs():
        timed_out["value"] = True
        for widget in QApplication.topLevelWidgets():
            if isinstance(widget, RewardEditDialog) and widget.isVisible():
                widget.reject()
                widget.close()

    edit_watchdog.timeout.connect(close_stuck_edit_dialogs)
    edit_watchdog.start(5000)
    try:
        label.linkActivated.emit(str(doc_id))
    finally:
        edit_watchdog.stop()
        edit_watchdog.timeout.disconnect(close_stuck_edit_dialogs)
        edit_watchdog.deleteLater()
    assert not timed_out["value"], "編輯: 對話框未在 5 秒內完成"
    edited = fetch_reward(reward_db, doc_id)
    assert edited[1] == "2026-07-24", "編輯: register_date 不得改變"
    assert edited[2] == "P01", "編輯: sender_id 不得改變"
    assert edited[3:] == ("更新後事由", "王小明,名單外甲"), "編輯: DB 值"
    assert entry_table.item(0, 3).text() == "更新後事由", "編輯: 預覽事由"
    assert entry_table.item(0, 4).text() == "王小明,名單外甲", "編輯: 預覽人員"


def test_link_cursor_filter_ignores_deleted_table(qapp):
    """已刪除表格遺留的 event filter 收到事件時，不得解參考失效 Qt wrapper。"""
    table = QTableWidget()
    cursor_filter = LinkCursorFilter(table, 0)
    table.viewport().installEventFilter(cursor_filter)

    table.deleteLater()
    QApplication.sendPostedEvents(None, QEvent.DeferredDelete)

    assert cursor_filter._table is None


def test_preview_table_delayed_setup_stops_when_table_is_deleted(qapp):
    """預覽表刪除後，延後初始化回呼不得操作已失效的 table wrapper。"""
    table = QTableWidget()
    setupPreviewTable(table, ["欄位"])

    table.deleteLater()
    QApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    QTest.qWait(600)


def test_preview_table_nested_resize_retry_stops_when_table_is_deleted(qapp):
    """初始 resize 排出的零寬 retry 不得在 table 刪除後操作失效 wrapper。"""
    table = QTableWidget()
    table.setFixedSize(0, 0)
    setupPreviewTable(table, ["欄位"])

    QTest.qWait(250)  # 200ms 初始 resize 已因未顯示的零寬 viewport 排出 100ms retry
    table.deleteLater()
    QApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    QTest.qWait(200)
