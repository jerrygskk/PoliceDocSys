# -*- coding: utf-8 -*-
"""敘獎筆數出現在備份還原與開機救援摘要。"""
import unittest

from PySide6.QtWidgets import QApplication, QLabel

from ui_utils.backup_restore_panel import _formatDocCounts as backup_summary
from ui_utils.rescue_dialog import _formatDocCounts as rescue_summary
from ui_utils.settings_dialogs import ResetDialog


class TestRewardSummary(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_backup_restore_preview_includes_reward(self):
        text = backup_summary({"task": 1, "crim": 2, "gen": 3, "reward": 4})
        self.assertIn("敘獎 4 筆", text)

    def test_rescue_preview_includes_reward(self):
        text = rescue_summary({"task": 1, "crim": 2, "gen": 3, "reward": 4})
        self.assertIn("敘獎 4 筆", text)

    def test_missing_reward_table_uses_dash(self):
        counts = {"task": 1, "crim": 2, "gen": 3, "reward": None}
        self.assertIn("敘獎 — 筆", backup_summary(counts))
        self.assertIn("敘獎 — 筆", rescue_summary(counts))

    def test_reset_confirmation_shows_reward_count(self):
        # 不需讀 DB：空路徑只會令停用項目清單查詢失敗，故使用既有測試 DB
        import os
        import sqlite3
        import tempfile
        from lib.db_schema import applySchema
        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        try:
            conn = sqlite3.connect(path)
            applySchema(conn)
            conn.close()
            dlg = ResetDialog(path, doc_summary="交辦 1 筆、刑案 2 筆、一般 3 筆、敘獎 4 筆")
            labels = "\n".join(x.text() for x in dlg.findChildren(QLabel))
            self.assertIn("敘獎 4 筆", labels)
            dlg.close()
        finally:
            os.remove(path)


if __name__ == "__main__":
    unittest.main()
