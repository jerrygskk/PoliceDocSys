# -*- coding: utf-8 -*-
import os
import sqlite3
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QDate
from PySide6.QtWidgets import (
    QApplication, QComboBox, QDateEdit, QLabel, QLineEdit, QTableWidget,
    QTabWidget, QWidget,
)

_app = QApplication.instance() or QApplication([])


class TestRewardIssue(unittest.TestCase):
    def setUp(self):
        from tabs.tab_reward_issue import TabRewardIssue

        tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        tmp.close()
        self.db_path = tmp.name
        conn = sqlite3.connect(self.db_path)
        conn.executescript("""
            CREATE TABLE Document_Reward (
                doc_id TEXT PRIMARY KEY,
                create_date TEXT,
                register_date TEXT,
                sender_id INTEGER,
                reason TEXT,
                recipients TEXT
            );
            CREATE TABLE Ref_Personnel (
                staff_id INTEGER PRIMARY KEY,
                staff_name TEXT,
                is_active INTEGER,
                sort_order INTEGER
            );
            CREATE TABLE Ref_Departments (
                dept_id INTEGER PRIMARY KEY,
                dept_name TEXT,
                is_active INTEGER,
                sort_order INTEGER
            );
            INSERT INTO Ref_Personnel VALUES (7, '王小明', 1, 1);
        """)
        conn.commit()
        conn.close()

        self.tabs = QTabWidget()
        self.tabs.addTab(QWidget(), "敘獎發文")
        self.tab = TabRewardIssue(self.tabs, self.db_path)
        self.tab.lineEdit = QLineEdit()
        self.tab.table = QTableWidget(0, 6)
        self.tab.issue_date = QDateEdit()
        self.tab.issue_date.setDate(QDate(2026, 7, 21))
        self.tab.issue_sender = QComboBox()
        self.tab.issue_sender.setEditable(True)
        self.tab.issue_sender.addItem("", None)
        self.tab.issue_sender.addItem("王小明", 7)
        self.tab.issue_sender.setCurrentIndex(1)
        self.tab._pending = set()
        self.tab._pending_banner = QLabel()

        self.reward_page = SimpleNamespace(reward_data_dirty=False)
        self.browse_page = SimpleNamespace(
            _forceReload=lambda: None,
            _pending_reload_keys=set(),
        )
        self.tab._manager = SimpleNamespace(
            tabs={3: self.reward_page, 4: self.tab, 6: self.browse_page})

    def tearDown(self):
        self.tabs.deleteLater()
        try:
            os.unlink(self.db_path)
        except PermissionError:
            pass

    def _insert(self, doc_id, register_date, *, create_date="2026-07-01"):
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            "INSERT INTO Document_Reward "
            "(doc_id, create_date, register_date, sender_id, reason, recipients) "
            "VALUES (?, ?, ?, NULL, ?, ?)",
            (doc_id, create_date, register_date, f"事由-{doc_id}", f"人員-{doc_id}"),
        )
        conn.commit()
        conn.close()

    def _query(self, doc_id):
        self.tab.lineEdit.setText(doc_id)
        self.tab.handleQuery()

    def test_query_classifies_missing_deleted_unissued_and_reissued(self):
        self._insert("DEL", None)
        self._insert("NEW", "")
        self._insert("OLD", "2026-06-30")

        with patch("tabs.tab_reward_issue.msgWarning") as warning:
            self._query("MISS")
            warning.assert_called_once_with("查無資料", "找不到編號「MISS」")

        with patch("tabs.tab_reward_issue.msgWarning") as warning:
            self._query("DEL")
            warning.assert_called_once_with("查無資料", "編號「DEL」已被刪除")

        self._query("NEW")
        self._query("OLD")
        self.assertEqual(self.tab.table.rowCount(), 2)
        self.assertEqual(self.tab.table.item(0, 1).text(), "NEW")
        self.assertIsNone(self.tab.table.cellWidget(0, 1))
        self.assertEqual(self.tab.table.item(0, 3).text(), "")
        old_date = self.tab.table.item(1, 3)
        self.assertEqual(old_date.text(), "2026-06-30")
        self.assertEqual(old_date.foreground().color().name(), "#e67e22")
        self.assertEqual(old_date.toolTip(), "原發文日期，發文後將被覆蓋")
        self.assertEqual(self.tab._pending, {"NEW", "OLD"})

        with patch("tabs.tab_reward_issue.msgInfo") as info:
            self._query("OLD")
            info.assert_called_once_with("提示", "「OLD」已在清單中")
        self.assertEqual(self.tab.table.rowCount(), 2)

    def test_issue_guard_skips_concurrently_deleted_and_counts_reissue(self):
        self._insert("NEW", "")
        self._insert("OLD", "2026-06-30")
        self._query("NEW")
        self._query("OLD")

        conn = sqlite3.connect(self.db_path)
        conn.execute("UPDATE Document_Reward SET register_date=NULL WHERE doc_id='NEW'")
        conn.commit()
        conn.close()

        with patch("tabs.tab_reward_issue.confirmBox", return_value=True) as confirm, \
                patch("tabs.tab_reward_issue.msgInfo") as info, \
                patch("tabs.tab_reward_issue.msgWarning") as warning:
            self.tab.handleIssue()

        confirm_text = confirm.call_args.args[1]
        self.assertIn("共 2 筆敘獎（其中 1 筆將覆蓋原發文日期）", confirm_text)
        warning.assert_called_once_with(
            "部分未更新", "有 1 筆在發文前已被刪除，本次未變動")
        info.assert_called_once_with(
            "完成", "已成功更新 1 筆發文日期（2026-07-21）")

        conn = sqlite3.connect(self.db_path)
        rows = dict(conn.execute(
            "SELECT doc_id, register_date FROM Document_Reward ORDER BY doc_id"))
        senders = dict(conn.execute(
            "SELECT doc_id, sender_id FROM Document_Reward ORDER BY doc_id"))
        conn.close()
        self.assertIsNone(rows["NEW"])
        self.assertIsNone(senders["NEW"])
        self.assertEqual(rows["OLD"], "2026-07-21")
        self.assertEqual(senders["OLD"], 7)
        self.assertEqual(self.tab.table.rowCount(), 2)
        self.assertEqual(self.tab.table.item(0, 3).text(), "")
        self.assertEqual(self.tab.table.item(1, 3).text(), "2026-07-21")
        self.assertEqual(self.tab._pending, set())
        self.assertFalse(self.tab._pending_banner.isVisible())
        self.assertTrue(self.reward_page.reward_data_dirty)
        self.assertEqual(self.browse_page._pending_reload_keys, {"reward"})

    def test_issue_empty_sender_and_empty_list_are_rejected(self):
        with patch("tabs.tab_reward_issue.msgInfo") as info:
            self.tab.handleIssue()
            info.assert_called_once_with("提示", "清單是空的，請先輸入編號")

        self._insert("NEW", "")
        self._query("NEW")
        self.tab.issue_sender.setCurrentIndex(0)
        with patch("tabs.tab_reward_issue.msgWarning") as warning, \
                patch("tabs.tab_reward_issue.confirmBox") as confirm:
            self.tab.handleIssue()
            warning.assert_called_once_with("欄位未填", "請選擇發文人員。")
            confirm.assert_not_called()

    def test_delete_one_row_only_removes_queue_state_and_hides_banner(self):
        self._insert("NEW", "")
        self._query("NEW")
        self.assertEqual(self.tab._pending, {"NEW"})
        self.assertFalse(self.tab._pending_banner.isHidden())

        self.tab._deleteByDocId("NEW")

        self.assertEqual(self.tab.table.rowCount(), 0)
        self.assertEqual(self.tab._pending, set())
        self.assertTrue(self.tab._pending_banner.isHidden())
        conn = sqlite3.connect(self.db_path)
        row = conn.execute(
            "SELECT register_date FROM Document_Reward WHERE doc_id='NEW'"
        ).fetchone()
        conn.close()
        self.assertEqual(row, ("",))

    def test_clear_all_clears_pending_and_banner_after_confirmation(self):
        self._insert("A", "")
        self._insert("B", "")
        self._query("A")
        self._query("B")
        self.assertEqual(self.tab._pending, {"A", "B"})

        with patch("tabs.tab_reward_issue.confirmBox", return_value=True):
            self.tab.handleClearAll()

        self.assertEqual(self.tab.table.rowCount(), 0)
        self.assertEqual(self.tab._pending, set())
        self.assertTrue(self.tab._pending_banner.isHidden())

    def test_cancel_issue_confirmation_preserves_database_and_queue(self):
        self._insert("NEW", "")
        self._query("NEW")

        with patch("tabs.tab_reward_issue.confirmBox", return_value=False):
            self.tab.handleIssue()

        conn = sqlite3.connect(self.db_path)
        row = conn.execute(
            "SELECT register_date, sender_id FROM Document_Reward WHERE doc_id='NEW'"
        ).fetchone()
        conn.close()
        self.assertEqual(row, ("", None))
        self.assertEqual(self.tab.table.item(0, 3).text(), "")
        self.assertEqual(self.tab._pending, {"NEW"})
        self.assertFalse(self.tab._pending_banner.isHidden())
        self.assertFalse(self.reward_page.reward_data_dirty)
        self.assertEqual(self.browse_page._pending_reload_keys, set())

    def test_issue_reissues_all_retained_rows_including_already_issued(self):
        # 比照交辦發文送全列：保留的已發文列在下次發文會一併被覆蓋重發。
        self._insert("FIRST", "")
        self._query("FIRST")
        with patch("tabs.tab_reward_issue.confirmBox", return_value=True), \
                patch("tabs.tab_reward_issue.msgInfo"):
            self.tab.handleIssue()

        self.assertEqual(self.tab.table.rowCount(), 1)
        self.assertEqual(self.tab.table.item(0, 3).text(), "2026-07-21")
        self.assertEqual(self.tab._pending, set())

        self._insert("SECOND", "")
        self._query("SECOND")
        self.assertEqual(self.tab.table.rowCount(), 2)
        self.assertEqual(self.tab._pending, {"SECOND"})
        self.tab.issue_date.setDate(QDate(2026, 7, 22))

        with patch("tabs.tab_reward_issue.confirmBox", return_value=True) as confirm, \
                patch("tabs.tab_reward_issue.msgInfo"):
            self.tab.handleIssue()

        # 送全列：FIRST（已發文，將覆蓋）＋ SECOND（未發文），共 2 筆
        self.assertIn("共 2 筆敘獎（其中 1 筆將覆蓋原發文日期）",
                      confirm.call_args.args[1])
        conn = sqlite3.connect(self.db_path)
        rows = dict(conn.execute(
            "SELECT doc_id, register_date FROM Document_Reward ORDER BY doc_id"))
        conn.close()
        self.assertEqual(rows, {
            "FIRST": "2026-07-22",
            "SECOND": "2026-07-22",
        })
        self.assertEqual(self.tab.table.rowCount(), 2)
        self.assertEqual(self.tab.table.item(0, 3).text(), "2026-07-22")
        self.assertEqual(self.tab.table.item(1, 3).text(), "2026-07-22")
        self.assertEqual(self.tab._pending, set())
        self.assertTrue(self.tab._pending_banner.isHidden())

    def test_issue_resends_retained_rows_and_still_guards_sender(self):
        # 保留列（_pending 已空）仍參與送全列：sender guard 生效、有效送文者則重發。
        self._insert("DONE", "")
        self._query("DONE")
        with patch("tabs.tab_reward_issue.confirmBox", return_value=True), \
                patch("tabs.tab_reward_issue.msgInfo"):
            self.tab.handleIssue()

        self.assertEqual(self.tab.table.rowCount(), 1)
        self.assertEqual(self.tab._pending, set())
        self.assertEqual(self.tab.table.item(0, 3).text(), "2026-07-21")

        # _pending 已空，但保留列仍被收集 → 未選送文者時擋下、不進 confirm
        self.tab.issue_sender.setCurrentIndex(0)
        with patch("tabs.tab_reward_issue.msgWarning") as warning, \
                patch("tabs.tab_reward_issue.confirmBox") as confirm:
            self.tab.handleIssue()
        warning.assert_called_once_with("欄位未填", "請選擇發文人員。")
        confirm.assert_not_called()

        # 選回有效送文者、改日期 → 保留列被重發（退件重發，免重掃）
        self.tab.issue_sender.setCurrentIndex(1)
        self.tab.issue_date.setDate(QDate(2026, 7, 22))
        with patch("tabs.tab_reward_issue.confirmBox", return_value=True) as confirm, \
                patch("tabs.tab_reward_issue.msgInfo"):
            self.tab.handleIssue()
        self.assertIn("共 1 筆敘獎（其中 1 筆將覆蓋原發文日期）",
                      confirm.call_args.args[1])
        conn = sqlite3.connect(self.db_path)
        row = conn.execute(
            "SELECT register_date FROM Document_Reward WHERE doc_id='DONE'").fetchone()
        conn.close()
        self.assertEqual(row[0], "2026-07-22")
        self.assertEqual(self.tab.table.item(0, 3).text(), "2026-07-22")

    def test_ref_changed_refreshes_sender_choices_and_clears_flag(self):
        conn = sqlite3.connect(self.db_path)
        conn.execute("INSERT INTO Ref_Personnel VALUES (8, '李小華', 1, 2)")
        conn.commit()
        conn.close()
        self.tab._ref_changed = True

        self.tab.on_activated()

        self.assertFalse(self.tab._ref_changed)
        self.assertEqual(self.tab.issue_sender.currentData(), 7)
        self.assertEqual(self.tab.issue_sender.findData(8) >= 0, True)
        self.assertEqual(self.tab.issue_sender.itemText(
            self.tab.issue_sender.findData(8)), "李小華")

    def test_table_is_read_only_and_controller_has_no_role_or_input_lock_gate(self):
        import inspect
        import tabs.tab_reward_issue as module

        source = inspect.getsource(module)
        self.assertNotIn("InputLockMixin", source)
        self.assertNotIn("AuthManager", source)
        self.tab.setup(0)
        self.assertEqual(
            self.tab.table.editTriggers(),
            QTableWidget.EditTrigger.NoEditTriggers,
        )
        self.assertIsNotNone(self.tab.get_focus_widget())
        self.assertEqual(self.tab.get_tables(), [self.tab.table])


if __name__ == "__main__":
    unittest.main()
