# -*- coding: utf-8 -*-
"""資料庫瀏覽頁的罰單子頁（tabs/tab_dbbrowse.py，key="ticket"）測試（offscreen）。

保護對象：
  - TABLE_META["ticket"] 資料化（base/id_col/pending_date_col 等）與 BROWSE_KEYS 註冊。
  - 權限 gate：非 admin 不可經 _onEdit 開啟編輯彈窗（_canEditKey("ticket") 必為 False）。
  - 刪除分流：瀏覽頁刪除罰單必須走 lib.ticket_utils.deleteTicket()（清空式軟刪除、
    不寫 Trash_Documents），不得誤用 softDeleteDoc()。

人名一律虛構（push 前有 test_no_pii 掃真名）。
"""
import os
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QTabWidget, QWidget

import res.resources_rc  # noqa: F401  資源（icon）註冊，_fillRow 會用到 :/icon_pdf.svg
from lib.auth_manager import AuthManager
from lib.db_schema import applySchema
from tabs.tab_dbbrowse import BROWSE_KEYS, TABLE_META, TabDBBrowse

_app = QApplication.instance() or QApplication([])


class _TicketBrowseBase(unittest.TestCase):
    def setUp(self):
        fd, self.db = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        conn = sqlite3.connect(self.db)
        applySchema(conn)
        conn.executescript("""
            INSERT INTO Ref_Personnel(staff_id,staff_name,is_active,sort_order) VALUES
                ('P01','測試員甲',1,1),('P02','測試員乙',1,2);
            INSERT INTO Document_Ticket(doc_id,create_date,register_date,sender_id,
                issuer_id,ticket_no) VALUES
                ('1','2026-07-01','2026-07-02','P01','P02','AB1234'),
                ('2','2026-07-03','','',        'P02','CD5678');
        """)
        conn.commit()
        conn.close()
        self._extra_tabs = []
        AuthManager.instance()._role = "user"

    def tearDown(self):
        AuthManager.instance()._role = "user"
        for t in self._extra_tabs:
            t.deleteLater()
        try:
            os.remove(self.db)
        except OSError:
            pass

    def _make_browse(self, role="user"):
        AuthManager.instance()._role = role
        tabs = QTabWidget()
        tabs.addTab(QWidget(), "瀏覽")
        self._extra_tabs.append(tabs)
        tab = TabDBBrowse(tabs, self.db)
        tab.setup(0)
        return tab

    def _ticket_row(self, doc_id):
        conn = sqlite3.connect(self.db)
        try:
            row = conn.execute(
                "SELECT doc_id, create_date, register_date, sender_id, "
                "issuer_id, ticket_no FROM Document_Ticket WHERE doc_id=?",
                (doc_id,)).fetchone()
        finally:
            conn.close()
        if row is None:
            return None

        class _Row:
            pass
        r = _Row()
        (r.doc_id, r.create_date, r.register_date, r.sender_id,
         r.issuer_id, r.ticket_no) = row
        return r

    def _trash_count(self):
        conn = sqlite3.connect(self.db)
        try:
            return conn.execute(
                "SELECT COUNT(*) FROM Trash_Documents "
                "WHERE table_name='Document_Ticket'").fetchone()[0]
        finally:
            conn.close()


class TestTicketBrowseRegistry(_TicketBrowseBase):
    """meta 資料化：key 已註冊，且核心欄位與 brief 規格一致。"""

    def test_ticket_registered_in_browse(self):
        self.assertIn("ticket", BROWSE_KEYS)
        meta = TABLE_META["ticket"]
        self.assertEqual(meta["base"], "Document_Ticket")
        self.assertEqual(meta["id_col"], "doc_id")
        self.assertEqual(meta["pending_date_col"], "register_date")
        self.assertTrue(meta.get("admin_only_edit"))
        from lib.ticket_utils import deleteTicket
        self.assertIs(meta.get("delete_handler"), deleteTicket)

    def test_ticket_page_loads_rows(self):
        tab = self._make_browse(role="admin")
        tab.buildInitial("ticket")
        table = tab._ui["ticket"]["table"]
        self.assertEqual(table.rowCount(), 2)
        self.assertEqual(tab._docorder["ticket"], ["1", "2"])


class TestTicketBrowsePermission(_TicketBrowseBase):
    """權限 gate：非 admin 每個進入點皆不可編輯罰單瀏覽資料。"""

    def test_non_admin_cannot_edit_ticket_outside_registration_tab(self):
        tab = self._make_browse(role="user")
        self.assertFalse(tab._canEditKey("ticket"))
        from unittest.mock import MagicMock
        dialog_factory = MagicMock()
        with patch.dict(TABLE_META["ticket"], {"dialog": dialog_factory}):
            tab._onEdit("ticket", 0, "1")
            dialog_factory.assert_not_called()

    def test_archive_role_cannot_edit_ticket(self):
        # 歸檔管理者也不可（罰單為 admin 專屬，不同於刑案/一般）。
        tab = self._make_browse(role="archive")
        self.assertFalse(tab._canEditKey("ticket"))

    def test_admin_can_edit_ticket(self):
        tab = self._make_browse(role="admin")
        self.assertTrue(tab._canEditKey("ticket"))

    def test_link_cell_click_blocked_for_non_admin(self):
        tab = self._make_browse(role="user")
        tab.buildInitial("ticket")
        link_col = next(i for i, c in enumerate(TABLE_META["ticket"]["cols"])
                         if c.get("link"))
        with patch.object(tab, "_onEdit") as on_edit:
            tab._onLinkCell("ticket", 0, link_col, link_col)
            on_edit.assert_not_called()

    def test_link_cell_click_opens_for_admin(self):
        tab = self._make_browse(role="admin")
        tab.buildInitial("ticket")
        link_col = next(i for i, c in enumerate(TABLE_META["ticket"]["cols"])
                         if c.get("link"))
        with patch.object(tab, "_onEdit") as on_edit:
            tab._onLinkCell("ticket", 0, link_col, link_col)
            on_edit.assert_called_once_with("ticket", 0, "1")


class TestTicketBrowseDelete(_TicketBrowseBase):
    """刪除分流：必須走 deleteTicket()，清空欄位保留 doc_id、不進 Trash_Documents。"""

    def test_registration_delete_uses_empty_shell_not_trash(self):
        tab = self._make_browse(role="admin")
        tab.buildInitial("ticket")
        with patch("tabs.tab_dbbrowse.confirmBox", return_value=True):
            tab._onDelete("ticket", "1")
        row = self._ticket_row("1")
        self.assertIsNone(row.ticket_no)
        self.assertIsNone(row.register_date)
        self.assertEqual(self._trash_count(), 0)

    def test_non_admin_cannot_delete_ticket(self):
        tab = self._make_browse(role="user")
        tab.buildInitial("ticket")
        with patch("tabs.tab_dbbrowse.confirmBox") as confirm:
            tab._onDelete("ticket", "1")
            confirm.assert_not_called()
        row = self._ticket_row("1")
        self.assertEqual(row.ticket_no, "AB1234")   # 未被刪除


if __name__ == "__main__":
    unittest.main()
