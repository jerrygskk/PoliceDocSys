"""閒置逾時設定（lib/db_utils 閒置區塊）純邏輯單元測試（暫存 sqlite，無 GUI）。

涵蓋：
  - parseIdleMinutes：合法值、非數字、超出範圍、空白 → 預設保底
  - getIdleTimeoutsMs：未設定走預設、設定後 round-trip、壞值走預設
執行：專案根目錄下 `python -m unittest tests.test_idle_timeouts`
"""
import os
import sys
import sqlite3
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lib import db_schema
from lib.db_utils import (
    parseIdleMinutes, getIdleTimeoutsMs, setSetting,
    IDLE_TIMEOUT_KEYS, IDLE_TIMEOUT_DEFAULTS,
)


class TestParseIdleMinutes(unittest.TestCase):
    def test_valid_int(self):
        self.assertEqual(parseIdleMinutes("logout", "15"), 15.0)

    def test_valid_float(self):
        self.assertEqual(parseIdleMinutes("close", "14.5"), 14.5)

    def test_valid_with_spaces(self):
        self.assertEqual(parseIdleMinutes("close", " 9.5 "), 9.5)

    def test_non_numeric_falls_back(self):
        self.assertEqual(parseIdleMinutes("logout", "abc"),
                         IDLE_TIMEOUT_DEFAULTS["logout"])

    def test_empty_falls_back(self):
        self.assertEqual(parseIdleMinutes("close", ""),
                         IDLE_TIMEOUT_DEFAULTS["close"])

    def test_none_falls_back(self):
        self.assertEqual(parseIdleMinutes("logout", None),
                         IDLE_TIMEOUT_DEFAULTS["logout"])

    def test_below_range_falls_back(self):
        self.assertEqual(parseIdleMinutes("close", "0.4"),
                         IDLE_TIMEOUT_DEFAULTS["close"])

    def test_above_range_falls_back(self):
        self.assertEqual(parseIdleMinutes("logout", "999"),
                         IDLE_TIMEOUT_DEFAULTS["logout"])

    def test_boundaries_valid(self):
        self.assertEqual(parseIdleMinutes("logout", "1"), 1.0)
        self.assertEqual(parseIdleMinutes("close", "60"), 60.0)

    def test_zero_means_disabled(self):
        # 0 為合法值＝停用該機制（不退回預設）
        self.assertEqual(parseIdleMinutes("logout", "0"), 0.0)
        self.assertEqual(parseIdleMinutes("close", "0"), 0.0)
        self.assertEqual(parseIdleMinutes("close", "0.0"), 0.0)

    def test_between_zero_and_one_falls_back(self):
        # 0 與下限之間（如 0.5）非合法值 → 退回預設
        self.assertEqual(parseIdleMinutes("close", "0.5"),
                         IDLE_TIMEOUT_DEFAULTS["close"])

    def test_negative_falls_back(self):
        self.assertEqual(parseIdleMinutes("logout", "-5"),
                         IDLE_TIMEOUT_DEFAULTS["logout"])


class TestGetIdleTimeoutsMs(unittest.TestCase):
    def setUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        conn = sqlite3.connect(self.db_path)
        db_schema.applySchema(conn)
        conn.commit()
        conn.close()

    def tearDown(self):
        os.remove(self.db_path)

    def test_unset_returns_defaults(self):
        logout_ms, close_ms = getIdleTimeoutsMs(self.db_path)
        self.assertEqual(logout_ms, int(IDLE_TIMEOUT_DEFAULTS["logout"] * 60000))
        self.assertEqual(close_ms, int(IDLE_TIMEOUT_DEFAULTS["close"] * 60000))

    def test_roundtrip(self):
        setSetting(self.db_path, IDLE_TIMEOUT_KEYS["logout"], "5")
        setSetting(self.db_path, IDLE_TIMEOUT_KEYS["close"], "9.5")
        logout_ms, close_ms = getIdleTimeoutsMs(self.db_path)
        self.assertEqual(logout_ms, 5 * 60000)
        self.assertEqual(close_ms, int(9.5 * 60000))

    def test_zero_roundtrip_disabled(self):
        # 兩機制皆設 0（停用）→ 回 0 ms，main.py 據此不啟動計時器
        setSetting(self.db_path, IDLE_TIMEOUT_KEYS["logout"], "0")
        setSetting(self.db_path, IDLE_TIMEOUT_KEYS["close"], "0")
        self.assertEqual(getIdleTimeoutsMs(self.db_path), (0, 0))

    def test_bad_values_fall_back(self):
        setSetting(self.db_path, IDLE_TIMEOUT_KEYS["logout"], "not-a-number")
        setSetting(self.db_path, IDLE_TIMEOUT_KEYS["close"], "-3")
        logout_ms, close_ms = getIdleTimeoutsMs(self.db_path)
        self.assertEqual(logout_ms, int(IDLE_TIMEOUT_DEFAULTS["logout"] * 60000))
        self.assertEqual(close_ms, int(IDLE_TIMEOUT_DEFAULTS["close"] * 60000))

    def test_missing_db_returns_defaults(self):
        # 檔案不存在／不可讀 → 不拋例外、走預設（getConn 會建新空檔，
        # 但 App_Settings 表不存在時 getSetting 會拋 → 走 except 保底）
        bogus = self.db_path + ".nope"
        try:
            logout_ms, close_ms = getIdleTimeoutsMs(bogus)
        finally:
            if os.path.exists(bogus):
                os.remove(bogus)
        self.assertEqual(logout_ms, int(IDLE_TIMEOUT_DEFAULTS["logout"] * 60000))
        self.assertEqual(close_ms, int(IDLE_TIMEOUT_DEFAULTS["close"] * 60000))


if __name__ == "__main__":
    unittest.main()
