# -*- coding: utf-8 -*-
"""簽收表標題設定（db_utils.printTitle / printTitlesUnset）純邏輯測試。

受測模組 import 時會載入 PySide6（db_utils 依賴），故執行環境需裝 PySide6。
"""
import os
import sys
import sqlite3
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from lib import db_utils


class TestPrintTitles(unittest.TestCase):
    def setUp(self):
        fd, self.db = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        conn = sqlite3.connect(self.db)
        conn.execute("CREATE TABLE App_Settings(key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        conn.commit(); conn.close()

    def tearDown(self):
        os.remove(self.db)

    def test_default_when_unset(self):
        # 未設定 → 回 ○○ 預設
        self.assertEqual(db_utils.printTitle(self.db, "task"),
                         db_utils.PRINT_TITLE_DEFAULTS["print_title_task"])
        self.assertIn("○○", db_utils.printTitle(self.db, "crim"))
        self.assertEqual(db_utils.printTitle(self.db, "note"),
                         db_utils.PRINT_TITLE_DEFAULTS["print_note_current"])

    def test_returns_stored_value(self):
        db_utils.setSetting(self.db, "print_title_task", "中山分局交辦單發文簽收表")
        self.assertEqual(db_utils.printTitle(self.db, "task"),
                         "中山分局交辦單發文簽收表")

    def test_empty_stored_falls_back_to_default(self):
        # 存空字串＝未設定 → 仍回預設（列印不致空白）
        db_utils.setSetting(self.db, "print_title_gen", "")
        self.assertEqual(db_utils.printTitle(self.db, "gen"),
                         db_utils.PRINT_TITLE_DEFAULTS["print_title_gen"])

    def test_bad_which(self):
        self.assertEqual(db_utils.printTitle(self.db, "nope"), "")

    def test_unset_flag_true_when_any_blank(self):
        # 全未設定 → True
        self.assertTrue(db_utils.printTitlesUnset(self.db))
        # 設了三個、註記仍空 → 仍 True
        db_utils.setSetting(self.db, "print_title_task", "A署交辦單發文簽收表")
        db_utils.setSetting(self.db, "print_title_crim", "A署刑案陳報單發文簽收表")
        db_utils.setSetting(self.db, "print_title_gen",  "A署一般陳報單發文簽收表")
        self.assertTrue(db_utils.printTitlesUnset(self.db))

    def test_unset_flag_false_when_all_set(self):
        for key in db_utils.PRINT_TITLE_DEFAULTS:
            db_utils.setSetting(self.db, key, "已設定值")
        self.assertFalse(db_utils.printTitlesUnset(self.db))


if __name__ == "__main__":
    unittest.main()
