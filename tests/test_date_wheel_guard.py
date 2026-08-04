# -*- coding: utf-8 -*-
"""全域日期框輸入防護（滑鼠滾輪＋調整鍵）的真實 Qt 事件回歸測試。"""
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QDate, QEvent, QPoint, QPointF, Qt, QObject
from PySide6.QtTest import QTest
from PySide6.QtGui import QKeyEvent, QWheelEvent
from PySide6.QtWidgets import QApplication, QCalendarWidget, QDateEdit, QWidget

from ui_utils import loadUi
from ui_utils.widgets import (
    NullableDateEdit, installDateEditInputGuard, installDateEditWheelGuard)


_app = QApplication.instance() or QApplication([])
_LAYOUT_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "layouts")


def _wheel_event():
    return QWheelEvent(
        QPointF(8, 8), QPointF(8, 8), QPoint(), QPoint(0, 120),
        Qt.NoButton, Qt.NoModifier, Qt.ScrollPhase.NoScrollPhase, False,
    )


def _send_wheel(receiver):
    event = _wheel_event()
    QApplication.sendEvent(receiver, event)
    return event


class _WheelObserver(QObject):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.wheel_events = 0

    def eventFilter(self, _obj, event):
        if event.type() == QEvent.Wheel:
            self.wheel_events += 1
        return False


class TestDateEditWheelGuard(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.guard = installDateEditWheelGuard(_app)

    def _date_edit(self):
        edit = QDateEdit()
        edit.setDate(QDate(2026, 7, 28))
        edit.setFocus()
        return edit

    def test_installer_is_idempotent_and_app_owns_guard(self):
        self.assertIs(installDateEditWheelGuard(_app), self.guard)
        self.assertIs(self.guard.parent(), _app)

    def test_wheel_on_focused_and_unfocused_date_edit_does_not_change_date(self):
        for focused in (True, False):
            with self.subTest(focused=focused):
                edit = self._date_edit()
                if not focused:
                    edit.clearFocus()
                before = edit.date()
                event = _send_wheel(edit)
                self.assertEqual(edit.date(), before)
                self.assertTrue(event.isAccepted())

    def test_wheel_on_date_edit_internal_line_edit_does_not_change_date(self):
        edit = self._date_edit()
        before = edit.date()
        event = _send_wheel(edit.lineEdit())
        self.assertEqual(edit.date(), before)
        self.assertTrue(event.isAccepted())

    def test_dynamic_date_edit_is_guarded_after_installation(self):
        container = QWidget()
        edit = QDateEdit(container)
        edit.setDate(QDate(2026, 7, 28))
        before = edit.date()
        _send_wheel(edit)
        self.assertEqual(edit.date(), before)

    def test_all_loaded_layout_date_edits_are_guarded(self):
        for filename in os.listdir(_LAYOUT_DIR):
            if not filename.endswith(".ui"):
                continue
            with self.subTest(layout=filename):
                window = loadUi(os.path.join(_LAYOUT_DIR, filename))
                try:
                    for edit in window.findChildren(QDateEdit):
                        edit.setDate(QDate(2026, 7, 28))
                        before = edit.date()
                        _send_wheel(edit)
                        self.assertEqual(edit.date(), before)
                finally:
                    window.deleteLater()

    def test_nullable_date_edit_is_not_intercepted(self):
        edit = NullableDateEdit()
        event = _wheel_event()
        self.assertFalse(self.guard.eventFilter(edit, event))

    def test_calendar_wheel_is_not_intercepted(self):
        edit = self._date_edit()
        edit.setCalendarPopup(True)
        calendar = edit.calendarWidget()
        self.assertIsInstance(calendar, QCalendarWidget)
        event = _wheel_event()
        self.assertFalse(self.guard.eventFilter(calendar, event))

    def test_idle_style_filter_observes_wheel_before_date_guard_consumes_it(self):
        observer = _WheelObserver(_app)
        _app.installEventFilter(observer)
        try:
            _send_wheel(self._date_edit())
            self.assertEqual(observer.wheel_events, 1)
        finally:
            _app.removeEventFilter(observer)


if __name__ == "__main__":
    unittest.main()


class TestDateEditKeyGuard(unittest.TestCase):
    """調整鍵（上下／PageUp／PageDown）在日期框上一律停用。

    這些鍵會在「使用者以為自己在填別的欄位」時改掉游標所在的年／月／日，畫面上
    只有一個數字變動、極不容易察覺。2026-08-04 實際事故：某日發文日期的年份被多加
    一年，當天 12 筆有 8 筆寫成隔年，簽收表只印得出前 4 筆。
    """

    @classmethod
    def setUpClass(cls):
        cls.guard = installDateEditInputGuard(_app)

    def _date_edit(self):
        edit = QDateEdit()
        edit.setDate(QDate(2026, 7, 28))
        edit.setFocus()
        return edit

    @staticmethod
    def _key(receiver, key):
        event = QKeyEvent(QEvent.KeyPress, key, Qt.NoModifier)
        QApplication.sendEvent(receiver, event)
        return event

    def test_blocked_keys_do_not_change_date(self):
        for key in (Qt.Key_Up, Qt.Key_Down, Qt.Key_Left, Qt.Key_Right,
                    Qt.Key_PageUp, Qt.Key_PageDown):
            edit = self._date_edit()
            before = edit.date()
            self._key(edit, key)
            self.assertEqual(edit.date(), before, f"{key} 不得改動日期")

    def test_step_key_on_internal_line_edit_is_also_blocked(self):
        """實際按鍵先落在 QDateEdit 內部的 QLineEdit 上，故必須往上追父層。"""
        edit = self._date_edit()
        before = edit.date()
        self._key(edit.lineEdit(), Qt.Key_Up)
        self.assertEqual(edit.date(), before)

    def test_typing_digits_still_works(self):
        """只擋調整鍵，不得連打字一起擋掉——否則日期就不能改了。"""
        edit = self._date_edit()
        edit.setDisplayFormat("yyyy-MM-dd")
        edit.setSelectedSection(QDateEdit.YearSection)
        for ch in "2028":
            QApplication.sendEvent(
                edit, QKeyEvent(QEvent.KeyPress, Qt.Key_0 + int(ch),
                                Qt.NoModifier, ch))
        self.assertEqual(edit.date().year(), 2028)

    def test_guard_swallows_every_direction_key_but_nothing_else(self):
        """直接驗防護的契約：四個方向鍵與 PageUp／PageDown 全吃掉，其餘一律放行。

        方向鍵連左右也擋（維護者裁示）：切段落本身雖不改值，但切完接著誤觸上下鍵
        就會改到別的段落，而使用者常以為自己還在別的欄位移動游標。要改日期只留
        「打數字」與「月曆挑」兩條路。

        ⚠️ 不用「按右鍵看段落有沒有換」來驗——離線未顯示的 QDateEdit 不會移動
        游標段落，那是測試環境限制、不是防護的行為。
        """
        edit = self._date_edit()
        for key in (Qt.Key_Up, Qt.Key_Down, Qt.Key_Left, Qt.Key_Right,
                    Qt.Key_PageUp, Qt.Key_PageDown):
            event = QKeyEvent(QEvent.KeyPress, key, Qt.NoModifier)
            self.assertTrue(self.guard.eventFilter(edit, event), f"{key} 應被攔下")
        for key in (Qt.Key_Home, Qt.Key_End, Qt.Key_Backspace, Qt.Key_Delete,
                    Qt.Key_Tab, Qt.Key_Return, Qt.Key_5):
            event = QKeyEvent(QEvent.KeyPress, key, Qt.NoModifier)
            self.assertFalse(self.guard.eventFilter(edit, event), f"{key} 不得攔")

    def test_calendar_popup_keys_are_not_intercepted(self):
        """月曆是刻意的挑日操作，方向鍵必須維持原本行為。"""
        calendar = QCalendarWidget()
        event = QKeyEvent(QEvent.KeyPress, Qt.Key_Down, Qt.NoModifier)
        self.assertFalse(self.guard.eventFilter(calendar, event))

    def test_nullable_date_edit_is_not_intercepted(self):
        """NullableDateEdit 是 QLineEdit，本來就只能打字，不受此防護影響。"""
        edit = NullableDateEdit()
        edit.setText("2026-07-28")
        self._key(edit, Qt.Key_Up)
        self.assertEqual(edit.text(), "2026-07-28")


class TestDateEditSpinButtonsDisabled(unittest.TestCase):
    """點擊防護：`calendarPopup=True` 時，Qt 會讓「點輸入區」等同按到 spin 箭頭。

    2026-08-04 現場回報「有些點擊會莫名讓年份 +1」，實測（300×36 offscreen）：
      - `calendarPopup=False`：只有右側箭頭區會改值（正常）
      - `calendarPopup=True`（本專案所有版面的設定）：整條輸入區點下去都會改值
      - 加上 `NoButtons`：完全不會改，且月曆下拉照常開啟
    與全域樣式無關（拿掉 APPLE_STYLE 重測相同），是 Qt 本身的行為。
    """

    @classmethod
    def setUpClass(cls):
        cls.guard = installDateEditInputGuard(_app)

    def _popup_date_edit(self):
        edit = QDateEdit()
        edit.setDisplayFormat("yyyy-MM-dd")
        edit.setCalendarPopup(True)
        edit.resize(300, 36)
        edit.show()
        _app.processEvents()
        edit.setDate(QDate(2026, 8, 4))
        return edit

    def test_new_date_edit_gets_no_spin_buttons(self):
        edit = self._popup_date_edit()
        self.assertEqual(edit.buttonSymbols(), QDateEdit.NoButtons)
        edit.close()

    def test_clicking_anywhere_in_the_field_never_changes_the_year(self):
        """回歸鎖：改動前 x=0～276 幾乎每個點都會讓年份 ±1。"""
        edit = self._popup_date_edit()
        base = edit.date()
        for x in range(0, edit.width(), 6):
            edit.setDate(base)
            QTest.mouseClick(edit, Qt.LeftButton, Qt.NoModifier, QPoint(x, 18))
            _app.processEvents()
            self.assertEqual(edit.date(), base, f"x={x} 的點擊改到了日期")
        edit.close()

    def test_existing_date_edits_are_fixed_when_guard_installs(self):
        """安裝前就建好的日期框收不到 Polish，安裝時要補掃一次。"""
        edit = QDateEdit()
        edit.setButtonSymbols(QDateEdit.UpDownArrows)
        installDateEditInputGuard(_app)
        self.assertEqual(edit.buttonSymbols(), QDateEdit.NoButtons)

    def test_calendar_popup_still_opens(self):
        """關掉箭頭不得順手把月曆也關掉——那是使用者唯一的滑鼠改期途徑。"""
        edit = self._popup_date_edit()
        QTest.mouseClick(edit, Qt.LeftButton, Qt.NoModifier,
                         QPoint(edit.width() - 8, 18))
        _app.processEvents()
        opened = any(
            w.isVisible() and (isinstance(w, QCalendarWidget) or w.findChild(QCalendarWidget))
            for w in QApplication.topLevelWidgets())
        self.assertTrue(opened, "月曆下拉應仍可開啟")
        for w in QApplication.topLevelWidgets():
            if isinstance(w, QCalendarWidget) or w.findChild(QCalendarWidget):
                w.hide()
        edit.close()
