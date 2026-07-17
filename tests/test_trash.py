# -*- coding: utf-8 -*-
"""誤刪還原回收筒（db_utils 的 snapshotRow／writeTrash／restoreFromTrash）。

受測模組 import 時會載入 PySide6（db_utils 依賴），故執行環境需裝 PySide6。
"""
import os
import sys
import sqlite3
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from lib import db_schema
from lib import db_utils
from ui_utils.trash_panel import _TRASH_CAT


def _make_db():
    conn = sqlite3.connect(":memory:")
    # 最小三主表（只取本測試用得到的欄）
    conn.executescript("""
        CREATE TABLE Document_Criminal (
            doc_id TEXT PRIMARY KEY, report_date TEXT, sender_id TEXT,
            subject_summary TEXT, processor_id TEXT,
            is_reported INTEGER DEFAULT 0, is_electronic TEXT DEFAULT '',
            last_modified TEXT);
        CREATE TABLE Document_Task (doc_id TEXT PRIMARY KEY, subject TEXT);
        CREATE TABLE Document_General (doc_id TEXT PRIMARY KEY, subject TEXT);
        CREATE TRIGGER trg_crim_update AFTER UPDATE ON Document_Criminal
        WHEN NEW.last_modified IS OLD.last_modified
        BEGIN
            UPDATE Document_Criminal SET last_modified=datetime('now','localtime')
            WHERE doc_id = NEW.doc_id;
        END;
    """)
    # 回收筒表走正式 DDL（驗證與 db_schema 同步）
    for sql in db_schema._TABLES:
        if "Trash_Documents" in sql:
            conn.execute(sql)
    return conn


# 模擬瀏覽頁刑案清空式刪除
_CLEAR_CRIM = (
    "UPDATE Document_Criminal SET report_date=NULL, sender_id=NULL, "
    "subject_summary=NULL, processor_id=NULL, is_reported=0, "
    "is_electronic='' WHERE doc_id=?")


class TestTrash(unittest.TestCase):
    def setUp(self):
        self.conn = _make_db()
        self.conn.execute(
            "INSERT INTO Document_Criminal(doc_id, report_date, sender_id, "
            "subject_summary, processor_id, is_reported, is_electronic) "
            "VALUES('C001','2026-06-01','S01','竊盜案','P02',1,'C001-竊盜.pdf')")
        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    def test_snapshot_returns_all_columns(self):
        snap = db_utils.snapshotRow(self.conn, "Document_Criminal", "C001")
        self.assertEqual(snap["subject_summary"], "竊盜案")
        self.assertEqual(snap["is_reported"], 1)
        self.assertEqual(snap["is_electronic"], "C001-竊盜.pdf")

    def test_snapshot_bad_table_or_missing(self):
        self.assertIsNone(db_utils.snapshotRow(self.conn, "Evil", "C001"))
        self.assertIsNone(
            db_utils.snapshotRow(self.conn, "Document_Criminal", "NOPE"))

    def test_delete_then_restore_round_trip(self):
        # 1. 快照 → 寫回收筒 → 清空（模擬刪除）
        snap = db_utils.snapshotRow(self.conn, "Document_Criminal", "C001")
        db_utils.writeTrash(
            self.conn, table_name="Document_Criminal", doc_id="C001",
            payload=snap, subject="竊盜案", doc_person="陳某", deleted_role="admin")
        self.conn.execute(_CLEAR_CRIM, ("C001",))
        self.conn.commit()

        # 空殼確認：列還在、欄已清
        row = self.conn.execute(
            "SELECT subject_summary, is_reported, is_electronic "
            "FROM Document_Criminal WHERE doc_id='C001'").fetchone()
        self.assertEqual(row, (None, 0, ""))

        # 回收筒有一筆
        tr = self.conn.execute(
            "SELECT trash_id, subject, doc_person, deleted_role, deleted_ts "
            "FROM Trash_Documents").fetchone()
        self.assertEqual(tr[1], "竊盜案")
        self.assertEqual(tr[2], "陳某")
        self.assertEqual(tr[3], "admin")
        self.assertTrue(tr[4])  # ts 非空

        # 2. 還原
        ret = db_utils.restoreFromTrash(self.conn, tr[0])
        self.conn.commit()
        self.assertEqual(ret, ("Document_Criminal", "C001"))

        # 資料填回原列、回收筒清空
        back = self.conn.execute(
            "SELECT report_date, sender_id, subject_summary, processor_id, "
            "is_reported, is_electronic FROM Document_Criminal "
            "WHERE doc_id='C001'").fetchone()
        self.assertEqual(
            back, ("2026-06-01", "S01", "竊盜案", "P02", 1, "C001-竊盜.pdf"))
        self.assertEqual(
            self.conn.execute(
                "SELECT COUNT(*) FROM Trash_Documents").fetchone()[0], 0)

    def test_restore_bumps_last_modified(self):
        # 還原須讓 trigger 把 last_modified 蓋成當下（否則瀏覽/歸檔頁指紋偵測不到）。
        # 先把 last_modified 壓成舊值（UPDATE 動到該欄，trigger 的 WHEN 不成立而不蓋）
        self.conn.execute(
            "UPDATE Document_Criminal SET last_modified='2020-01-01 00:00:00' "
            "WHERE doc_id='C001'")
        self.conn.commit()
        snap = db_utils.snapshotRow(self.conn, "Document_Criminal", "C001")
        self.assertEqual(snap["last_modified"], "2020-01-01 00:00:00")  # 快照含舊值
        db_utils.writeTrash(
            self.conn, table_name="Document_Criminal", doc_id="C001",
            payload=snap, subject="竊盜案")
        self.conn.execute(_CLEAR_CRIM, ("C001",))
        self.conn.commit()
        tid = self.conn.execute(
            "SELECT trash_id FROM Trash_Documents").fetchone()[0]
        db_utils.restoreFromTrash(self.conn, tid)
        self.conn.commit()
        lm = self.conn.execute(
            "SELECT last_modified FROM Document_Criminal "
            "WHERE doc_id='C001'").fetchone()[0]
        # 不可停在快照舊值；應已被 trigger 蓋成新時間
        self.assertNotEqual(lm, "2020-01-01 00:00:00")
        self.assertGreater(lm, "2021-01-01")

    def test_restore_bad_id_returns_none(self):
        self.assertIsNone(db_utils.restoreFromTrash(self.conn, 999))

    def test_writetrash_missing_table_silent(self):
        # 沒有 Trash_Documents 表時不得拋例外
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE Document_Task (doc_id TEXT PRIMARY KEY)")
        try:
            db_utils.writeTrash(
                conn, table_name="Document_Task", doc_id="T1",
                payload={"doc_id": "T1"}, subject="x")
        finally:
            conn.close()

    def test_reward_trash_category_is_reward(self):
        self.assertEqual(_TRASH_CAT["Document_Reward"], "敘獎")


if __name__ == "__main__":
    unittest.main()
