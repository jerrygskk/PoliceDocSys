"""lib/db_utils.py 稽核 helper 單元測試（暫存 sqlite，無 GUI）。

涵蓋：
  - buildDetail 的 `[類別][動作]內容` 格式組裝
  - auditStaffName 以 staff_id 解析姓名快照（查無回原 id）
  - writeAudit 寫入 + 讀回 round-trip（含同 conn 與業務操作同 transaction）
  - 操作紀錄檢視（tab_audit.parseDetail）detail 解析

執行：專案根目錄下 `python -m unittest tests.test_audit`
"""
import os
import sys
import sqlite3
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lib.db_utils import buildDetail, auditStaffName, writeAudit, writeAuditSafe
from tabs.tab_audit import CATEGORIES, parseDetail


_AUDIT_DDL = """
CREATE TABLE Audit_Log (
  log_id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts TEXT NOT NULL, role TEXT, action TEXT,
  target_table TEXT, target_id TEXT, operator TEXT, detail TEXT
)"""


class TestBuildDetail(unittest.TestCase):
    def test_delete_format(self):
        self.assertEqual(
            buildDetail("交辦", "刪除", "主旨：協尋失蹤人口"),
            "[交辦][刪除]主旨：協尋失蹤人口")

    def test_modify_format(self):
        self.assertEqual(
            buildDetail("交辦", "修改", "王小明 → 陳大華"),
            "[交辦][修改]王小明 → 陳大華")

    def test_archive_cancel_nested_tag(self):
        self.assertEqual(
            buildDetail("歸檔", "取消", "[電子]主旨：機車竊盜案"),
            "[歸檔][取消][電子]主旨：機車竊盜案")

    def test_empty_content(self):
        self.assertEqual(buildDetail("系統", "登入失敗"), "[系統][登入失敗]")


class _DbBase(unittest.TestCase):
    def setUp(self):
        fd, self.db = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self.conn = sqlite3.connect(self.db)
        self.conn.execute(_AUDIT_DDL)
        self.conn.execute(
            "CREATE TABLE Ref_Personnel (staff_id TEXT, staff_name TEXT)")
        self.conn.execute(
            "INSERT INTO Ref_Personnel VALUES ('P01','林志明')")
        self.conn.commit()

    def tearDown(self):
        self.conn.close()
        os.remove(self.db)


class TestStaffName(_DbBase):
    def test_known_id(self):
        self.assertEqual(auditStaffName(self.conn, "P01"), "林志明")

    def test_unknown_id_returns_id(self):
        self.assertEqual(auditStaffName(self.conn, "P99"), "P99")

    def test_empty_id(self):
        self.assertEqual(auditStaffName(self.conn, None), "")
        self.assertEqual(auditStaffName(self.conn, ""), "")


class TestWriteAudit(_DbBase):
    def test_roundtrip(self):
        writeAudit(self.conn, role="user", action="DELETE",
                   target_table="Document_Task", target_id="T0042",
                   operator="林志明",
                   detail=buildDetail("交辦", "刪除", "主旨：協尋失蹤人口"))
        self.conn.commit()
        row = self.conn.execute(
            "SELECT role, action, target_table, target_id, operator, detail "
            "FROM Audit_Log").fetchone()
        self.assertEqual(
            row,
            ("user", "DELETE", "Document_Task", "T0042", "林志明",
             "[交辦][刪除]主旨：協尋失蹤人口"))

    def test_ts_autofilled(self):
        writeAudit(self.conn, role="admin", action="RESET", detail="x")
        self.conn.commit()
        ts = self.conn.execute("SELECT ts FROM Audit_Log").fetchone()[0]
        self.assertTrue(ts and len(ts) >= 16)   # 'YYYY-MM-DD HH:MM:SS'

    def test_missing_table_does_not_raise(self):
        # 缺 Audit_Log 表的舊 DB：writeAudit 應靜默跳過、不中斷業務
        c2 = sqlite3.connect(":memory:")
        try:
            writeAudit(c2, role="user", action="DELETE", detail="x")  # 不應丟例外
        finally:
            c2.close()

    def test_shared_transaction_rollback(self):
        # 與業務操作同一 conn：未 commit 前 rollback，log 也一併回滾
        writeAudit(self.conn, role="user", action="DELETE", detail="x")
        self.conn.rollback()
        n = self.conn.execute("SELECT COUNT(*) FROM Audit_Log").fetchone()[0]
        self.assertEqual(n, 0)


class TestWriteAuditSafe(_DbBase):
    """writeAuditSafe：自開連線寫獨立事件 → commit → close，全程吞例外。"""

    def test_roundtrip_commits(self):
        writeAuditSafe(self.db, role="admin", action="PWD",
                       operator="林志明",
                       detail=buildDetail("系統", "修改", "admin變更密碼"))
        # 另開連線確認已 commit 落地（非靠 self.conn）
        c2 = sqlite3.connect(self.db)
        try:
            row = c2.execute(
                "SELECT role, action, operator, detail FROM Audit_Log").fetchone()
        finally:
            c2.close()
        self.assertEqual(
            row, ("admin", "PWD", "林志明", "[系統][修改]admin變更密碼"))

    def test_bad_path_does_not_raise(self):
        # 路徑不可寫 / 缺表一律靜默，不中斷呼叫端
        writeAuditSafe("/no/such/dir/x.db", role="user",
                       action="LOGIN_FAIL", detail="x")


class TestParseDetail(unittest.TestCase):
    """操作紀錄檢視（tab_audit）：detail 拆「類別／動作／內容」三欄。"""

    def test_full(self):
        self.assertEqual(
            parseDetail("[刑案][刪除]主旨：機車失竊案"),
            ("刑案", "刪除", "主旨：機車失竊案"))

    def test_empty_content(self):
        self.assertEqual(parseDetail("[系統][登入失敗]"),
                         ("系統", "登入失敗", ""))

    def test_content_with_brackets(self):
        # 內容含中括號不應被誤切（只吃前兩組 [..]）
        self.assertEqual(
            parseDetail("[歸檔][取消][電子] 主旨：協尋"),
            ("歸檔", "取消", "[電子] 主旨：協尋"))

    def test_no_format(self):
        self.assertEqual(parseDetail("純文字沒有前綴"),
                         ("", "", "純文字沒有前綴"))

    def test_blank(self):
        self.assertEqual(parseDetail(""), ("", "", ""))
        self.assertEqual(parseDetail(None), ("", "", ""))

    def test_arrow_content(self):
        self.assertEqual(
            parseDetail("[交辦][修改]王志明 → 林佳蓉"),
            ("交辦", "修改", "王志明 → 林佳蓉"))

    def test_reward_category_is_filterable(self):
        self.assertIn("敘獎", CATEGORIES)


if __name__ == "__main__":
    unittest.main()
