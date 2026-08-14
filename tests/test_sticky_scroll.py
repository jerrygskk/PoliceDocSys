# -*- coding: utf-8 -*-
"""預覽表黏底捲動公版（ui_utils/sticky_scroll.py）的狀態轉換測試（offscreen）。

保護對象（五個分頁共用這支公版，行為壞掉會同時影響登錄頁與瀏覽頁）：
  - 內容超過一頁時自動黏底並捲到最新一筆。
  - **任何手動捲動都要退出黏底**——不只滾輪與拖曳滑塊，點捲軸箭頭／軌道、
    鍵盤捲動也算。漏掉的話下次有新資料又被拉回底部，使用者剛找到的位置就沒了。
  - 列數變動造成的捲軸位移不是手動捲動，不得誤判成「使用者捲走了」。
  - 程式自己捲到底（黏底跟隨、⤓ 鈕）不得把黏底狀態關掉。
"""
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import (
    QAbstractSlider, QApplication, QTableWidget, QTableWidgetItem,
)

from ui_utils.sticky_scroll import attachStickyScroll

_app = QApplication.instance() or QApplication([])


class _StickyBase(unittest.TestCase):
    def setUp(self):
        self.table = QTableWidget(0, 1)
        self.table.resize(200, 120)          # 讓內容確實超過可視範圍
        self.table.show()
        self._addRows(40)
        self.btn = attachStickyScroll(self.table)
        self._settle()
        self.sb = self.table.verticalScrollBar()

    def tearDown(self):
        self.table.deleteLater()
        self._settle()

    def _addRows(self, n):
        for _ in range(n):
            r = self.table.rowCount()
            self.table.insertRow(r)
            self.table.setItem(r, 0, QTableWidgetItem(f"列 {r}"))

    def _settle(self):
        """讓 QTimer.singleShot(0, ...) 的延後動作真的跑到。"""
        for _ in range(3):
            _app.processEvents()

    @property
    def sticky(self):
        return self.btn.sticky_state["sticky"]


class TestStickyStartup(_StickyBase):

    def test_auto_sticks_to_bottom_when_scrollable(self):
        self.assertTrue(self.sticky)
        self.assertEqual(self.sb.value(), self.sb.maximum())


class TestManualScrollExitsSticky(_StickyBase):
    """每一種手動捲動路徑都要退出黏底。"""

    def test_scrollbar_arrow_exits_sticky(self):
        self.sb.triggerAction(QAbstractSlider.SliderSingleStepSub)
        self._settle()
        self.assertFalse(self.sticky)

    def test_scrollbar_track_page_exits_sticky(self):
        self.sb.triggerAction(QAbstractSlider.SliderPageStepSub)
        self._settle()
        self.assertFalse(self.sticky)

    def test_jump_to_top_exits_sticky(self):
        self.sb.triggerAction(QAbstractSlider.SliderToMinimum)
        self._settle()
        self.assertFalse(self.sticky)

    def test_position_kept_when_new_rows_arrive_after_manual_scroll(self):
        """退出黏底後新增資料不得把畫面拉走。"""
        self.sb.triggerAction(QAbstractSlider.SliderSingleStepSub)
        self._settle()
        pos = self.sb.value()
        self._addRows(20)
        self._settle()
        self.assertFalse(self.sticky)
        self.assertEqual(self.sb.value(), pos)


class TestPendingScrollRace(_StickyBase):
    """排程中的自動捲底不得蓋過稍後的手動捲動。"""

    def test_manual_scroll_wins_over_already_scheduled_autoscroll(self):
        # ① 新增列 → 排入「稍後捲到底」；② timer 還沒跑就手動捲走；
        # ③ timer 跑到時必須放棄捲底，否則使用者剛選好的位置被硬拉走。
        # ⚠️ 中間這次 processEvents 不可省：捲軸的 rangeChanged 要等事件迴圈才發出，
        # 少了它排程根本還沒進佇列，這條競態就沒被測到（看起來綠、其實沒驗）。
        self._addRows(20)
        _app.processEvents()
        self.assertLess(self.sb.value(), self.sb.maximum())   # 捲底仍在佇列裡

        self.sb.triggerAction(QAbstractSlider.SliderSingleStepSub)
        pos = self.sb.value()
        self.assertFalse(self.sticky)

        self._settle()                          # 舊排程在此執行
        self.assertFalse(self.sticky)
        self.assertEqual(self.sb.value(), pos)

    def test_manual_scroll_wins_over_first_auto_stick(self):
        """首次自動黏底的排程同樣要讓位（同一個競態，不同入口）。"""
        table = QTableWidget(0, 1)
        table.resize(200, 120)
        table.show()
        for _ in range(40):
            r = table.rowCount()
            table.insertRow(r)
            table.setItem(r, 0, QTableWidgetItem(f"列 {r}"))
        btn = attachStickyScroll(table)
        _app.processEvents()                     # 首次自動黏底成立，捲底排進佇列
        self.assertTrue(btn.sticky_state["sticky"])

        sb = table.verticalScrollBar()
        sb.triggerAction(QAbstractSlider.SliderToMinimum)   # 排程執行前先手動捲走
        for _ in range(3):
            _app.processEvents()

        self.assertFalse(btn.sticky_state["sticky"])
        self.assertEqual(sb.value(), sb.minimum())
        table.deleteLater()


class TestStickyKeptWhenNotManual(_StickyBase):

    def test_new_rows_keep_sticky_and_follow_bottom(self):
        self._addRows(20)
        self._settle()
        self.assertTrue(self.sticky)
        self.assertEqual(self.sb.value(), self.sb.maximum())

    def test_button_returns_to_bottom_and_resticks(self):
        self.sb.triggerAction(QAbstractSlider.SliderToMinimum)
        self._settle()
        self.assertFalse(self.sticky)

        self.btn.click()
        self._settle()
        self.assertTrue(self.sticky)
        self.assertEqual(self.sb.value(), self.sb.maximum())

    def test_table_rebuild_does_not_drop_sticky(self):
        """整表重建（瀏覽頁 _reload）捲軸會歸零，那不是使用者捲的。"""
        self.table.setRowCount(0)
        self._settle()
        self._addRows(40)
        self._settle()
        self.assertTrue(self.sticky)
        self.assertEqual(self.sb.value(), self.sb.maximum())


if __name__ == "__main__":
    unittest.main()
