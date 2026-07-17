"""lib/auth_manager.py 權限 / 密碼邏輯單元測試（暫存 sqlite，無 GUI）。

涵蓋：
  - 便捷身分判斷 is_admin() / is_manager() / is_archive()
  - login 正確/錯誤密碼、登出
  - change_password 舊密碼驗證 + 寫回 round-trip + 撞另一組密碼擋下（conflict）

注意：AuthManager 是單例，但這裡直接 `AuthManager()` 建獨立實例避免污染全域
單例狀態（_role 預設 'user'）。
執行：專案根目錄下 `python -m unittest tests.test_auth_manager`
"""
import os
import sys
import hashlib
import sqlite3
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lib.auth_manager import AuthManager, _hash_eq


def _hash(p):
    return hashlib.sha256(p.encode()).hexdigest()


class TestHashEq(unittest.TestCase):
    def test_equal(self):
        self.assertTrue(_hash_eq(_hash("admin"), _hash("admin")))

    def test_not_equal(self):
        self.assertFalse(_hash_eq(_hash("admin"), _hash("0000")))

    def test_none_stored(self):
        self.assertFalse(_hash_eq(None, _hash("admin")))

    def test_non_str_stored(self):
        self.assertFalse(_hash_eq(123, _hash("admin")))


class _AuthBase(unittest.TestCase):
    def setUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            "CREATE TABLE App_Settings (key TEXT PRIMARY KEY, value TEXT)")
        conn.execute(
            "INSERT INTO App_Settings VALUES('admin_password_hash', ?)",
            (_hash("admin"),))
        conn.execute(
            "INSERT INTO App_Settings VALUES('archive_password_hash', ?)",
            (_hash("0000"),))
        conn.commit()
        conn.close()
        self.auth = AuthManager()   # 獨立實例，不動全域單例

    def tearDown(self):
        os.remove(self.db_path)


class TestPermissions(_AuthBase):
    def test_default_is_user(self):
        self.assertEqual(self.auth.current_role, "user")
        self.assertFalse(self.auth.is_admin())

    def test_user_is_not_manager(self):
        # 一般使用者非管理身分（便捷判斷取代已移除的 can()）
        self.assertFalse(self.auth.is_admin())
        self.assertFalse(self.auth.is_archive())
        self.assertFalse(self.auth.is_manager())

    def test_admin_is_top_role(self):
        self.auth.login("admin", self.db_path)
        self.assertTrue(self.auth.is_admin())
        self.assertTrue(self.auth.is_manager())
        self.assertFalse(self.auth.is_archive())


class TestLogin(_AuthBase):
    def test_admin_password(self):
        self.assertTrue(self.auth.login("admin", self.db_path))
        self.assertEqual(self.auth.current_role, "admin")
        self.assertTrue(self.auth.is_admin())
        self.assertTrue(self.auth.is_manager())
        self.assertFalse(self.auth.is_archive())

    def test_archive_password(self):
        self.assertTrue(self.auth.login("0000", self.db_path))
        self.assertEqual(self.auth.current_role, "archive")
        self.assertTrue(self.auth.is_archive())
        self.assertTrue(self.auth.is_manager())     # 歸檔管理也算管理身分
        self.assertFalse(self.auth.is_admin())      # 但不是最高權限

    def test_actor_name(self):
        self.assertEqual(self.auth.actor_name(), "一般使用者")
        self.auth.login("0000", self.db_path)
        self.assertEqual(self.auth.actor_name(), "歸檔管理")
        self.auth.login("admin", self.db_path)
        self.assertEqual(self.auth.actor_name(), "管理者")

    def test_wrong_password(self):
        self.assertFalse(self.auth.login("9999", self.db_path))
        self.assertEqual(self.auth.current_role, "user")

    def test_logout(self):
        self.auth.login("admin", self.db_path)
        self.auth.logout()
        self.assertEqual(self.auth.current_role, "user")
        self.assertFalse(self.auth.is_manager())

    def test_bad_db_path(self):
        self.assertFalse(self.auth.login("admin", "Z:/does/not/exist.db"))


class TestChangePassword(_AuthBase):
    def test_user_role_cannot_change(self):
        # 未登入（user）不得變更密碼
        self.assertEqual(
            self.auth.change_password("admin", "1234", self.db_path), "error")

    def test_admin_change_then_login_with_new(self):
        self.auth.login("admin", self.db_path)
        self.assertEqual(
            self.auth.change_password("admin", "1234", self.db_path), "ok")
        self.auth.logout()
        self.assertFalse(self.auth.login("admin", self.db_path))
        self.assertTrue(self.auth.login("1234", self.db_path))
        self.assertTrue(self.auth.is_admin())
        conn = sqlite3.connect(self.db_path)
        val = conn.execute(
            "SELECT value FROM App_Settings WHERE key='admin_password_hash'"
        ).fetchone()[0]
        conn.close()
        self.assertEqual(val, _hash("1234"))

    def test_archive_change_only_affects_archive_group(self):
        self.auth.login("0000", self.db_path)
        self.assertEqual(
            self.auth.change_password("0000", "5678", self.db_path), "ok")
        self.auth.logout()
        # 歸檔密碼換新；管理者密碼不受影響
        self.assertTrue(self.auth.login("5678", self.db_path))
        self.assertEqual(self.auth.current_role, "archive")
        self.auth.logout()
        self.assertTrue(self.auth.login("admin", self.db_path))
        self.assertEqual(self.auth.current_role, "admin")

    def test_wrong_old_password_rejected(self):
        self.auth.login("admin", self.db_path)
        self.assertEqual(
            self.auth.change_password("xxxx", "1234", self.db_path), "wrong_old")
        self.auth.logout()
        self.assertTrue(self.auth.login("admin", self.db_path))

    def test_admin_cannot_set_archive_password(self):
        # admin 新密碼撞到 archive 現值 → conflict，且 DB 不動
        self.auth.login("admin", self.db_path)
        self.assertEqual(
            self.auth.change_password("admin", "0000", self.db_path), "conflict")
        self.auth.logout()
        # 兩組密碼皆維持原值、各自登得進正確身分
        self.assertTrue(self.auth.login("admin", self.db_path))
        self.assertEqual(self.auth.current_role, "admin")
        self.auth.logout()
        self.assertTrue(self.auth.login("0000", self.db_path))
        self.assertEqual(self.auth.current_role, "archive")

    def test_archive_cannot_set_admin_password(self):
        # archive 新密碼撞到 admin 現值 → conflict（防 archive 變相奪權）
        self.auth.login("0000", self.db_path)
        self.assertEqual(
            self.auth.change_password("0000", "admin", self.db_path), "conflict")
        self.auth.logout()
        self.assertTrue(self.auth.login("0000", self.db_path))
        self.assertEqual(self.auth.current_role, "archive")

    def test_change_to_same_as_own_current_is_allowed(self):
        # 撞「自己那組」現值不算 conflict（等於沒改，不影響另一組登入）
        self.auth.login("admin", self.db_path)
        self.assertEqual(
            self.auth.change_password("admin", "admin", self.db_path), "ok")


if __name__ == "__main__":
    unittest.main()
