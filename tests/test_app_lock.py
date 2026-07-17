"""app_lock 純邏輯回歸測試（APP 層軟性互斥鎖檔）。純 stdlib，不碰 GUI。"""
import os
import tempfile
import unittest
from datetime import datetime, timedelta

from lib import app_lock


class FormatParseTest(unittest.TestCase):
    def test_round_trip(self):
        text = app_lock.format_lock("PC1", "alice", "2026-06-26T10:00:00",
                                    "2026-06-26T10:01:00", 1234)
        d = app_lock.parse_lock(text)
        self.assertEqual(d["machine"], "PC1")
        self.assertEqual(d["user"], "alice")
        self.assertEqual(d["pid"], 1234)
        self.assertEqual(d["heartbeat"], "2026-06-26T10:01:00")

    def test_parse_garbage(self):
        self.assertIsNone(app_lock.parse_lock("not json {"))
        self.assertIsNone(app_lock.parse_lock(""))

    def test_parse_non_dict(self):
        self.assertIsNone(app_lock.parse_lock("[1, 2, 3]"))


class IsStaleTest(unittest.TestCase):
    def test_fresh(self):
        now = datetime(2026, 6, 26, 10, 5, 0)
        hb = (now - timedelta(seconds=30)).isoformat()
        self.assertFalse(app_lock.is_stale(hb, now.isoformat()))

    def test_stale(self):
        now = datetime(2026, 6, 26, 10, 5, 0)
        hb = (now - timedelta(minutes=10)).isoformat()
        self.assertTrue(app_lock.is_stale(hb, now.isoformat()))

    def test_bad_timestamp_is_stale(self):
        # 壞掉的時間戳＝視為失效，可接管
        self.assertTrue(app_lock.is_stale("garbage", "2026-06-26T10:00:00"))

    def test_boundary(self):
        now = datetime(2026, 6, 26, 10, 5, 0)
        hb = (now - timedelta(seconds=app_lock.STALE_SECONDS + 1)).isoformat()
        self.assertTrue(app_lock.is_stale(hb, now.isoformat()))


class IsMineTest(unittest.TestCase):
    def test_mine(self):
        info = {"machine": "PC1", "pid": 99}
        self.assertTrue(app_lock.is_mine(info, "PC1", 99))

    def test_not_mine_diff_machine(self):
        info = {"machine": "PC2", "pid": 99}
        self.assertFalse(app_lock.is_mine(info, "PC1", 99))

    def test_not_mine_diff_pid(self):
        info = {"machine": "PC1", "pid": 1}
        self.assertFalse(app_lock.is_mine(info, "PC1", 99))

    def test_none_info(self):
        self.assertFalse(app_lock.is_mine(None, "PC1", 99))


class LockPathTest(unittest.TestCase):
    def test_beside_db(self):
        p = app_lock.lock_file_path(os.path.join("X", "Y", "dbfile.db"))
        self.assertEqual(os.path.basename(p), app_lock.LOCK_NAME)
        self.assertEqual(os.path.dirname(p), os.path.abspath(os.path.join("X", "Y")))


class IoTest(unittest.TestCase):
    def test_read_missing_returns_none(self):
        self.assertIsNone(app_lock.read_lock(os.path.join(
            tempfile.gettempdir(), "definitely_no_such_lock_xyz.lock")))

    def test_write_read_remove_cycle(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "dbfile.lock")
            ok = app_lock.write_lock(path, "PC1", "bob", "2026-06-26T10:00:00",
                                     "2026-06-26T10:00:00", 7)
            self.assertTrue(ok)
            info = app_lock.read_lock(path)
            self.assertEqual(info["user"], "bob")
            # 非本實例不刪
            app_lock.remove_lock(path, machine="OTHER", pid=7)
            self.assertTrue(os.path.exists(path))
            # 本實例才刪
            app_lock.remove_lock(path, machine="PC1", pid=7)
            self.assertFalse(os.path.exists(path))


if __name__ == "__main__":
    unittest.main()
