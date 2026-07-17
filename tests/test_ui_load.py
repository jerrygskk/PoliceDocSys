# -*- coding: utf-8 -*-
"""layouts/*.ui 全檔載入 smoke test（offscreen，不開視窗）。

保護對象：
  - .ui 檔改壞（margin 寫法錯、property 打錯、XML 壞掉）→ QUiLoader 回 None
  - 主視窗版面 centralwidget 物件名鐵約定（DEVELOPER §2 踩雷表 #1）
新增 LayoutN.ui 會被 glob 自動涵蓋，不需改本檔。
"""
import glob
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import (
    QApplication, QWidget, QDateEdit, QLabel, QLineEdit, QPushButton, QListWidget,
    QTableWidget,
)
import res.resources_rc          # 註冊 qrc（.ui 內引用 :/ 資源），勿刪
from ui_utils import loadUi

_app = QApplication.instance() or QApplication([])

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_LAYOUT_DIR = os.path.join(_ROOT, "layouts")


class TestUiLoad(unittest.TestCase):

    def _ui_files(self):
        return sorted(glob.glob(os.path.join(_LAYOUT_DIR, "*.ui")))

    def test_glob_finds_files(self):
        # 防呆：glob 到空清單會讓整組測試虛假通過
        self.assertGreaterEqual(len(self._ui_files()), 11)  # Layout1~10 + main_menu

    def test_all_ui_files_load(self):
        for path in self._ui_files():
            with self.subTest(ui=os.path.basename(path)):
                w = loadUi(path)
                self.assertIsNotNone(
                    w, f"{os.path.basename(path)} 載入失敗（QUiLoader 回 None）")
                w.deleteLater()

    def test_layout_files_have_centralwidget(self):
        # 只驗主視窗版面（Layout*.ui）；main_menu.ui 是 dialog 型不適用
        for path in self._ui_files():
            name = os.path.basename(path)
            if not name.startswith("Layout"):
                continue
            with self.subTest(ui=name):
                w = loadUi(path)
                self.assertIsNotNone(w)
                self.assertIsNotNone(w.findChild(QWidget, "centralwidget"),
                                     f"{name} 缺 centralwidget（物件名必須全小寫）")
                w.deleteLater()

    def test_reward_layout_has_required_controls(self):
        path = os.path.join(_LAYOUT_DIR, "Layout9.ui")
        w = loadUi(path)
        self.assertIsNotNone(w)
        required = (
            (QDateEdit, "reward_date"),
            (QLineEdit, "reward_reason"),
            (QLineEdit, "reward_recipients"),
            (QPushButton, "btn_reward_submit"),
            (QPushButton, "btn_reward_clear"),
            (QListWidget, "reward_personnel_list"),
            (QTableWidget, "reward_tableWidget"),
        )
        for cls, name in required:
            with self.subTest(control=name):
                self.assertIsNotNone(w.findChild(cls, name))
        table = w.findChild(QTableWidget, "reward_tableWidget")
        self.assertEqual(table.columnCount(), 5)
        reward_date = w.findChild(QDateEdit, "reward_date")
        self.assertEqual(reward_date.minimumWidth(), 300)
        self.assertEqual(reward_date.maximumWidth(), 300)
        self.assertEqual(reward_date.minimumHeight(), 36)
        self.assertEqual(reward_date.maximumHeight(), 36)
        for name in ("reward_reason", "reward_recipients"):
            field = w.findChild(QLineEdit, name)
            self.assertEqual(field.minimumWidth(), 500)
            self.assertEqual(field.maximumWidth(), 500)
        self.assertEqual(w.findChild(QLineEdit, "reward_reason").placeholderText(),
                         "請輸入敘獎事由")
        self.assertEqual(w.findChild(QLineEdit, "reward_recipients").placeholderText(),
                         "請輸入或點選右側候選人員")
        root_css = w.findChild(QWidget, "centralwidget").styleSheet().lower()
        self.assertIn("background-color", root_css)
        self.assertIn("#ffffff", root_css)
        self.assertIn("color", root_css)
        self.assertIn("#000000", root_css)
        w.deleteLater()

    def test_ticket_layout_has_approved_placeholder(self):
        path = os.path.join(_LAYOUT_DIR, "Layout10.ui")
        w = loadUi(path)
        self.assertIsNotNone(w)
        labels = w.findChildren(QLabel)
        self.assertEqual(
            [label.text() for label in labels],
            ["▲ 罰單登錄", "本功能建置中，將於後續版本提供。"],
        )
        root_css = w.findChild(QWidget, "centralwidget").styleSheet().lower()
        self.assertIn("background-color", root_css)
        self.assertIn("#ffffff", root_css)
        self.assertIn("color", root_css)
        self.assertIn("#000000", root_css)
        w.deleteLater()


if __name__ == "__main__":
    unittest.main()
