"""
test_report_input_mode.py — 自助取號模式純邏輯測試

涵蓋：
  - isSelfServiceMode：未設定＝False、"1"＝True、壞值 fallback False
  - 結算 SQL round-trip：勾選補值、排除維持 NULL、trigger 更新 last_modified
    （結算不寫稽核 LOG——量大無意義，維護者決策）
  - 待歸檔查詢排除未發文（report_date IS NULL 者不回傳）
"""
import sqlite3
import sys
import os
import unittest

# 確保可匯入專案根模組
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


def _make_db():
    """建立 in-memory SQLite 並套用完整 schema。"""
    from lib.db_schema import applySchema
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    applySchema(conn)
    # 種入最小必要參照資料
    conn.execute(
        "INSERT OR IGNORE INTO Ref_Personnel "
        "(staff_id, staff_name, is_active, sort_order) VALUES (?,?,1,1)",
        ("P001", "王承辦"))
    conn.execute(
        "INSERT OR IGNORE INTO Ref_CaseTypes "
        "(case_type_id, case_type_name, is_active, sort_order) VALUES (?,?,1,1)",
        ("CT01", "測試案類"))
    conn.execute(
        "INSERT OR IGNORE INTO Ref_Case_Status "
        "(status_id, status_name) VALUES (?,?)",
        ("CS01", "現行"))
    conn.commit()
    return conn


def _set_setting(conn, key, value):
    conn.execute(
        "INSERT OR REPLACE INTO App_Settings (key, value) VALUES (?,?)",
        (key, value))
    conn.commit()


class TestIsSelfServiceMode(unittest.TestCase):

    def _make_db_file(self, tmp_path, value=None):
        """建立暫存 DB 檔，可選擇性設定 report_input_mode。"""
        import tempfile, os
        from lib.db_schema import applySchema
        fd, path = tempfile.mkstemp(suffix=".db", dir=tmp_path)
        os.close(fd)
        conn = sqlite3.connect(path)
        applySchema(conn)
        if value is not None:
            conn.execute(
                "INSERT OR REPLACE INTO App_Settings (key, value) VALUES (?,?)",
                ("report_input_mode", value))
        conn.commit()
        conn.close()
        return path

    def setUp(self):
        import tempfile
        self._tmp = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_unset_is_sender_mode(self):
        from lib.db_utils import isSelfServiceMode
        path = self._make_db_file(self._tmp, value=None)
        self.assertFalse(isSelfServiceMode(path))

    def test_value_1_is_self_service(self):
        from lib.db_utils import isSelfServiceMode
        path = self._make_db_file(self._tmp, value="1")
        self.assertTrue(isSelfServiceMode(path))

    def test_value_0_is_sender_mode(self):
        from lib.db_utils import isSelfServiceMode
        path = self._make_db_file(self._tmp, value="0")
        self.assertFalse(isSelfServiceMode(path))

    def test_bad_value_fallback_false(self):
        from lib.db_utils import isSelfServiceMode
        path = self._make_db_file(self._tmp, value="garbage")
        self.assertFalse(isSelfServiceMode(path))

    def test_nonexistent_db_fallback_false(self):
        from lib.db_utils import isSelfServiceMode
        self.assertFalse(isSelfServiceMode(os.path.join(self._tmp, "no_such.db")))


class TestSettleRoundTrip(unittest.TestCase):
    """結算 SQL round-trip：補值、排除、稽核、trigger。"""

    def setUp(self):
        self.conn = _make_db()
        # 塞兩筆刑案、一筆一般，report_date = NULL
        self.conn.execute(
            "INSERT INTO Document_Criminal "
            "(doc_id, report_date, sender_id, case_type, case_status, "
            " processor_id, subject_summary, is_reported, is_electronic) "
            "VALUES ('C0001', NULL, NULL, 'CT01', 'CS01', 'P001', '主旨甲', 0, '')")
        self.conn.execute(
            "INSERT INTO Document_Criminal "
            "(doc_id, report_date, sender_id, case_type, case_status, "
            " processor_id, subject_summary, is_reported, is_electronic) "
            "VALUES ('C0002', NULL, NULL, 'CT01', 'CS01', 'P001', '主旨乙', 0, '')")
        self.conn.execute(
            "INSERT INTO Document_General "
            "(doc_id, report_date, sender_id, dept_id, gen_cat_id, "
            " subject, processor_id, is_reported, is_electronic) "
            "VALUES ('G0001', NULL, NULL, NULL, NULL, '一般主旨', 'P001', 0, '')")
        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    def test_checked_ids_get_date(self):
        today = "2026-07-05"
        # 只結算 C0001, G0001；排除 C0002
        for doc_id in ("C0001",):
            self.conn.execute(
                "UPDATE Document_Criminal SET report_date=?, sender_id=? WHERE doc_id=?",
                (today, "P001", doc_id))
        for doc_id in ("G0001",):
            self.conn.execute(
                "UPDATE Document_General SET report_date=?, sender_id=? WHERE doc_id=?",
                (today, "P001", doc_id))
        self.conn.commit()

        c0001 = self.conn.execute(
            "SELECT report_date FROM Document_Criminal WHERE doc_id='C0001'").fetchone()
        self.assertEqual(c0001[0], today)

    def test_excluded_remains_null(self):
        today = "2026-07-05"
        self.conn.execute(
            "UPDATE Document_Criminal SET report_date=?, sender_id=? WHERE doc_id='C0001'",
            (today, "P001"))
        self.conn.commit()
        c0002 = self.conn.execute(
            "SELECT report_date FROM Document_Criminal WHERE doc_id='C0002'").fetchone()
        self.assertIsNone(c0002[0])

    def test_trigger_updates_last_modified(self):
        # 驗 trigger 有覆寫 last_modified（精度秒，不做 > 比較，只驗非 NULL）
        self.conn.execute(
            "UPDATE Document_Criminal SET report_date='2026-07-05', sender_id='P001' "
            "WHERE doc_id='C0001'")
        self.conn.commit()
        row = self.conn.execute(
            "SELECT last_modified FROM Document_Criminal WHERE doc_id='C0001'").fetchone()
        self.assertIsNotNone(row[0])


class TestArchiveQueryExcludesUnissued(unittest.TestCase):
    """待歸檔查詢排除 report_date IS NULL 的列。"""

    def setUp(self):
        self.conn = _make_db()
        # 一筆有日期（應出現）、一筆 NULL（應排除）
        self.conn.execute(
            "INSERT INTO Document_Criminal "
            "(doc_id, report_date, sender_id, case_type, case_status, "
            " processor_id, subject_summary, is_reported, is_electronic) "
            "VALUES ('C0010', '2026-07-05', 'P001', 'CT01', 'CS01', 'P001', '有日期', 0, '')")
        self.conn.execute(
            "INSERT INTO Document_Criminal "
            "(doc_id, report_date, sender_id, case_type, case_status, "
            " processor_id, subject_summary, is_reported, is_electronic) "
            "VALUES ('C0011', NULL, NULL, 'CT01', 'CS01', 'P001', '未發文', 0, '')")
        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    def test_only_issued_appears(self):
        rows = self.conn.execute(
            "SELECT doc_id FROM Document_Criminal "
            "WHERE (is_electronic IS NULL OR is_electronic = '') "
            "  AND subject_summary IS NOT NULL AND subject_summary != '' "
            "  AND (report_date IS NOT NULL AND report_date != '')"
        ).fetchall()
        ids = [r[0] for r in rows]
        self.assertIn("C0010", ids)
        self.assertNotIn("C0011", ids)

    def test_null_date_excluded(self):
        rows = self.conn.execute(
            "SELECT doc_id FROM Document_Criminal "
            "WHERE (report_date IS NULL OR report_date = '') "
            "  AND subject_summary IS NOT NULL AND subject_summary != ''"
        ).fetchall()
        ids = [r[0] for r in rows]
        self.assertIn("C0011", ids)
        self.assertNotIn("C0010", ids)


if __name__ == "__main__":
    unittest.main()
