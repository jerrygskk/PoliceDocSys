# -*- coding: utf-8 -*-
"""共用軟刪除 helper（db_utils.softDeleteDoc）：快照→回收筒→清空→稽核。

涵蓋四處刪除合併後的差異規則：
  - operator 取值：admin 留空、非 admin 業務頁記 operator 來源欄的人、
    瀏覽頁（audit_operator=False）一律留空
  - 各主表清空式 UPDATE、回收筒對象人取承辦人、稽核類別正確

受測模組 import 時會載入 PySide6（db_utils 依賴），故執行環境需裝 PySide6。
"""
import os
import sys
import sqlite3
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from lib import db_schema
from lib import db_utils


def _make_db():
    conn = sqlite3.connect(":memory:")
    conn.executescript("""
        CREATE TABLE Ref_Personnel (staff_id TEXT PRIMARY KEY, staff_name TEXT);
        CREATE TABLE Document_Task (
            doc_id TEXT PRIMARY KEY, receive_date TEXT, receive_id TEXT,
            dept_id TEXT, subject TEXT, processor_id TEXT, deadline TEXT,
            dispatch_date TEXT, sender_id TEXT, timestamp TEXT);
        CREATE TABLE Document_Criminal (
            doc_id TEXT PRIMARY KEY, report_date TEXT, sender_id TEXT,
            case_type TEXT, case_status TEXT, processor_id TEXT,
            subject_summary TEXT, occurrence_date TEXT, reporter_name TEXT,
            receiver_id TEXT, is_reported INTEGER DEFAULT 0,
            is_electronic TEXT DEFAULT '');
        CREATE TABLE Document_General (
            doc_id TEXT PRIMARY KEY, report_date TEXT, sender_id TEXT,
            dept_id TEXT, gen_cat_id TEXT, subject TEXT, processor_id TEXT,
            is_reported INTEGER DEFAULT 0, is_electronic TEXT DEFAULT '');
    """)
    for sql in db_schema._TABLES:        # Audit_Log + Trash_Documents 走正式 DDL
        conn.execute(sql)
    conn.executescript("""
        INSERT INTO Ref_Personnel VALUES('P01','王收文');
        INSERT INTO Ref_Personnel VALUES('P02','李承辦');
        INSERT INTO Ref_Personnel VALUES('P03','張陳報');
    """)
    return conn


class TestSoftDelete(unittest.TestCase):
    def setUp(self):
        self.conn = _make_db()

    def tearDown(self):
        self.conn.close()

    def _audit(self):
        return self.conn.execute(
            "SELECT operator, target_table, detail FROM Audit_Log "
            "ORDER BY log_id DESC LIMIT 1").fetchone()

    def _trash(self):
        return self.conn.execute(
            "SELECT subject, doc_person, deleted_role FROM Trash_Documents "
            "ORDER BY trash_id DESC LIMIT 1").fetchone()

    def test_task_delete_by_user_records_receiver(self):
        self.conn.execute(
            "INSERT INTO Document_Task(doc_id, receive_id, subject, processor_id)"
            " VALUES('T1','P01','協尋','P02')")
        subj = db_utils.softDeleteDoc(
            self.conn, table="Document_Task", doc_id="T1",
            role="user", is_admin=False)
        self.conn.commit()
        self.assertEqual(subj, "協尋")
        # 清空：除 doc_id 外全 NULL
        row = self.conn.execute(
            "SELECT subject, receive_id, processor_id FROM Document_Task "
            "WHERE doc_id='T1'").fetchone()
        self.assertEqual(row, (None, None, None))
        # 稽核 operator = 收文者；回收筒對象人 = 承辦人
        op, tbl, detail = self._audit()
        self.assertEqual(op, "王收文")
        self.assertEqual(tbl, "Document_Task")
        self.assertIn("協尋", detail)
        self.assertEqual(self._trash(), ("協尋", "李承辦", "user"))

    def test_task_delete_by_admin_operator_blank(self):
        self.conn.execute(
            "INSERT INTO Document_Task(doc_id, receive_id, subject, processor_id)"
            " VALUES('T2','P01','失蹤','P02')")
        db_utils.softDeleteDoc(
            self.conn, table="Document_Task", doc_id="T2",
            role="admin", is_admin=True)
        self.conn.commit()
        self.assertIsNone(self._audit()[0])      # admin → operator 留空
        self.assertEqual(self._trash()[1], "李承辦")

    def test_criminal_delete_by_user_records_sender(self):
        self.conn.execute(
            "INSERT INTO Document_Criminal(doc_id, sender_id, subject_summary,"
            " processor_id) VALUES('C1','P03','竊盜','P02')")
        subj = db_utils.softDeleteDoc(
            self.conn, table="Document_Criminal", doc_id="C1",
            role="archive", is_admin=False)
        self.conn.commit()
        self.assertEqual(subj, "竊盜")
        self.assertEqual(self._audit()[0], "張陳報")   # 刑案 operator 來源 = sender
        self.assertEqual(self._trash()[1], "李承辦")

    def test_browse_delete_operator_always_blank(self):
        self.conn.execute(
            "INSERT INTO Document_General(doc_id, sender_id, subject, processor_id)"
            " VALUES('G1','P03','陳報事項','P02')")
        # 瀏覽頁：audit_operator=False → 即使非 admin 也留空
        db_utils.softDeleteDoc(
            self.conn, table="Document_General", doc_id="G1",
            role="user", is_admin=False, audit_operator=False)
        self.conn.commit()
        self.assertIsNone(self._audit()[0])
        self.assertEqual(self._trash()[0], "陳報事項")

    def test_bad_table_noop(self):
        self.assertEqual(
            db_utils.softDeleteDoc(self.conn, table="Evil", doc_id="x",
                                   role="admin", is_admin=True), "")


if __name__ == "__main__":
    unittest.main()
