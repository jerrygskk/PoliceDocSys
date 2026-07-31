"""
test_report_input_mode.py — 自助取號模式純邏輯測試

涵蓋：
  - isSelfServiceMode：未設定＝False、"1"＝True、壞值 fallback False
  - 結算 SQL round-trip：勾選補值、排除維持 NULL、trigger 更新 last_modified
  - 待歸檔查詢排除未發文（report_date IS NULL 者不回傳）
"""
import sqlite3
import sys
import os
import tempfile
import unittest
from unittest import mock

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


class _FakeCombo:
    def __init__(self, data, text=""):
        self._data = data
        self._text = text or str(data or "")

    def currentData(self):
        return self._data

    def currentText(self):
        return self._text


class _FakeLineEdit:
    def __init__(self, text):
        self._text = text

    def text(self):
        return self._text

    def clear(self):
        self._text = ""


class _FakeRadio:
    def __init__(self, checked):
        self._checked = checked

    def isChecked(self):
        return self._checked


class _FakeNullableDate:
    def validateNow(self):
        pass

    def isBlank(self):
        return False

    def hasError(self):
        return False

    def getDate(self):
        from PySide6.QtCore import QDate
        return QDate(2026, 7, 20)


class _FixedQDate:
    @staticmethod
    def currentDate():
        return _FixedQDate()

    def toString(self, _format):
        return "2026-07-29"


class TestReportCreateDate(unittest.TestCase):
    """新增公文時，登錄日期固定為送出當天而非使用者選定的發文日。"""

    def setUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        conn = _make_db_file(self.db_path)
        conn.close()

        from tabs.tab_report import TabReport
        self.tab = TabReport(None, self.db_path)
        self.tab.radio_status_a = _FakeRadio(True)
        self.tab.radio_status_b = _FakeRadio(False)
        self.tab.crim_casetype = _FakeCombo("CT01", "測試案類")
        self.tab.crim_processor = _FakeCombo("P001", "王承辦")
        self.tab.crim_receiver = _FakeCombo("P001", "王承辦")
        self.tab.crim_subject = _FakeLineEdit("刑案陳報")
        self.tab.crim_occdate = _FakeNullableDate()
        self.tab.crim_reporter = _FakeLineEdit("報案人")
        self.tab.crim_table = None

        self.tab.radio_gen_cat_a = _FakeRadio(True)
        self.tab.radio_gen_cat_b = _FakeRadio(False)
        self.tab.gen_dept = _FakeCombo("D01", "測試單位")
        self.tab.gen_processor = _FakeCombo("P001", "王承辦")
        self.tab.gen_subject = _FakeLineEdit("一般陳報")
        self.tab.gen_table = None

    def tearDown(self):
        os.remove(self.db_path)

    @staticmethod
    def _manager_auth():
        auth = mock.Mock()
        auth.is_manager.return_value = True
        return auth

    def test_sender_mode_criminal_uses_today_not_selected_report_date(self):
        from tabs import tab_report
        with mock.patch.object(tab_report.AuthManager, "instance",
                               return_value=self._manager_auth()), \
             mock.patch.object(tab_report, "QDate", _FixedQDate), \
             mock.patch.object(tab_report, "msgWarning",
                               side_effect=AssertionError("unexpected warning")), \
             mock.patch.object(tab_report, "reportError",
                               side_effect=lambda _title, exc: (_ for _ in ()).throw(exc)), \
             mock.patch.object(tab_report, "DEBUG_MODE", True):
            self.tab._submitCriminal("2026-07-15", "P001")

        conn = sqlite3.connect(self.db_path)
        try:
            row = conn.execute(
                "SELECT create_date, report_date, sender_id "
                "FROM Document_Criminal WHERE subject_summary='刑案陳報'"
            ).fetchone()
        finally:
            conn.close()
        self.assertEqual(row, ("2026-07-29", "2026-07-15", "P001"))

    def test_self_service_general_uses_today_and_leaves_report_fields_null(self):
        from tabs import tab_report
        conn = sqlite3.connect(self.db_path)
        _set_setting(conn, "report_mode_gen", "1")
        conn.close()
        with mock.patch.object(tab_report.AuthManager, "instance",
                               return_value=self._manager_auth()), \
             mock.patch.object(tab_report, "QDate", _FixedQDate), \
             mock.patch.object(tab_report, "msgWarning",
                               side_effect=AssertionError("unexpected warning")), \
             mock.patch.object(tab_report, "reportError",
                               side_effect=lambda _title, exc: (_ for _ in ()).throw(exc)), \
             mock.patch.object(tab_report, "DEBUG_MODE", True):
            self.tab._submitGeneral(None, None)

        conn = sqlite3.connect(self.db_path)
        try:
            row = conn.execute(
                "SELECT create_date, report_date, sender_id "
                "FROM Document_General WHERE subject='一般陳報'"
            ).fetchone()
        finally:
            conn.close()
        self.assertEqual(row, ("2026-07-29", None, None))


class TestSeedDefaults(unittest.TestCase):
    """新建資料庫須以各類型 key 預設送文者模式。"""

    def test_seed_sets_migrated_kinds_to_sender_mode(self):
        """crim／gen／ticket 三把 key 有播種（它們有舊全域 key 要覆蓋）。"""
        from lib.db_schema import applySchema
        from lib.db_seed import seedFreshDb
        from lib.db_utils import REPORT_MODE_KEYS
        conn = sqlite3.connect(":memory:")
        applySchema(conn)
        seedFreshDb(conn)
        conn.commit()
        for kind in ("crim", "gen", "ticket"):
            key = REPORT_MODE_KEYS[kind]
            row = conn.execute(
                "SELECT value FROM App_Settings WHERE key=?", (key,)).fetchone()
            self.assertIsNotNone(row, f"{key} 未播種")
            self.assertEqual(row[0], "0", f"{key} 預設不是送文者模式")
        conn.close()

    def test_seed_leaves_reward_key_absent_and_defaults_to_sender_mode(self):
        """reward 不吃舊全域 key，故不需播種；key 不存在即送文者模式。"""
        import tempfile
        from lib.db_schema import applySchema
        from lib.db_seed import seedFreshDb
        from lib.db_utils import REPORT_MODE_KEYS, isSelfServiceMode
        tmp = tempfile.mkdtemp()
        path = os.path.join(tmp, "seed.db")
        conn = sqlite3.connect(path)
        applySchema(conn)
        seedFreshDb(conn)
        conn.commit()
        row = conn.execute(
            "SELECT value FROM App_Settings WHERE key=?",
            (REPORT_MODE_KEYS["reward"],)).fetchone()
        conn.close()
        self.assertIsNone(row)
        self.assertFalse(isSelfServiceMode(path, "reward"))
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)

    def test_seed_does_not_write_legacy_key(self):
        from lib.db_schema import applySchema
        from lib.db_seed import seedFreshDb
        conn = sqlite3.connect(":memory:")
        applySchema(conn)
        seedFreshDb(conn)
        conn.commit()
        row = conn.execute(
            "SELECT value FROM App_Settings WHERE key='report_input_mode'").fetchone()
        self.assertIsNone(row)
        conn.close()


class TestIsSelfServiceMode(unittest.TestCase):

    def _make_db_file(self, tmp_path, settings=None):
        """建立暫存 DB 檔，並寫入指定 App_Settings。"""
        import tempfile, os
        from lib.db_schema import applySchema
        fd, path = tempfile.mkstemp(suffix=".db", dir=tmp_path)
        os.close(fd)
        conn = sqlite3.connect(path)
        applySchema(conn)
        for key, value in (settings or {}).items():
            conn.execute(
                "INSERT OR REPLACE INTO App_Settings (key, value) VALUES (?,?)",
                (key, value))
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
        path = self._make_db_file(self._tmp)
        self.assertFalse(isSelfServiceMode(path, "crim"))

    def test_one_is_self_service(self):
        from lib.db_utils import isSelfServiceMode
        path = self._make_db_file(self._tmp, {"report_input_mode": "1"})
        self.assertTrue(isSelfServiceMode(path, "crim"))

    def test_zero_is_sender_mode(self):
        from lib.db_utils import isSelfServiceMode
        path = self._make_db_file(self._tmp, {"report_input_mode": "0"})
        self.assertFalse(isSelfServiceMode(path, "crim"))

    def test_garbage_falls_back_to_sender_mode(self):
        from lib.db_utils import isSelfServiceMode
        path = self._make_db_file(self._tmp, {"report_input_mode": "yes"})
        self.assertFalse(isSelfServiceMode(path, "crim"))

    def test_missing_db_falls_back_to_sender_mode(self):
        from lib.db_utils import isSelfServiceMode
        self.assertFalse(isSelfServiceMode(
            os.path.join(self._tmp, "no_such.db"), "crim"))


class TestPerKindMode(unittest.TestCase):
    """Per-kind mode keys override the legacy global fallback."""

    def setUp(self):
        import tempfile
        self._tmp = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _db(self, settings=None):
        import tempfile
        fd, path = tempfile.mkstemp(suffix=".db", dir=self._tmp)
        os.close(fd)
        from lib.db_schema import applySchema
        conn = sqlite3.connect(path)
        applySchema(conn)
        for key, value in (settings or {}).items():
            conn.execute(
                "INSERT OR REPLACE INTO App_Settings (key, value) VALUES (?,?)",
                (key, value))
        conn.commit()
        conn.close()
        return path

    def test_keys_are_independent(self):
        from lib.db_utils import isSelfServiceMode
        path = self._db({"report_mode_crim": "1", "report_mode_gen": "0",
                         "report_mode_ticket": "0"})
        self.assertTrue(isSelfServiceMode(path, "crim"))
        self.assertFalse(isSelfServiceMode(path, "gen"))
        self.assertFalse(isSelfServiceMode(path, "ticket"))

    def test_new_key_overrides_legacy(self):
        from lib.db_utils import isSelfServiceMode
        path = self._db({"report_input_mode": "1", "report_mode_ticket": "0"})
        self.assertFalse(isSelfServiceMode(path, "ticket"))
        self.assertTrue(isSelfServiceMode(path, "crim"))

    def test_legacy_fallback_when_new_keys_absent(self):
        from lib.db_utils import isSelfServiceMode
        path = self._db({"report_input_mode": "1"})
        for kind in ("crim", "gen", "ticket"):
            self.assertTrue(isSelfServiceMode(path, kind))

    def test_unknown_kind_is_sender_mode(self):
        from lib.db_utils import isSelfServiceMode
        self.assertFalse(isSelfServiceMode(
            self._db({"report_input_mode": "1"}), "assignment"))

    def test_reward_never_uses_legacy_global_fallback(self):
        """舊庫殘留 report_input_mode=1 不得讓敘獎莫名變自助取號。

        reward 是後來才掛回陳報模式的流程，只認自己的 report_mode_reward。
        """
        from lib.db_utils import isSelfServiceMode, LEGACY_MODE_FALLBACK_KINDS
        self.assertNotIn("reward", LEGACY_MODE_FALLBACK_KINDS)
        legacy_only = self._db({"report_input_mode": "1"})
        self.assertFalse(isSelfServiceMode(legacy_only, "reward"))
        # 其餘三種仍保留歷史相容回退
        for kind in LEGACY_MODE_FALLBACK_KINDS:
            self.assertTrue(isSelfServiceMode(legacy_only, kind))
        # 明寫自己的 key 才生效
        self.assertTrue(isSelfServiceMode(
            self._db({"report_mode_reward": "1"}), "reward"))
        self.assertFalse(isSelfServiceMode(
            self._db({"report_input_mode": "1", "report_mode_reward": "0"}),
            "reward"))

    def test_any_self_service_ignores_legacy_key_for_reward_only_db(self):
        """只有敘獎設自助時 anySelfServiceMode 為真；只有舊 key 時 reward 不算。"""
        from lib.db_utils import anySelfServiceMode
        self.assertTrue(anySelfServiceMode(self._db({"report_mode_reward": "1"})))

    def test_kind_is_required(self):
        from lib.db_utils import isSelfServiceMode
        with self.assertRaises(TypeError):
            isSelfServiceMode(self._db())

    def test_any_self_service_truth_table(self):
        from lib.db_utils import anySelfServiceMode
        for crim in ("0", "1"):
            for gen in ("0", "1"):
                for ticket in ("0", "1"):
                    path = self._db({"report_mode_crim": crim,
                                     "report_mode_gen": gen,
                                     "report_mode_ticket": ticket})
                    self.assertEqual(anySelfServiceMode(path),
                                     "1" in (crim, gen, ticket),
                                     f"crim={crim} gen={gen} ticket={ticket}")

    def test_any_self_service_uses_legacy_fallback(self):
        from lib.db_utils import anySelfServiceMode
        self.assertTrue(anySelfServiceMode(self._db({"report_input_mode": "1"})))
        self.assertFalse(anySelfServiceMode(self._db()))


class TestSettleRoundTrip(unittest.TestCase):
    """結算 SQL round-trip：補值、排除、trigger。"""

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
    """結算發文處理刑案／一般陳報／敘獎／罰單四種型態。"""

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

    def test_settle_registry_includes_reward(self):
        from ui_utils.settle_dialog import SETTLE_META, count_unissued
        self.assertEqual(
            [meta["key"] for meta in SETTLE_META],
            ["crim", "gen", "reward", "ticket"])
        # setUp 塞了一筆未發文敘獎（register_date=''），必須被算進去
        counts = count_unissued(self.path)
        self.assertEqual(
            counts, {"crim": 0, "gen": 0, "reward": 1, "ticket": 0})

    def test_settle_updates_reward_and_skips_already_issued(self):
        """敘獎結算：未發文補值成功；已發文／已軟刪除的列 rowcount=0 自然跳過。"""
        from lib.db_utils import getConn
        from ui_utils.settle_dialog import settle_selected
        conn = getConn(self.path)
        try:
            conn.execute(
                "INSERT INTO Document_Reward"
                "(doc_id,create_date,register_date,sender_id,reason,recipients) "
                "VALUES ('2','2026-07-01','2026-07-02','P001','已發文','王承辦')")
            conn.execute(
                "INSERT INTO Document_Reward"
                "(doc_id,create_date,register_date,sender_id,reason,recipients) "
                "VALUES ('3',NULL,NULL,NULL,NULL,NULL)")
            conn.commit()
            settled = settle_selected(
                conn, {"reward": ["1", "2", "3"]}, "2026-07-31", "P001")
            conn.commit()
            self.assertEqual(settled, 1)
            rows = dict(conn.execute(
                "SELECT doc_id, register_date FROM Document_Reward").fetchall())
        finally:
            conn.close()
        self.assertEqual(rows["1"], "2026-07-31")   # 未發文 → 補上
        self.assertEqual(rows["2"], "2026-07-02")   # 已發文 → 不動
        self.assertIsNone(rows["3"])                # 軟刪除哨兵 → 不復活


class TestUnissuedCountQueries(unittest.TestCase):
    """count_unissued 必須直接以各主表的 COUNT 查詢未發文資料。"""

    def setUp(self):
        import tempfile
        from lib.db_schema import applySchema

        self._tmp = tempfile.mkdtemp()
        self.path = os.path.join(self._tmp, "unissued_count.db")
        self.conn = sqlite3.connect(self.path)
        applySchema(self.conn)
        self.conn.executescript("""
            INSERT INTO Document_Criminal
                (doc_id, report_date, case_type, case_status, processor_id,
                 subject_summary, is_reported, is_electronic)
            VALUES
                ('C-UNISSUED', NULL, 'CT01', 'CS01', 'P001', '刑案待發文', 0, ''),
                ('C-ISSUED', '2026-07-27', 'CT01', 'CS01', 'P001', '刑案已發文', 0, ''),
                ('C-EMPTY', NULL, 'CT01', 'CS01', 'P001', '', 0, ''),
                ('C-DELETED', NULL, 'CT01', 'CS01', 'P001', NULL, 0, '');

            INSERT INTO Document_General
                (doc_id, report_date, processor_id, subject, is_reported, is_electronic)
            VALUES
                ('G-UNISSUED', '', 'P001', '一般待發文', 0, ''),
                ('G-ISSUED', '2026-07-27', 'P001', '一般已發文', 0, ''),
                ('G-EMPTY', '', 'P001', '', 0, ''),
                ('G-DELETED', NULL, 'P001', NULL, 0, '');

            INSERT INTO Document_Ticket
                (doc_id, create_date, register_date, issuer_id, ticket_no)
            VALUES
                ('T-UNISSUED', '2026-07-27', '', 'P001', 'TICKET01'),
                ('T-ISSUED', '2026-07-27', '2026-07-27', 'P001', 'TICKET02'),
                ('T-DELETED', NULL, NULL, NULL, NULL);

            INSERT INTO Document_Reward
                (doc_id, create_date, register_date, sender_id, reason, recipients)
            VALUES
                ('R-UNISSUED', '2026-07-27', '', NULL, '待發文', '甲'),
                ('R-ISSUED', '2026-07-27', '2026-07-27', 'P001', '已發文', '乙'),
                ('R-DELETED', NULL, NULL, NULL, NULL, NULL);
        """)
        # 實務資料可能因舊資料／外鍵資料清理留下這兩種 issuer；計數不可因
        # 顯示名稱的 JOIN 而遺漏它們。
        self.conn.execute("PRAGMA ignore_check_constraints = ON")
        self.conn.execute(
            "INSERT INTO Document_Ticket "
            "(doc_id, create_date, register_date, issuer_id, ticket_no) "
            "VALUES ('T-NULL-ISSUER', '2026-07-27', '', NULL, 'TICKET03')")
        self.conn.execute(
            "INSERT INTO Document_Ticket "
            "(doc_id, create_date, register_date, issuer_id, ticket_no) "
            "VALUES ('T-MISSING-ISSUER', '2026-07-27', '', 'P404', 'TICKET04')")
        self.conn.execute(
            "INSERT INTO Document_Ticket "
            "(doc_id, create_date, register_date, issuer_id, ticket_no) "
            "VALUES ('T-EMPTY', '2026-07-27', '', 'P001', '')")
        self.conn.execute("PRAGMA ignore_check_constraints = OFF")
        self.conn.commit()

    def tearDown(self):
        self.conn.close()
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_counts_match_unissued_rows_and_do_not_load_rows(self):
        """改回以 load_unissued 取長度或漏掉主表條件時必須失敗。"""
        from ui_utils.settle_dialog import count_unissued, load_unissued

        expected = {"crim": 1, "gen": 1, "reward": 1, "ticket": 3}
        with mock.patch("ui_utils.settle_dialog.load_unissued",
                        side_effect=AssertionError("count must use COUNT SQL")):
            self.assertEqual(count_unissued(self.path), expected)

        rows = load_unissued(self.path)
        self.assertEqual(
            {kind: len(rows[kind]) for kind in expected}, expected)


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

    def _read_rows(self, sql):
        conn = sqlite3.connect(self.db_path)
        try:
            return conn.execute(sql).fetchall()
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

    def _add_general_for_settlement(self):
        self.conn.execute(
            "INSERT INTO Document_General "
            "(doc_id, report_date, sender_id, dept_id, gen_cat_id, subject, processor_id) "
            "VALUES ('G0050', NULL, NULL, 'D01', 'GC01', '混合結算一般', 'P001')")
        self.conn.commit()

    def test_selected_non_today_issue_date_round_trips_all_three_types(self):
        """選擇過去的發文日，刑案、一般與罰單都必須原樣寫入。"""
        from ui_utils.settle_dialog import settle_selected
        self._add_general_for_settlement()

        selected = {"crim": ["C0050"], "gen": ["G0050"], "ticket": ["T0050"]}
        self.assertEqual(settle_selected(self.conn, selected, "2026-07-09", "P001"), 3)
        self.assertEqual(self._criminal_report_date(), "2026-07-09")
        self.assertEqual(
            self._read_row("SELECT report_date FROM Document_General WHERE doc_id='G0050'")[0],
            "2026-07-09")
        self.assertEqual(self._ticket_register_date(), "2026-07-09")

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

    def test_criminal_soft_deleted_after_load_is_not_revived_or_audited(self):
        """載入後被軟刪除的刑案空殼不得被結算 UPDATE 復活。"""
        from ui_utils.settle_dialog import settle_selected
        self.conn.execute(
            "UPDATE Document_Criminal "
            "SET report_date=NULL, sender_id=NULL, subject_summary=NULL "
            "WHERE doc_id='C0050'")
        self.conn.commit()

        settled_n = settle_selected(
            self.conn, {"crim": ["C0050"], "gen": [], "ticket": []},
            "2026-07-23", "P001")

        self.assertEqual(settled_n, 0)
        self.assertEqual(
            self._read_row(
                "SELECT report_date, sender_id, subject_summary "
                "FROM Document_Criminal WHERE doc_id='C0050'"),
            (None, None, None))
        self.assertEqual(self._read_row("SELECT COUNT(*) FROM Audit_Log")[0], 0)

    def test_general_soft_deleted_after_load_is_not_revived_or_audited(self):
        """載入後被軟刪除的一般公文空殼不得被結算 UPDATE 復活。"""
        from ui_utils.settle_dialog import settle_selected
        self._add_general_for_settlement()
        self.conn.execute(
            "UPDATE Document_General "
            "SET report_date=NULL, sender_id=NULL, subject='' "
            "WHERE doc_id='G0050'")
        self.conn.commit()

        settled_n = settle_selected(
            self.conn, {"crim": [], "gen": ["G0050"], "ticket": []},
            "2026-07-23", "P001")

        self.assertEqual(settled_n, 0)
        self.assertEqual(
            self._read_row(
                "SELECT report_date, sender_id, subject "
                "FROM Document_General WHERE doc_id='G0050'"),
            (None, None, ""))
        self.assertEqual(self._read_row("SELECT COUNT(*) FROM Audit_Log")[0], 0)


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

    def test_settle_preserves_create_date(self):
        self.conn.execute(
            "INSERT INTO Document_Criminal "
            "(doc_id, create_date, report_date, sender_id, subject_summary) "
            "VALUES ('C0093', '2026-07-11', NULL, NULL, '保留登錄日期')")

        cur = self.conn.execute(
            self.meta["crim"]["update"],
            ("2026-07-20", "P002", "C0093"))
        row = self.conn.execute(
            "SELECT create_date, report_date, sender_id "
            "FROM Document_Criminal WHERE doc_id='C0093'").fetchone()

        self.assertEqual(cur.rowcount, 1)
        self.assertEqual(tuple(row), ("2026-07-11", "2026-07-20", "P002"))


class TestModeResidueWarning(unittest.TestCase):
    """切回送文者模式時，僅提示該型態留下的未發文資料。"""

    def test_returns_none_without_self_to_sender_residue(self):
        from ui_utils.settings_panels import mode_residue_warning

        self.assertIsNone(mode_residue_warning(
            {"crim": (True, False), "gen": (False, True)},
            {"crim": 0, "gen": 9, "ticket": 2}))

    def test_lists_each_switching_type_with_its_count(self):
        from ui_utils.settings_panels import mode_residue_warning

        self.assertEqual(mode_residue_warning(
            {"crim": (True, False), "gen": (True, False),
             "ticket": (True, False)},
            {"crim": 2, "gen": 4, "ticket": 3}),
            "目前有 2 件刑案陳報尚未發文，切換後仍需到「簽收單列印」頁結算。\n"
            "目前有 4 件一般陳報尚未發文，切換後仍需到「簽收單列印」頁結算。\n"
            "目前有 3 張罰單尚未發文，切換後仍需到「簽收單列印」頁結算。")


class TestInputModePanelSave(unittest.TestCase):
    """設定面板儲存後三個 key 皆為明確值。"""

    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtWidgets import QApplication
        cls._app = QApplication.instance() or QApplication([])

    def setUp(self):
        import tempfile
        from lib.auth_manager import AuthManager
        from lib.db_schema import applySchema
        self._tmp = tempfile.mkdtemp()
        self._path = os.path.join(self._tmp, "t.db")
        conn = sqlite3.connect(self._path)
        applySchema(conn)
        conn.commit()
        conn.close()
        self._auth = AuthManager.instance()
        self._orig_role = self._auth._role
        self._auth._role = "admin"

    def tearDown(self):
        import shutil
        self._auth._role = self._orig_role
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_save_writes_all_flow_keys_explicitly(self):
        from lib.db_utils import getSetting, REPORT_MODE_KEYS
        from ui_utils.settings_panels import InputModePanel
        panel = InputModePanel(self._path)
        panel._radios["ticket"][1].setChecked(True)
        self.assertTrue(panel._save())
        self.assertEqual(getSetting(self._path, REPORT_MODE_KEYS["ticket"], None), "1")
        for kind in ("crim", "gen", "reward"):
            self.assertEqual(
                getSetting(self._path, REPORT_MODE_KEYS[kind], None), "0")

    def test_panel_offers_reward_row(self):
        """敘獎重新掛回陳報模式：面板必須有這一列可設定。"""
        from ui_utils.settings_panels import InputModePanel
        panel = InputModePanel(self._path)
        self.assertIn("reward", panel._radios)
        self.assertEqual([k for k, _ in InputModePanel._ROWS],
                         ["crim", "gen", "reward", "ticket"])

    def test_save_audits_old_and_new_value(self):
        from ui_utils.settings_panels import InputModePanel
        panel = InputModePanel(self._path)
        panel._radios["crim"][1].setChecked(True)
        panel._save()
        conn = sqlite3.connect(self._path)
        details = [r[0] for r in conn.execute(
            "SELECT detail FROM Audit_Log").fetchall()]
        conn.close()
        self.assertTrue(
            any("刑案陳報：送文者輸入 → 自助取號" in d for d in details),
            f"稽核未帶舊值：{details}")

    def test_save_is_rejected_for_non_admin(self):
        from lib.db_utils import getSetting, REPORT_MODE_KEYS
        from ui_utils.settings_panels import InputModePanel
        panel = InputModePanel(self._path)
        self._auth._role = "user"
        self.assertFalse(panel._save())
        self.assertIsNone(getSetting(self._path, REPORT_MODE_KEYS["crim"], None))

    def _audit_count(self):
        conn = sqlite3.connect(self._path)
        try:
            return conn.execute("SELECT COUNT(*) FROM Audit_Log").fetchone()[0]
        finally:
            conn.close()

    def _mode_values(self):
        from lib.db_utils import REPORT_MODE_KEYS, getSetting
        return {kind: getSetting(self._path, key, None)
                for kind, key in REPORT_MODE_KEYS.items()}

    def test_cancel_residue_warning_writes_nothing_and_reloads_radios(self):
        from lib.db_utils import REPORT_MODE_KEYS, setSetting
        from ui_utils.settings_panels import InputModePanel
        setSetting(self._path, REPORT_MODE_KEYS["crim"], "1")
        before_values = self._mode_values()
        panel = InputModePanel(self._path)
        panel._radios["crim"][0].setChecked(True)

        with mock.patch("ui_utils.settle_dialog.count_unissued",
                        return_value={"crim": 2, "gen": 0, "ticket": 0}) as count, \
             mock.patch("ui_utils.settings_panels.confirmBox", return_value=False) as confirm:
            self.assertFalse(panel._save())

        count.assert_called_once_with(self._path)
        self.assertEqual(confirm.call_args.args[0], "提醒")
        self.assertEqual(confirm.call_args.kwargs["confirm_text"], "仍要切換")
        self.assertEqual(confirm.call_args.kwargs["cancel_text"], "取消")
        self.assertFalse(confirm.call_args.kwargs["default_confirm"])
        self.assertEqual(self._mode_values(), before_values)
        self.assertTrue(panel._radios["crim"][1].isChecked())
        self.assertEqual(self._audit_count(), 0)

    def test_confirm_residue_warning_saves_and_audits_normally(self):
        from lib.db_utils import REPORT_MODE_KEYS, getSetting, setSetting
        from ui_utils.settings_panels import InputModePanel
        setSetting(self._path, REPORT_MODE_KEYS["ticket"], "1")
        panel = InputModePanel(self._path)
        panel._radios["ticket"][0].setChecked(True)

        with mock.patch("ui_utils.settle_dialog.count_unissued",
                        return_value={"crim": 0, "gen": 0, "ticket": 3}), \
             mock.patch("ui_utils.settings_panels.confirmBox", return_value=True):
            self.assertTrue(panel._save())

        self.assertEqual(getSetting(self._path, REPORT_MODE_KEYS["ticket"], None), "0")
        self.assertEqual(self._audit_count(), 1)

    def test_sender_to_self_does_not_prompt_for_residue(self):
        from ui_utils.settings_panels import InputModePanel
        panel = InputModePanel(self._path)
        panel._radios["gen"][1].setChecked(True)

        with mock.patch("ui_utils.settle_dialog.count_unissued") as count, \
             mock.patch("ui_utils.settings_panels.confirmBox") as confirm:
            self.assertTrue(panel._save())

        count.assert_not_called()
        confirm.assert_not_called()

    def test_residue_probe_failure_reports_error_reloads_and_writes_nothing(self):
        """殘料探查失敗時須 fail closed，且 radio 回復資料庫原值。"""
        from lib.db_utils import REPORT_MODE_KEYS, setSetting
        from ui_utils.settings_panels import InputModePanel
        setSetting(self._path, REPORT_MODE_KEYS["crim"], "1")
        before_values = self._mode_values()
        panel = InputModePanel(self._path)
        panel._radios["crim"][0].setChecked(True)

        with mock.patch(
                "ui_utils.settle_dialog.count_unissued",
                side_effect=sqlite3.OperationalError("probe failed")), \
             mock.patch("ui_utils.settings_panels.reportError") as report, \
             mock.patch("lib.db_utils.setSetting") as write:
            self.assertFalse(panel._save())

        report.assert_called_once()
        self.assertEqual(report.call_args.args[0], "讀取未發文資料失敗")
        write.assert_not_called()
        self.assertEqual(self._mode_values(), before_values)
        self.assertTrue(panel._radios["crim"][1].isChecked())
        self.assertEqual(self._audit_count(), 0)


class TestResetLegacyKeyCleanup(unittest.TestCase):
    """跨年度重置僅在三種新 key 都存在時移除舊 fallback key。"""

    def setUp(self):
        import tempfile
        self._tmp = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _db(self, settings):
        from lib.db_schema import applySchema
        path = os.path.join(self._tmp, "t.db")
        conn = sqlite3.connect(path)
        applySchema(conn)
        for k, v in settings.items():
            conn.execute(
                "INSERT OR REPLACE INTO App_Settings (key, value) VALUES (?,?)",
                (k, v))
        conn.commit()
        conn.close()
        return path

    def _keys(self, path):
        conn = sqlite3.connect(path)
        rows = conn.execute("SELECT key FROM App_Settings").fetchall()
        conn.close()
        return {r[0] for r in rows}

    def test_legacy_key_removed_when_all_new_keys_present(self):
        from lib.db_utils import performYearEndReset
        path = self._db({"report_input_mode": "1",
                         "report_mode_crim": "1",
                         "report_mode_gen": "0",
                         "report_mode_ticket": "0"})
        performYearEndReset(path)
        keys = self._keys(path)
        self.assertNotIn("report_input_mode", keys)
        self.assertIn("report_mode_crim", keys)

    def test_legacy_key_kept_when_a_new_key_missing(self):
        from lib.db_utils import performYearEndReset
        path = self._db({"report_input_mode": "1",
                         "report_mode_crim": "1"})
        performYearEndReset(path)
        self.assertIn("report_input_mode", self._keys(path))

    def test_new_keys_survive_reset(self):
        from lib.db_utils import getSetting, performYearEndReset
        path = self._db({"report_mode_crim": "1",
                         "report_mode_gen": "0",
                         "report_mode_ticket": "1"})
        performYearEndReset(path)
        self.assertEqual(getSetting(path, "report_mode_crim", None), "1")
        self.assertEqual(getSetting(path, "report_mode_ticket", None), "1")


if __name__ == "__main__":
    unittest.main()
