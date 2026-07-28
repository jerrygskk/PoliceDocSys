"""Tests for settlement entry and filter-chip visibility."""
import os
import shutil
import sqlite3
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


class TestVisibleChipKeys(unittest.TestCase):
    """A zero-count sender-mode type must not retain a filter chip."""

    def _keys(self, modes, counts):
        from ui_utils.settle_dialog import visible_chip_keys
        return visible_chip_keys(modes, counts)

    def test_non_self_and_zero_rows_is_hidden(self):
        self.assertEqual(
            self._keys(
                {"crim": False, "gen": False, "ticket": False},
                {"crim": 0, "gen": 0, "ticket": 0},
            ),
            set(),
        )

    def test_self_service_shows_even_with_zero_rows(self):
        self.assertEqual(
            self._keys(
                {"crim": True, "gen": False, "ticket": False},
                {"crim": 0, "gen": 0, "ticket": 0},
            ),
            {"crim"},
        )

    def test_non_self_with_leftover_rows_still_shows(self):
        self.assertEqual(
            self._keys(
                {"crim": False, "gen": False, "ticket": False},
                {"crim": 0, "gen": 0, "ticket": 3},
            ),
            {"ticket"},
        )

    def test_self_service_with_rows_shows(self):
        self.assertEqual(
            self._keys(
                {"crim": True, "gen": True, "ticket": False},
                {"crim": 2, "gen": 0, "ticket": 0},
            ),
            {"crim", "gen"},
        )

    def test_missing_count_treated_as_zero(self):
        self.assertEqual(
            self._keys({"crim": False, "gen": False, "ticket": False}, {}),
            set(),
        )


class TestSettleEntryVisible(unittest.TestCase):
    """Sender mode retains the entry only while unissued records remain."""

    def setUp(self):
        from lib.db_schema import applySchema
        self._tmp = tempfile.mkdtemp()
        self._path = os.path.join(self._tmp, "t.db")
        conn = sqlite3.connect(self._path)
        applySchema(conn)
        for kind in ("crim", "gen", "ticket"):
            conn.execute(
                "INSERT OR REPLACE INTO App_Settings (key, value) VALUES (?, '0')",
                (f"report_mode_{kind}",),
            )
        conn.commit()
        conn.close()

    def tearDown(self):
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _set_mode(self, kind, on):
        conn = sqlite3.connect(self._path)
        conn.execute(
            "INSERT OR REPLACE INTO App_Settings (key, value) VALUES (?, ?)",
            (f"report_mode_{kind}", "1" if on else "0"),
        )
        conn.commit()
        conn.close()

    def _add_unissued_criminal(self):
        conn = sqlite3.connect(self._path)
        conn.execute(
            "INSERT INTO Document_Criminal "
            "(doc_id, report_date, processor_id, subject_summary) "
            "VALUES ('1', NULL, 'P001', 'Unissued record')"
        )
        conn.commit()
        conn.close()

    def test_hidden_when_all_sender_mode_and_no_unissued(self):
        from ui_utils.settle_dialog import settle_entry_visible
        self.assertFalse(settle_entry_visible(self._path))

    def test_visible_when_any_self_service(self):
        from ui_utils.settle_dialog import settle_entry_visible
        self._set_mode("ticket", True)
        self.assertTrue(settle_entry_visible(self._path))

    def test_visible_when_sender_mode_but_leftover_unissued(self):
        from ui_utils.settle_dialog import settle_entry_visible
        self._add_unissued_criminal()
        self.assertTrue(settle_entry_visible(self._path))


class TestSettleRefreshFailure(unittest.TestCase):
    def test_count_failure_is_not_retried_during_same_refresh(self):
        from PySide6.QtWidgets import QApplication, QLabel
        from tabs.tab_print import TabPrint

        QApplication.instance() or QApplication([])
        fake = SimpleNamespace(
            db_path="unused.db",
            _settle_group=Mock(),
            lbl_unissued=QLabel(),
        )
        fake._refresh_unissued = lambda counts, unavailable=False: TabPrint._refresh_unissued(
            fake, counts, unavailable)
        with patch("ui_utils.settle_dialog.count_unissued",
                   side_effect=RuntimeError("database unavailable")) as count, \
             patch("ui_utils.settle_dialog.settle_entry_visible",
                   return_value=True):
            TabPrint._refresh_settle_group(fake)

        self.assertEqual(count.call_count, 1)
        self.assertEqual(fake.lbl_unissued.text(), "未發文：—")
        fake._settle_group.setVisible.assert_called_once_with(True)


class TestSettleCompletionRefresh(unittest.TestCase):
    """結算最後一筆殘留資料後，入口必須依新狀態隱藏。"""

    def setUp(self):
        from lib.db_schema import applySchema
        self._tmp = tempfile.mkdtemp()
        self._path = os.path.join(self._tmp, "t.db")
        conn = sqlite3.connect(self._path)
        applySchema(conn)
        for kind in ("crim", "gen", "ticket"):
            conn.execute(
                "INSERT OR REPLACE INTO App_Settings (key, value) VALUES (?, '0')",
                (f"report_mode_{kind}",),
            )
        conn.execute(
            "INSERT INTO Document_Criminal "
            "(doc_id, report_date, processor_id, subject_summary) "
            "VALUES ('1', NULL, 'P001', 'Last unissued record')"
        )
        conn.commit()
        conn.close()

    def tearDown(self):
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_settling_last_sender_mode_leftover_hides_entry(self):
        from PySide6.QtWidgets import QApplication, QLabel
        from tabs.tab_print import TabPrint

        QApplication.instance() or QApplication([])
        fake = SimpleNamespace(
            db_path=self._path,
            tab_widget=None,
            date_edit=None,
            _settle_group=Mock(),
            lbl_unissued=QLabel(),
            _on_generate=Mock(),
        )
        fake._refresh_unissued = lambda counts=None, unavailable=False: TabPrint._refresh_unissued(
            fake, counts, unavailable)
        fake._refresh_settle_group = lambda: TabPrint._refresh_settle_group(fake)
        fake._settle_group.setVisible(True)  # 結算前：殘留資料使入口可見。

        class LastRecordSettlement:
            def __init__(self, db_path, parent=None):
                self.db_path = db_path

            def exec(self):
                conn = sqlite3.connect(self.db_path)
                conn.execute(
                    "UPDATE Document_Criminal SET report_date='2026-07-27', "
                    "sender_id='P001' WHERE doc_id='1'"
                )
                conn.commit()
                conn.close()

            def settled(self):
                return True

        with patch("ui_utils.settle_dialog.SettleDialog", LastRecordSettlement):
            TabPrint._on_settle(fake)

        fake._settle_group.setVisible.assert_called_with(False)

    def test_successful_settlement_generates_receipt_for_selected_date(self):
        """一條龍列印必須帶結算彈窗選定的日期，不可回填今天。"""
        from PySide6.QtCore import QDate
        from PySide6.QtWidgets import QApplication, QLabel
        from tabs.tab_print import TabPrint

        QApplication.instance() or QApplication([])
        date_edit = Mock()
        fake = SimpleNamespace(
            db_path=self._path,
            tab_widget=None,
            date_edit=date_edit,
            _settle_group=Mock(),
            lbl_unissued=QLabel(),
            _on_generate=Mock(),
        )
        fake._refresh_unissued = lambda counts=None, unavailable=False: TabPrint._refresh_unissued(
            fake, counts, unavailable)
        fake._refresh_settle_group = lambda: TabPrint._refresh_settle_group(fake)

        class SelectedDateSettlement:
            def __init__(self, db_path, parent=None):
                pass

            def exec(self):
                pass

            def settled(self):
                return True

            def settledDate(self):
                return QDate(2026, 7, 9)

        with patch("ui_utils.settle_dialog.SettleDialog", SelectedDateSettlement):
            TabPrint._on_settle(fake)

        date_edit.setDate.assert_called_once_with(QDate(2026, 7, 9))
        fake._on_generate.assert_called_once_with()

    def test_unsuccessful_settlement_does_not_generate_receipt(self):
        """零筆成功的對話框結果不得觸發自動列印。"""
        from PySide6.QtWidgets import QApplication, QLabel
        from tabs.tab_print import TabPrint

        QApplication.instance() or QApplication([])
        date_edit = Mock()
        fake = SimpleNamespace(
            db_path=self._path,
            tab_widget=None,
            date_edit=date_edit,
            _settle_group=Mock(),
            lbl_unissued=QLabel(),
            _on_generate=Mock(),
        )

        class NoSuccessfulSettlement:
            def __init__(self, db_path, parent=None):
                pass

            def exec(self):
                pass

            def settled(self):
                return False

            def settledDate(self):
                return None

        with patch("ui_utils.settle_dialog.SettleDialog", NoSuccessfulSettlement):
            TabPrint._on_settle(fake)

        date_edit.setDate.assert_not_called()
        fake._on_generate.assert_not_called()


if __name__ == "__main__":
    unittest.main()
