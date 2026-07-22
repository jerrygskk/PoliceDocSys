# -*- coding: utf-8 -*-
"""Tab 4 敘獎發文選單文案與圖示資源契約。"""
import os
import unittest
import xml.etree.ElementTree as ET

from PySide6.QtCore import QResource
from PySide6.QtGui import QIcon
from PySide6.QtGui import QImage, QPainter
from PySide6.QtSvg import QSvgRenderer

import res.resources_rc  # noqa: F401 - 註冊 qrc 後驗證實際 QIcon 路徑


_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class TestRewardIssueMenuAssets(unittest.TestCase):

    def test_tab4_and_menu_tile_are_named_reward_issue(self):
        layout = ET.parse(os.path.join(_ROOT, "layouts", "Layout1.ui"))
        tab4 = layout.find(".//widget[@name='tab_ticket']/attribute[@name='title']/string")
        self.assertIsNotNone(tab4)
        self.assertEqual(tab4.text, "敘獎發文")

        menu = ET.parse(os.path.join(_ROOT, "layouts", "main_menu.ui"))
        tile = menu.find(".//widget[@name='btn_ticket']/property[@name='text']/string")
        self.assertIsNotNone(tile)
        self.assertEqual(tile.text, "敘獎發文")

    def test_ticket_menu_resource_is_reward_glyph_with_dispatch_palette_and_arrow(self):
        qrc = ET.parse(os.path.join(_ROOT, "res", "resources.qrc"))
        resource = qrc.find(".//file[@alias='menu/reward_issue.svg']")
        self.assertIsNotNone(resource)
        self.assertEqual(resource.text, "buttons/menu_reward_issue.svg")

        icon = ET.parse(os.path.join(_ROOT, "res", "buttons", "menu_reward_issue.svg")).getroot()
        self.assertEqual(icon.attrib.get("viewBox"), "0 0 512 512")
        self.assertEqual(icon.attrib.get("width"), "512")
        self.assertEqual(icon.attrib.get("height"), "512")
        self.assertEqual(icon.attrib.get("stroke"), "#4977b1")
        self.assertEqual(icon.attrib.get("stroke-width"), "36")
        self.assertIsNotNone(icon.find(".//*[@id='reward-glyph']"))
        self.assertIsNotNone(icon.find(".//*[@id='outbound-arrow']"))
        self.assertFalse(any("transform" in element.attrib for element in icon.iter()))

        # main.py 的 QIcon 路徑必須由 qrc 真正提供，避免只更新磁碟 SVG。
        compiled = QResource(":/menu/reward_issue.svg")
        self.assertTrue(compiled.isValid())
        self.assertFalse(QIcon(":/menu/reward_issue.svg").isNull())
        with open(os.path.join(_ROOT, "res", "buttons", "menu_reward_issue.svg"), "rb") as fh:
            self.assertEqual(
                bytes(compiled.data()).replace(b"\r\n", b"\n"),
                fh.read().replace(b"\r\n", b"\n"),
            )

        renderer = QSvgRenderer(bytes(compiled.data()))
        self.assertTrue(renderer.isValid())
        image = QImage(512, 512, QImage.Format_ARGB32)
        image.fill(0)
        painter = QPainter(image)
        renderer.render(painter)
        painter.end()
        occupied = [
            (x, y) for y in range(image.height()) for x in range(image.width())
            if image.pixelColor(x, y).alpha() > 0
        ]
        self.assertTrue(occupied)
        xs, ys = zip(*occupied)
        self.assertGreater(min(xs), 16)
        self.assertGreater(min(ys), 16)
        self.assertLess(max(xs), 495)
        self.assertLess(max(ys), 495)


if __name__ == "__main__":
    unittest.main()
