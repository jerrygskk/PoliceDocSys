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
    QApplication, QWidget, QComboBox, QDateEdit, QLineEdit, QPushButton,
    QListWidget, QTableWidget, QVBoxLayout,
)
import res.resources_rc          # 註冊 qrc（.ui 內引用 :/ 資源），勿刪
from ui_utils import loadUi
from ui_utils.widgets import RecipientCombo

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
            (QLineEdit, "reward_reason"),
            (RecipientCombo, "reward_recipients"),   # 敘獎人員改為可編輯下拉
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
        self.assertIsNone(w.findChild(QDateEdit, "reward_date"))
        self.assertIsNone(w.findChild(QComboBox, "reward_sender"))
        # 事由（QLineEdit）／人員（RecipientCombo）欄保留可延展輸入寬度。
        for cls, name in ((QLineEdit, "reward_reason"),
                          (RecipientCombo, "reward_recipients")):
            field = w.findChild(cls, name)
            self.assertEqual(field.minimumWidth(), 220)
            self.assertEqual(field.maximumWidth(), 16777215)
            self.assertEqual(field.minimumHeight(), 36)
            self.assertEqual(field.maximumHeight(), 36)
        self.assertEqual(w.findChild(QLineEdit, "reward_reason").placeholderText(),
                         "請輸入敘獎事由")
        # 敘獎人員（RecipientCombo）的 placeholder 於 tab setup 時設在其 lineEdit，
        # 不在 .ui，故 raw 載入不檢查。
        root_css = w.findChild(QWidget, "centralwidget").styleSheet().lower()
        self.assertIn("background-color", root_css)
        self.assertIn("#ffffff", root_css)
        self.assertIn("color", root_css)
        self.assertIn("#000000", root_css)
        w.deleteLater()

    def test_reward_issue_layout_has_required_controls_and_no_inline_style(self):
        path = os.path.join(_LAYOUT_DIR, "Layout10.ui")
        w = loadUi(path)
        self.assertIsNotNone(w)
        required = (
            (QLineEdit, "lineEdit_reward_num"),
            (QPushButton, "btn_reward_input"),
            (QDateEdit, "reward_issue_date"),
            (QComboBox, "reward_issue_sender"),
            (QPushButton, "btn_reward_issue"),
            (QPushButton, "btn_reward_issue_clear"),
            (QTableWidget, "reward_issue_table"),
        )
        for cls, name in required:
            with self.subTest(control=name):
                self.assertIsNotNone(w.findChild(cls, name))
        table = w.findChild(QTableWidget, "reward_issue_table")
        self.assertEqual(table.columnCount(), 6)
        self.assertEqual(
            [table.horizontalHeaderItem(i).text() for i in range(6)],
            ["", "編號", "登錄日期", "發文日期", "敘獎事由", "敘獎人員"],
        )
        for cls, name in (
                (QDateEdit, "reward_issue_date"),
                (QComboBox, "reward_issue_sender")):
            field = w.findChild(cls, name)
            self.assertEqual(field.minimumWidth(), 220)
            self.assertEqual(field.maximumWidth(), 220)
            self.assertEqual(field.minimumHeight(), 36)
            self.assertEqual(field.maximumHeight(), 36)
        self.assertTrue(w.findChild(QComboBox, "reward_issue_sender").isEditable())
        root_css = w.findChild(QWidget, "centralwidget").styleSheet().lower()
        self.assertEqual(root_css, "")
        w.deleteLater()

    def test_reward_issue_layout_uses_same_default_outer_margins_as_dispatch(self):
        dispatch = loadUi(os.path.join(_LAYOUT_DIR, "Layout1.ui"))
        reward_issue = loadUi(os.path.join(_LAYOUT_DIR, "Layout10.ui"))
        self.assertIsNotNone(dispatch)
        self.assertIsNotNone(reward_issue)
        dispatch_layout = dispatch.findChild(QVBoxLayout, "mainVerticalLayout")
        reward_layout = reward_issue.findChild(QVBoxLayout, "mainVerticalLayout")
        self.assertEqual(reward_layout.contentsMargins(),
                         dispatch_layout.contentsMargins())
        dispatch.deleteLater()
        reward_issue.deleteLater()


if __name__ == "__main__":
    unittest.main()
