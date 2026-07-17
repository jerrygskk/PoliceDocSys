"""ui_utils/status.py 純邏輯單元測試（逾期計算 + 狀態顏色）。

calcOverdue 用 datetime.now()，故「剩餘/逾期/今日」分支一律用相對今天的日期
計算（today±N），不寫死絕對日期，避免測試隔天就失效。
執行：專案根目錄下 `python -m unittest tests.test_status`
"""
import os
import sys
import unittest
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ui_utils.status import calcOverdue, colorForStatus

_FMT = "%Y-%m-%d"


def _d(offset_days):
    return (date.today() + timedelta(days=offset_days)).strftime(_FMT)


class TestCalcOverdue(unittest.TestCase):
    # ── 無限辦日期 = 免覆 ──────────────────────────────
    def test_no_deadline(self):
        self.assertEqual(calcOverdue("", ""), "免覆")
        self.assertEqual(calcOverdue(None, None), "免覆")
        self.assertEqual(calcOverdue("None", ""), "免覆")
        self.assertEqual(calcOverdue("nan", ""), "免覆")

    # ── 未發文：以今天為基準 ──────────────────────────
    def test_remaining_days(self):
        self.assertEqual(calcOverdue(_d(3), ""), "剩餘 3 日")

    def test_due_today(self):
        self.assertEqual(calcOverdue(_d(0), ""), "今日到期")

    def test_overdue_days(self):
        self.assertEqual(calcOverdue(_d(-5), ""), "逾期 5 日")

    # ── 已發文：以發文日 vs 限辦日比較（與今天無關）────
    def test_dispatched_on_time(self):
        self.assertEqual(calcOverdue("2026-06-10", "2026-06-10"), "已發文")
        self.assertEqual(calcOverdue("2026-06-10", "2026-06-08"), "已發文")

    def test_dispatched_overdue(self):
        self.assertEqual(
            calcOverdue("2026-06-10", "2026-06-13"), "已發文（逾期 3 日）")

    # ── 格式錯誤 ──────────────────────────────────────
    def test_bad_format(self):
        self.assertEqual(calcOverdue("2026/06/10", ""), "格式錯誤")
        self.assertEqual(calcOverdue("not-a-date", ""), "格式錯誤")


class TestColorForStatus(unittest.TestCase):
    def _name(self, status):
        c = colorForStatus(status)
        return c.name() if c is not None else None

    def test_overdue_red(self):
        self.assertEqual(self._name("逾期 5 日"), "#e74c3c")

    def test_today_orange(self):
        self.assertEqual(self._name("今日到期"), "#e67e22")

    def test_dispatched_green(self):
        self.assertEqual(self._name("已發文"), "#27ae60")

    def test_dispatched_overdue_orange(self):
        # 已發文但逾期 → 橘（非紅、非綠）
        self.assertEqual(self._name("已發文（逾期 3 日）"), "#e67e22")

    def test_no_color(self):
        self.assertIsNone(self._name("剩餘 3 日"))
        self.assertIsNone(self._name("免覆"))


if __name__ == "__main__":
    unittest.main()
