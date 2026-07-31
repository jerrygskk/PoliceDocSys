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

    def test_right_column_does_not_shift_between_modes(self):
        """切換刑案／一般時，右半部欄位不得左右位移（實機截圖比對過的回歸）。

        一般模式會隱藏「報案人」那組（col7／col8），空出的寬度若沒被最右側
        的 Expanding 欄吃掉，就會被 col3 標籤欄分走、整塊右半部往右跳。
        ⚠️ 必須 show() 後再量，未顯示的 widget 量不到真實寬度（LAY-8）。
        """
        tab = self._make_tab()
        self._tabs.resize(1400, 800)
        self._tabs.show()
        self._tabs.setCurrentIndex(2)
        self._app.processEvents()

        def snapshot():
            self._app.processEvents()
            return (tab.rpt_sender.x(), tab.rpt_sender.width())

        tab.type_tabbar.setCurrentIndex(0)
        crim = snapshot()
        tab.type_tabbar.setCurrentIndex(1)
        gen = snapshot()
        tab.type_tabbar.setCurrentIndex(0)
        crim_again = snapshot()

        self.assertEqual(crim, gen, "切到一般模式後右半部位移了")
        self.assertEqual(crim, crim_again, "切回刑案模式後右半部位移了")
        self._tabs.hide()

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
