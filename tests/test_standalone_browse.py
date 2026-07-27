# -*- coding: utf-8 -*-
"""獨立版（警政快速登錄系統）資料庫瀏覽白名單測試（offscreen）。

保護對象：
  - `TabDBBrowse(allowed_keys=...)` 限縮瀏覽範圍為敘獎與罰單，未知 key 拒絕建構。
  - 子頁籤以 `subtabs.setTabData()` 保存公文類型 key（不得用 currentIndex()/
    BROWSE_KEYS 做位置映射），獨立版恰為 ("reward", "ticket")。
  - 獨立版不出現交辦單／刑案／一般陳報子頁，因此案類互轉、開啟歸檔 PDF 等
    敘獎/罰單用不到的入口自然不存在。
  - 完整版（預設 allowed_keys=BROWSE_KEYS）行為零變化。

人名一律虛構（push 前有 test_no_pii 掃真名）。
"""
import os
import sqlite3
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QTabWidget, QWidget

import res.resources_rc  # noqa: F401  資源（icon）註冊，_fillRow 會用到 :/icon_pdf.svg
from lib.auth_manager import AuthManager
from lib.db_schema import applySchema
from tabs.tab_dbbrowse import BROWSE_KEYS, TABLE_META, TabDBBrowse
from ui_utils.reward_dialog import RewardEditDialog
from ui_utils.ticket_dialog import TicketEditDialog

_app = QApplication.instance() or QApplication([])

ENTRY_BROWSE_KEYS = ("reward", "ticket")


class _StandaloneBrowseBase(unittest.TestCase):
    def setUp(self):
        fd, self.db = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        conn = sqlite3.connect(self.db)
        applySchema(conn)
        conn.executescript("""
            INSERT INTO Ref_Personnel(staff_id,staff_name,is_active,sort_order) VALUES
                ('P01','測試員甲',1,1),('P02','測試員乙',1,2);
            INSERT INTO Ref_Departments(dept_id,dept_name,is_active,sort_order) VALUES
                ('D01','偵查隊',1,1);
            INSERT INTO Ref_CaseTypes(case_type_id,case_type_name,is_active,sort_order)
                VALUES('CT01','竊盜案',1,1);
        """)
        conn.executemany(
            "INSERT INTO Document_Task"
            "(doc_id,receive_date,receive_id,dept_id,subject,processor_id,"
            " deadline,dispatch_date,sender_id,timestamp) VALUES(?,?,?,?,?,?,?,?,?,?)",
            [("1", "2026-07-01", "P02", "D01", "甲案交辦事由", "P01",
              "2026-07-20", "2026-07-05", "P02", "2026-07-01 09:00:00")])
        conn.executemany(
            "INSERT INTO Document_Criminal"
            "(doc_id,report_date,sender_id,case_type,case_status,processor_id,"
            " subject_summary,is_reported,is_electronic) VALUES(?,?,?,?,?,?,?,?,?)",
            [("1", "2026-07-01", "P02", "CT01", "", "P01", "甲嫌竊盜案", 0, "")])
        conn.executemany(
            "INSERT INTO Document_Reward"
            "(doc_id,create_date,register_date,reason,recipients) VALUES(?,?,?,?,?)",
            [("1", "2026-07-16", "2026-07-17", "專案有功", "測試甲")])
        conn.executemany(
            "INSERT INTO Document_Ticket"
            "(doc_id,create_date,register_date,sender_id,issuer_id,ticket_no) "
            "VALUES(?,?,?,?,?,?)",
            [("1", "2026-07-01", "2026-07-02", "P01", "P02", "AB1234")])
        conn.commit()
        conn.close()
        self._extra_tabs = []
        AuthManager.instance()._role = "user"

    def tearDown(self):
        AuthManager.instance()._role = "user"
        for t in self._extra_tabs:
            t.deleteLater()
        try:
            os.remove(self.db)
        except OSError:
            pass

    def _make_browse(self, allowed_keys=None):
        tabs = QTabWidget()
        tabs.addTab(QWidget(), "瀏覽")
        self._extra_tabs.append(tabs)
        if allowed_keys is None:
            tab = TabDBBrowse(tabs, self.db)
        else:
            tab = TabDBBrowse(tabs, self.db, allowed_keys=allowed_keys)
        tab.setup(0)
        return tab


class TestFullBrowseUnchanged(_StandaloneBrowseBase):
    """完整版預設 allowed_keys=BROWSE_KEYS，行為必須零變化。"""

    def test_default_allowed_keys_is_full_browse_keys(self):
        tab = self._make_browse()
        self.assertEqual(tab.allowed_keys, BROWSE_KEYS)

    def test_full_subtabs_tab_data_matches_browse_keys_order(self):
        tab = self._make_browse()
        keys = [tab.subtabs.tabBar().tabData(i) for i in range(tab.subtabs.count())]
        self.assertEqual(keys, list(BROWSE_KEYS))
        self.assertEqual(tab.subtabs.count(), len(BROWSE_KEYS))


class TestEntryBrowseWhitelist(_StandaloneBrowseBase):
    """獨立版：allowed_keys=("reward","ticket")。"""

    def test_entry_allowed_keys_is_reward_and_ticket(self):
        tab = self._make_browse(allowed_keys=ENTRY_BROWSE_KEYS)
        self.assertEqual(tab.allowed_keys, ENTRY_BROWSE_KEYS)

    def test_entry_subtabs_tab_data_is_reward_and_ticket_only(self):
        tab = self._make_browse(allowed_keys=ENTRY_BROWSE_KEYS)
        keys = [tab.subtabs.tabBar().tabData(i) for i in range(tab.subtabs.count())]
        self.assertEqual(keys, list(ENTRY_BROWSE_KEYS))
        self.assertEqual(tab.subtabs.count(), 2)

    def test_entry_browse_has_no_task_crim_gen_subtabs(self):
        tab = self._make_browse(allowed_keys=ENTRY_BROWSE_KEYS)
        keys = {tab.subtabs.tabBar().tabData(i) for i in range(tab.subtabs.count())}
        self.assertNotIn("task", keys)
        self.assertNotIn("crim", keys)
        self.assertNotIn("gen", keys)
        # crim/gen 才有案類互轉、開啟歸檔 PDF 的入口；沒有這兩個子頁，
        # 這些操作在獨立版自然不存在，不需另外隱藏。
        self.assertNotIn("archive", TABLE_META["reward"])
        self.assertNotIn("archive", TABLE_META["ticket"])

    def test_entry_browse_only_builds_ui_for_allowed_keys(self):
        tab = self._make_browse(allowed_keys=ENTRY_BROWSE_KEYS)
        self.assertEqual(set(tab._ui.keys()), set(ENTRY_BROWSE_KEYS))

    def test_entry_all_rows_only_contains_allowed_keys(self):
        tab = self._make_browse(allowed_keys=ENTRY_BROWSE_KEYS)
        for key in ENTRY_BROWSE_KEYS:
            tab.buildInitial(key)
        self.assertLessEqual(set(tab._allRows), set(ENTRY_BROWSE_KEYS))
        self.assertEqual(set(tab._allRows), set(ENTRY_BROWSE_KEYS))

    def test_entry_get_tables_only_returns_allowed_keys_tables(self):
        tab = self._make_browse(allowed_keys=ENTRY_BROWSE_KEYS)
        self.assertEqual(len(tab.get_tables()), 2)

    def test_entry_reuses_table_meta_edit_and_delete_handlers(self):
        # 獨立版不得另寫 handler：修改／刪除仍走 TABLE_META 既有定義。
        tab = self._make_browse(allowed_keys=ENTRY_BROWSE_KEYS)
        self.assertIs(TABLE_META["reward"]["dialog"], RewardEditDialog)
        self.assertIs(TABLE_META["ticket"]["dialog"], TicketEditDialog)
        self.assertIn("delete_handler", TABLE_META["ticket"])
        self.assertNotIn("delete_handler", TABLE_META["reward"])
        del tab  # 僅需確認建構成功，不需額外互動


class TestUnknownBrowseKeyRejected(_StandaloneBrowseBase):
    def test_unknown_key_raises_value_error(self):
        tabs = QTabWidget()
        tabs.addTab(QWidget(), "瀏覽")
        self._extra_tabs.append(tabs)
        with self.assertRaises(ValueError):
            TabDBBrowse(tabs, self.db, allowed_keys=("reward", "bogus"))


if __name__ == "__main__":
    unittest.main()
