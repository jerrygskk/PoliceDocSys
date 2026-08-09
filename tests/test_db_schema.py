# -*- coding: utf-8 -*-
"""db_schema.ensureSchema 冪等確保附加式結構（純 stdlib，可單測）。"""
import os
import re
import sys
import tempfile
import sqlite3
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from lib import db_schema


def _tables(conn):
    return {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}


def _cols(conn, table):
    return [r[1] for r in conn.execute(f"PRAGMA table_info({table})")]


class TestEnsureSchema(unittest.TestCase):
    def setUp(self):
        fd, self.db = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        # 建一個最小 baseline：只有一張無關表，沒有 Audit_Log
        conn = sqlite3.connect(self.db)
        conn.execute("CREATE TABLE App_Settings (key TEXT PRIMARY KEY, value TEXT)")
        conn.commit()
        conn.close()

    def tearDown(self):
        try:
            os.remove(self.db)
        except OSError:
            pass

    def test_creates_audit_log(self):
        db_schema.ensureSchema(self.db)
        conn = sqlite3.connect(self.db)
        try:
            self.assertIn("Audit_Log", _tables(conn))
            self.assertEqual(
                _cols(conn, "Audit_Log"),
                ["log_id", "ts", "role", "action",
                 "target_table", "target_id", "operator", "detail"])
        finally:
            conn.close()

    def test_idempotent(self):
        # 跑兩次不報錯、表只一張、欄位不變
        db_schema.ensureSchema(self.db)
        db_schema.ensureSchema(self.db)
        conn = sqlite3.connect(self.db)
        try:
            n = conn.execute(
                "SELECT COUNT(*) FROM sqlite_master "
                "WHERE type='table' AND name='Audit_Log'").fetchone()[0]
            self.assertEqual(n, 1)
        finally:
            conn.close()

    def test_does_not_wipe_existing_data(self):
        # 既有 Audit_Log 含資料 → ensureSchema 不得重建/清空
        conn = sqlite3.connect(self.db)
        for sql in db_schema._TABLES:
            conn.execute(sql)
        conn.execute(
            "INSERT INTO Audit_Log(ts, role, action, detail) "
            "VALUES('2026-06-27', 'admin', '登入', '[系統][登入]')")
        conn.commit()
        conn.close()

        db_schema.ensureSchema(self.db)

        conn = sqlite3.connect(self.db)
        try:
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM Audit_Log").fetchone()[0], 1)
        finally:
            conn.close()

    def test_missing_db_no_raise(self):
        # 路徑不存在 / 空值不得拋例外
        db_schema.ensureSchema(os.path.join(tempfile.gettempdir(), "no_such.db"))
        db_schema.ensureSchema("")
        db_schema.ensureSchema(None)

    def test_add_column_idempotent(self):
        conn = sqlite3.connect(self.db)
        try:
            db_schema._add_column(conn, "App_Settings", "note", "TEXT")
            self.assertIn("note", _cols(conn, "App_Settings"))
            # 再加一次不報錯、不重複
            db_schema._add_column(conn, "App_Settings", "note", "TEXT")
            self.assertEqual(_cols(conn, "App_Settings").count("note"), 1)
        finally:
            conn.close()

    def test_upgrades_legacy_reward_table_with_create_date(self):
        conn = sqlite3.connect(self.db)
        try:
            conn.execute(
                "CREATE TABLE Document_Reward ("
                "doc_id TEXT PRIMARY KEY, register_date DATE, sender_id TEXT, "
                "reason TEXT, recipients TEXT, last_modified DATETIME)")
            conn.execute(
                "INSERT INTO Document_Reward(doc_id, register_date) VALUES(?, ?)",
                ("legacy-unissued", ""))
            conn.commit()
        finally:
            conn.close()

        db_schema.ensureSchema(self.db)

        conn = sqlite3.connect(self.db)
        try:
            self.assertIn("create_date", _cols(conn, "Document_Reward"))
            self.assertEqual(
                conn.execute(
                    "SELECT create_date, register_date FROM Document_Reward "
                    "WHERE doc_id=?", ("legacy-unissued",)).fetchone(),
                (None, ""))
        finally:
            conn.close()

    def test_upgrades_legacy_report_tables_without_backfill_and_rebuilds_views(self):
        conn = sqlite3.connect(self.db)
        try:
            conn.execute(
                "CREATE TABLE Document_Criminal ("
                "doc_id TEXT PRIMARY KEY, report_date DATE, sender_id TEXT, "
                "case_type TEXT, case_status TEXT, processor_id TEXT, "
                "subject_summary TEXT, occurrence_date DATE, "
                "reporter_name TEXT, receiver_id TEXT, is_reported BOOLEAN, "
                "is_electronic TEXT, last_modified DATETIME)")
            conn.execute(
                "CREATE TABLE Document_General ("
                "doc_id TEXT PRIMARY KEY, report_date DATE, sender_id TEXT, "
                "dept_id TEXT, gen_cat_id TEXT, subject TEXT, "
                "processor_id TEXT, is_reported BOOLEAN, "
                "is_electronic TEXT, last_modified DATETIME)")
            conn.execute(
                "INSERT INTO Document_Criminal"
                "(doc_id, report_date, subject_summary) VALUES(?, ?, ?)",
                ("C1", "2026-07-01", "舊刑案"))
            conn.execute(
                "INSERT INTO Document_General"
                "(doc_id, report_date, subject) VALUES(?, ?, ?)",
                ("G1", "2026-07-02", "舊一般"))
            conn.execute(
                "CREATE VIEW View_Criminal_Full AS "
                "SELECT doc_id AS '送文編號' FROM Document_Criminal")
            conn.execute(
                "CREATE VIEW View_General_Full AS "
                "SELECT doc_id AS '送文編號' FROM Document_General")
            conn.commit()
        finally:
            conn.close()

        db_schema.ensureSchema(self.db)

        conn = sqlite3.connect(self.db)
        try:
            self.assertIn("create_date", _cols(conn, "Document_Criminal"))
            self.assertIn("create_date", _cols(conn, "Document_General"))
            self.assertIsNone(conn.execute(
                "SELECT create_date FROM Document_Criminal WHERE doc_id='C1'"
            ).fetchone()[0])
            self.assertIsNone(conn.execute(
                "SELECT create_date FROM Document_General WHERE doc_id='G1'"
            ).fetchone()[0])
            self.assertIn("登錄日期", _cols(conn, "View_Criminal_Full"))
            self.assertIn("登錄日期", _cols(conn, "View_General_Full"))
        finally:
            conn.close()

    def test_rebuilds_both_report_views_atomically(self):
        conn = sqlite3.connect(self.db)
        try:
            db_schema.applySchema(conn)
            conn.execute("DROP VIEW View_Criminal_Full")
            conn.execute("DROP VIEW View_General_Full")
            conn.execute(
                "CREATE VIEW View_Criminal_Full AS "
                "SELECT doc_id AS '舊刑案欄' FROM Document_Criminal")
            conn.execute(
                "CREATE VIEW View_General_Full AS "
                "SELECT doc_id AS '舊一般欄' FROM Document_General")
            conn.commit()
        finally:
            conn.close()

        broken_views = list(db_schema._VIEWS)
        general_index = next(
            i for i, sql in enumerate(broken_views)
            if "View_General_Full" in sql)
        broken_views[general_index] = (
            "CREATE VIEW IF NOT EXISTS View_General_Full AS SELECT FROM")
        with mock.patch.object(db_schema, "_VIEWS", tuple(broken_views)):
            db_schema.ensureSchema(self.db)

        conn = sqlite3.connect(self.db)
        try:
            self.assertEqual(
                conn.execute("SELECT 舊刑案欄 FROM View_Criminal_Full").fetchall(),
                [])
            self.assertEqual(
                conn.execute("SELECT 舊一般欄 FROM View_General_Full").fetchall(),
                [])
        finally:
            conn.close()

    def test_skips_view_repair_if_report_column_addition_still_failed(self):
        conn = sqlite3.connect(self.db)
        try:
            conn.execute(
                "CREATE TABLE Document_Criminal (doc_id TEXT PRIMARY KEY)")
            conn.execute(
                "CREATE TABLE Document_General (doc_id TEXT PRIMARY KEY)")
            conn.execute(
                "CREATE VIEW View_Criminal_Full AS "
                "SELECT doc_id AS '舊刑案欄' FROM Document_Criminal")
            conn.execute(
                "CREATE VIEW View_General_Full AS "
                "SELECT doc_id AS '舊一般欄' FROM Document_General")
            conn.commit()
        finally:
            conn.close()

        with mock.patch.object(db_schema, "_add_column", return_value=None):
            db_schema.ensureSchema(self.db)

        conn = sqlite3.connect(self.db)
        try:
            self.assertNotIn("create_date", _cols(conn, "Document_Criminal"))
            self.assertEqual(_cols(conn, "View_Criminal_Full"), ["舊刑案欄"])
            self.assertEqual(_cols(conn, "View_General_Full"), ["舊一般欄"])
        finally:
            conn.close()

    def test_preserves_existing_report_create_dates_while_repairing_views(self):
        db_schema.ensureSchema(self.db)
        conn = sqlite3.connect(self.db)
        try:
            conn.execute(
                "INSERT INTO Document_Criminal(doc_id, create_date) "
                "VALUES('C-FILLED', '2026-07-15')")
            conn.execute(
                "INSERT INTO Document_General(doc_id, create_date) "
                "VALUES('G-FILLED', '2026-07-16')")
            conn.execute("DROP VIEW View_Criminal_Full")
            conn.execute("DROP VIEW View_General_Full")
            conn.execute(
                "CREATE VIEW View_Criminal_Full AS "
                "SELECT doc_id AS '送文編號' FROM Document_Criminal")
            conn.execute(
                "CREATE VIEW View_General_Full AS "
                "SELECT doc_id AS '送文編號' FROM Document_General")
            conn.commit()
        finally:
            conn.close()

        db_schema.ensureSchema(self.db)

        conn = sqlite3.connect(self.db)
        try:
            self.assertEqual(conn.execute(
                "SELECT create_date FROM Document_Criminal "
                "WHERE doc_id='C-FILLED'").fetchone()[0], "2026-07-15")
            self.assertEqual(conn.execute(
                "SELECT create_date FROM Document_General "
                "WHERE doc_id='G-FILLED'").fetchone()[0], "2026-07-16")
        finally:
            conn.close()

    def test_equivalent_view_formatting_is_not_rebuilt(self):
        db_schema.ensureSchema(self.db)
        conn = sqlite3.connect(self.db)
        try:
            original = conn.execute(
                "SELECT sql FROM sqlite_master "
                "WHERE type='view' AND name='View_Criminal_Full'").fetchone()[0]
            reformatted = re.sub(
                r"\bAS '([^']+)'", r'AS "\1"', original).replace(
                    "\n", "  \n")
            conn.execute("DROP VIEW View_Criminal_Full")
            conn.execute(reformatted)
            conn.commit()
            stored_before = conn.execute(
                "SELECT sql FROM sqlite_master "
                "WHERE type='view' AND name='View_Criminal_Full'").fetchone()[0]
        finally:
            conn.close()

        db_schema.ensureSchema(self.db)

        conn = sqlite3.connect(self.db)
        try:
            stored_after = conn.execute(
                "SELECT sql FROM sqlite_master "
                "WHERE type='view' AND name='View_Criminal_Full'").fetchone()[0]
            self.assertEqual(stored_after, stored_before)
        finally:
            conn.close()

    def test_view_literal_whitespace_difference_triggers_rebuild(self):
        db_schema.ensureSchema(self.db)
        canonical = next(
            sql for sql in db_schema._VIEWS if "View_General_Full" in sql)
        altered = canonical.replace("THEN '已歸檔'", "THEN '已 歸檔'")
        conn = sqlite3.connect(self.db)
        try:
            conn.execute("DROP VIEW View_General_Full")
            conn.execute(altered)
            conn.execute(
                "INSERT INTO Document_General"
                "(doc_id, subject, is_electronic) VALUES('G1', '主旨', 'file.pdf')")
            conn.commit()
        finally:
            conn.close()

        db_schema.ensureSchema(self.db)

        conn = sqlite3.connect(self.db)
        try:
            self.assertEqual(conn.execute(
                "SELECT 電子檔 FROM View_General_Full "
                "WHERE 送文編號='G1'").fetchone()[0], "已歸檔")
        finally:
            conn.close()

    def test_view_literal_escaped_quote_difference_triggers_rebuild(self):
        db_schema.ensureSchema(self.db)
        canonical = next(
            sql for sql in db_schema._VIEWS if "View_General_Full" in sql)
        altered = canonical.replace(
            "ELSE '否' END AS '紙本'", "ELSE '否''' END AS '紙本'")
        conn = sqlite3.connect(self.db)
        try:
            conn.execute("DROP VIEW View_General_Full")
            conn.execute(altered)
            conn.execute(
                "INSERT INTO Document_General"
                "(doc_id, subject, is_reported) VALUES('G1', '主旨', 0)")
            conn.commit()
        finally:
            conn.close()

        db_schema.ensureSchema(self.db)

        conn = sqlite3.connect(self.db)
        try:
            self.assertEqual(conn.execute(
                "SELECT 紙本 FROM View_General_Full "
                "WHERE 送文編號='G1'").fetchone()[0], "否")
        finally:
            conn.close()

    def test_non_ascii_identifier_difference_triggers_rebuild(self):
        db_schema.ensureSchema(self.db)
        canonical = next(
            sql for sql in db_schema._VIEWS if "View_Criminal_Full" in sql)
        altered = canonical.replace("CS.status_name", "Cſ.status_name")
        conn = sqlite3.connect(self.db)
        try:
            conn.execute("DROP VIEW View_Criminal_Full")
            conn.execute(altered)
            conn.execute(
                "INSERT INTO Ref_Case_Status(status_id, status_name) "
                "VALUES('CS01', '現行')")
            conn.execute(
                "INSERT INTO Document_Criminal"
                "(doc_id, subject_summary, case_status) "
                "VALUES('C1', '案由', 'CS01')")
            conn.commit()
        finally:
            conn.close()

        db_schema.ensureSchema(self.db)

        conn = sqlite3.connect(self.db)
        try:
            self.assertEqual(conn.execute(
                "SELECT 發文分類 FROM View_Criminal_Full "
                "WHERE 送文編號='C1'").fetchone()[0], "現行")
        finally:
            conn.close()

    def test_fresh_report_views_include_create_date(self):
        db_schema.ensureSchema(self.db)

        conn = sqlite3.connect(self.db)
        try:
            self.assertIn("登錄日期", _cols(conn, "View_Criminal_Full"))
            self.assertIn("登錄日期", _cols(conn, "View_General_Full"))
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
