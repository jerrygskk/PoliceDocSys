# -*- coding: utf-8 -*-
"""程式固定淺色 palette，Windows 深色模式下文字仍看得見（PITFALLS QSS-9）。"""
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication, QTableWidget, QTableWidgetItem

from lib.theme import APPLE_STYLE, TEXT_COLOR, apply_light_palette
from ui_utils.table import setupPreviewTable


_app = QApplication.instance() or QApplication([])


class LightPaletteTest(unittest.TestCase):
    def setUp(self):
        self._orig_pal = _app.palette()
        self._orig_ss = _app.styleSheet()

    def tearDown(self):
        _app.setPalette(self._orig_pal)
        _app.setStyleSheet(self._orig_ss)

    def test_palette_roles_are_light(self):
        apply_light_palette(_app)
        pal = _app.palette()
        self.assertEqual(pal.color(QPalette.Text).name(), TEXT_COLOR)
        self.assertEqual(pal.color(QPalette.WindowText).name(), TEXT_COLOR)
        self.assertEqual(pal.color(QPalette.Base).name(), "#ffffff")

    def test_table_text_visible_under_simulated_dark_mode(self):
        """模擬深色模式（系統文字色變白）後套公版，預覽表格文字須畫成深色。"""
        dark = QPalette(_app.palette())
        for role in (QPalette.Text, QPalette.WindowText):
            dark.setColor(role, QColor("white"))
        _app.setPalette(dark)
        apply_light_palette(_app)
        _app.setStyleSheet(APPLE_STYLE)

        table = QTableWidget(1, 1)
        setupPreviewTable(table, ["欄"])
        table.setItem(0, 0, QTableWidgetItem("█████"))
        table.clearSelection()
        table.resize(300, 120)
        table.show()
        _app.processEvents()
        img = table.viewport().grab().toImage()
        rect = table.visualItemRect(table.item(0, 0))
        darkest = min(
            max(c.red(), c.green(), c.blue())
            for x in range(rect.left(), rect.right(), 2)
            for y in range(rect.top(), rect.bottom(), 2)
            for c in [img.pixelColor(x, y)]
        )
        table.close()
        self.assertLessEqual(darkest, 100)


if __name__ == "__main__":
    unittest.main()
