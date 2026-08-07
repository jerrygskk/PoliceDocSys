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


class _TicketDialogCasBase(unittest.TestCase):
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
        # ⚠️ 明確把「上次異動時間」壓成過去的值，模擬真實情境（這筆是先前
        # 登錄的，不是開窗當下才寫進去的）。樂觀鎖比對的 `last_modified` 只有
        # 秒精度，若讓 INSERT 與後續的他機修改落在同一秒，字串會一模一樣而
        # 比不出差異——那是這套機制的已知窄縫，見
        # `db_utils.LAST_MODIFIED_CAS_SQL` 與 PITFALLS SQL-7，
        # 由 test_same_second_change_is_a_known_blind_spot 明確釘住。
        conn.execute(
            "UPDATE Document_Ticket SET last_modified='2026-08-01 09:00:00' "
            "WHERE doc_id='1'")
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


class TestTicketDialogRuntimeCas(_TicketDialogCasBase):
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
            "資料已更新", "這筆資料已被異動，請關閉後重新開啟修改。")
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
            "資料已更新", "這筆資料已被異動，請關閉後重新開啟修改。")
        dlg.deleteLater()


class TestKnownBlindSpot(_TicketDialogCasBase):
    """⚠️ 秒精度窄縫：把它寫成測試，免得日後被當成新 bug 反覆追。

    `last_modified` 由 trigger 寫 `datetime('now','localtime')`，只有**秒**精度
    （PITFALLS SQL-7）。因此若他機的修改與「開窗時讀到的那個異動時間」落在
    同一秒，兩邊字串相同，樂觀鎖比不出差異而放行。

    要撞到必須：這筆在我開窗的**同一秒**才剛被改過，且他機又在那一秒內再改
    一次。2026-08-07 與維護者議定接受此風險（改成毫秒精度＝動五張主表 trigger
    與所有指紋比較點，須另立經核可的全域計畫，見 PITFALLS SQL-7）。
    ⚠️ 不要為了補這個縫把舊的欄位比對加回去並存——兩套機制並存是這次要消滅的
    東西，且欄位比對另有「改成 B 又改回 A」抓不到的漏洞。
    """

    def test_same_second_change_is_a_known_blind_spot(self):
        dlg = TicketEditDialog(self.db, "1", source="entry")
        conn = sqlite3.connect(self.db)
        # 他機修改，但把 last_modified 停在與開窗快照完全相同的值（同一秒）
        conn.execute(
            "UPDATE Document_Ticket SET issuer_id='P002',ticket_no='REMOTE99' "
            "WHERE doc_id='1'")
        conn.execute(
            "UPDATE Document_Ticket SET last_modified='2026-08-01 09:00:00' "
            "WHERE doc_id='1'")
        conn.commit()
        conn.close()
        dlg._set_combo(dlg.w_issuer, "P001")
        dlg.w_ticket_no.setText("LOCAL88")

        with patch("ui_utils.ticket_dialog.msgWarning") as warning:
            dlg._on_save()

        # 擋不下來——本機的值覆蓋了他機的修改。這是已知且已接受的行為。
        self.assertEqual(
            self._row(), ("2026-08-01", "", None, "P001", "LOCAL88"))
        warning.assert_not_called()
        dlg.deleteLater()


if __name__ == "__main__":
    unittest.main()
