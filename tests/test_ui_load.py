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
    QApplication, QWidget, QComboBox, QDateEdit, QLabel, QLineEdit, QPushButton,
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
        # Layout1~9、11 ＋ main_menu（Layout10＝敘獎發文頁移除後的空號）
        self.assertGreaterEqual(len(self._ui_files()), 11)

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
            (QComboBox, "reward_sender"),
            (QLabel, "reward_sender_hint"),
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
        # 發文日期／發文人員兩欄固定寬（比照陳報頁），送文者模式填、發文結算模式反灰。
        for cls, name in ((QDateEdit, "reward_date"),
                          (QComboBox, "reward_sender")):
            field = w.findChild(cls, name)
            self.assertEqual(field.minimumWidth(), 220)
            self.assertEqual(field.maximumWidth(), 220)
            self.assertEqual(field.minimumHeight(), 36)
            self.assertEqual(field.maximumHeight(), 36)
        self.assertTrue(w.findChild(QComboBox, "reward_sender").isEditable())
        # 標籤欄固定 90×36（與 Layout11 罰單登錄同骨架，欄位起始 x 才會對齊）
        for name in ("label_date", "label_sender", "label_reason",
                     "label_recipients"):
            lbl = w.findChild(QLabel, name)
            self.assertEqual(lbl.minimumWidth(), 90, name)
            self.assertEqual(lbl.maximumWidth(), 90, name)
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

    def test_ticket_layout_has_required_controls(self):
        from PySide6.QtWidgets import QGroupBox
        path = os.path.join(_LAYOUT_DIR, "Layout11.ui")
        w = loadUi(path)
        self.assertIsNotNone(w)
        required = (
            (QComboBox, "ticket_sender"),
            (QLabel, "ticket_sender_hint"),
            (QComboBox, "ticket_issuer"),
            (QPushButton, "ticket_clear_issuer"),
            (QLineEdit, "ticket_no"),
            (QTableWidget, "ticket_table"),
            (QPushButton, "ticket_add"),
            (QGroupBox, "ticket_candidates"),
            (QListWidget, "ticket_candidates_list"),
        )
        for cls, name in required:
            with self.subTest(control=name):
                self.assertIsNotNone(w.findChild(cls, name))
        table = w.findChild(QTableWidget, "ticket_table")
        self.assertEqual(
            [table.horizontalHeaderItem(i).text()
             for i in range(table.columnCount())],
            ["", "編號", "登錄日期", "發文日期", "罰單編號", "開立人員", ""],
        )
        # 兩個人員下拉皆可打字（completer 篩選），高度與其他頁一致（LAY-6）；
        # 人員欄固定 220（與敘獎登錄同骨架），長輸入欄才留伸縮。
        for name in ("ticket_sender", "ticket_issuer"):
            combo = w.findChild(QComboBox, name)
            self.assertTrue(combo.isEditable())
            self.assertEqual(combo.minimumWidth(), 220)
            self.assertEqual(combo.maximumWidth(), 220)
            self.assertEqual(combo.minimumHeight(), 36)
            self.assertEqual(combo.maximumHeight(), 36)
        for name in ("lbl_ticket_sender", "lbl_ticket_issuer", "lbl_ticket_no"):
            lbl = w.findChild(QLabel, name)
            self.assertEqual(lbl.minimumWidth(), 90, name)
            self.assertEqual(lbl.maximumWidth(), 90, name)
        # 罰單編號固定 546＝敘獎登錄「發文人員」下拉的右緣（見 Layout11 註解）
        ticket_no = w.findChild(QLineEdit, "ticket_no")
        self.assertEqual(ticket_no.minimumWidth(), 546)
        self.assertEqual(ticket_no.maximumWidth(), 546)
        root_css = w.findChild(QWidget, "centralwidget").styleSheet().lower()
        self.assertIn("background-color", root_css)
        self.assertIn("#ffffff", root_css)
        self.assertIn("#000000", root_css)
        w.deleteLater()

    def test_reward_and_ticket_forms_share_column_skeleton(self):
        """敘獎登錄與罰單登錄的表單骨架必須對齊（實機截圖比對過的回歸）。

        兩頁同寬時：主欄位起始 x 相同、長輸入欄右緣相同、提示條都不撐滿。
        ⚠️ 必須 show() 後再量，未顯示的 widget 量不到真實寬度（LAY-8）。
        """
        reward = loadUi(os.path.join(_LAYOUT_DIR, "Layout9.ui"))
        ticket = loadUi(os.path.join(_LAYOUT_DIR, "Layout11.ui"))
        self.assertIsNotNone(reward)
        self.assertIsNotNone(ticket)
        try:
            for w in (reward, ticket):
                # 寬度須大於兩頁的 layout 最小寬（敘獎 row0 欄位多、最小寬較大），
                # 否則視窗停在最小寬、量到的是「還沒開始伸縮」的假結果。
                w.resize(1400, 700)
                w.show()
            _app.processEvents()

            r_first = reward.findChild(QDateEdit, "reward_date")
            t_first = ticket.findChild(QComboBox, "ticket_sender")
            self.assertEqual(r_first.x(), t_first.x(), "主欄位起始 x 未對齊")

            r_long = reward.findChild(QLineEdit, "reward_reason")
            t_long = ticket.findChild(QLineEdit, "ticket_no")
            self.assertEqual(r_long.x(), t_long.x(), "長輸入欄起始 x 未對齊")
            self.assertEqual(r_long.geometry().right(),
                             t_long.geometry().right(), "長輸入欄右緣未對齊")

            # 長輸入欄右緣＝敘獎登錄「發文人員」下拉的右緣
            r_sender = reward.findChild(QComboBox, "reward_sender")
            self.assertEqual(r_long.geometry().right(),
                             r_sender.geometry().right(),
                             "長輸入欄右緣未對齊發文人員下拉")

            # 提示條依文字寬度，不得被拉寬撐滿整列
            for w, name in ((reward, "reward_sender_hint"),
                            (ticket, "ticket_sender_hint")):
                hint = w.findChild(QLabel, name)
                self.assertLessEqual(hint.width(), hint.sizeHint().width() + 2,
                                     f"{name} 被撐寬了，應依文字寬度")
        finally:
            for w in (reward, ticket):
                w.close()
                w.deleteLater()


if __name__ == "__main__":
    unittest.main()
