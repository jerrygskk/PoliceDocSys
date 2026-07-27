"""Regression coverage for per-kind self-service mode switching."""
import os
import shutil
import sqlite3
import sys
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from PySide6.QtCore import QDate  # noqa: E402
from PySide6.QtWidgets import QApplication, QTabWidget, QWidget  # noqa: E402


class TestReportModeSwitch(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])

    def setUp(self):
        from lib.db_schema import applySchema
        from lib.db_seed import seedFreshDb

        self._tmp = tempfile.mkdtemp()
        self._path = os.path.join(self._tmp, "t.db")
        conn = sqlite3.connect(self._path)
        applySchema(conn)
        seedFreshDb(conn)
        for key, value in (("report_mode_crim", "1"),
                           ("report_mode_gen", "0")):
            conn.execute(
                "INSERT OR REPLACE INTO App_Settings (key, value) VALUES (?, ?)",
                (key, value))
        conn.commit()
        conn.close()

    def tearDown(self):
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _make_tab(self):
        from tabs.tab_report import TabReport

        self._tabs = QTabWidget()
        for _ in range(3):
            self._tabs.addTab(QWidget(), "")
        self.addCleanup(self._tabs.deleteLater)
        tab = TabReport(self._tabs, self._path)
        tab.setup(2)
        return tab

    def test_crim_self_service_blanks_and_disables(self):
        tab = self._make_tab()
        tab.type_tabbar.setCurrentIndex(0)
        self.assertFalse(tab.rpt_date.isEnabled())
        self.assertFalse(tab.rpt_sender.isEnabled())
        self.assertEqual(tab.rpt_date.specialValueText(), " ")

    def test_switch_to_gen_restores_editable_today(self):
        tab = self._make_tab()
        tab.type_tabbar.setCurrentIndex(0)
        tab.type_tabbar.setCurrentIndex(1)
        self.assertTrue(tab.rpt_date.isEnabled())
        self.assertTrue(tab.rpt_sender.isEnabled())
        self.assertEqual(tab.rpt_date.specialValueText(), "")
        self.assertEqual(tab.rpt_date.date(), QDate.currentDate())

    def test_switch_back_to_crim_blanks_again(self):
        tab = self._make_tab()
        tab.type_tabbar.setCurrentIndex(1)
        tab.type_tabbar.setCurrentIndex(0)
        self.assertFalse(tab.rpt_date.isEnabled())
        self.assertEqual(tab.rpt_date.specialValueText(), " ")


if __name__ == "__main__":
    unittest.main()
