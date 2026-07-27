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


if __name__ == "__main__":
    unittest.main()
