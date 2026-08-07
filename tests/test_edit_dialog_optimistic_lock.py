# -*- coding: utf-8 -*-
"""交辦／刑案／一般三個編輯彈窗的 `last_modified` 樂觀鎖；只使用暫存 DB。

⚠️ 這三個彈窗在 2026-08-07 之前**完全沒有併發保護**（直接
`UPDATE ... WHERE doc_id=?`，誰後存誰蓋掉）；罰單與敘獎各有一套欄位比對。
三套一併收斂成 `last_modified` 樂觀鎖後，本檔是這三處的第一份測試。
機制說明見 `lib/db_utils.LAST_MODIFIED_CAS_SQL` 與 DEVELOPER §10。

⚠️ 彈框盤點（PITFALLS TST-7）：這條路徑上會彈的框只有 `_rejectIfStale` 的
`msgWarning`。⚠️ **patch 目標是 `ui_utils.ui_common.msgWarning`，不是
`ui_utils.edit_dialog.msgWarning`**——`edit_dialog` 為避開循環 import，是在
**函式內**才 `from .ui_common import msgWarning`，模組上根本沒有這個屬性
（patch 會直接 `AttributeError`）。名字在呼叫當下才從來源模組查，故換來源模組
才攔得到。這與各分頁「模組層 import、要 patch 分頁自己的名字」剛好相反，
判準永遠是**「這個名字實際在哪裡被查到」**。
`_on_save` 內的欄位檢查與 `confirmBox` 在資料填好時不會觸發；日期防呆遮蔽由
根 `conftest.py` 統一掛，本檔不得自己再 patch 一份。
"""
import os
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from lib.auth_manager import AuthManager
from lib.db_schema import applySchema
from lib.db_seed import seedFreshDb
from ui_utils.edit_dialog import (
    CriminalEditDialog, GeneralEditDialog, TaskEditDialog,
)

_app = QApplication.instance() or QApplication([])

# 開窗快照壓成過去的值：`last_modified` 只有秒精度，若讓建檔與後續的他機修改
# 落在同一秒，字串會相同而比不出差異（已知窄縫，見 db_utils 該區塊註解）。
_SNAPSHOT = "2026-08-01 09:00:00"


class _DialogCasBase(unittest.TestCase):
    TABLE = None

    def setUp(self):
        fd, self.db = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        conn = sqlite3.connect(self.db)
        applySchema(conn)
        seedFreshDb(conn)
        conn.executescript("""
            INSERT OR REPLACE INTO Ref_Personnel
                (staff_id,staff_name,is_active,sort_order)
                VALUES('P001','甲員',1,1),('P002','乙員',1,2);
        """)
        self._insertRow(conn)
        conn.execute(
            f"UPDATE {self.TABLE} SET last_modified=? WHERE doc_id='1'",
            (_SNAPSHOT,))
        conn.commit()
        conn.close()
        AuthManager.instance()._role = "admin"

    def tearDown(self):
        AuthManager.instance()._role = "user"
        try:
            os.remove(self.db)
        except OSError:
            pass

    def _insertRow(self, conn):
        raise NotImplementedError

    def _remoteChange(self, sql, last_modified="2026-08-01 10:00:00"):
        """模擬他機異動：改值並把 last_modified 換掉。"""
        conn = sqlite3.connect(self.db)
        conn.execute(sql)
        conn.execute(
            f"UPDATE {self.TABLE} SET last_modified=? WHERE doc_id='1'",
            (last_modified,))
        conn.commit()
        conn.close()

    def _value(self, column):
        conn = sqlite3.connect(self.db)
        try:
            return conn.execute(
                f"SELECT {column} FROM {self.TABLE} WHERE doc_id='1'"
            ).fetchone()[0]
        finally:
            conn.close()

    def _assertBlocked(self, dlg, column, expected):
        with patch("ui_utils.ui_common.msgWarning") as warn:
            dlg._on_save()
        self.assertEqual(self._value(column), expected,
                         "他機的值被本機覆蓋了，樂觀鎖沒擋住")
        warn.assert_called_once()
        self.assertEqual(warn.call_args[0][0], "資料已更新")


class TestTaskDialogOptimisticLock(_DialogCasBase):
    TABLE = "Document_Task"

    def _insertRow(self, conn):
        conn.execute(
            "INSERT INTO Document_Task"
            "(doc_id,receive_date,receive_id,dept_id,subject,processor_id) "
            "VALUES('1','2026-08-01','P001','D01','原主旨','P001')")

    def test_blocks_save_when_row_changed_while_open(self):
        dlg = TaskEditDialog(self.db, "1")
        self.addCleanup(dlg.deleteLater)
        self._remoteChange(
            "UPDATE Document_Task SET subject='他機主旨' WHERE doc_id='1'")
        dlg.w_subject.setText("本機主旨")
        self._assertBlocked(dlg, "subject", "他機主旨")

    def test_saves_normally_when_nobody_touched_the_row(self):
        """防「鎖太緊、正常流程也存不了」。"""
        dlg = TaskEditDialog(self.db, "1")
        self.addCleanup(dlg.deleteLater)
        dlg.w_subject.setText("本機主旨")
        with patch("ui_utils.ui_common.msgWarning") as warn:
            dlg._on_save()
        warn.assert_not_called()
        self.assertEqual(self._value("subject"), "本機主旨")


class TestCriminalDialogOptimisticLock(_DialogCasBase):
    TABLE = "Document_Criminal"

    def _insertRow(self, conn):
        conn.execute(
            "INSERT INTO Document_Criminal"
            "(doc_id,create_date,report_date,sender_id,case_type,case_status,"
            " processor_id,subject_summary,occurrence_date) "
            "VALUES('1','2026-08-01',NULL,NULL,'CT01','CS01','P001',"
            "'原案由','2026-07-30')")

    def test_blocks_save_when_row_changed_while_open(self):
        dlg = CriminalEditDialog(self.db, "1")
        self.addCleanup(dlg.deleteLater)
        self._remoteChange(
            "UPDATE Document_Criminal SET subject_summary='他機案由' "
            "WHERE doc_id='1'")
        dlg.w_subject.setText("本機案由")
        self._assertBlocked(dlg, "subject_summary", "他機案由")

    def test_blocks_save_when_row_was_settled_while_open(self):
        """最實際的情境：開著視窗時這筆被列印頁結算發文了。

        陳報的未發文哨兵是 **NULL**（不是空字串），結算後才寫入日期。
        """
        dlg = CriminalEditDialog(self.db, "1")
        self.addCleanup(dlg.deleteLater)
        self._remoteChange(
            "UPDATE Document_Criminal SET report_date='2026-08-05',"
            "sender_id='P002' WHERE doc_id='1'")
        dlg.w_subject.setText("本機案由")
        self._assertBlocked(dlg, "report_date", "2026-08-05")

    def test_saves_normally_when_nobody_touched_the_row(self):
        dlg = CriminalEditDialog(self.db, "1")
        self.addCleanup(dlg.deleteLater)
        dlg.w_subject.setText("本機案由")
        with patch("ui_utils.ui_common.msgWarning") as warn:
            dlg._on_save()
        warn.assert_not_called()
        self.assertEqual(self._value("subject_summary"), "本機案由")


class TestGeneralDialogOptimisticLock(_DialogCasBase):
    TABLE = "Document_General"

    def _insertRow(self, conn):
        conn.execute(
            "INSERT INTO Document_General"
            "(doc_id,create_date,report_date,sender_id,dept_id,gen_cat_id,"
            " subject,processor_id) "
            "VALUES('1','2026-08-01',NULL,NULL,'D01','GC01','原主旨','P001')")

    def test_blocks_save_when_row_changed_while_open(self):
        dlg = GeneralEditDialog(self.db, "1")
        self.addCleanup(dlg.deleteLater)
        self._remoteChange(
            "UPDATE Document_General SET subject='他機主旨' WHERE doc_id='1'")
        dlg.w_subject.setText("本機主旨")
        self._assertBlocked(dlg, "subject", "他機主旨")

    def test_saves_normally_when_nobody_touched_the_row(self):
        dlg = GeneralEditDialog(self.db, "1")
        self.addCleanup(dlg.deleteLater)
        dlg.w_subject.setText("本機主旨")
        with patch("ui_utils.ui_common.msgWarning") as warn:
            dlg._on_save()
        warn.assert_not_called()
        self.assertEqual(self._value("subject"), "本機主旨")


if __name__ == "__main__":
    unittest.main()
