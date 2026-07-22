import os
import sqlite3

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QDate, QTimer, Qt
from PySide6.QtWidgets import (
    QApplication, QLabel, QPushButton, QTabWidget, QWidget,
)

from lib.db_schema import applySchema
from tabs.tab_reward import TabReward
from tabs.tab_reward_issue import TabRewardIssue
from ui_utils.reward_dialog import RewardEditDialog


SELECTORS = {
    "entry_reason": "reward_reason",
    "entry_recipients": "reward_recipients",
    "entry_table": "reward_table",
    "entry_table_object": "reward_tableWidget",
    "entry_submit": "btn_submit",
    "entry_submit_object": "btn_reward_submit",
    "issue_number": "lineEdit",
    "issue_table": "table",
    "issue_date": "issue_date",
    "issue_sender": "issue_sender",
    "issue_input_button": "btn_reward_input",
    "issue_button": "btn_reward_issue",
    "edit_reason": "w_reason",
    "edit_recipients": "w_recipients",
    "edit_save": "btn_save",
    "pending_set": "_pending",
    "pending_banner": "_pending_banner",
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


def test_reward_lifecycle_pilot(qtbot, reward_db, monkeypatch):
    monkeypatch.setattr("tabs.tab_reward_issue.confirmBox", lambda *a, **k: True)
    monkeypatch.setattr("tabs.tab_reward_issue.msgInfo", lambda *a, **k: None)

    tabs = QTabWidget()
    tabs.addTab(QWidget(), "登錄")
    tabs.addTab(QWidget(), "發文")
    qtbot.addWidget(tabs)
    entry = TabReward(tabs, reward_db)
    issue = TabRewardIssue(tabs, reward_db)
    entry.setup(0)
    issue.setup(1)
    tabs.show()

    entry_reason = getattr(entry, SELECTORS["entry_reason"])
    entry_recipients = getattr(entry, SELECTORS["entry_recipients"])
    entry_table = getattr(entry, SELECTORS["entry_table"])
    entry_submit = getattr(entry, SELECTORS["entry_submit"])
    issue_number = getattr(issue, SELECTORS["issue_number"])
    issue_table = getattr(issue, SELECTORS["issue_table"])
    issue_date = getattr(issue, SELECTORS["issue_date"])
    issue_sender = getattr(issue, SELECTORS["issue_sender"])
    issue_input = tabs.widget(1).findChild(
        QPushButton, SELECTORS["issue_input_button"]
    )
    issue_button = tabs.widget(1).findChild(
        QPushButton, SELECTORS["issue_button"]
    )
    assert entry_table.objectName() == SELECTORS["entry_table_object"], "登錄: 表格 selector"
    assert entry_submit.objectName() == SELECTORS["entry_submit_object"], "登錄: 送出 selector"
    assert issue_input is not None, "待發: 找不到輸入按鈕"
    assert issue_button is not None, "發文: 找不到發文按鈕"

    # 登錄
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
    assert registered[1] == "", "登錄: register_date 應為空字串"
    assert registered[2] is None, "登錄: sender_id 應為 NULL"
    assert registered[3:] == ("協助查緝", "王小明"), "登錄: 事由或人員"
    assert entry_table.rowCount() == 1, "登錄: 預覽表應有一列"

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
    label.linkActivated.emit(str(doc_id))
    edited = fetch_reward(reward_db, doc_id)
    assert edited[1] == "", "編輯: register_date 不得改變"
    assert edited[2] is None, "編輯: sender_id 不得改變"
    assert edited[3:] == ("更新後事由", "王小明,名單外甲"), "編輯: DB 值"
    assert entry_table.item(0, 3).text() == "更新後事由", "編輯: 預覽事由"
    assert entry_table.item(0, 4).text() == "王小明,名單外甲", "編輯: 預覽人員"

    # 待發：加入 UI queue 不得修改 DB。
    tabs.setCurrentIndex(1)
    issue_number.setText(str(doc_id))
    qtbot.mouseClick(issue_input, Qt.LeftButton)
    pending = fetch_reward(reward_db, doc_id)
    assert issue_table.rowCount() == 1, "待發: 表格應有一列"
    pending_set = getattr(issue, SELECTORS["pending_set"])
    pending_banner = getattr(issue, SELECTORS["pending_banner"])
    assert pending_set == {str(doc_id)}, "待發: pending set"
    assert not pending_banner.isHidden(), "待發: banner 應顯示"
    assert pending[1:3] == ("", None), "待發: DB 不得改變"

    # 發文：production 保留該列，只更新第 3 欄並清除 pending/banner。
    issue_date.setDate(QDate(2026, 7, 24))
    sender_index = issue_sender.findData("P01")
    assert sender_index >= 0, "發文: 找不到 P01"
    issue_sender.setCurrentIndex(sender_index)
    qtbot.mouseClick(issue_button, Qt.LeftButton)
    issued = fetch_reward(reward_db, doc_id)
    assert issued == (
        QDate.currentDate().toString("yyyy-MM-dd"),
        "2026-07-24", "P01", "更新後事由", "王小明,名單外甲",
    ), "發文: DB 日期、人員、事由或受獎人不符"
    assert issue_table.rowCount() == 1, "發文: production 應保留該列"
    assert issue_table.item(0, 3).text() == "2026-07-24", "發文: UI 日期"
    assert pending_set == set(), "發文: pending 應清空"
    assert pending_banner.isHidden(), "發文: banner 應隱藏"
