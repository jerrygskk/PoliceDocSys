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
            "(doc_id,create_date,report_date,sender_id,case_type,case_status,processor_id,"
            " subject_summary,is_reported,is_electronic) VALUES(?,?,?,?,?,?,?,?,?,?)",
            [("1", "2026-06-29", "2026-07-01", "P02", "CT01", "CS01", "P01", "甲嫌竊盜案", 0, ""),
             ("2", "2026-06-30", "2026-07-02", "P02", "CT01", "CS01", "P02", "乙嫌竊盜案", 0, "")])
        conn.execute(
            "INSERT INTO Document_General"
            "(doc_id,create_date,report_date,sender_id,dept_id,gen_cat_id,"
            " subject,processor_id,is_reported,is_electronic) "
            "VALUES(?,?,?,?,?,?,?,?,?,?)",
            ("1", "2026-06-28", None, None, "D01", "GC01",
             "一般測試主旨", "P01", 0, ""))
        # 罰單：兩筆
        conn.executemany(
            "INSERT INTO Document_Ticket"
            "(doc_id,create_date,register_date,sender_id,issuer_id,ticket_no) "
            "VALUES(?,?,?,?,?,?)",
            [("1", "2026-07-01", "2026-07-02", "P01", "P02", "AB1234"),
             ("2", "2026-07-03", "", None, "P02", "CD5678")])
        conn.commit()
        conn.close()

        self.tabs = QTabWidget()
        self.tabs.addTab(QWidget(), "瀏覽")
        self.tab = TabDBBrowse(self.tabs, self.db)
        self.tab.setup(0)
        # 本檔用固定的過去日期建資料，測的是差異更新與三結構對齊，不是期間篩選。
        # 罰單／敘獎的「近期」預設啟用會把這些列藏起（測 setRowHidden 的斷言就會
        # 誤判為資料沒同步），故此處關掉；該鈕自身行為由 test_browse_recent.py 顧。
        for key in ("ticket", "reward"):
            btn = self.tab._ui.get(key, {}).get("recent")
            if btn:
                btn.setChecked(False)
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

    def _visible_rows(self, key):
        table = self.tab._ui[key]["table"]
        return [
            [table.item(row, col).text() if table.item(row, col) else ""
             for col in range(table.columnCount())]
            for row in range(table.rowCount())
            if not table.isRowHidden(row)
        ]


class TestReloadAlignment(_BrowseBase):
    """不變式 1：_reload 後 rowCount == len(_allRows) == len(_docorder)，順序一致。"""

    def test_task_reload_three_structures_aligned(self):
        self.tab.buildInitial("task")
        self._assert_aligned("task", ["1", "2", "3"])

    def test_crim_reload_three_structures_aligned(self):
        self.tab.buildInitial("crim")
        self._assert_aligned("crim", ["1", "2"])

    def test_ticket_reload_three_structures_aligned(self):
        self.tab.buildInitial("ticket")
        self._assert_aligned("ticket", ["1", "2"])

    def test_report_browse_create_date_is_after_id_and_searchable(self):
        for key in ("crim", "gen"):
            with self.subTest(key=key):
                cols = TABLE_META[key]["cols"]
                expected_header = "輸入日期" if key == "crim" else "登錄日期"
                self.assertEqual(cols[2]["header"], expected_header)
                self.assertEqual(cols[2]["view_col"], "登錄日期")
                self.assertTrue(cols[2]["search"])
                self.assertEqual(TABLE_META[key]["pending_date_col"], "陳報日期")

    def test_criminal_browse_uses_requested_date_headers(self):
        headers_by_view_col = {
            col.get("view_col"): col["header"]
            for col in TABLE_META["crim"]["cols"]
        }
        self.assertEqual(headers_by_view_col["登錄日期"], "輸入日期")
        self.assertEqual(headers_by_view_col["受理日期"], "刑案單陳報/受理日期")
        self.assertEqual(headers_by_view_col["陳報日期"], "發文日期")

    def test_report_browse_uses_requested_default_column_widths(self):
        crim_by_view_col = {
            col.get("view_col"): col
            for col in TABLE_META["crim"]["cols"]
        }
        self.assertEqual(crim_by_view_col["登錄日期"]["w"], 135)
        self.assertEqual(crim_by_view_col["案類"]["w"], 250)
        self.assertEqual(crim_by_view_col["嫌疑人_案由"]["w"], 290)
        self.assertTrue(crim_by_view_col["嫌疑人_案由"]["stretch"])
        self.assertEqual(crim_by_view_col["陳報日期"]["w"], 135)

        gen_by_view_col = {
            col.get("view_col"): col
            for col in TABLE_META["gen"]["cols"]
        }
        self.assertEqual(gen_by_view_col["登錄日期"]["w"], 135)
        self.assertEqual(gen_by_view_col["陳報主旨"]["w"], 290)
        self.assertTrue(gen_by_view_col["陳報主旨"]["stretch"])
        self.assertEqual(gen_by_view_col["陳報日期"]["w"], 135)

    def test_report_browse_scoped_create_date_search(self):
        for key, query, expected_id in (
                ("crim", "2026-06-30", "2"),
                ("gen", "2026-06-28", "1")):
            with self.subTest(key=key):
                self.tab.buildInitial(key)
                scope = self.tab._ui[key]["scope"]
                scope.setCurrentIndex(scope.findText("登錄日期"))
                self.tab._ui[key]["kw"].setText(query)
                self.tab._applyFilter(key)
                visible = [
                    self.tab._docorder[key][row]
                    for row in range(self.tab._ui[key]["table"].rowCount())
                    if not self.tab._ui[key]["table"].isRowHidden(row)
                ]
                self.assertEqual(visible, [expected_id])


class TestDiffUpdateAlignment(_BrowseBase):
    """不變式 2：外部 INSERT / UPDATE / 軟刪除清空後 _diffUpdate 仍 1:1、內容正確。"""

    def test_external_insert_keeps_visible_rows_current(self):
        self.tab.buildInitial("task")
        before = self._visible_rows("task")
        conn = sqlite3.connect(self.db)
        same_timestamp = conn.execute(
            "SELECT MAX(last_modified) FROM Document_Task"
        ).fetchone()[0]
        conn.execute(
            "INSERT INTO Document_Task(doc_id,receive_date,dept_id,subject,"
            "processor_id,deadline,last_modified) VALUES(?,?,?,?,?,?,?)",
            ("4", "2026-07-04", "D01", "第四筆交辦事由", "P01",
             "2026-07-25", same_timestamp),
        )
        conn.commit()
        conn.close()

        self.tab.on_activated()

        after = self._visible_rows("task")
        subject_col = _col_idx("task", "交辦事由")
        self.assertEqual(len(after), len(before) + 1)
        self.assertIn("第四筆交辦事由", [row[subject_col] for row in after])

    def test_external_update_reflects_in_visible_cell(self):
        self.tab.buildInitial("task")
        conn = sqlite3.connect(self.db)
        conn.execute(
            "UPDATE Document_Task SET subject=?, last_modified=? WHERE doc_id=?",
            ("第二筆已更新事由", "2099-01-01 00:00:00", "2"),
        )
        conn.commit()
        conn.close()

        self.tab.on_activated()

        rows = self._visible_rows("task")
        subject_col = _col_idx("task", "交辦事由")
        self.assertIn("第二筆已更新事由", [row[subject_col] for row in rows])

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

    def test_ticket_settlement_update_reflected_via_on_activated(self):
        # 模擬發文結算（settle_selected 的效果）：另一頁把未發文罰單補上
        # 發文日期／發文者。驗證瀏覽頁「切回來」真正用到的入口 on_activated()
        # （指紋比對→_diffUpdate），不是直接呼叫 _diffUpdate() 繞過指紋層。
        self.tab.buildInitial("ticket")
        conn = sqlite3.connect(self.db)
        conn.execute(
            "UPDATE Document_Ticket SET register_date=?, sender_id=?, "
            "last_modified=? WHERE doc_id=?",
            ("2026-07-23", "P01", "2099-01-01 00:00:00", "2"))
        conn.commit()
        conn.close()

        self.tab.on_activated()

        rows = self._visible_rows("ticket")
        date_col = _col_idx("ticket", "register_date")
        self.assertIn("2026-07-23", [row[date_col] for row in rows])

    def test_ticket_external_insert_reflected_via_on_activated(self):
        self.tab.buildInitial("ticket")
        conn = sqlite3.connect(self.db)
        conn.execute(
            "INSERT INTO Document_Ticket"
            "(doc_id,create_date,register_date,sender_id,issuer_id,ticket_no) "
            "VALUES(?,?,?,?,?,?)",
            ("3", "2026-07-05", "2026-07-05", "P01", "P02", "EF9012"))
        conn.commit()
        conn.close()

        self.tab.on_activated()

        self._assert_aligned("ticket", ["1", "2", "3"])

    def test_ticket_delete_via_domain_helper_removes_row_and_keeps_alignment(self):
        # 罰單瀏覽頁刪除走 lib.ticket_utils.deleteTicket()（非 _DELETE_CLEAR_SQL），
        # 驗證 _diffUpdate 仍能感知並保持 1:1 對應（與其餘三表共用同一機制）。
        from lib.ticket_utils import deleteTicket
        self.tab.buildInitial("ticket")
        conn = sqlite3.connect(self.db)
        deleteTicket(conn, doc_id="1", role="admin")
        conn.commit()
        conn.close()
        self.tab._diffUpdate("ticket")
        self._assert_aligned("ticket", ["2"])


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


class TestGenericViewNumericOrder(unittest.TestCase):
    """保護對象：queryBrowseRows 泛用 view 路徑的 ORDER BY（非 raw 表，如 task/crim/gen/ticket）。

    doc_id 為文字欄，若無明確數字排序，rowid 掃描順序在查詢計畫改變（如走
    doc_id PK 索引）時會退化成字串序（'10' 排在 '2' 之前）。故意先插入
    doc_id='10' 再插入 '2'，只有明確 ORDER BY CAST(... AS INTEGER) 才能
    正確排出 ['2', '10']。"""

    def setUp(self):
        fd, self.db = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        conn = sqlite3.connect(self.db)
        applySchema(conn)
        conn.executescript("""
            INSERT INTO Ref_Personnel(staff_id,staff_name,is_active,sort_order) VALUES
                ('P01','測試員A',1,1),('P02','測試員B',1,2),('P03','測試員C',1,3);
            INSERT INTO Ref_Departments(dept_id,dept_name,is_active,sort_order) VALUES
                ('D01','偵查隊',1,1);
        """)
        conn.executemany(
            "INSERT INTO Document_Task"
            "(doc_id,receive_date,receive_id,dept_id,subject,processor_id,"
            " deadline,dispatch_date,sender_id,timestamp) VALUES(?,?,?,?,?,?,?,?,?,?)",
            [("10", "2026-07-01", "P02", "D01", "先插入的十號", "P01",
              "2026-07-20", "2026-07-05", "P03", "2026-07-01 09:00:00"),
             ("2", "2026-07-02", "P02", "D01", "後插入的二號", "P02",
              "2026-07-21", None, "P03", "2026-07-02 09:00:00")])
        conn.commit()
        conn.close()
        self.addCleanup(lambda: os.remove(self.db) if os.path.exists(self.db) else None)

    def test_task_view_orders_doc_id_numerically(self):
        from tabs.tab_dbbrowse import queryBrowseRows
        conn = sqlite3.connect(self.db)
        try:
            rows = queryBrowseRows(conn, "task")
        finally:
            conn.close()
        self.assertEqual([r["編號"] for r in rows], ["2", "10"])


if __name__ == "__main__":
    unittest.main()
