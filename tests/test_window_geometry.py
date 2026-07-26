# -*- coding: utf-8 -*-
"""啟動時「依實際可用桌面收斂主視窗」的純函式測試（offscreen，不開視窗）。

保護對象：
  - 只在超出可用範圍時才收斂，沒超出不干預 .ui 預設值
  - 用的是 availableGeometry（已扣工作列），不是整個螢幕 geometry
  - 收斂後位置也要落在可用範圍內
"""
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QRect
from PySide6.QtWidgets import QApplication, QWidget

from lib.window_geometry import apply_startup_geometry, fit_window_to_available

_app = QApplication.instance() or QApplication([])


class FakeScreen:
    """假 QScreen：只提供 apply_startup_geometry 需要的 availableGeometry()。"""

    def __init__(self, available_rect, full_rect=None):
        self._available = available_rect
        self._full = full_rect if full_rect is not None else available_rect

    def availableGeometry(self):
        return self._available

    def geometry(self):
        return self._full


class FitWindowToAvailableTests(unittest.TestCase):

    def test_not_exceeding_stays_unchanged(self):
        win = QRect(0, 0, 1440, 780)
        avail = QRect(0, 0, 1920, 1032)
        self.assertEqual(fit_window_to_available(win, avail), win)

    def test_height_only_overflow_shrinks_height_keeps_width(self):
        win = QRect(0, 0, 1440, 800)
        avail = QRect(0, 0, 1920, 700)
        result = fit_window_to_available(win, avail)
        self.assertEqual(result.width(), 1440)
        self.assertEqual(result.height(), 700)
        self.assertEqual(result.x(), 0)
        self.assertEqual(result.y(), 0)

    def test_width_only_overflow_shrinks_width_keeps_height(self):
        win = QRect(0, 0, 1440, 780)
        avail = QRect(0, 0, 1200, 1032)
        result = fit_window_to_available(win, avail)
        self.assertEqual(result.width(), 1200)
        self.assertEqual(result.height(), 780)

    def test_both_overflow_shrink_both(self):
        win = QRect(0, 0, 1440, 780)
        avail = QRect(0, 0, 1024, 700)
        result = fit_window_to_available(win, avail)
        self.assertEqual(result.width(), 1024)
        self.assertEqual(result.height(), 700)
        self.assertEqual(result.x(), 0)
        self.assertEqual(result.y(), 0)

    def test_position_outside_available_gets_pulled_back(self):
        # 尺寸本身沒超出，但位置在可用範圍之外（如切到較小/位移的螢幕）
        win = QRect(1800, 900, 800, 600)
        avail = QRect(0, 0, 1920, 1032)
        result = fit_window_to_available(win, avail)
        self.assertEqual(result.width(), 800)
        self.assertEqual(result.height(), 600)
        self.assertLessEqual(result.x() + result.width(), avail.x() + avail.width())
        self.assertLessEqual(result.y() + result.height(), avail.y() + avail.height())
        self.assertGreaterEqual(result.x(), avail.x())
        self.assertGreaterEqual(result.y(), avail.y())

    def test_maintainer_scenario_1440x780_on_1032_available_height_untouched(self):
        # 維護者實測情境：可用高度 1032 實際像素，換算邏輯像素約 826（125% 縮放）
        win = QRect(0, 0, 1440, 780)
        avail = QRect(0, 0, 1536, 826)
        self.assertEqual(fit_window_to_available(win, avail), win)

    def test_small_laptop_1366x768_available_shrinks_window(self):
        # 筆電情境：可用範圍比視窗小，須收斂
        win = QRect(0, 0, 1440, 780)
        avail = QRect(0, 0, 1366, 728)  # 扣工作列後高度更小
        result = fit_window_to_available(win, avail)
        self.assertEqual(result.width(), 1366)
        self.assertEqual(result.height(), 728)


class ApplyStartupGeometryTests(unittest.TestCase):

    def test_uses_available_geometry_not_full_screen_geometry(self):
        """screen.geometry()（未扣工作列）比 availableGeometry() 大很多時，
        必須依 availableGeometry() 收斂，不能被較大的 geometry() 誤導成不用縮。"""
        window = QWidget()
        window.setGeometry(0, 0, 1440, 800)
        screen = FakeScreen(
            available_rect=QRect(0, 0, 1920, 700),   # 扣工作列後較小
            full_rect=QRect(0, 0, 1920, 1080),       # 整個螢幕（未扣工作列）
        )
        apply_startup_geometry(window, screen)
        self.assertEqual(window.geometry().height(), 700)

    def test_no_op_when_within_available_geometry(self):
        window = QWidget()
        window.setGeometry(0, 0, 1440, 780)
        screen = FakeScreen(available_rect=QRect(0, 0, 1920, 1032))
        before = QRect(window.geometry())
        apply_startup_geometry(window, screen)
        self.assertEqual(window.geometry(), before)


if __name__ == "__main__":
    unittest.main()
