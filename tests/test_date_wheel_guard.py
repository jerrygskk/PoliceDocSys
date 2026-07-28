# -*- coding: utf-8 -*-
"""全域日期框滑鼠滾輪防護的真實 Qt 事件回歸測試。"""
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QDate, QEvent, QPoint, QPointF, Qt, QObject
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import QApplication, QCalendarWidget, QDateEdit, QWidget

from ui_utils import loadUi
from ui_utils.widgets import NullableDateEdit, installDateEditWheelGuard


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
