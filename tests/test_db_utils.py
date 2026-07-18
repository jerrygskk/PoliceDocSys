"""lib/db_utils.py 純 SQL / 檔案邏輯單元測試（用暫存 sqlite，無 GUI）。

涵蓋：
  - nextDocId 只增不減
  - listInactiveRefItems 只列停用、依 sort_order
  - performYearEndReset 兩段式重編 id 不撞 PK、清主表、刪停用、歸零 Seq、清歸檔設定、rollback
  - getSetting / setSetting upsert
  - resolveArchivedPdf 各狀態碼（用暫存資料夾）
執行：專案根目錄下 `python -m unittest tests.test_db_utils`
"""
import os
import sys
import sqlite3
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lib import db_utils, db_schema
from lib.db_utils import (
    nextDocId, listInactiveRefItems, performYearEndReset,
    getSetting, setSetting, resolveArchivedPdf, ARCHIVE_ROOT_KEY,
)


def _build_schema(conn):
    # 直接套用正式 schema 的「程式碼唯一來源」，避免測試自刻假 schema 與正式走鐘。
    # 不播種子（種子在 db_seed），測試自行塞所需資料列。
    db_schema.applySchema(conn)


class _DbTestBase(unittest.TestCase):
    def setUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self.conn = sqlite3.connect(self.db_path)
        _build_schema(self.conn)
        self.conn.commit()

    def tearDown(self):
        self.conn.close()
        os.remove(self.db_path)


class TestIndexes(_DbTestBase):
    def test_indexes_created(self):
        names = {r[0] for r in self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index'").fetchall()}
        for idx in ("idx_task_lastmod", "idx_crim_lastmod", "idx_gen_lastmod",
                    "idx_reward_lastmod", "idx_audit_ts"):
            self.assertIn(idx, names)


class TestGetConn(_DbTestBase):
    def test_busy_timeout_applied(self):
        conn = db_utils.getConn(self.db_path)
        try:
            val = conn.execute("PRAGMA busy_timeout").fetchone()[0]
        finally:
            conn.close()
        self.assertEqual(val, 3000)


class TestNextDocId(_DbTestBase):
    def test_increments(self):
        self.conn.execute(
            "INSERT INTO Seq_DocId VALUES('Document_Task', 5)")
        self.assertEqual(nextDocId(self.conn, "Document_Task"), "6")
        self.assertEqual(nextDocId(self.conn, "Document_Task"), "7")

    def test_from_zero(self):
        self.conn.execute("INSERT INTO Seq_DocId VALUES('Document_Criminal', 0)")
        self.assertEqual(nextDocId(self.conn, "Document_Criminal"), "1")


class TestListInactive(_DbTestBase):
    def test_only_inactive_sorted(self):
        self.conn.executemany(
            "INSERT INTO Ref_Personnel(staff_id,staff_name,alias,is_active,sort_order) "
            "VALUES(?,?,?,?,?)",
            [("P01", "在職甲", "", 1, 1),
             ("P02", "離職乙", "", 0, 3),
             ("P03", "離職丙", "", 0, 2)])
        self.conn.commit()
        out = listInactiveRefItems(self.db_path)
        # 只含停用，依 sort_order：丙(2) 先於乙(3)
        self.assertEqual(out, [("人員", "P03", "離職丙"),
                               ("人員", "P02", "離職乙")])

    def test_empty(self):
        self.assertEqual(listInactiveRefItems(self.db_path), [])


class TestYearEndReset(_DbTestBase):
    def _seed(self):
        c = self.conn
        c.execute("INSERT INTO Document_Task(doc_id) VALUES('T1')")
        c.execute("INSERT INTO Document_Criminal(doc_id) VALUES('C1')")
        c.execute("INSERT INTO Document_General(doc_id) VALUES('G1')")
        c.execute("INSERT INTO Seq_DocId VALUES('Document_Task', 42)")
        # 人員：故意讓 sort_order 與 id 不同序，且含一個停用
        c.executemany(
            "INSERT INTO Ref_Personnel(staff_id,staff_name,alias,is_active,sort_order) "
            "VALUES(?,?,?,?,?)",
            [("P05", "甲", "", 1, 2),
             ("P09", "乙", "", 1, 1),
             ("P03", "丙停用", "", 0, 3)])
        c.execute("INSERT INTO App_Settings VALUES(?, 'X:/old')",
                  (ARCHIVE_ROOT_KEY,))
        c.commit()

    def test_full_reset(self):
        self._seed()
        self.conn.execute(
            "INSERT INTO Trash_Documents(table_name, doc_id, payload, "
            "deleted_ts) VALUES('Document_Task','T1','{}','2026-01-01')")
        self.conn.commit()
        performYearEndReset(self.db_path)
        c = sqlite3.connect(self.db_path)
        try:
            # 主表清空
            for t in ("Document_Task", "Document_Criminal", "Document_General"):
                self.assertEqual(
                    c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0], 0)
            # 回收筒一併清空
            self.assertEqual(
                c.execute("SELECT COUNT(*) FROM Trash_Documents").fetchone()[0], 0)
            # 停用刪除，存活 2 人，依 sort_order 重編：乙(原so1)→P01、甲(原so2)→P02
            rows = c.execute(
                "SELECT staff_id, staff_name, sort_order FROM Ref_Personnel "
                "ORDER BY sort_order").fetchall()
            self.assertEqual(rows, [("P01", "乙", 1), ("P02", "甲", 2)])
            # Seq 歸零
            self.assertEqual(
                c.execute("SELECT last_id FROM Seq_DocId").fetchone()[0], 0)
            # 歸檔設定清空
            self.assertEqual(getSetting(self.db_path, ARCHIVE_ROOT_KEY), "")
        finally:
            c.close()

    def test_no_pk_collision_on_shift(self):
        # 重編後 id 集合與舊集合有交集（P05/P09→P01/P02），兩段式須不撞 PK
        self._seed()
        try:
            performYearEndReset(self.db_path)
        except sqlite3.IntegrityError:
            self.fail("兩段式重編仍撞 PRIMARY KEY")

    def test_rollback_on_failure(self):
        self._seed()
        # 移除 Seq_DocId 表使重置中途失敗，驗證 rollback（資料不變）
        self.conn.execute("DROP TABLE Seq_DocId")
        self.conn.commit()
        with self.assertRaises(sqlite3.Error):
            performYearEndReset(self.db_path)
        c = sqlite3.connect(self.db_path)
        try:
            # 主表仍在（已 rollback）
            self.assertEqual(
                c.execute("SELECT COUNT(*) FROM Document_Task").fetchone()[0], 1)
            # 人員未被重編（P05 仍在）
            self.assertIsNotNone(
                c.execute("SELECT 1 FROM Ref_Personnel WHERE staff_id='P05'"
                          ).fetchone())
        finally:
            c.close()


class TestSettings(_DbTestBase):
    def test_get_default(self):
        self.assertEqual(getSetting(self.db_path, "missing", "def"), "def")

    def test_set_then_get(self):
        setSetting(self.db_path, "k", "v1")
        self.assertEqual(getSetting(self.db_path, "k"), "v1")

    def test_upsert_overwrites(self):
        setSetting(self.db_path, "k", "v1")
        setSetting(self.db_path, "k", "v2")
        self.assertEqual(getSetting(self.db_path, "k"), "v2")

    def test_none_stored_as_empty(self):
        setSetting(self.db_path, "k", None)
        self.assertEqual(getSetting(self.db_path, "k"), "")


class TestResolveArchivedPdf(_DbTestBase):
    def setUp(self):
        super().setUp()
        self.tmpdir = tempfile.mkdtemp()
        db_utils.clearPdfIndexCache()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)
        super().tearDown()

    def test_noroot(self):
        self.assertEqual(
            resolveArchivedPdf(self.db_path, "crim", "a.pdf")[1], "noroot")

    def test_empty_fname(self):
        self.assertEqual(
            resolveArchivedPdf(self.db_path, "crim", "")[1], "notfound")

    def test_noaccess(self):
        setSetting(self.db_path, ARCHIVE_ROOT_KEY,
                   os.path.join(self.tmpdir, "不存在"))
        self.assertEqual(
            resolveArchivedPdf(self.db_path, "crim", "a.pdf")[1], "noaccess")

    def test_notfound(self):
        setSetting(self.db_path, ARCHIVE_ROOT_KEY, self.tmpdir)
        self.assertEqual(
            resolveArchivedPdf(self.db_path, "crim", "missing.pdf")[1],
            "notfound")

    def test_ok_recursive(self):
        sub = os.path.join(self.tmpdir, "刑案")
        os.makedirs(sub)
        target = os.path.join(sub, "103-1150612.pdf")
        open(target, "w").close()
        setSetting(self.db_path, ARCHIVE_ROOT_KEY, self.tmpdir)
        path, code = resolveArchivedPdf(self.db_path, "crim", "103-1150612.pdf")
        self.assertEqual(code, "ok")
        self.assertEqual(os.path.normpath(path), os.path.normpath(target))


class TestToUncPath(unittest.TestCase):
    """toUncPath 純分支（已是 UNC／空值）。磁碟機代號解析需 Windows 網路環境，
    不在此測；這裡只測與平台無關的決定性分支。"""

    def test_already_unc_passthrough(self):
        self.assertEqual(db_utils.toUncPath(r"\\srv\share\歸檔\2026"),
                         r"\\srv\share\歸檔\2026")

    def test_unc_trailing_slash_trimmed(self):
        self.assertEqual(db_utils.toUncPath("\\\\srv\\share\\"), r"\\srv\share")

    def test_forward_slash_unc_normalized(self):
        self.assertEqual(db_utils.toUncPath("//srv/share/a"), r"\\srv\share\a")

    def test_empty_returns_none(self):
        self.assertIsNone(db_utils.toUncPath(""))
        self.assertIsNone(db_utils.toUncPath(None))


class TestIsDiskFullError(unittest.TestCase):
    def test_oserror_enospc(self):
        exc = OSError(28, "No space left on device")
        self.assertTrue(db_utils.isDiskFullError(exc))

    def test_sqlite_disk_image_full(self):
        exc = sqlite3.OperationalError("database or disk is full")
        self.assertTrue(db_utils.isDiskFullError(exc))

    def test_unrelated_oserror_not_disk_full(self):
        exc = OSError(13, "Permission denied")
        self.assertFalse(db_utils.isDiskFullError(exc))

    def test_unrelated_exception_not_disk_full(self):
        self.assertFalse(db_utils.isDiskFullError(ValueError("foo")))


class TestDiskSpaceThreshold(unittest.TestCase):
    def setUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.write(fd, b"x" * 1000)
        os.close(fd)

    def tearDown(self):
        os.remove(self.db_path)

    def test_threshold_scales_with_db_size(self):
        base = db_utils.diskSpaceThreshold(self.db_path)
        self.assertEqual(
            base,
            db_utils.DISK_RUNTIME_FOOTPRINT + 1000 * 2 + db_utils.DISK_SAFETY_MARGIN)

    def test_missing_db_treated_as_zero_size(self):
        threshold = db_utils.diskSpaceThreshold(os.path.join(
            os.path.dirname(self.db_path), "does_not_exist.db"))
        self.assertEqual(
            threshold, db_utils.DISK_RUNTIME_FOOTPRINT + db_utils.DISK_SAFETY_MARGIN)

    def test_checks_same_drive_merged(self):
        # 暫存碟與 DB 同顆 → 單一合併門檻（＝diskSpaceThreshold，與舊行為一致）
        checks = db_utils.diskSpaceChecks(
            self.db_path, temp_dir=os.path.dirname(self.db_path))
        self.assertEqual(len(checks), 1)
        self.assertEqual(checks[0][1], db_utils.diskSpaceThreshold(self.db_path))

    def test_checks_different_drives_split(self):
        # 不同顆（DB 在 UNC 網路碟）→ 暫存碟查解壓峰值、DB 碟查備份空間
        fake_db = r"\\server\share\dbfile.db"   # 不存在＝db_size 0，splitdrive 可辨識
        checks = db_utils.diskSpaceChecks(fake_db, temp_dir=os.path.dirname(self.db_path))
        self.assertEqual(len(checks), 2)
        roots = [c[0] for c in checks]
        self.assertIn(os.path.dirname(self.db_path), roots)
        self.assertEqual(
            checks[0][1],
            db_utils.DISK_RUNTIME_FOOTPRINT + db_utils.DISK_SAFETY_MARGIN)
        self.assertEqual(checks[1][1], db_utils.DISK_SAFETY_MARGIN)   # db_size=0

    def test_same_drive_case_insensitive(self):
        self.assertTrue(db_utils._sameDrive(r"C:\temp", r"c:\data"))
        self.assertFalse(db_utils._sameDrive(r"C:\temp", r"\\server\share\x"))


if __name__ == "__main__":
    unittest.main()
