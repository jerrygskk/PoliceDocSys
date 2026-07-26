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


def _make_db_file(path):
    """比照 `_make_db()`，但建在磁碟檔案而非 :memory:（供需要驗證真正
    commit 落盤的測試使用）。"""
    from lib.db_schema import applySchema
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    applySchema(conn)
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


class TestSettleDocumentTypes(unittest.TestCase):
    """結算發文處理刑案／一般陳報／罰單；敘獎改由獨立發文頁處理。"""

    def setUp(self):
        import tempfile
        from lib.db_schema import applySchema
        self._tmp = tempfile.mkdtemp()
        self.path = os.path.join(self._tmp, "reward.db")
        conn = sqlite3.connect(self.path)
        applySchema(conn)
        conn.execute(
            "INSERT OR IGNORE INTO Ref_Personnel "
            "(staff_id, staff_name, is_active, sort_order) VALUES ('P001','王承辦',1,1)")
        conn.execute(
            "INSERT INTO Document_Reward"
            "(doc_id,create_date,register_date,reason,recipients) "
            "VALUES ('1','2026-07-01','','事由甲','王承辦')")
        conn.commit()
        conn.close()

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_settle_registry_and_counts_exclude_reward(self):
        from ui_utils.settle_dialog import SETTLE_META, count_unissued
        self.assertEqual(
            [meta["key"] for meta in SETTLE_META], ["crim", "gen", "ticket"])
        counts = count_unissued(self.path)
        self.assertEqual(counts, {"crim": 0, "gen": 0, "ticket": 0})


class TestSettleMetaTicket(unittest.TestCase):
    """Task 7：罰單併入結算 registry（單一擴充點驗證）。"""

    def setUp(self):
        import tempfile
        from lib.db_schema import applySchema
        self._tmp = tempfile.mkdtemp()
        self.path = os.path.join(self._tmp, "ticket_settle.db")
        conn = sqlite3.connect(self.path)
        applySchema(conn)
        conn.execute(
            "INSERT OR IGNORE INTO Ref_Personnel "
            "(staff_id, staff_name, is_active, sort_order) VALUES ('P001','王小明',1,1)")
        conn.execute(
            "INSERT INTO Document_Ticket"
            "(doc_id,create_date,register_date,sender_id,issuer_id,ticket_no) "
            "VALUES ('1','2026-07-20','',NULL,'P001','D4RD15263')")
        conn.commit()
        conn.close()

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_settle_meta_includes_ticket(self):
        from ui_utils.settle_dialog import SETTLE_META
        meta = {m["key"]: m for m in SETTLE_META}["ticket"]
        self.assertEqual(meta["label"], "罰單")
        self.assertEqual(meta["color"], "#6b4fa3")
        self.assertTrue(meta["with_sender"])
        self.assertTrue(meta.get("strict"))

    def test_ticket_unissued_query_and_search_fields(self):
        from ui_utils.settle_dialog import load_unissued
        data = load_unissued(self.path)
        row = data["ticket"][0]
        self.assertEqual(row["doc_id"], "1")
        self.assertEqual(row["processor"], "王小明")
        self.assertEqual(row["subject"], "D4RD15263")


class TestSettleSelectedAtomicity(unittest.TestCase):
    """Task 7：settle_selected() 混合結算的原子性（罰單衝突需整批 rollback）。

    用檔案 DB（非 :memory:）：斷言一律另開一條連線讀取，確保真的 commit
    落到磁碟，而不是只在同一條 conn 上看到「未 commit 也能看到」的假象
    （曾以刪掉 conn.commit() 驗證：用同一條 conn 斷言時三條測試仍全綠）。
    """

    def setUp(self):
        import tempfile
        fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self.conn = _make_db_file(self.db_path)
        self.conn.execute(
            "INSERT INTO Document_Criminal "
            "(doc_id, report_date, sender_id, case_type, case_status, "
            " processor_id, subject_summary, is_reported, is_electronic) "
            "VALUES ('C0050', NULL, NULL, 'CT01', 'CS01', 'P001', '混合結算刑案', 0, '')")
        self.conn.execute(
            "INSERT INTO Document_Ticket"
            "(doc_id,create_date,register_date,sender_id,issuer_id,ticket_no) "
            "VALUES ('T0050','2026-07-20','',NULL,'P001','A1B2C3')")
        self.conn.commit()

    def tearDown(self):
        self.conn.close()
        try:
            os.remove(self.db_path)
        except OSError:
            pass

    def _read_row(self, sql):
        # 另開一條連線讀，確保看到的是「已 commit 落盤」的資料，
        # 不是同一條 conn 上未 commit 也能看見的內容。
        conn = sqlite3.connect(self.db_path)
        try:
            return conn.execute(sql).fetchone()
        finally:
            conn.close()

    def _criminal_report_date(self):
        return self._read_row(
            "SELECT report_date FROM Document_Criminal "
            "WHERE doc_id='C0050'")[0]

    def _ticket_register_date(self):
        return self._read_row(
            "SELECT register_date FROM Document_Ticket "
            "WHERE doc_id='T0050'")[0]

    def test_mixed_settlement_rolls_back_on_ticket_conflict(self):
        from ui_utils.settle_dialog import SettlementConflict, settle_selected
        # 模擬他機已搶先把該罰單發文（register_date 不再是 ''）。
        self.conn.execute(
            "UPDATE Document_Ticket SET register_date='2026-07-22' "
            "WHERE doc_id='T0050'")
        self.conn.commit()

        selected = {"crim": ["C0050"], "gen": [], "ticket": ["T0050"]}
        with self.assertRaises(SettlementConflict):
            settle_selected(self.conn, selected, "2026-07-23", "P001")

        self.assertIsNone(self._criminal_report_date())
        self.assertEqual(self._ticket_register_date(), "2026-07-22")

    def test_mixed_settlement_commits_when_no_conflict(self):
        from ui_utils.settle_dialog import settle_selected
        selected = {"crim": ["C0050"], "gen": [], "ticket": ["T0050"]}
        settled_n = settle_selected(self.conn, selected, "2026-07-23", "P001")
        self.assertEqual(settled_n, 2)
        self.assertEqual(self._criminal_report_date(), "2026-07-23")
        self.assertEqual(self._ticket_register_date(), "2026-07-23")

    def test_settlement_updates_ticket_last_modified_for_browse_fingerprint(self):
        # 瀏覽頁的「切回來即刷新」完全靠指紋 (COUNT, MAX(last_modified))；
        # settle_selected() 若漏了某型態、trigger 沒被觸發，瀏覽頁會凍結在舊資料。
        from ui_utils.settle_dialog import settle_selected
        settle_selected(self.conn, {"crim": [], "gen": [], "ticket": ["T0050"]},
                         "2026-07-23", "P001")
        after = self._read_row(
            "SELECT last_modified FROM Document_Ticket WHERE doc_id='T0050'")[0]
        # trigger 精度只到秒，不做 > 比較（比照 TestSettleRoundTrip 既有寫法），
        # 只驗 trigger 確實有寫入而非 NULL（NULL 代表 trigger 未觸發，指紋算不出來）。
        self.assertIsNotNone(after)

    def test_settlement_writes_no_audit_row(self):
        # 結算不寫稽核 LOG 是既有維護者決策（量大無查核意義，見 DEVELOPER
        # 「自助取號模式」§3），本測試鎖住此行為避免日後不小心補寫造成雙軌。
        from ui_utils.settle_dialog import settle_selected
        settle_selected(self.conn, {"crim": ["C0050"], "gen": [], "ticket": ["T0050"]},
                         "2026-07-23", "P001")
        rows = self._read_row("SELECT COUNT(*) FROM Audit_Log")
        self.assertEqual(rows[0], 0)

    def test_non_strict_type_conflict_skips_without_raising(self):
        """刑案／一般沿用既有部分結算語意：非 strict 型態衝突不 raise、不 rollback。"""
        from ui_utils.settle_dialog import settle_selected
        self.conn.execute(
            "UPDATE Document_Criminal SET report_date='2026-07-22', sender_id='P001' "
            "WHERE doc_id='C0050'")
        self.conn.commit()

        selected = {"crim": ["C0050"], "gen": [], "ticket": ["T0050"]}
        settled_n = settle_selected(self.conn, selected, "2026-07-23", "P001")
        self.assertEqual(settled_n, 1)  # 只有罰單真的被結算
        self.assertEqual(self._criminal_report_date(), "2026-07-22")  # 維持原值
        self.assertEqual(self._ticket_register_date(), "2026-07-23")


class TestSettleConcurrencyGuard(unittest.TestCase):
    """結算視窗資料過期時，不覆寫他機異動或復活軟刪除列。"""

    def setUp(self):
        self.conn = _make_db()
        self.conn.execute(
            "INSERT OR IGNORE INTO Ref_Personnel "
            "(staff_id, staff_name, is_active, sort_order) VALUES (?,?,1,2)",
            ("P002", "李送文"))
        from ui_utils.settle_dialog import SETTLE_META
        self.meta = {meta["key"]: meta for meta in SETTLE_META}

    def tearDown(self):
        self.conn.close()

    def test_settle_skips_already_issued_crim(self):
        self.conn.execute(
            "INSERT INTO Document_Criminal "
            "(doc_id, report_date, sender_id, subject_summary) "
            "VALUES ('C0091', NULL, NULL, '刑案併發測試')")
        self.conn.execute(
            "UPDATE Document_Criminal SET report_date=?, sender_id=? "
            "WHERE doc_id=?", ("2026-07-01", "P001", "C0091"))

        cur = self.conn.execute(
            self.meta["crim"]["update"],
            ("2026-07-20", "P002", "C0091"))
        row = self.conn.execute(
            "SELECT report_date, sender_id FROM Document_Criminal "
            "WHERE doc_id='C0091'").fetchone()

        self.assertEqual(cur.rowcount, 0)
        self.assertEqual(tuple(row), ("2026-07-01", "P001"))

    def test_settle_skips_already_issued_gen(self):
        self.conn.execute(
            "INSERT INTO Document_General "
            "(doc_id, report_date, sender_id, subject) "
            "VALUES ('G0091', NULL, NULL, '一般併發測試')")
        self.conn.execute(
            "UPDATE Document_General SET report_date=?, sender_id=? "
            "WHERE doc_id=?", ("2026-07-01", "P001", "G0091"))

        cur = self.conn.execute(
            self.meta["gen"]["update"],
            ("2026-07-20", "P002", "G0091"))
        row = self.conn.execute(
            "SELECT report_date, sender_id FROM Document_General "
            "WHERE doc_id='G0091'").fetchone()

        self.assertEqual(cur.rowcount, 0)
        self.assertEqual(tuple(row), ("2026-07-01", "P001"))

    def test_settle_still_updates_unissued(self):
        self.conn.execute(
            "INSERT INTO Document_Criminal "
            "(doc_id, report_date, sender_id, subject_summary) "
            "VALUES ('C0092', NULL, NULL, '正常刑案')")
        crim_cur = self.conn.execute(
            self.meta["crim"]["update"],
            ("2026-07-20", "P002", "C0092"))
        crim = self.conn.execute(
            "SELECT report_date, sender_id FROM Document_Criminal "
            "WHERE doc_id='C0092'").fetchone()

        self.assertEqual(crim_cur.rowcount, 1)
        self.assertEqual(tuple(crim), ("2026-07-20", "P002"))


if __name__ == "__main__":
    unittest.main()
