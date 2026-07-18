# -*- coding: utf-8 -*-
"""資料庫瀏覽頁（tabs/tab_dbbrowse.py）列同步不變式測試（offscreen）。

保護對象：`_allRows[key]` / `_docorder[key]` 與表格列的 1:1 對應，以及
`_applyRowVisibility` 的 setUpdatesEnabled try/finally 保證。此頁歷史上出過
「搜尋取到錯列」的雷，根因即三者失去對應、或 updatesEnabled 卡在 False。

只驗純狀態邏輯（reload / diffUpdate / filter / 可見性），不驗點擊互動、
表格渲染外觀（仍須上機）。人名一律虛構（push 前有 test_no_pii 掃真名）。
"""
import os
import sqlite3
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QTabWidget, QWidget

import res.resources_rc  # noqa: F401  資源（icon）註冊，_fillRow 會用到 :/icon_pdf.svg
from lib.db_schema import applySchema
from lib.db_utils import _DELETE_CLEAR_SQL
from tabs.tab_dbbrowse import TABLE_META, TabDBBrowse

_app = QApplication.instance() or QApplication([])


def _col_idx(key, view_col):
    """依 view_col 取得該欄在表格中的欄索引（避免硬編數字）。"""
    return next(i for i, c in enumerate(TABLE_META[key]["cols"])
               if c.get("view_col") == view_col)


class _BrowseBase(unittest.TestCase):
    """建立含最小參照資料與三主表測試列的暫存 DB，並實例化瀏覽頁。"""

    def setUp(self):
        fd, self.db = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        conn = sqlite3.connect(self.db)
        applySchema(conn)   # 正式 DDL：三主表 + 參照表 + last_modified trigger
        conn.executescript("""
            INSERT INTO Ref_Personnel(staff_id,staff_name,is_active,sort_order) VALUES
                ('P01','測試員A',1,1),('P02','測試員B',1,2),('P03','測試員C',1,3);
            INSERT INTO Ref_Departments(dept_id,dept_name,is_active,sort_order) VALUES
                ('D01','偵查隊',1,1);
            INSERT INTO Ref_CaseTypes(case_type_id,case_type_name,is_active,sort_order)
                VALUES('CT01','竊盜案',1,1);
            INSERT INTO Ref_Case_Status(status_id,status_name) VALUES('CS01','現行');
            INSERT INTO Ref_General_Category(gen_cat_id,gen_cat_name) VALUES('GC01','業務');
        """)
        # 交辦：三筆，主旨互異（供搜尋過濾驗證）
        conn.executemany(
            "INSERT INTO Document_Task"
            "(doc_id,receive_date,receive_id,dept_id,subject,processor_id,"
            " deadline,dispatch_date,sender_id,timestamp) VALUES(?,?,?,?,?,?,?,?,?,?)",
            [("1", "2026-07-01", "P02", "D01", "甲案交辦事由", "P01",
              "2026-07-20", "2026-07-05", "P03", "2026-07-01 09:00:00"),
             ("2", "2026-07-02", "P02", "D01", "乙案交辦事由", "P02",
              "2026-07-21", None, "P03", "2026-07-02 09:00:00"),
             ("3", "2026-07-03", "P02", "D01", "丙案交辦事由", "P03",
              "2026-07-22", None, "P03", "2026-07-03 09:00:00")])
        # 刑案：兩筆
        conn.executemany(
            "INSERT INTO Document_Criminal"
            "(doc_id,report_date,sender_id,case_type,case_status,processor_id,"
            " subject_summary,is_reported,is_electronic) VALUES(?,?,?,?,?,?,?,?,?)",
            [("1", "2026-07-01", "P02", "CT01", "CS01", "P01", "甲嫌竊盜案", 0, ""),
             ("2", "2026-07-02", "P02", "CT01", "CS01", "P02", "乙嫌竊盜案", 0, "")])
        conn.commit()
        conn.close()

        self.tabs = QTabWidget()
        self.tabs.addTab(QWidget(), "瀏覽")
        self.tab = TabDBBrowse(self.tabs, self.db)
        self.tab.setup(0)
        self.addCleanup(self.tabs.deleteLater)

    def tearDown(self):
        try:
            os.remove(self.db)
        except OSError:
            pass

    def _assert_aligned(self, key, expected_ids):
        """三結構 1:1 且 doc_id 順序一致的共用斷言。"""
        table = self.tab._ui[key]["table"]
        order = self.tab._docorder[key]
        all_rows = self.tab._allRows[key]
        id_col = TABLE_META[key]["id_col"]
        self.assertEqual(table.rowCount(), len(order))
        self.assertEqual(len(all_rows), len(order))
        self.assertEqual(order, expected_ids)
        self.assertEqual([str(r.get(id_col) or "") for r in all_rows], expected_ids)


class TestReloadAlignment(_BrowseBase):
    """不變式 1：_reload 後 rowCount == len(_allRows) == len(_docorder)，順序一致。"""

    def test_task_reload_three_structures_aligned(self):
        self.tab.buildInitial("task")
        self._assert_aligned("task", ["1", "2", "3"])

    def test_crim_reload_three_structures_aligned(self):
        self.tab.buildInitial("crim")
        self._assert_aligned("crim", ["1", "2"])


class TestDiffUpdateAlignment(_BrowseBase):
    """不變式 2：外部 INSERT / UPDATE / 軟刪除清空後 _diffUpdate 仍 1:1、內容正確。"""

    def test_external_insert_keeps_alignment(self):
        self.tab.buildInitial("task")
        boundary = self.tab._lastLoad["task"]
        conn = sqlite3.connect(self.db)
        conn.execute(
            "INSERT INTO Document_Task(doc_id,receive_date,dept_id,subject,"
            "processor_id,deadline,last_modified) VALUES('4','2026-07-04','D01',"
            "'丁案交辦事由','P01','2026-07-25',?)", (boundary,))
        conn.commit()
        conn.close()
        self.tab._diffUpdate("task")
        # 交辦無 sort_numeric_desc → 新列 append 於末端
        self._assert_aligned("task", ["1", "2", "3", "4"])
        subj_col = _col_idx("task", "交辦事由")
        table = self.tab._ui["task"]["table"]
        self.assertEqual(table.item(3, subj_col).text(), "丁案交辦事由")

    def test_external_update_reflects_in_row_and_allrows(self):
        self.tab.buildInitial("task")
        boundary = self.tab._lastLoad["task"]
        conn = sqlite3.connect(self.db)
        conn.execute(
            "UPDATE Document_Task SET subject='乙案已改主旨', last_modified=? "
            "WHERE doc_id='2'", (boundary,))
        conn.commit()
        conn.close()
        self.tab._diffUpdate("task")
        self._assert_aligned("task", ["1", "2", "3"])
        subj_col = _col_idx("task", "交辦事由")
        table = self.tab._ui["task"]["table"]
        pos = self.tab._docorder["task"].index("2")
        self.assertEqual(table.item(pos, subj_col).text(), "乙案已改主旨")
        self.assertEqual(self.tab._allRows["task"][pos]["交辦事由"], "乙案已改主旨")

    def test_soft_delete_clear_removes_row_and_keeps_alignment(self):
        # 真實清空式 UPDATE（_DELETE_CLEAR_SQL）：清欄位保留 doc_id，不碰
        # last_modified（靠 trigger 蓋成當下），diffUpdate 判為 emptied → 移除列。
        self.tab.buildInitial("task")
        conn = sqlite3.connect(self.db)
        conn.execute(_DELETE_CLEAR_SQL["Document_Task"], ("2",))
        conn.commit()
        conn.close()
        self.tab._diffUpdate("task")
        self._assert_aligned("task", ["1", "3"])

    def test_crim_soft_delete_clear_removes_row(self):
        self.tab.buildInitial("crim")
        conn = sqlite3.connect(self.db)
        conn.execute(_DELETE_CLEAR_SQL["Document_Criminal"], ("1",))
        conn.commit()
        conn.close()
        self.tab._diffUpdate("crim")
        self._assert_aligned("crim", ["2"])


class TestRowVisibilityUpdatesEnabled(_BrowseBase):
    """不變式 3：_applyRowVisibility 過程丟例外時，updatesEnabled 最終仍為 True。"""

    def test_updates_enabled_restored_on_exception(self):
        self.tab.buildInitial("task")
        table = self.tab._ui["task"]["table"]
        self.assertTrue(table.updatesEnabled())   # 前置：預設為 True

        class _Boom:
            def get(self, *a, **k):
                raise RuntimeError("模擬可見性計算中途失敗")

        # matched_map 於迴圈內每列被 .get()；換成必炸物件，確保在 try 區塊內丟例外
        self.tab._matchedCols["task"] = _Boom()
        with self.assertRaises(RuntimeError):
            self.tab._applyRowVisibility("task")
        # finally 必須把 updatesEnabled 還原成 True，否則表格會卡死不重繪
        self.assertTrue(table.updatesEnabled())


class TestApplyFilter(_BrowseBase):
    """不變式 4：搜尋過濾後隱藏/可見列與關鍵字命中一致，且不影響 1:1 對應。"""

    def test_keyword_hides_non_matching_rows_only(self):
        self.tab.buildInitial("task")
        table = self.tab._ui["task"]["table"]
        self.tab._ui["task"]["kw"].setText("乙案")
        self.tab._applyFilter("task")
        # 三結構對應不因過濾改變（過濾只 setRowHidden，不動 order/allRows）
        self._assert_aligned("task", ["1", "2", "3"])
        order = self.tab._docorder["task"]
        for pos, did in enumerate(order):
            hidden = table.isRowHidden(pos)
            self.assertEqual(hidden, did != "2",
                             f"doc_id={did} 可見性與命中不一致")
        # footer shown 應為 1
        self.assertEqual(self.tab._lastSearch["task"][2], 1)

    def test_clear_keyword_shows_all_rows(self):
        self.tab.buildInitial("task")
        table = self.tab._ui["task"]["table"]
        self.tab._ui["task"]["kw"].setText("乙案")
        self.tab._applyFilter("task")
        self.tab._ui["task"]["kw"].setText("")
        self.tab._applyFilter("task")
        for pos in range(table.rowCount()):
            self.assertFalse(table.isRowHidden(pos))
        self.assertEqual(self.tab._lastSearch["task"][2], 3)

    def test_scoped_search_matches_only_selected_column(self):
        # 範圍限定「交辦事由」欄：搜「測試員A」（承辦人名）在此範圍不應命中
        self.tab.buildInitial("task")
        table = self.tab._ui["task"]["table"]
        scope = self.tab._ui["task"]["scope"]
        idx = scope.findText("交辦事由")
        self.assertGreaterEqual(idx, 0)
        scope.setCurrentIndex(idx)
        self.tab._ui["task"]["kw"].setText("測試員A")
        self.tab._applyFilter("task")
        for pos in range(table.rowCount()):
            self.assertTrue(table.isRowHidden(pos))
        self.assertEqual(self.tab._lastSearch["task"][2], 0)


if __name__ == "__main__":
    unittest.main()
