# -*- coding: utf-8 -*-
"""可打字 QComboBox 提示文字顏色（attachComboHint）回歸測試。

背景（另見 PITFALLS QTW-7／QTW-12）：
  - 顏色曾掛在 `currentIndexChanged` 上判斷 `idx == 0`，但 `setupFilterCombo`
    裝的 `_onTextChanged` 在打字時會 `combo.blockSignals(True)` 重建清單，
    重建後 index 恆為 0，`currentIndexChanged` 打字期間結構上不會觸發，
    導致自訂輸入文字永遠顯示灰色——這個雷回歸過兩三次。
  - 本檔鎖定六種狀態的顏色，並專門釘住「不得依賴 currentIndexChanged」
    這條性質。
"""
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent
from PySide6.QtWidgets import QApplication, QComboBox

from lib.theme import HINT_COLOR, TEXT_COLOR
from ui_utils.widgets import attachComboHint, setupFilterCombo

_app = QApplication.instance() or QApplication([])

_HINT = "輸入或下拉選擇"
_DATA = [(1, "竊盜"), (2, "詐欺")]


def _make_combo():
    combo = QComboBox()
    combo.setEditable(True)
    setupFilterCombo(combo, _DATA)
    attachComboHint(combo, _HINT)
    return combo


def _color(combo):
    """從目前 stylesheet 取出 color 值。"""
    sheet = combo.styleSheet()
    # "QComboBox { color: #xxxxxx; }"
    marker = "color:"
    idx = sheet.index(marker) + len(marker)
    return sheet[idx:].split(";")[0].strip()


def _send_focus(combo, event_type):
    QApplication.sendEvent(combo, QEvent(event_type))
    QApplication.sendEvent(combo.lineEdit(), QEvent(event_type))
    _app.processEvents()


class TestAttachComboHint(unittest.TestCase):

    def test_initial_state_is_hint_and_gray(self):
        combo = _make_combo()
        self.assertEqual(combo.currentText(), _HINT)
        self.assertEqual(_color(combo), HINT_COLOR)

    def test_focus_in_clears_hint_and_turns_black(self):
        combo = _make_combo()
        _send_focus(combo, QEvent.FocusIn)
        self.assertEqual(combo.currentText(), "")
        self.assertEqual(_color(combo), TEXT_COLOR)

    def test_typing_custom_text_is_black(self):
        combo = _make_combo()
        _send_focus(combo, QEvent.FocusIn)
        combo.lineEdit().setText("電信詐欺")
        combo.lineEdit().textEdited.emit("電信詐欺")
        self.assertEqual(combo.currentText(), "電信詐欺")
        self.assertEqual(_color(combo), TEXT_COLOR)

    def test_typing_text_matching_list_item_is_black(self):
        combo = _make_combo()
        _send_focus(combo, QEvent.FocusIn)
        combo.lineEdit().setText("竊盜")
        combo.lineEdit().textEdited.emit("竊盜")
        self.assertEqual(combo.currentText(), "竊盜")
        self.assertEqual(_color(combo), TEXT_COLOR)

    def test_leaving_with_content_stays_black(self):
        combo = _make_combo()
        _send_focus(combo, QEvent.FocusIn)
        combo.lineEdit().setText("竊盜")
        combo.lineEdit().textEdited.emit("竊盜")
        _send_focus(combo, QEvent.FocusOut)
        self.assertEqual(combo.currentText(), "竊盜")
        self.assertEqual(_color(combo), TEXT_COLOR)

    def test_leaving_empty_restores_hint_and_gray(self):
        combo = _make_combo()
        _send_focus(combo, QEvent.FocusIn)
        _send_focus(combo, QEvent.FocusOut)
        self.assertEqual(combo.currentText(), _HINT)
        self.assertEqual(_color(combo), HINT_COLOR)

    def test_color_survives_blocksignals_rebuild_not_index_dependent(self):
        """釘住：顏色判斷不可依賴 currentIndexChanged。

        模擬 setupFilterCombo._onTextChanged 的 blockSignals 重建流程：
        重建後 index 恆為 0，若顏色邏輯依賴 currentIndexChanged 判斷
        `idx == 0`，這裡會誤判成灰色；正確實作應仍為黑字。
        """
        combo = _make_combo()
        _send_focus(combo, QEvent.FocusIn)
        # 模擬 _onTextChanged 內部行為：blockSignals 期間重建 + setEditText
        combo.blockSignals(True)
        combo.clear()
        combo.addItem("", None)
        for id_, name in _DATA:
            if "電信詐欺" in name or "電信詐欺" == name:
                combo.addItem(name, id_)
        combo.setEditText("電信詐欺")
        combo.blockSignals(False)
        self.assertEqual(combo.currentIndex(), 0)  # 重建後 index 恆為 0
        self.assertEqual(combo.currentText(), "電信詐欺")
        # blockSignals 期間不會觸發任何 signal，故手動呼叫 textEdited 模擬
        # 真實使用者打字流程（lineEdit().textEdited 才是實際驅動來源）。
        combo.lineEdit().textEdited.emit("電信詐欺")
        self.assertEqual(_color(combo), TEXT_COLOR,
                         "打字後 index 恆為 0，顏色判斷若依賴 "
                         "currentIndexChanged+idx==0 會誤判成灰字")

    def test_repeated_attach_does_not_duplicate_connections(self):
        """attachComboHint 對同一 combo 重複呼叫三次（比照 tab_report）
        不應累積 signal 連線或 eventFilter，行為仍正確。"""
        def _type_into(c):
            _send_focus(c, QEvent.FocusIn)
            c.lineEdit().setText("竊盜")
            c.lineEdit().textEdited.emit("竊盜")

        combo = _make_combo()
        for _ in range(2):  # _make_combo 內已呼叫一次，這裡再呼叫兩次 = 共三次
            attachComboHint(combo, _HINT)

        # 打字一次只應觸發一次 repaint（無法直接量 repaint 次數，改以
        # 行為正確性＋stylesheet 沒有異常疊加內容間接驗證）。
        _type_into(combo)
        self.assertEqual(_color(combo), TEXT_COLOR)

        # ⚠️ 以「只掛一次的 combo」當對照，**不要寫死 `count("color:") == 1`**：
        # `attachComboHint` 除了基底色，還必須寫 `QComboBox:disabled` 的灰字
        # （否則會蓋掉公版反灰，唯讀時案類欄文字不變灰，見 PITFALLS QSS-8），
        # 色碼本來就不只一個。要驗的是「重複掛不會累積」，比對相等才是判準。
        once = _make_combo()
        _type_into(once)
        self.assertEqual(combo.styleSheet(), once.styleSheet())

        _send_focus(combo, QEvent.FocusIn)
        combo.lineEdit().setText("")
        combo.lineEdit().textEdited.emit("")
        _send_focus(combo, QEvent.FocusOut)
        self.assertEqual(combo.currentText(), _HINT)
        self.assertEqual(_color(combo), HINT_COLOR)
        # 同上：與只掛一次的 combo 走完同一段流程後比對，不寫死色碼數量。
        once2 = _make_combo()
        _send_focus(once2, QEvent.FocusIn)
        once2.lineEdit().setText("")
        once2.lineEdit().textEdited.emit("")
        _send_focus(once2, QEvent.FocusOut)
        self.assertEqual(combo.styleSheet(), once2.styleSheet())


class TestFocusInClearDoesNotWipeSelection(unittest.TestCase):
    """釘住：focus-in 的延後清空不得清掉使用者當下選好的值。

    點下拉鈕是「同一下取得焦點＋展開清單」，focus-in 排的延後清空可能落在
    使用者選完項目之後。舊寫法無條件 `clearEditText`，會把剛帶入的姓名清成
    空白——症狀＝空白欄第一次下拉選了沒反應、要再拉一次（案類欄實際踩過）。
    """

    def test_selection_made_before_deferred_clear_survives(self):
        combo = _make_combo()
        self.assertEqual(combo.currentText(), _HINT)

        # FocusIn 排入延後清空，但先不讓事件迴圈跑
        QApplication.sendEvent(combo, QEvent(QEvent.FocusIn))
        QApplication.sendEvent(combo.lineEdit(), QEvent(QEvent.FocusIn))

        # 使用者在延後清空跑到之前就從清單選了項目
        combo.setCurrentIndex(combo.findData(1))

        _app.processEvents()   # 此時延後清空才執行

        self.assertEqual(combo.currentText(), "竊盜")
        self.assertEqual(combo.currentData(), 1)
        self.assertEqual(_color(combo), TEXT_COLOR)

    def test_deferred_clear_still_clears_when_nothing_selected(self):
        """沒選任何東西時，原本的「點入即清提示字」行為不變。"""
        combo = _make_combo()
        _send_focus(combo, QEvent.FocusIn)
        self.assertEqual(combo.currentText(), "")


class TestTicketCombosHaveNoHint(unittest.TestCase):
    """罰單頁的單一人名下拉比照陳報頁發文人員：不掛提示文字。

    維護者指示：提示文字（attachComboHint）只用於陳報頁的案類欄；
    人名下拉一律只掛 setupFilterCombo，第 0 項維持空字串。
    """

    def test_ticket_tab_personnel_combos_have_empty_first_item(self):
        from tabs import tab_ticket
        import inspect

        src = inspect.getsource(tab_ticket)
        self.assertNotIn("attachComboHint(", src,
                         "罰單頁不得再掛提示文字，應比照陳報頁發文人員")

        combo = QComboBox()
        combo.setEditable(True)
        setupFilterCombo(combo, [(1, "王小明"), (2, "陳大文")])
        self.assertEqual(combo.itemText(0), "")
        self.assertIsNone(combo.currentData())
        self.assertIsNone(getattr(combo, "_hint_filter", None))


if __name__ == "__main__":
    unittest.main()
