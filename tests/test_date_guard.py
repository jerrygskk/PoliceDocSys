# -*- coding: utf-8 -*-
"""日期防呆的門檻判斷（純邏輯，不開視窗）。

行為來源：2026-08-04 實際事故——某日發文日期的年份被誤改成隔年，當天 12 筆有 8 筆
寫成 2027，簽收表只印得出前 4 筆。門檻由維護者裁定：早於今日 1 天即提示、晚於今日
10 天才提示；查獲／受理日期只檢查往後那一側（往前本來就常態）。
"""
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QDate

import ui_utils.date_guard as date_guard
from ui_utils.date_guard import (
    FUTURE_GAP_DAYS, PAST_GAP_DAYS, dateGapDays, describeDateGap,
    needsDateConfirm)


TODAY = QDate(2026, 8, 4)


def _shift(days):
    return TODAY.addDays(days).toString("yyyy-MM-dd")


class TestDateGapDays(unittest.TestCase):
    def test_sign_convention(self):
        """晚於今日為正、早於今日為負——提示文字的方向字（早／晚）靠它決定。"""
        self.assertEqual(dateGapDays(_shift(3), today=TODAY), 3)
        self.assertEqual(dateGapDays(_shift(-3), today=TODAY), -3)
        self.assertEqual(dateGapDays(_shift(0), today=TODAY), 0)

    def test_accepts_qdate_and_string(self):
        self.assertEqual(dateGapDays(TODAY.addDays(5), today=TODAY), 5)

    def test_unparsable_returns_none_and_never_blocks(self):
        """空值／哨兵／壞格式一律回 None：發文結算模式送的就是空字串，不能被擋。"""
        for bad in (None, "", "   ", "2026/08/04", "not-a-date"):
            self.assertIsNone(dateGapDays(bad, today=TODAY), bad)
            self.assertFalse(needsDateConfirm(bad, today=TODAY), bad)


class TestThresholds(unittest.TestCase):
    def test_today_never_prompts(self):
        self.assertFalse(needsDateConfirm(_shift(0), today=TODAY))

    def test_one_day_earlier_prompts(self):
        """早於今日只要 1 天就問：往前是誤改最常見的方向。"""
        self.assertEqual(PAST_GAP_DAYS, 1)
        self.assertTrue(needsDateConfirm(_shift(-1), today=TODAY))
        self.assertTrue(needsDateConfirm(_shift(-30), today=TODAY))

    def test_future_prompts_only_from_threshold(self):
        """晚於今日 10 天內不問（可能是預定發文日），滿 10 天才問。"""
        self.assertEqual(FUTURE_GAP_DAYS, 10)
        self.assertFalse(needsDateConfirm(_shift(FUTURE_GAP_DAYS - 1), today=TODAY))
        self.assertTrue(needsDateConfirm(_shift(FUTURE_GAP_DAYS), today=TODAY))

    def test_year_typo_is_caught(self):
        """實際事故：年份被多加一年（+365 天）必須被抓到。"""
        self.assertTrue(needsDateConfirm("2027-08-04", today=TODAY))

    def test_future_only_field_ignores_past_but_keeps_same_future_threshold(self):
        """查獲／受理日期：往前多久都正常（案件受理常在數週前），
        往後的門檻與其他欄位相同。"""
        self.assertFalse(needsDateConfirm(_shift(-90), future_only=True, today=TODAY))
        self.assertFalse(
            needsDateConfirm(_shift(FUTURE_GAP_DAYS - 1), future_only=True, today=TODAY))
        self.assertTrue(
            needsDateConfirm(_shift(FUTURE_GAP_DAYS), future_only=True, today=TODAY))


class TestMessage(unittest.TestCase):
    def test_message_states_date_direction_and_gap(self):
        """提示要寫出日期本身與差距天數，使用者才看得出被改到哪一段。"""
        msg = describeDateGap("2027-08-04", "發文日期", today=TODAY)
        self.assertIn("2027-08-04", msg)
        self.assertIn("365 天之後", msg)

        msg = describeDateGap(_shift(-2), "收文日期", today=TODAY)
        self.assertIn("2 天之前", msg)


class TestConfirmScope(unittest.TestCase):
    """「本次已確認」以頁面為單位分開記，各頁各問一次。

    為什麼要分開：公文陳報、敘獎登錄、交辦單收文按下送出就直接寫、沒有內容確認
    視窗，日期誤改沒有第二道關卡。若各頁共用同一組記錄，在 A 頁確認過某日期後，
    B 頁的日期欄剛好被誤改成同一天就會靜默放行。
    """

    def setUp(self):
        date_guard.resetConfirmedDates()
        self._calls = []
        self._orig = date_guard.confirmBox
        date_guard.confirmBox = lambda *a, **kw: (self._calls.append(a), True)[1]
        self.addCleanup(setattr, date_guard, "confirmBox", self._orig)
        self.addCleanup(date_guard.resetConfirmedDates)

    def _ask(self, scope):
        return date_guard.confirmDateGap(
            _shift(FUTURE_GAP_DAYS), "發文日期", scope=scope, today=TODAY)

    def test_same_page_same_date_asks_once(self):
        """同頁連續登錄只問一次——每筆都問會被無視，反而失去提醒效果。"""
        self.assertTrue(self._ask("report"))
        self.assertTrue(self._ask("report"))
        self.assertEqual(len(self._calls), 1)

    def test_other_page_asks_again_despite_same_label_and_date(self):
        """欄位名稱與日期都相同，換一頁仍要再問一次。"""
        self._ask("report")
        self._ask("reward")
        self._ask("receive")
        self.assertEqual(len(self._calls), 3)

    def test_scope_defaults_to_label(self):
        """未指定 scope 時退回以欄位名稱當代號（舊行為）。"""
        date_guard.confirmDateGap(_shift(FUTURE_GAP_DAYS), "發文日期",
                                  today=TODAY)
        date_guard.confirmDateGap(_shift(FUTURE_GAP_DAYS), "發文日期",
                                  today=TODAY)
        self.assertEqual(len(self._calls), 1)


if __name__ == "__main__":
    unittest.main()
