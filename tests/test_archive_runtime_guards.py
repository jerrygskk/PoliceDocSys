# -*- coding: utf-8 -*-
"""歸檔 runtime 權限與檔名／DB 一致性；所有檔案與 DB 皆為暫存。"""

import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from lib.auth_manager import AuthManager
from tabs.tab_archive import TabArchive


class _Text:
    def __init__(self, value=""):
        self.value = value

    def text(self):
        return self.value

    def setText(self, value):
        self.value = value


class TestArchiveRuntimeGuards(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db = self.root / "archive.db"
        conn = sqlite3.connect(self.db)
        conn.execute(
            "CREATE TABLE Document_Criminal("
            "doc_id TEXT PRIMARY KEY, is_reported INTEGER, is_electronic TEXT)"
        )
        conn.execute(
            "INSERT INTO Document_Criminal VALUES('1', 0, NULL)"
        )
        conn.commit()
        conn.close()
        self.old_pdf = self.root / "scan.pdf"
        self.old_pdf.write_bytes(b"%PDF-1.4\n%%EOF\n")
        AuthManager.instance()._role = "user"

    def tearDown(self):
        AuthManager.instance()._role = "user"
        self.tmp.cleanup()

    def _stub(self, *, doc_id="1"):
        ui = {
            "h_pk": _Text(doc_id),
            "h_date": _Text("20260802"),
            "h_subj": _Text("測試案由"),
            "h_proc": _Text("甲員"),
        }
        return SimpleNamespace(
            _selected={"crim": doc_id},
            _docrows={
                "crim": {
                    doc_id: {"嫌疑人_案由": "測試案由", "紙本": ""}
                }
            },
            _ui={"crim": ui},
            _curPdf={"crim": str(self.old_pdf)},
            _pdfs={"crim": [str(self.old_pdf)]},
            _sigs={},
            _getConn=lambda: sqlite3.connect(self.db),
            _diffDocs=lambda key: None,
            _rematch=lambda key: None,
            _refreshFinal=lambda key: None,
            _loadDocs=lambda key: None,
            _tableSignature=lambda key: (0, None),
        )

    def _row(self, doc_id="1"):
        conn = sqlite3.connect(self.db)
        try:
            return conn.execute(
                "SELECT is_reported,is_electronic "
                "FROM Document_Criminal WHERE doc_id=?", (doc_id,)
            ).fetchone()
        finally:
            conn.close()

    def test_paper_only_direct_call_as_user_has_no_db_side_effect(self):
        stub = SimpleNamespace()
        with patch("tabs.tab_archive.confirmBox") as confirm:
            TabArchive._archivePaperOnly(stub, "crim")
        confirm.assert_not_called()
        self.assertEqual(self._row(), (0, None))

    def test_paper_only_downgrade_in_confirm_has_no_db_side_effect(self):
        AuthManager.instance()._role = "archive"
        stub = self._stub()

        def downgrade(*args, **kwargs):
            AuthManager.instance()._role = "user"
            return True

        with patch("tabs.tab_archive.confirmBox", side_effect=downgrade):
            TabArchive._archivePaperOnly(stub, "crim")

        self.assertEqual(self._row(), (0, None))

    def test_paper_only_manager_success_is_preserved(self):
        AuthManager.instance()._role = "archive"
        stub = self._stub()
        with patch("tabs.tab_archive.confirmBox", return_value=True):
            TabArchive._archivePaperOnly(stub, "crim")
        self.assertEqual(self._row(), (1, None))

    def test_archive_direct_call_as_user_does_not_rename_or_write(self):
        stub = SimpleNamespace()
        with patch("tabs.tab_archive.confirmBox") as confirm:
            TabArchive._doArchive(stub, "crim")
        confirm.assert_not_called()
        self.assertTrue(self.old_pdf.exists())
        self.assertEqual(self._row(), (0, None))

    def test_archive_downgrade_in_confirm_does_not_rename_or_write(self):
        AuthManager.instance()._role = "archive"
        stub = self._stub()

        def downgrade(*args, **kwargs):
            AuthManager.instance()._role = "user"
            return True

        with patch("tabs.tab_archive.confirmBox", side_effect=downgrade):
            TabArchive._doArchive(stub, "crim")

        self.assertTrue(self.old_pdf.exists())
        self.assertEqual(self._row(), (0, None))

    def test_archive_manager_success_renames_and_updates_db_together(self):
        AuthManager.instance()._role = "admin"
        stub = self._stub()
        expected = self.root / "1-20260802-測試案由-甲員.pdf"

        with patch("tabs.tab_archive.confirmBox", return_value=True):
            TabArchive._doArchive(stub, "crim")

        self.assertFalse(self.old_pdf.exists())
        self.assertTrue(expected.exists())
        self.assertEqual(self._row(), (1, expected.name))

    def test_archive_missing_db_row_restores_original_filename(self):
        AuthManager.instance()._role = "archive"
        stub = self._stub(doc_id="404")
        renamed = self.root / "404-20260802-測試案由-甲員.pdf"

        with patch("tabs.tab_archive.confirmBox", return_value=True), \
                patch("tabs.tab_archive.reportError"):
            TabArchive._doArchive(stub, "crim")

        self.assertTrue(self.old_pdf.exists())
        self.assertFalse(renamed.exists())
        self.assertIsNone(self._row("404"))

    def test_archive_restore_retries_after_one_temporary_rename_failure(self):
        AuthManager.instance()._role = "archive"
        stub = self._stub(doc_id="404")
        renamed = self.root / "404-20260802-測試案由-甲員.pdf"
        real_rename = os.rename
        calls = []

        def fail_first_restore(src, dst):
            calls.append((src, dst))
            if len(calls) == 2:
                raise OSError("暫時無法還原")
            return real_rename(src, dst)

        with patch("tabs.tab_archive.confirmBox", return_value=True), \
                patch("tabs.tab_archive.os.rename", side_effect=fail_first_restore), \
                patch("tabs.tab_archive.reportError") as report:
            TabArchive._doArchive(stub, "crim")

        self.assertEqual(len(calls), 3)
        self.assertTrue(self.old_pdf.exists())
        self.assertFalse(renamed.exists())
        report.assert_called_once()

    def test_archive_persistent_restore_failure_reports_both_errors(self):
        AuthManager.instance()._role = "archive"
        stub = self._stub(doc_id="404")
        renamed = self.root / "404-20260802-測試案由-甲員.pdf"
        real_rename = os.rename
        calls = []

        def always_fail_restore(src, dst):
            calls.append((src, dst))
            if len(calls) == 1:
                return real_rename(src, dst)
            raise OSError("持續無法還原")

        with patch("tabs.tab_archive.confirmBox", return_value=True), \
                patch("tabs.tab_archive.os.rename", side_effect=always_fail_restore), \
                patch("tabs.tab_archive.reportError") as report:
            TabArchive._doArchive(stub, "crim")

        self.assertGreaterEqual(len(calls), 3)
        self.assertFalse(self.old_pdf.exists())
        self.assertTrue(renamed.exists())
        title, error = report.call_args.args[:2]
        self.assertIn("檔名無法還原", title)
        self.assertIsInstance(error, ExceptionGroup)
        self.assertTrue(any(isinstance(exc, LookupError)
                            for exc in error.exceptions))
        self.assertTrue(any(isinstance(exc, OSError)
                            and "持續無法還原" in str(exc)
                            for exc in error.exceptions))

    def test_archive_does_not_overwrite_old_path_recreated_during_db_failure(self):
        AuthManager.instance()._role = "archive"
        stub = self._stub(doc_id="404")
        renamed = self.root / "404-20260802-測試案由-甲員.pdf"
        original_get_conn = stub._getConn

        def recreate_old_then_connect():
            self.old_pdf.write_bytes(b"rebuilt")
            return original_get_conn()

        stub._getConn = recreate_old_then_connect
        with patch("tabs.tab_archive.confirmBox", return_value=True), \
                patch("tabs.tab_archive.reportError") as report:
            TabArchive._doArchive(stub, "crim")

        self.assertEqual(self.old_pdf.read_bytes(), b"rebuilt")
        self.assertTrue(renamed.exists())
        title, error = report.call_args.args[:2]
        self.assertIn("檔名無法還原", title)
        self.assertIsInstance(error, ExceptionGroup)


if __name__ == "__main__":
    unittest.main()
