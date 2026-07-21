# -*- coding: utf-8 -*-
import os
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QTabWidget, QWidget

from lib.db_schema import applySchema
from tabs.tab_dbbrowse import BROWSE_KEYS, PRELOAD_KEYS, TABLE_META, TabDBBrowse, queryBrowseRows

_app = QApplication.instance() or QApplication([])


class TestRewardBrowse(unittest.TestCase):
    def setUp(self):
        fd, self.db = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        conn = sqlite3.connect(self.db)
        applySchema(conn)
        conn.executemany(
            "INSERT INTO Document_Reward"
            "(doc_id,create_date,register_date,reason,recipients) VALUES(?,?,?,?,?)",
            [("2", "2026-07-16", "", "協助查緝", "測試甲,測試乙"),
             ("10", "2026-07-17", "2026-07-18", "專案有功", "測試丙"),
             ("11", None, None, None, None)])
        conn.commit()
        conn.close()

    def tearDown(self):
        os.remove(self.db)

    def _tab(self):
        tabs = QTabWidget()
        tabs.addTab(QWidget(), "瀏覽")
        tab = TabDBBrowse(tabs, self.db)
        tab.setup(0)
        self.addCleanup(tabs.deleteLater)
        return tab

    def test_metadata_is_raw_and_has_single_key_source(self):
        self.assertEqual(BROWSE_KEYS, ("task", "crim", "gen", "reward"))
        self.assertEqual(PRELOAD_KEYS, ("task", "crim", "gen"))
        meta = TABLE_META["reward"]
        self.assertTrue(meta["raw"])
        self.assertTrue(meta["sort_numeric"])
        self.assertNotIn("view", meta)
        self.assertNotIn("proc_fk", meta)
        self.assertEqual(
            [col["header"] for col in meta["cols"]],
            ["", "編號", "登錄日期", "發文日期", "發文人員", "敘獎事由", "敘獎人員"])
        self.assertFalse(any(TABLE_META[key].get("sort_numeric")
                             for key in PRELOAD_KEYS))

    def test_query_is_active_only_numeric_asc_and_searchable_snapshots(self):
        conn = sqlite3.connect(self.db)
        rows = queryBrowseRows(conn, "reward")
        conn.close()
        self.assertEqual([r["doc_id"] for r in rows], ["2", "10"])
        self.assertEqual(rows[0]["create_date"], "2026-07-16")
        self.assertEqual(rows[0]["register_date"], "")
        self.assertIn("有功", rows[1]["reason"])
        self.assertIn("測試乙", rows[0]["recipients"])

    def test_query_joins_sender_name_from_ref_personnel(self):
        conn = sqlite3.connect(self.db)
        conn.execute(
            "INSERT OR IGNORE INTO Ref_Personnel"
            "(staff_id,staff_name,is_active,sort_order) VALUES('P009','趙發文',1,1)")
        conn.execute(
            "UPDATE Document_Reward SET sender_id='P009' WHERE doc_id='10'")
        conn.commit()
        rows = queryBrowseRows(conn, "reward")
        conn.close()
        by_id = {r["doc_id"]: r for r in rows}
        self.assertEqual(by_id["10"]["sender_name"], "趙發文")
        self.assertIsNone(by_id["2"]["sender_name"])   # 無 sender → JOIN 回 NULL

    def test_reward_is_lazy_loaded(self):
        tab = self._tab()
        tab.markLoaded()
        self.assertEqual(tab._loaded_keys, set(PRELOAD_KEYS))
        tab.subtabs.setCurrentIndex(3)
        _app.processEvents()
        self.assertIn("reward", tab._loaded_keys)
        self.assertEqual(tab._docorder["reward"], ["2", "10"])

    def test_only_empty_issue_date_shows_unissued_orange(self):
        tab = self._tab()
        tab.buildInitial("reward")
        table = tab._ui["reward"]["table"]
        self.assertEqual(table.item(0, 2).text(), "2026-07-16")
        self.assertEqual(table.item(0, 3).text(), "未發文")
        self.assertEqual(table.item(0, 3).foreground().color().name(), "#e67e22")

    def test_handlers_and_actual_operations_both_gate_permissions(self):
        tab = self._tab()
        tab._docorder = {"reward": ["10"]}
        with patch("tabs.tab_dbbrowse.AuthManager.instance") as auth:
            auth.return_value.is_manager.return_value = False
            auth.return_value.is_admin.return_value = False
            with patch.object(tab, "_onEdit") as edit, patch.object(tab, "_onDelete") as delete:
                tab._onLinkCell("reward", 0, 1, 1)
                tab._onDeleteCell("reward", 0, 0, 0)
                edit.assert_not_called()
                delete.assert_not_called()
            with patch("tabs.tab_dbbrowse.confirmBox") as confirm:
                tab._onDelete("reward", "10")
                confirm.assert_not_called()
            with patch("tabs.tab_dbbrowse.RewardEditDialog") as dialog:
                tab._onEdit("reward", 0, "10")
                dialog.assert_not_called()

    def test_archive_manager_edit_matrix_blocks_task_and_reward_only(self):
        # 歸檔管理者：交辦單(task)／敘獎(reward)不可改；刑案／一般仍可。
        tab = self._tab()
        with patch("tabs.tab_dbbrowse.AuthManager.instance") as auth:
            auth.return_value.is_admin.return_value = False
            auth.return_value.is_manager.return_value = True
            self.assertFalse(tab._canEditKey("task"))
            self.assertFalse(tab._canEditKey("reward"))
            self.assertTrue(tab._canEditKey("crim"))
            self.assertTrue(tab._canEditKey("gen"))
        # 最高權限管理者：四表皆可
        with patch("tabs.tab_dbbrowse.AuthManager.instance") as auth:
            auth.return_value.is_admin.return_value = True
            auth.return_value.is_manager.return_value = True
            for k in ("task", "reward", "crim", "gen"):
                self.assertTrue(tab._canEditKey(k))

    def test_archive_manager_cannot_open_reward_edit_dialog(self):
        tab = self._tab()
        tab._docorder = {"reward": ["10"]}
        with patch("tabs.tab_dbbrowse.AuthManager.instance") as auth:
            auth.return_value.is_admin.return_value = False
            auth.return_value.is_manager.return_value = True   # 歸檔管理
            with patch("tabs.tab_dbbrowse.RewardEditDialog") as dialog:
                tab._onEdit("reward", 0, "10")
                tab._onLinkCell("reward", 0, 1, 1)
                dialog.assert_not_called()

    def test_signature_excludes_soft_deleted_rows(self):
        tab = self._tab()
        self.assertEqual(tab._tableSignature("reward")[0], 2)

    def test_diff_removes_soft_deleted_row_and_keeps_three_structures_aligned(self):
        tab = self._tab()
        tab.buildInitial("reward")
        conn = sqlite3.connect(self.db)
        conn.execute("UPDATE Document_Reward SET register_date=NULL WHERE doc_id='10'")
        conn.commit()
        conn.close()
        tab._diffUpdate("reward")
        self.assertEqual(tab._docorder["reward"], ["2"])
        self.assertEqual([r["doc_id"] for r in tab._allRows["reward"]], ["2"])
        self.assertEqual(tab._ui["reward"]["table"].rowCount(), 1)

    def test_diff_catches_same_timestamp_insert_and_places_it_in_order(self):
        tab = self._tab()
        tab.buildInitial("reward")
        boundary = tab._lastLoad["reward"]
        conn = sqlite3.connect(self.db)
        conn.execute(
            "INSERT INTO Document_Reward"
            "(doc_id,create_date,register_date,reason,recipients,last_modified) "
            "VALUES('20','2026-07-19','2026-07-20','同秒新增','測試丁',?)", (boundary,))
        conn.commit()
        conn.close()
        tab._diffUpdate("reward")
        self.assertEqual(tab._docorder["reward"], ["2", "10", "20"])
        self.assertEqual([r["doc_id"] for r in tab._allRows["reward"]], ["2", "10", "20"])
        self.assertEqual(tab._ui["reward"]["table"].item(2, 1).text(), "20")

    def test_diff_catches_same_timestamp_update_in_place(self):
        tab = self._tab()
        tab.buildInitial("reward")
        boundary = tab._lastLoad["reward"]
        conn = sqlite3.connect(self.db)
        conn.execute(
            "UPDATE Document_Reward SET reason='同秒修改', last_modified=? WHERE doc_id='2'",
            (boundary,))
        conn.commit()
        conn.close()
        tab._diffUpdate("reward")
        self.assertEqual(tab._docorder["reward"], ["2", "10"])
        self.assertEqual([r["doc_id"] for r in tab._allRows["reward"]], ["2", "10"])
        self.assertEqual(tab._ui["reward"]["table"].item(0, 5).text(), "同秒修改")

    def test_real_soft_delete_sql_lands_in_no_active_filter_changed_ids(self):
        # SQL round-trip：以真實清空式 UPDATE（_DELETE_CLEAR_SQL）軟刪一列，
        # 該 UPDATE 不碰 last_modified，靠 trigger 蓋成當下時間。驗證「不帶
        # active 過濾」的 changed_ids 查詢抓得到被刪列（fix 的前提），而舊有
        # 「帶 register_date IS NOT NULL」的查詢則漏掉它。
        conn = sqlite3.connect(self.db)
        since = conn.execute("SELECT MAX(last_modified) FROM Document_Reward").fetchone()[0]
        from lib.db_utils import _DELETE_CLEAR_SQL
        conn.execute(_DELETE_CLEAR_SQL["Document_Reward"], ("10",))
        conn.commit()
        no_filter = {r[0] for r in conn.execute(
            "SELECT doc_id FROM Document_Reward WHERE last_modified >= ?", (since,))}
        with_filter = {r[0] for r in conn.execute(
            "SELECT doc_id FROM Document_Reward WHERE last_modified >= ? "
            "AND register_date IS NOT NULL", (since,))}
        conn.close()
        self.assertIn("10", no_filter)
        self.assertNotIn("10", with_filter)

    def test_diff_removes_row_soft_deleted_via_real_clear_sql(self):
        tab = self._tab()
        tab.buildInitial("reward")
        conn = sqlite3.connect(self.db)
        from lib.db_utils import _DELETE_CLEAR_SQL
        conn.execute(_DELETE_CLEAR_SQL["Document_Reward"], ("10",))
        conn.commit()
        conn.close()
        tab._diffUpdate("reward")
        self.assertEqual(tab._docorder["reward"], ["2"])
        self.assertEqual([r["doc_id"] for r in tab._allRows["reward"]], ["2"])
        self.assertEqual(tab._ui["reward"]["table"].rowCount(), 1)

    def test_legacy_task_diff_still_appends_numeric_new_id(self):
        conn = sqlite3.connect(self.db)
        conn.execute(
            "INSERT INTO Document_Task(doc_id,receive_date,subject,last_modified) "
            "VALUES('10','2026-07-17','既有交辦','2026-07-17 10:00:00')")
        conn.commit()
        conn.close()
        tab = self._tab()
        tab.buildInitial("task")
        boundary = tab._lastLoad["task"]
        conn = sqlite3.connect(self.db)
        conn.execute(
            "INSERT INTO Document_Task(doc_id,receive_date,subject,last_modified) "
            "VALUES('20','2026-07-18','新交辦',?)", (boundary,))
        conn.commit()
        conn.close()
        tab._diffUpdate("task")
        self.assertEqual(tab._docorder["task"], ["10", "20"])
        self.assertEqual([r["編號"] for r in tab._allRows["task"]], ["10", "20"])
        self.assertEqual(tab._ui["task"]["table"].item(1, 1).text(), "20")


if __name__ == "__main__":
    unittest.main()
