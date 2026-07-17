"""friendlyErrorMessage 純邏輯回歸測試（全域錯誤訊息白話化）。

受測模組 lib.db_utils import 時會載入 PySide6（同 test_db_utils）。
"""
import sqlite3
import unittest

from lib.db_utils import friendlyErrorMessage, _GENERIC_ERROR


class FriendlyErrorMessageTest(unittest.TestCase):
    def test_db_locked(self):
        e = sqlite3.OperationalError("database is locked")
        msg = friendlyErrorMessage(type(e), e)
        self.assertIn("忙線", msg)
        self.assertNotIn("locked", msg)  # 不洩漏技術字串

    def test_operational_other(self):
        e = sqlite3.OperationalError("no such table: Foo")
        msg = friendlyErrorMessage(type(e), e)
        self.assertIn("資料庫", msg)
        self.assertNotIn("no such table", msg)

    def test_database_malformed(self):
        e = sqlite3.DatabaseError("database disk image is malformed")
        msg = friendlyErrorMessage(type(e), e)
        self.assertIn("損毀", msg)

    def test_permission_error(self):
        e = PermissionError("[Errno 13] Permission denied: 'x'")
        self.assertIn("權限", friendlyErrorMessage(type(e), e))

    def test_file_not_found(self):
        e = FileNotFoundError("missing")
        self.assertIn("找不到", friendlyErrorMessage(type(e), e))

    def test_os_error_network_drive(self):
        e = OSError("network path not found")
        self.assertIn("網路磁碟機", friendlyErrorMessage(type(e), e))

    def test_unknown_falls_back_to_generic(self):
        e = ValueError("某個內部例外")
        self.assertEqual(friendlyErrorMessage(type(e), e), _GENERIC_ERROR)

    def test_no_traceback_leaked(self):
        # 任何訊息都不應含 Traceback 等工程字樣
        for e in (sqlite3.OperationalError("x"), RuntimeError("y")):
            msg = friendlyErrorMessage(type(e), e)
            self.assertNotIn("Traceback", msg)
            self.assertNotIn("Error", msg)

    def test_none_exc_type(self):
        # exc_type 為 None 時靠 value 型別判斷，不崩潰
        e = PermissionError("denied")
        self.assertIn("權限", friendlyErrorMessage(None, e))

    def test_disk_full_gets_dedicated_message(self):
        e = sqlite3.OperationalError("database or disk is full")
        self.assertIn("空間不足", friendlyErrorMessage(type(e), e))

    def test_generic_operational_error_not_disk_full(self):
        e = sqlite3.OperationalError("no such table: Foo")
        self.assertNotIn("空間不足", friendlyErrorMessage(type(e), e))


if __name__ == "__main__":
    unittest.main()
