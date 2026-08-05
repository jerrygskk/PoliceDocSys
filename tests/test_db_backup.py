"""lib.db_backup 純邏輯與 sqlite backup round-trip 測試。"""
import os
import sqlite3
import tempfile
import unittest
import unittest.mock
from datetime import date

from lib import db_backup


class TestDailyDue(unittest.TestCase):
    def test_due_when_today_absent(self):
        self.assertTrue(db_backup.is_daily_due([date(2026, 6, 25)], date(2026, 6, 26)))

    def test_not_due_when_today_present(self):
        d = date(2026, 6, 26)
        self.assertFalse(db_backup.is_daily_due([date(2026, 6, 25), d], d))

    def test_due_when_empty(self):
        self.assertTrue(db_backup.is_daily_due([], date(2026, 6, 26)))


class TestWeeklyDue(unittest.TestCase):
    def test_due_when_empty(self):
        self.assertTrue(db_backup.is_weekly_due([], date(2026, 6, 26)))

    def test_not_due_same_iso_week(self):
        # 2026-06-22(週一) 與 2026-06-26(週五) 同一 ISO 週
        self.assertFalse(
            db_backup.is_weekly_due([date(2026, 6, 22)], date(2026, 6, 26)))

    def test_due_previous_week(self):
        self.assertTrue(
            db_backup.is_weekly_due([date(2026, 6, 19)], date(2026, 6, 26)))


class TestMonthlyDue(unittest.TestCase):
    def test_due_when_empty(self):
        self.assertTrue(db_backup.is_monthly_due([], date(2026, 6, 26)))

    def test_not_due_same_month(self):
        self.assertFalse(
            db_backup.is_monthly_due([date(2026, 6, 1)], date(2026, 6, 26)))

    def test_due_previous_month(self):
        self.assertTrue(
            db_backup.is_monthly_due([date(2026, 5, 31)], date(2026, 6, 1)))

    def test_same_month_different_year_is_due(self):
        self.assertTrue(
            db_backup.is_monthly_due([date(2025, 6, 1)], date(2026, 6, 26)))


class TestParse(unittest.TestCase):
    def test_daily_roundtrip(self):
        d = date(2026, 6, 26)
        self.assertEqual(
            db_backup.parse_daily_dates([db_backup.daily_filename(d)]), [d])

    def test_weekly_roundtrip(self):
        d = date(2026, 6, 26)
        self.assertEqual(
            db_backup.parse_weekly_dates([db_backup.weekly_filename(d)]), [d])

    def test_monthly_roundtrip(self):
        d = date(2026, 6, 26)
        self.assertEqual(
            db_backup.parse_monthly_dates([db_backup.monthly_filename(d)]), [d])

    def test_daily_ignores_weekly_monthly_and_junk(self):
        names = [db_backup.weekly_filename(date(2026, 6, 26)),
                 db_backup.monthly_filename(date(2026, 6, 26)),
                 "dbfile.db", "foo.txt", "dbfile_backup_day_bad.db"]
        self.assertEqual(db_backup.parse_daily_dates(names), [])


class TestPrune(unittest.TestCase):
    def test_keeps_recent_drops_old(self):
        dates = [date(2026, 6, d) for d in (20, 21, 22, 23, 24, 25, 26)]
        # 留最近 3 份 → 該刪最舊 4 份
        self.assertEqual(
            db_backup.prune_targets(dates, 3),
            [date(2026, 6, 20), date(2026, 6, 21),
             date(2026, 6, 22), date(2026, 6, 23)])

    def test_nothing_to_prune_within_keep(self):
        dates = [date(2026, 6, 25), date(2026, 6, 26)]
        self.assertEqual(db_backup.prune_targets(dates, 7), [])


class TestRunAutoBackup(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.src = os.path.join(self.tmp, "dbfile.db")
        conn = sqlite3.connect(self.src)
        conn.execute("CREATE TABLE t(id INTEGER PRIMARY KEY, v TEXT)")
        conn.executemany("INSERT INTO t(v) VALUES(?)", [("a",), ("b",), ("c",)])
        conn.commit()
        conn.close()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_do_backup_roundtrip(self):
        dest = os.path.join(self.tmp, "copy.db")
        self.assertTrue(db_backup.do_backup(self.src, dest))
        self.assertTrue(os.path.exists(dest))
        self.assertFalse(os.path.exists(dest + ".tmp"))  # tmp 已換掉
        conn = sqlite3.connect(dest)
        n = conn.execute("SELECT COUNT(*) FROM t").fetchone()[0]
        conn.close()
        self.assertEqual(n, 3)

    def test_creates_daily_weekly_and_monthly(self):
        db_backup.run_auto_backup(self.src)
        bdir = db_backup.backup_dir(self.src)
        names = os.listdir(bdir)
        self.assertEqual(len(db_backup.parse_daily_dates(names)), 1)
        self.assertEqual(len(db_backup.parse_weekly_dates(names)), 1)
        self.assertEqual(len(db_backup.parse_monthly_dates(names)), 1)

    def test_same_day_reopen_is_idempotent(self):
        db_backup.run_auto_backup(self.src)
        db_backup.run_auto_backup(self.src)  # 同日再開不應多備
        names = os.listdir(db_backup.backup_dir(self.src))
        self.assertEqual(len(db_backup.parse_daily_dates(names)), 1)
        self.assertEqual(len(db_backup.parse_weekly_dates(names)), 1)
        self.assertEqual(len(db_backup.parse_monthly_dates(names)), 1)


class TestExtraDirs(unittest.TestCase):
    """異地備份：run_auto_backup extra_dirs 一併備份、latest_backup_date。"""
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.src = os.path.join(self.tmp, "dbfile.db")
        conn = sqlite3.connect(self.src)
        conn.execute("CREATE TABLE t(id INTEGER PRIMARY KEY)")
        conn.commit(); conn.close()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_extra_dir_gets_its_own_backup(self):
        second = os.path.join(self.tmp, "offsite")
        db_backup.run_auto_backup(self.src, extra_dirs=[second])
        self.assertEqual(len(db_backup.parse_daily_dates(os.listdir(second))), 1)
        # 主備份仍照做
        self.assertEqual(
            len(db_backup.parse_daily_dates(os.listdir(db_backup.backup_dir(self.src)))), 1)

    def test_blank_extra_dir_ignored(self):
        # 空字串不應建立任何資料夾或拋例外
        db_backup.run_auto_backup(self.src, extra_dirs=["", "   "])
        self.assertTrue(os.path.isdir(db_backup.backup_dir(self.src)))

    def test_latest_backup_date(self):
        second = os.path.join(self.tmp, "offsite")
        db_backup.run_auto_backup(self.src, extra_dirs=[second])
        self.assertEqual(db_backup.latest_backup_date(second), date.today())

    def test_latest_backup_date_none_when_missing(self):
        self.assertIsNone(
            db_backup.latest_backup_date(os.path.join(self.tmp, "nope")))


class TestEnsureDirOnExisting(unittest.TestCase):
    """已存在的備份資料夾不得再呼叫 os.makedirs。

    現場踩過：異地備份填 UNC 分享根目錄（`\\\\host\\share`）時，Windows 對該路徑的
    makedirs 回 WinError 50，`exist_ok=True` 吞不掉（它只吞 FileExistsError），
    於是資料夾明明存在、異地備份卻每次開機都靜默失敗。
    """
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_existing_dir_skips_makedirs(self):
        calls = []
        real = os.makedirs

        def spy(path, **kw):
            calls.append(path)
            return real(path, **kw)

        os.makedirs(os.path.join(self.tmp, "here"), exist_ok=True)
        with unittest.mock.patch.object(os, "makedirs", spy):
            db_backup._ensure_dir(os.path.join(self.tmp, "here"))
        self.assertEqual(calls, [])

    def test_missing_dir_still_created(self):
        target = os.path.join(self.tmp, "new", "deep")
        db_backup._ensure_dir(target)
        self.assertTrue(os.path.isdir(target))

    def test_share_root_like_error_does_not_break_backup(self):
        """模擬 WinError 50：資料夾存在但 makedirs 會拋 → 備份仍應完成。"""
        src = os.path.join(self.tmp, "dbfile.db")
        conn = sqlite3.connect(src)
        conn.execute("CREATE TABLE t(id INTEGER PRIMARY KEY)")
        conn.commit(); conn.close()
        second = os.path.join(self.tmp, "share_root")
        os.makedirs(second, exist_ok=True)

        def boom(path, **kw):
            raise OSError(22, "不支援這個要求。", path, 50)

        with unittest.mock.patch.object(os, "makedirs", boom):
            db_backup.run_auto_backup(src, extra_dirs=[second])
        self.assertEqual(len(db_backup.parse_daily_dates(os.listdir(second))), 1)


class TestDescribeBackupErrors(unittest.TestCase):
    """備份失敗訊息白話化：一律以 winerror／errno 判斷，不比對訊息文字。"""
    def _win(self, code):
        return OSError(22, "whatever", r"\\host\share", code)

    def test_share_root_not_supported(self):
        msg = db_backup.describeBackupDirError(
            self._win(50), r"\\10.107.43.104\long", is_extra=True)
        self.assertIn("異地備份位置無法使用", msg)
        self.assertIn(r"\\10.107.43.104\long", msg)
        self.assertIn("分享名稱", msg)
        self.assertIn("主備份不受影響", msg)

    def test_network_path_not_found(self):
        msg = db_backup.describeBackupDirError(self._win(53), r"\\h\s", is_extra=True)
        self.assertIn("找不到這個網路路徑", msg)

    def test_main_dir_failure_wording_is_stronger(self):
        msg = db_backup.describeBackupDirError(
            PermissionError(13, "denied"), "C:/x/backups", is_extra=False)
        self.assertIn("備份資料夾無法使用", msg)
        self.assertIn("沒有寫入權限", msg)
        self.assertIn("error.log", msg)

    def test_disk_full(self):
        e = OSError(28, "No space left on device")
        self.assertIn("磁碟空間不足",
                      db_backup.describeBackupDirError(e, "D:/b", is_extra=True))

    def test_missing_folder(self):
        e = FileNotFoundError(2, "not found")
        self.assertIn("找不到這個資料夾",
                      db_backup.describeBackupDirError(e, "D:/b", is_extra=True))

    def test_unknown_falls_back(self):
        msg = db_backup.describeBackupDirError(RuntimeError("?"), "D:/b")
        self.assertIn("無法存取", msg)

    def test_write_error_message(self):
        msg = db_backup.describeBackupWriteError(
            self._win(64), r"\\h\s\dbfile_backup_day_20260804.db")
        self.assertIn("備份檔寫入失敗", msg)
        self.assertIn("連線已中斷", msg)
        self.assertIn("其餘備份不受影響", msg)

    def test_brief_message_has_no_reason_parens(self):
        msg = db_backup.briefBackupDirError(r"\\10.107.43.104\long", is_extra=True)
        self.assertEqual(
            msg, r"異地備份位置無法使用：\\10.107.43.104\long。本次已略過異地備份。")

    def test_last_backup_error_recorded_and_cleared(self):
        tmp = tempfile.mkdtemp()
        try:
            src = os.path.join(tmp, "dbfile.db")
            conn = sqlite3.connect(src)
            conn.execute("CREATE TABLE t(id INTEGER PRIMARY KEY)")
            conn.commit(); conn.close()
            second = os.path.join(tmp, "offsite")

            def boom(path, **kw):
                raise OSError(22, "不支援這個要求。", path, 50)

            with unittest.mock.patch.object(db_backup, "_ensure_dir", boom):
                db_backup.run_auto_backup(src, extra_dirs=[second])
            self.assertIn("異地備份位置無法使用",
                          db_backup.last_backup_error(second))
            # 下次成功即清掉
            db_backup.run_auto_backup(src, extra_dirs=[second])
            self.assertIsNone(db_backup.last_backup_error(second))
        finally:
            import shutil
            shutil.rmtree(tmp, ignore_errors=True)

    def test_last_backup_error_none_for_unknown_path(self):
        self.assertIsNone(db_backup.last_backup_error("D:/never/used"))

    def test_locale_independent(self):
        """同一錯誤碼、不同語系文字，分類結果必須相同。"""
        zh = OSError(22, "不支援這個要求。", r"\\h\s", 50)
        en = OSError(22, "The request is not supported", r"\\h\s", 50)
        self.assertEqual(db_backup.describeBackupDirError(zh, "p"),
                         db_backup.describeBackupDirError(en, "p"))


class TestQuickCheck(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_good_db_passes(self):
        p = os.path.join(self.tmp, "good.db")
        conn = sqlite3.connect(p)
        conn.execute("CREATE TABLE t(id INTEGER)")
        conn.commit(); conn.close()
        self.assertTrue(db_backup.quick_check(p))

    def test_missing_file_passes(self):
        # 檔案不存在＝非損毀（交由建表流程），不擋開程式
        self.assertTrue(db_backup.quick_check(os.path.join(self.tmp, "nope.db")))

    def test_corrupt_file_fails(self):
        p = os.path.join(self.tmp, "bad.db")
        with open(p, "wb") as f:
            f.write(b"SQLite format 3\x00" + b"\xff" * 4000)
        self.assertFalse(db_backup.quick_check(p))


class TestDeepCheckIfDue(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db = os.path.join(self.tmp, "dbfile.db")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _good_db(self):
        conn = sqlite3.connect(self.db)
        conn.execute("CREATE TABLE t(id INTEGER)")
        conn.commit(); conn.close()

    def _corrupt_db(self):
        with open(self.db, "wb") as f:
            f.write(b"SQLite format 3\x00" + b"\xff" * 4000)

    def _make_weekly_file(self, d):
        bdir = db_backup.backup_dir(self.db)
        os.makedirs(bdir, exist_ok=True)
        open(os.path.join(bdir, db_backup.weekly_filename(d)), "w").close()

    def test_not_due_skips_check_even_if_corrupt(self):
        # 本週已有週檔＝未到期：壞檔也不跑檢查、直接放行（證明沒跑深層檢查）
        self._corrupt_db()
        self._make_weekly_file(date.today())
        self.assertTrue(db_backup.deep_check_if_due(self.db))

    def test_due_good_db_passes(self):
        self._good_db()
        self.assertTrue(db_backup.deep_check_if_due(self.db))

    def test_due_corrupt_db_fails(self):
        self._corrupt_db()
        self.assertFalse(db_backup.deep_check_if_due(self.db))

    def test_due_missing_file_passes(self):
        self.assertTrue(
            db_backup.deep_check_if_due(os.path.join(self.tmp, "nope.db")))

    def test_missing_backup_dir_treated_as_due(self):
        # backups/ 不存在＝視為到期照跑：好檔跑完回 True
        self._good_db()
        self.assertFalse(os.path.isdir(db_backup.backup_dir(self.db)))
        self.assertTrue(db_backup.deep_check_if_due(self.db))


class TestListVerifyRestore(unittest.TestCase):
    def setUp(self):
        from lib import db_schema
        self.tmp = tempfile.mkdtemp()
        self.db = os.path.join(self.tmp, "dbfile.db")
        conn = sqlite3.connect(self.db)
        db_schema.applySchema(conn)
        conn.execute("INSERT INTO Document_Task(doc_id, receive_date) "
                     "VALUES('T1','2026-01-01')")
        conn.execute(
            "INSERT INTO Document_Criminal"
            "(doc_id, create_date, report_date, subject_summary) "
            "VALUES('C1','2026-01-01','2026-01-01','既有刑案')")
        conn.execute("INSERT INTO Ref_Personnel"
                     "(staff_id,staff_name,alias,is_active,sort_order) "
                     "VALUES('P01','甲員','',1,1)")
        # 罰單有效未發文列（register_date=''）
        conn.execute("INSERT INTO Document_Ticket"
                     "(doc_id,create_date,register_date,sender_id,issuer_id,"
                     "ticket_no) VALUES('1','2026-01-01','',NULL,'P01',"
                     "'D4RD15263')")
        conn.commit(); conn.close()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_list_backups_three_sources_sorted(self):
        second = os.path.join(self.tmp, "offsite")
        db_backup.run_auto_backup(self.db, extra_dirs=[second])
        import shutil
        shutil.copy2(self.db,
                     os.path.join(self.tmp, "dbfile_backup_20260102_030405.db"))
        entries = db_backup.list_backups(self.db, extra_dirs=[second])
        sources = {e["source"] for e in entries}
        self.assertIn("主備份", sources)
        self.assertIn("異地副本", sources)
        self.assertIn("重置留底", sources)
        kinds = {e["kind"] for e in entries}
        self.assertIn("每月", kinds)
        whens = [e["when"] for e in entries]
        self.assertEqual(whens, sorted(whens, reverse=True))

    def test_verify_good_and_reject_corrupt(self):
        ok, _ = db_backup.verify_backup(self.db)
        self.assertTrue(ok)
        bad = os.path.join(self.tmp, "bad.db")
        with open(bad, "wb") as f:
            f.write(b"SQLite format 3\x00" + b"\xff" * 4000)
        ok, msg = db_backup.verify_backup(bad)
        self.assertFalse(ok)
        self.assertTrue(msg)

    def test_verify_missing(self):
        ok, _ = db_backup.verify_backup(os.path.join(self.tmp, "nope.db"))
        self.assertFalse(ok)

    def test_doc_counts(self):
        c = sqlite3.connect(self.db)
        c.execute("INSERT INTO Document_Reward"
                  "(doc_id,register_date,reason,recipients) VALUES(?,?,?,?)",
                  ("R1", "2026-01-01", "事由", "甲員"))
        c.execute("INSERT INTO Document_Reward"
                  "(doc_id,register_date,reason,recipients) VALUES(?,?,?,?)",
                  ("R2", None, None, None))
        c.commit(); c.close()
        self.assertEqual(db_backup.backup_doc_counts(self.db),
                         {"task": 1, "crim": 1, "gen": 0, "reward": 1,
                          "ticket": 1})

    def test_backup_doc_counts_and_format_include_ticket(self):
        counts = db_backup.backup_doc_counts(self.db)
        self.assertEqual(counts["ticket"], 1)
        self.assertIn("罰單 1 筆", db_backup.formatDocCounts(counts))

    def test_unissued_registered_reports_are_counted_for_backup_and_reset(self):
        c = sqlite3.connect(self.db)
        c.execute(
            "INSERT INTO Document_Criminal"
            "(doc_id,create_date,report_date,subject_summary) "
            "VALUES('C2','2026-01-02',NULL,'未發文刑案')")
        c.execute(
            "INSERT INTO Document_General"
            "(doc_id,create_date,report_date,subject) "
            "VALUES('G1','2026-01-03',NULL,'未發文一般案')")
        c.commit()

        counts = db_backup.backup_doc_counts(self.db)
        self.assertEqual(counts["crim"], 2)
        self.assertEqual(counts["gen"], 1)

        from tabs.tab_settings import _resetDocCounts
        reset_counts = _resetDocCounts(c)
        self.assertEqual(reset_counts["crim"], 2)
        self.assertEqual(reset_counts["gen"], 1)
        c.close()

    def test_legacy_pending_reports_with_null_create_date_are_still_counted(self):
        c = sqlite3.connect(self.db)
        c.execute(
            "INSERT INTO Document_Criminal"
            "(doc_id,create_date,report_date,subject_summary) "
            "VALUES('C3',NULL,NULL,'舊庫未發文刑案')")
        c.execute(
            "INSERT INTO Document_General"
            "(doc_id,create_date,report_date,subject) "
            "VALUES('G2',NULL,NULL,'舊庫未發文一般案')")
        c.commit()

        counts = db_backup.backup_doc_counts(self.db)
        self.assertEqual(counts["crim"], 2)
        self.assertEqual(counts["gen"], 1)

        from tabs.tab_settings import _resetDocCounts
        reset_counts = _resetDocCounts(c)
        self.assertEqual(reset_counts["crim"], 2)
        self.assertEqual(reset_counts["gen"], 1)
        c.close()

    def test_deleted_ticket_shell_not_counted(self):
        c = sqlite3.connect(self.db)
        c.execute("INSERT INTO Document_Ticket(doc_id) VALUES('2')")
        c.commit(); c.close()
        self.assertEqual(db_backup.backup_doc_counts(self.db)["ticket"], 1)

    def test_restore_roundtrip_with_prerestore(self):
        db_backup.run_auto_backup(self.db)
        bdir = db_backup.backup_dir(self.db)
        src = os.path.join(bdir, next(
            n for n in os.listdir(bdir) if n.startswith("dbfile_backup_day_")))
        # 破壞本體後還原
        c = sqlite3.connect(self.db)
        c.execute("DELETE FROM Document_Task"); c.commit(); c.close()
        ok, _ = db_backup.restore_backup(self.db, src)
        self.assertTrue(ok)
        c = sqlite3.connect(self.db)
        n = c.execute("SELECT COUNT(*) FROM Document_Task "
                      "WHERE receive_date IS NOT NULL").fetchone()[0]
        c.close()
        self.assertEqual(n, 1)
        # 覆蓋前的留底存在
        self.assertTrue(any(x.startswith(db_backup.PRERESTORE_PREFIX)
                            for x in os.listdir(self.tmp)))

    def test_restore_missing_source(self):
        ok, _ = db_backup.restore_backup(
            self.db, os.path.join(self.tmp, "nope.db"))
        self.assertFalse(ok)

    def test_find_latest_usable_skips_corrupt(self):
        # 建兩份備份，把「較新」那份弄壞 → 應自動退回較舊那份
        db_backup.run_auto_backup(self.db)
        bdir = db_backup.backup_dir(self.db)
        good = os.path.join(bdir, "dbfile_backup_day_20260101.db")
        bad = os.path.join(bdir, "dbfile_backup_day_20260201.db")  # 日期較新
        import shutil
        shutil.copy2(self.db, good)
        with open(bad, "wb") as f:
            f.write(b"SQLite format 3\x00" + b"\xff" * 3000)
        e = db_backup.find_latest_usable_backup(self.db)
        self.assertIsNotNone(e)
        self.assertNotEqual(os.path.basename(e["path"]),
                            "dbfile_backup_day_20260201.db")

    def test_find_latest_usable_none(self):
        # 只有一份損毀備份 → 回 None
        bdir = db_backup.backup_dir(self.db)
        os.makedirs(bdir, exist_ok=True)
        with open(os.path.join(bdir, "dbfile_backup_day_20260101.db"), "wb") as f:
            f.write(b"not a db")
        self.assertIsNone(db_backup.find_latest_usable_backup(self.db))


class TestPruneTimestamped(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _touch(self, name):
        open(os.path.join(self.tmp, name), "w").close()

    def test_keeps_newest_n_deletes_older(self):
        names = [
            "dbfile_prerestore_20260101_120000.db",
            "dbfile_prerestore_20260201_120000.db",
            "dbfile_prerestore_20260301_120000.db",
            "dbfile_prerestore_20260401_120000.db",
        ]
        for n in names:
            self._touch(n)
        db_backup._prune_timestamped(
            self.tmp, db_backup._PRERESTORE_RE,
            db_backup.PRERESTORE_PREFIX, keep=3)
        remaining = set(os.listdir(self.tmp))
        self.assertNotIn(names[0], remaining)        # 最舊那份刪掉
        for n in names[1:]:
            self.assertIn(n, remaining)              # 其餘 3 份保留

    def test_within_keep_nothing_deleted(self):
        names = [
            "dbfile_prerestore_20260101_120000.db",
            "dbfile_prerestore_20260201_120000.db",
        ]
        for n in names:
            self._touch(n)
        db_backup._prune_timestamped(
            self.tmp, db_backup._PRERESTORE_RE,
            db_backup.PRERESTORE_PREFIX, keep=3)
        for n in names:
            self.assertIn(n, os.listdir(self.tmp))


class TestVerifyAdminPassword(unittest.TestCase):
    def setUp(self):
        import hashlib
        from lib import db_schema
        self.tmp = tempfile.mkdtemp()
        self.bk = os.path.join(self.tmp, "backup.db")
        conn = sqlite3.connect(self.bk)
        db_schema.applySchema(conn)
        conn.execute("INSERT INTO App_Settings(key,value) VALUES('admin_password_hash',?)",
                     (hashlib.sha256(b"secret").hexdigest(),))
        conn.commit(); conn.close()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_correct_password(self):
        self.assertTrue(db_backup.verify_admin_password(self.bk, "secret"))

    def test_wrong_password(self):
        self.assertFalse(db_backup.verify_admin_password(self.bk, "nope"))

    def test_missing_file(self):
        self.assertFalse(
            db_backup.verify_admin_password(os.path.join(self.tmp, "x.db"), "secret"))

    def test_missing_hash_row_falls_back_to_default(self):
        # 備份缺 admin_password_hash 列時退回預設密碼比對（否則 admin 被鎖在還原之外）
        from lib import db_schema
        bk2 = os.path.join(self.tmp, "no_hash.db")
        conn = sqlite3.connect(bk2)
        db_schema.applySchema(conn)
        conn.execute("DELETE FROM App_Settings WHERE key='admin_password_hash'")
        conn.commit(); conn.close()
        self.assertTrue(db_backup.verify_admin_password(bk2, "admin"))   # 預設密碼可過
        self.assertFalse(db_backup.verify_admin_password(bk2, "secret"))  # 其他不過


if __name__ == "__main__":
    unittest.main()
