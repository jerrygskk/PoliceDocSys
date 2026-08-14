# -*- coding: utf-8 -*-
"""預覽表欄寬公版（ui_utils/table.py 的 autoResizeTable）在「隱藏欄」情境下的行為。

保護對象（資料庫瀏覽的精簡／完整切換是把完整模式的欄位 setColumnHidden，
只有這裡會同時出現隱藏欄與伸縮欄，三個 bug 都是實機截圖才抓到的）：
  - 精簡模式：隱藏欄不得計入版面加總，否則「空間不夠」誤判成立，伸縮欄縮回
    固定值，表格右側留一片空白、主旨反而被省略成 ...。
  - 切回完整模式：隱藏欄要照樣量寬、照樣設值，否則停在 Qt 預設 80px 而整排切字。
  - setColumnHidden 會以寬度 0 送出 sectionResized，不得被當成使用者拉欄寬；
    誤判成 user_resized 會讓 autoResizeTable 從此直接 return，欄寬永遠不再更新。
  - 塞不下時本來就會出現水平捲軸，不得再把超出量倒扣在伸縮欄上（會被壓到下限）。
"""
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QTableWidget, QTableWidgetItem

from ui_utils.table import setupPreviewTable, autoResizeTable

_app = QApplication.instance() or QApplication([])

# 取交辦單瀏覽表的形狀：col 3 伸縮，後四欄僅完整模式顯示
_COLS = [
    ("", 32), ("編號", 64), ("承辦人", 80), ("交辦事由", 240), ("業務組", 80),
    ("狀態", 200), ("限辦日期", 140), ("發文日期", 140),
    ("收文日期", 140), ("收文人員", 120), ("送文人員", 120), ("紀錄時間", 240),
]
_STRETCH = 3
_SLIM_HIDDEN = range(8, 12)


class TableColWidthTest(unittest.TestCase):
    def _build(self, width):
        table = QTableWidget()
        table.resize(width, 600)
        setupPreviewTable(
            table, [h for h, _ in _COLS], stretch_col=_STRETCH,
            fixed_overrides={h: w for h, w in _COLS if h}, cap_mode=False,
        )
        table.setRowCount(1)
        for i in range(len(_COLS)):
            table.setItem(0, i, QTableWidgetItem("測試"))
        table.show()
        # 實機在 500ms 後才設 init_done；測試不等 timer，直接進入該狀態
        table.setProperty("init_done", True)
        self.addCleanup(table.deleteLater)
        return table

    @staticmethod
    def _setSlim(table, slim):
        for i in _SLIM_HIDDEN:
            table.setColumnHidden(i, slim)
        autoResizeTable(table)

    @staticmethod
    def _visibleSum(table):
        return sum(table.columnWidth(c) for c in range(table.columnCount())
                   if not table.isColumnHidden(c))

    def test_slim_stretch_fills_viewport(self):
        """精簡模式：伸縮欄吃掉剩餘寬度，總寬填滿且不超出 viewport。"""
        table = self._build(1800)
        self._setSlim(table, True)
        available = table.viewport().width()
        self.assertGreater(table.columnWidth(_STRETCH), 240,
                           "伸縮欄應撐大，而非停在固定值")
        self.assertLessEqual(self._visibleSum(table), available)
        self.assertGreater(self._visibleSum(table), available * 0.95,
                           "右側不應留白")

    def test_hidden_cols_keep_fixed_width_when_shown(self):
        """切回完整模式：原本隱藏的欄要拿到自己的固定寬，不得停在預設 80。"""
        table = self._build(1800)
        self._setSlim(table, True)
        self._setSlim(table, False)
        for idx in _SLIM_HIDDEN:
            self.assertEqual(table.columnWidth(idx), _COLS[idx][1],
                             f"第 {idx} 欄（{_COLS[idx][0]}）寬度不對")

    def test_hiding_cols_is_not_user_resize(self):
        """setColumnHidden 不得被當成使用者拉欄寬（否則自動調寬永久失效）。"""
        table = self._build(1800)
        self._setSlim(table, True)
        self.assertFalse(table.property("user_resized"))
        self._setSlim(table, False)
        self.assertFalse(table.property("user_resized"))

    def test_real_drag_still_marks_user_resized(self):
        """使用者真的拉欄寬仍要被記住，之後不再自動覆蓋。"""
        table = self._build(1800)
        self._setSlim(table, True)
        table.setColumnWidth(2, 200)
        self.assertTrue(table.property("user_resized"))
        autoResizeTable(table)
        self.assertEqual(table.columnWidth(2), 200)

    def test_overflow_keeps_stretch_at_fixed_width(self):
        """完整模式塞不下時出現水平捲軸即可，伸縮欄不得被倒扣到下限。"""
        table = self._build(1400)
        self._setSlim(table, True)
        self._setSlim(table, False)
        self.assertEqual(table.columnWidth(_STRETCH), 240)

    def test_toggle_round_trip_is_stable(self):
        """精簡→完整→精簡：欄寬要回到原本的精簡結果，不殘留。"""
        table = self._build(1800)
        self._setSlim(table, True)
        before = [table.columnWidth(c) for c in range(8)]
        self._setSlim(table, False)
        self._setSlim(table, True)
        self.assertEqual([table.columnWidth(c) for c in range(8)], before)


if __name__ == "__main__":
    unittest.main()
