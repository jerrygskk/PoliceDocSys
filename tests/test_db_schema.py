# -*- coding: utf-8 -*-
"""db_schema.ensureSchema 冪等確保附加式結構（純 stdlib，可單測）。"""
import os
import sys
import tempfile
import sqlite3
import unittest

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


if __name__ == "__main__":
    unittest.main()
