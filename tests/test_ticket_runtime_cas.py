# -*- coding: utf-8 -*-
"""罰單對話框載入期間的 lost-update 防護；只使用暫存 DB。"""

import os
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QDate
from PySide6.QtWidgets import QApplication

from lib.auth_manager import AuthManager
from lib.db_schema import applySchema
from ui_utils.ticket_dialog import TicketEditDialog


_app = QApplication.instance() or QApplication([])


class TestTicketDialogRuntimeCas(unittest.TestCase):
    def setUp(self):
        fd, self.db = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        conn = sqlite3.connect(self.db)
        applySchema(conn)
        conn.executemany(
            "INSERT INTO Ref_Personnel(staff_id,staff_name,is_active,sort_order) "
            "VALUES(?,?,1,?)",
            (("P001", "甲員", 1), ("P002", "乙員", 2)),
        )
        conn.execute(
            "INSERT INTO Document_Ticket("
            "doc_id,create_date,register_date,sender_id,issuer_id,ticket_no) "
            "VALUES('1','2026-08-01','',NULL,'P001','ORIG01')"
        )
        conn.commit()
        conn.close()
        AuthManager.instance()._role = "admin"

    def tearDown(self):
        AuthManager.instance()._role = "user"
        os.remove(self.db)

    def _row(self):
        conn = sqlite3.connect(self.db)
        try:
            return conn.execute(
                "SELECT create_date,register_date,sender_id,issuer_id,ticket_no "
                "FROM Document_Ticket WHERE doc_id='1'"
            ).fetchone()
        finally:
            conn.close()

    def test_entry_dialog_does_not_overwrite_change_made_while_open(self):
        dlg = TicketEditDialog(self.db, "1", source="entry")
        conn = sqlite3.connect(self.db)
        conn.execute(
            "UPDATE Document_Ticket SET issuer_id='P002',ticket_no='REMOTE99' "
            "WHERE doc_id='1'")
        conn.commit()
        conn.close()
        dlg._set_combo(dlg.w_issuer, "P001")
        dlg.w_ticket_no.setText("LOCAL88")

        with patch("ui_utils.ticket_dialog.msgWarning") as warning:
            dlg._on_save()

        self.assertEqual(
            self._row(), ("2026-08-01", "", None, "P002", "REMOTE99"))
        warning.assert_called_with(
            "資料已更新", "本筆罰單資料已被其他電腦修改，本次未儲存。")
        dlg.deleteLater()

    def test_browse_dialog_does_not_overwrite_change_made_while_open(self):
        dlg = TicketEditDialog(self.db, "1", source="browse")
        conn = sqlite3.connect(self.db)
        conn.execute(
            "UPDATE Document_Ticket SET create_date='2026-08-02',"
            "issuer_id='P002',ticket_no='REMOTE99' WHERE doc_id='1'")
        conn.commit()
        conn.close()
        dlg.w_create_date.setDate(QDate(2026, 8, 3))
        dlg.w_register_date.clear()
        dlg._set_combo(dlg.w_sender, None)
        dlg._set_combo(dlg.w_issuer, "P001")
        dlg.w_ticket_no.setText("LOCAL88")

        with patch("ui_utils.ticket_dialog.msgWarning") as warning:
            dlg._on_save()

        self.assertEqual(
            self._row(), ("2026-08-02", "", None, "P002", "REMOTE99"))
        warning.assert_called_with(
            "資料已更新", "本筆罰單資料已被其他電腦修改，本次未儲存。")
        dlg.deleteLater()


if __name__ == "__main__":
    unittest.main()
