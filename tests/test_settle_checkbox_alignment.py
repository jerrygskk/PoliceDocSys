# -*- coding: utf-8 -*-
"""結算預覽表表頭核取方塊繪製與對齊測試（offscreen）。"""
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QRect, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QCheckBox

from lib.theme import APPLE_STYLE
from ui_utils.settle_dialog import _DocTable


_app = QApplication.instance() or QApplication([])


class TestSettleCheckboxAlignment(unittest.TestCase):
    def test_header_checkbox_is_painted_without_overlay_widget(self):
        table = _DocTable()
        try:
            header = table.horizontalHeader()
            self.assertEqual(header.findChildren(QCheckBox), [])
            self.assertFalse(hasattr(table, "_chk_all_cont"))
        finally:
            table.close()
            table.deleteLater()

    def test_header_indicator_center_matches_first_section_center(self):
        old_style = _app.styleSheet()
        _app.setStyleSheet(APPLE_STYLE)
        table = _DocTable()
        try:
            table.resize(800, 300)
            table.show()
            _app.processEvents()

            header = table.horizontalHeader()
            section_rect = QRect(
                header.sectionViewportPosition(table.COL_CHK),
                0,
                header.sectionSize(table.COL_CHK),
                header.height(),
            )
            self.assertEqual(
                header.indicatorRect(table.COL_CHK).center(),
                section_rect.center(),
            )
        finally:
            table.close()
            table.deleteLater()
            _app.setStyleSheet(old_style)

    def test_clicking_first_header_section_emits_select_all_click(self):
        table = _DocTable()
        try:
            table.resize(800, 300)
            table.show()
            _app.processEvents()

            header = table.horizontalHeader()
            clicks = []
            header.clicked.connect(clicks.append)
            QTest.mouseClick(
                header.viewport(),
                Qt.LeftButton,
                pos=header.indicatorRect(table.COL_CHK).center(),
            )

            self.assertEqual(clicks, [True])
        finally:
            table.close()
            table.deleteLater()


if __name__ == "__main__":
    unittest.main()
