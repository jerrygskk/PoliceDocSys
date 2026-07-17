import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QDate

from ui_utils.widgets import (
    normalizeDateText, classifyNullableDate, NullableDateEdit,
)

_app = QApplication.instance() or QApplication([])


class TestNormalizeDateText(unittest.TestCase):
    """輸入正規化成 yyyy-MM-dd（純邏輯）。"""

    def test_eight_digits(self):
        self.assertEqual(normalizeDateText("20250130"), "2025-01-30")

    def test_dashed_zero_pad(self):
        self.assertEqual(normalizeDateText("2025-1-3"), "2025-01-03")
        self.assertEqual(normalizeDateText("2025-01-30"), "2025-01-30")

    def test_mixed_year_dash_fourdigits(self):
        # 年-四碼（使用者回報的 2026-0125）→ 2026-01-25
        self.assertEqual(normalizeDateText("2026-0125"), "2026-01-25")
        self.assertEqual(normalizeDateText("2026/01/25"), "2026-01-25")

    def test_strip_whitespace(self):
        self.assertEqual(normalizeDateText("  2025-01-30  "), "2025-01-30")

    def test_empty(self):
        self.assertEqual(normalizeDateText(""), "")
        self.assertEqual(normalizeDateText("   "), "")
        self.assertEqual(normalizeDateText(None), "")

    def test_passthrough_unrecognised(self):
        # 不認得的型態原樣回傳，交給 classify 判非法
        self.assertEqual(normalizeDateText("2"), "2")
        self.assertEqual(normalizeDateText("2025-13"), "2025-13")
        self.assertEqual(normalizeDateText("abc"), "abc")


class TestClassifyNullableDate(unittest.TestCase):
    """空白／合法／非法三態判定（純邏輯）。"""

    def test_empty(self):
        for t in ("", "   ", None):
            status, qd = classifyNullableDate(t)
            self.assertEqual(status, "empty")
            self.assertIsNone(qd)

    def test_valid_canonical(self):
        status, qd = classifyNullableDate("2025-01-30")
        self.assertEqual(status, "valid")
        self.assertEqual(qd, QDate(2025, 1, 30))

    def test_valid_eight_digits(self):
        status, qd = classifyNullableDate("20250130")
        self.assertEqual(status, "valid")
        self.assertEqual(qd, QDate(2025, 1, 30))

    def test_valid_short_form(self):
        status, qd = classifyNullableDate("2025-1-3")
        self.assertEqual(status, "valid")
        self.assertEqual(qd, QDate(2025, 1, 3))

    def test_invalid_partial(self):
        # 使用者清空後只敲一個 2：非空但非法 → invalid（不再被還原）
        self.assertEqual(classifyNullableDate("2")[0], "invalid")
        self.assertEqual(classifyNullableDate("2025-1")[0], "invalid")

    def test_invalid_out_of_range(self):
        self.assertEqual(classifyNullableDate("2025-13-40")[0], "invalid")
        self.assertEqual(classifyNullableDate("2025-02-30")[0], "invalid")

    def test_invalid_garbage(self):
        self.assertEqual(classifyNullableDate("abc")[0], "invalid")


class TestNullableDateEditWidget(unittest.TestCase):
    """元件對外 API 行為（offscreen，不開視窗）。"""

    def test_blank_state(self):
        w = NullableDateEdit()
        self.assertTrue(w.isBlank())
        self.assertFalse(w.hasError())
        self.assertIsNone(w.getDate())

    def test_clear_then_partial_is_error_not_revert(self):
        # 核心：清空後敲 2 → 非法亮錯、不還原成舊值
        w = NullableDateEdit()
        w.setDate(QDate(2025, 1, 30))
        self.assertEqual(w.text(), "2025-01-30")
        w.clear()
        w.setText("2")          # 模擬清空後手打一個字
        w.validateNow()         # 模擬離開欄位
        self.assertEqual(w.text(), "2")     # 沒有被還原成 2025-01-30
        self.assertTrue(w.hasError())
        self.assertIsNone(w.getDate())

    def test_manual_full_input(self):
        # 清空後完整手打 → 合法、正規化顯示
        w = NullableDateEdit()
        w.setText("20250130")
        w.validateNow()
        self.assertEqual(w.text(), "2025-01-30")
        self.assertFalse(w.hasError())
        self.assertEqual(w.getDate(), QDate(2025, 1, 30))

    def test_setdate_none_clears(self):
        w = NullableDateEdit()
        w.setDate(QDate(2024, 3, 5))
        w.setDate(None)
        self.assertTrue(w.isBlank())
        self.assertIsNone(w.getDate())

    def test_changed_signal_fires(self):
        w = NullableDateEdit()
        hits = []
        w.changed.connect(lambda: hits.append(1))
        w.setDate(QDate(2025, 1, 30))
        self.assertTrue(hits)


if __name__ == "__main__":
    unittest.main()
