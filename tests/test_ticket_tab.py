# -*- coding: utf-8 -*-
"""罰單登錄頁（Layout11.ui／tabs/tab_ticket.py）的版面契約與 Tab 行為。

涵蓋：
  - Layout11.ui 物件名契約（改名／刪元件即紅）
  - 兩種模式（自助取號／發文者登錄）的發文人員欄狀態與提示標籤
  - 必填驗證（純函式 `_validateInput()`，不彈視窗）
  - 新增／編輯／刪除的 DB round-trip 與稽核安全（自助模式強制 sender NULL）
  - 候選人員＝直接取代開立人員（取 currentData，不猜姓名字串）
offscreen 執行；任何會彈 QMessageBox 的路徑一律 patch，否則測試永久卡死。
"""
import os
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QDate, QObject
from PySide6.QtWidgets import QApplication, QTabWidget, QWidget

import res.resources_rc          # 註冊 qrc，勿刪
from lib.db_schema import applySchema
from ui_utils import loadUi
import tabs.tab_ticket as tab_ticket_module

_app = QApplication.instance() or QApplication([])

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_LAYOUT = os.path.join(_ROOT, "layouts", "Layout11.ui")

_OBJECT_NAMES = (
    "ticket_sender", "ticket_issuer", "ticket_clear_issuer",
    "ticket_no", "ticket_table", "ticket_add", "ticket_candidates",
)


class TestTicketLayoutContract(unittest.TestCase):
    def setUp(self):
        # 先驗檔案存在再 loadUi：檔案不存在時 loadUi 會彈 msgCritical，
        # offscreen 下該 modal 永遠等不到人按，整組測試會卡死。
        self.assertTrue(os.path.exists(_LAYOUT), "缺少 layouts/Layout11.ui")

    def test_ticket_layout_contract(self):
        ui = loadUi(_LAYOUT)
        self.assertIsNotNone(ui)
        for name in _OBJECT_NAMES:
            self.assertIsNotNone(ui.findChild(QObject, name), name)
        ui.deleteLater()

    def test_ticket_layout_has_visible_self_service_hint_label(self):
        # 自助模式提示不可只靠 tooltip（深色模式下 tooltip 整塊黑，PITFALLS QSS-7）
        from PySide6.QtWidgets import QLabel
        ui = loadUi(_LAYOUT)
        hint = ui.findChild(QLabel, "ticket_sender_hint")
        self.assertIsNotNone(hint)
        self.assertTrue(hint.text().strip())
        ui.deleteLater()


class TicketTabBase(unittest.TestCase):
    def setUp(self):
        fd, self.db = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        conn = sqlite3.connect(self.db)
        applySchema(conn)
        conn.executescript("""
            INSERT INTO Ref_Personnel(staff_id,staff_name,is_active,sort_order)
                VALUES('P001','測試甲',1,1),('P002','測試乙',1,2),
                      ('P003','測試丙',1,3);
        """)
        conn.commit()
        conn.close()
        self.tabs = QTabWidget()
        self.tabs.addTab(QWidget(), "罰單登錄")

    def tearDown(self):
        self.tabs.deleteLater()
        try:
            os.remove(self.db)
        except OSError:
            pass

    def _set_self_service(self, on):
        conn = sqlite3.connect(self.db)
        conn.execute("INSERT OR REPLACE INTO App_Settings(key,value) "
                     "VALUES('report_mode_ticket',?)", ("1" if on else "0",))
        conn.commit()
        conn.close()

    def _make_tab(self):
        from tabs.tab_ticket import TabTicket
        tab = TabTicket(self.tabs, self.db)
        tab.setup(0)
        return tab

    def _index_for(self, staff_id, tab=None, combo=None):
        combo = combo if combo is not None else tab.ticket_issuer
        return combo.findData(staff_id)

    def _fill(self, tab, *, issuer="P001", sender=None, ticket_no="D4RD15263"):
        tab.ticket_issuer.setCurrentIndex(self._index_for(issuer, tab))
        if sender is not None:
            tab.ticket_sender.setCurrentIndex(
                self._index_for(sender, combo=tab.ticket_sender))
        tab.ticket_no.setText(ticket_no)

    def _rows(self):
        conn = sqlite3.connect(self.db)
        try:
            return conn.execute(
                "SELECT doc_id,create_date,register_date,sender_id,issuer_id,"
                "ticket_no FROM Document_Ticket "
                "ORDER BY CAST(doc_id AS INTEGER)").fetchall()
        finally:
            conn.close()


class TestTicketMode(TicketTabBase):
    def test_self_service_keeps_sender_visible_but_disabled(self):
        self._set_self_service(True)
        tab = self._make_tab()
        tab._applyInputLock()
        self.assertFalse(tab.ticket_sender.isHidden())   # 保留位置、不可隱藏
        self.assertFalse(tab.ticket_sender.isEnabled())
        self.assertTrue(tab.ticket_sender_hint.isVisibleTo(tab.ticket_sender_hint.parent()))

    def test_sender_mode_enables_sender_and_hides_hint(self):
        self._set_self_service(False)
        tab = self._make_tab()
        tab._applyInputLock()
        self.assertTrue(tab.ticket_sender.isEnabled())
        self.assertFalse(
            tab.ticket_sender_hint.isVisibleTo(tab.ticket_sender_hint.parent()))

    def test_mode_is_reapplied_on_tab_reentry(self):
        # 模式判斷不可只在 setup() 做一次
        self._set_self_service(False)
        tab = self._make_tab()
        self.assertTrue(tab.ticket_sender.isEnabled())
        self._set_self_service(True)
        tab._onShown(0)
        self.assertFalse(tab.ticket_sender.isEnabled())
        self._set_self_service(False)
        tab.on_activated()
        self.assertTrue(tab.ticket_sender.isEnabled())


class TestTicketValidation(TicketTabBase):
    def test_sender_mode_requires_sender(self):
        self._set_self_service(False)
        tab = self._make_tab()
        tab.ticket_issuer.setCurrentIndex(self._index_for("P001", tab))
        tab.ticket_no.setText("D4RD15263")
        self.assertFalse(tab._validateInput())

    def test_sender_mode_valid_when_all_filled(self):
        self._set_self_service(False)
        tab = self._make_tab()
        self._fill(tab, sender="P002")
        self.assertTrue(tab._validateInput())

    def test_self_service_does_not_require_sender(self):
        self._set_self_service(True)
        tab = self._make_tab()
        self._fill(tab)
        self.assertTrue(tab._validateInput())

    def test_issuer_and_ticket_no_always_required(self):
        self._set_self_service(True)
        tab = self._make_tab()
        tab.ticket_no.setText("D4RD15263")
        self.assertFalse(tab._validateInput())     # 缺開立人員
        self._fill(tab, ticket_no="   ")
        self.assertFalse(tab._validateInput())     # 缺罰單編號


class TestTicketSubmit(TicketTabBase):
    def test_self_service_submit_ignores_residual_sender_value(self):
        self._set_self_service(True)
        tab = self._make_tab()
        # 反灰前殘留在 UI 的發文者值，提交時一律不得採用
        tab.ticket_sender.setCurrentIndex(
            self._index_for("P002", combo=tab.ticket_sender))
        self._fill(tab)
        # 直接釘住 Tab 層守衛：Tab 傳給 createTicket 的 sender_id 引數本身必須
        # 是 None。若只驗 DB 欄位，createTicket 內部對自助模式的覆寫會遮住
        # Tab 層破口，讓「Tab 誤讀殘留值」的 bug 測不出來（審查踩過）。
        with patch("tabs.tab_ticket.createTicket",
                   wraps=tab_ticket_module.createTicket) as spy:
            tab._submit()
        self.assertEqual(spy.call_count, 1)
        self.assertIsNone(spy.call_args.kwargs["sender_id"])
        self.assertTrue(spy.call_args.kwargs["self_service"])
        rows = self._rows()
        self.assertEqual(len(rows), 1)
        _, create_date, register_date, sender_id, issuer_id, ticket_no = rows[0]
        self.assertEqual(register_date, "")
        self.assertIsNone(sender_id)
        self.assertEqual(issuer_id, "P001")
        self.assertEqual(ticket_no, "D4RD15263")
        self.assertEqual(create_date, QDate.currentDate().toString("yyyy-MM-dd"))

    def test_sender_mode_submit_writes_register_date_and_sender(self):
        self._set_self_service(False)
        tab = self._make_tab()
        self._fill(tab, sender="P002", ticket_no=" d4rd15263 ")
        tab._submit()
        rows = self._rows()
        self.assertEqual(len(rows), 1)
        _, create_date, register_date, sender_id, issuer_id, ticket_no = rows[0]
        self.assertEqual(register_date, create_date)
        self.assertEqual(sender_id, "P002")
        self.assertEqual(ticket_no, "D4RD15263")   # 正規化：trim + 轉大寫

    def test_preview_shows_trimmed_issuer_name(self):
        # 預覽表「開立人員」欄顯示去後綴姓名，與同頁下拉／候選清單一致
        # （View 的 issuer_name 是未去後綴原值）。
        conn = sqlite3.connect(self.db)
        conn.execute("UPDATE Ref_Personnel SET staff_name='測試甲-19.06' "
                     "WHERE staff_id='P001'")
        conn.commit()
        conn.close()
        self._set_self_service(True)
        tab = self._make_tab()
        self._fill(tab, issuer="P001")
        tab._submit()
        self.assertEqual(tab.ticket_table.item(0, 5).text(), "測試甲")

    def test_submit_keeps_personnel_and_clears_ticket_no(self):
        self._set_self_service(True)
        tab = self._make_tab()
        self._fill(tab)
        tab._submit()
        self.assertEqual(tab.ticket_no.text(), "")
        self.assertEqual(tab.ticket_issuer.currentData(), "P001")
        self.assertEqual(tab.ticket_table.rowCount(), 1)
        self.assertEqual(len(tab._session_doc_ids), 1)

    def test_duplicate_ticket_no_is_blocked_with_warning(self):
        self._set_self_service(True)
        tab = self._make_tab()
        self._fill(tab)
        tab._submit()
        self._fill(tab, issuer="P002", ticket_no="d4rd15263")
        with patch("tabs.tab_ticket.msgWarning") as warn:
            tab._submit()
            warn.assert_called_once()
        self.assertEqual(len(self._rows()), 1)

    def test_invalid_ticket_no_is_blocked_with_warning(self):
        self._set_self_service(True)
        tab = self._make_tab()
        self._fill(tab, ticket_no="D4RD-152")
        with patch("tabs.tab_ticket.msgWarning") as warn:
            tab._submit()
            warn.assert_called_once()
        self.assertEqual(self._rows(), [])

    def test_submit_writes_no_audit_row(self):
        """登錄不寫操作紀錄（罰單只在刪除時寫，見 ticket_utils）。"""
        self._set_self_service(True)
        tab = self._make_tab()
        self._fill(tab)
        tab._submit()
        conn = sqlite3.connect(self.db)
        rows = conn.execute(
            "SELECT action,target_table FROM Audit_Log").fetchall()
        conn.close()
        self.assertEqual(rows, [])


class TestTicketPreviewCells(TicketTabBase):
    """預覽表第 0 欄 ✕ 刪除鈕、第 1 欄編號超連結，比照敘獎登錄的做法。"""

    def test_delete_button_and_doc_link_placement(self):
        from PySide6.QtWidgets import QLabel, QPushButton
        self._set_self_service(True)
        tab = self._make_tab()
        self._fill(tab)
        tab._submit()
        doc_id = tab._session_doc_ids[0]

        delete_widget = tab.ticket_table.cellWidget(0, 0)
        self.assertIsNotNone(delete_widget)
        self.assertIsNotNone(delete_widget.findChild(QPushButton, "deleteBtn"))

        link = tab.ticket_table.cellWidget(0, 1)
        self.assertIsInstance(link, QLabel)
        with patch("tabs.tab_ticket.TicketEditDialog") as dlg_cls:
            dlg_cls.return_value.exec.return_value = False
            link.linkActivated.emit(doc_id)
            dlg_cls.assert_called_once_with(tab.db_path, doc_id, tab.ticket_table)

    def test_preview_stretch_column_is_trailing_blank(self):
        """伸縮欄必須是最右側的空欄，不可是「罰單編號」。

        踩過的雷：預覽表把資料欄設成伸縮欄，視窗一拉寬該欄就被拉成整個
        視窗長度、版面爛掉，且右側候選人員面板（固定 240）會被擠壓。
        欄位配置改動時本測試必須跟著檢視，不要只改斷言數字了事。
        """
        tab = self._make_tab()
        headers = tab.PREVIEW_HEADERS
        self.assertEqual(headers[-1], "", "最右欄必須是空標題欄（供伸縮用）")
        self.assertEqual(tab.ticket_table.columnCount(), len(headers))
        stretch_col = tab.ticket_table.property("stretch_col")
        self.assertEqual(stretch_col, len(headers) - 1)
        # 罰單編號與開立人員同寬且固定，不參與伸縮
        self.assertEqual(headers[stretch_col - 2], "罰單編號")
        self.assertEqual(headers[stretch_col - 1], "開立人員")

    def test_preview_stretch_absorbs_width_and_fixed_cols_stay(self):
        """拉寬時只有伸縮欄變寬，其餘欄寬不動（右側面板不被擠壓的前提）。"""
        from PySide6.QtWidgets import QApplication
        from ui_utils.table import autoResizeTable
        tab = self._make_tab()
        table = tab.ticket_table
        stretch_col = table.property("stretch_col")

        # autoResizeTable 讀 viewport().width()，未 show 的 widget 量不到真實
        # 寬度（會小 500px 並走到「空間不足」分支）→ 必須 show + processEvents。
        table.show()
        for width, bucket in ((700, "narrow"), (1140, "wide")):
            table.resize(width, 300)
            QApplication.processEvents()
            autoResizeTable(table)
            cols = [table.columnWidth(c) for c in range(table.columnCount())]
            if bucket == "narrow":
                narrow = cols
            else:
                wide = cols

        for col in range(table.columnCount()):
            if col == stretch_col:
                self.assertGreater(wide[col], narrow[col],
                                   "伸縮欄應吸收變寬的空間")
            else:
                self.assertEqual(wide[col], narrow[col],
                                 f"第 {col} 欄不應隨視窗變寬而改變")
        self.assertEqual(narrow[stretch_col - 2], narrow[stretch_col - 1],
                         "罰單編號與開立人員應同寬")

    def test_preview_recomputes_on_window_resize_without_explicit_call(self):
        """放大視窗必須自動重算欄寬（不再需要切頁才更新）。

        實機踩過：最大化後伸縮欄停在舊寬度，表格右側留下一片空白。
        本測試刻意**不呼叫** autoResizeTable，只放大表格並等 debounce。
        """
        from PySide6.QtWidgets import QApplication, QTableWidget
        from tabs.tab_ticket import TabTicket
        from ui_utils.table import setupPreviewTable
        # ⚠️ 用獨立 table，不要拿分頁裡的：分頁內的表格受 layout 管理，
        # 直接 resize() 會在下一輪事件迴圈被 layout 還原，等 debounce 跑完時
        # 寬度早就變回去了（本測試踩過）。這裡驗的是監看機制本身。
        table = QTableWidget()
        setupPreviewTable(table, TabTicket.PREVIEW_HEADERS,
                          stretch_col=len(TabTicket.PREVIEW_HEADERS) - 1,
                          fixed_overrides={"登錄日期": 120})
        stretch_col = table.property("stretch_col")

        table.show()
        table.resize(700, 300)
        QApplication.processEvents()
        self._settle()
        before = table.columnWidth(stretch_col)

        table.resize(1300, 300)
        QApplication.processEvents()
        self._settle()
        self.assertGreater(table.columnWidth(stretch_col), before,
                           "放大視窗後伸縮欄未重算，右側會留白")
        table.deleteLater()

    @staticmethod
    def _settle(ms=400):
        """等 viewport resize 的 80ms debounce 跑完（不 sleep 死等，仍跑事件迴圈）。"""
        from PySide6.QtCore import QEventLoop, QTimer
        loop = QEventLoop()
        QTimer.singleShot(ms, loop.quit)
        loop.exec()


class TestTicketIssuerSelection(TicketTabBase):
    def test_candidate_click_replaces_issuer_using_staff_id(self):
        tab = self._make_tab()
        self._fill(tab, issuer="P001")
        item = None
        for i in range(tab.ticket_candidates_list.count()):
            cand = tab.ticket_candidates_list.item(i)
            if tab._candidateStaffId(cand) == "P003":
                item = cand
        self.assertIsNotNone(item)
        tab._onCandidateClicked(item)
        self.assertEqual(tab.ticket_issuer.currentData(), "P003")

    def test_clear_button_only_clears_issuer(self):
        tab = self._make_tab()
        self._fill(tab, sender="P002")
        tab._clearIssuer()
        self.assertIsNone(tab.ticket_issuer.currentData())
        self.assertEqual(tab.ticket_issuer.currentText().strip(), "")
        self.assertEqual(tab.ticket_sender.currentData(), "P002")
        self.assertEqual(tab.ticket_no.text(), "D4RD15263")

    def test_candidate_order_follows_personnel_sort_order_not_usage(self):
        """候選清單一律照 Ref_Personnel 的 sort_order，不受開立次數影響。"""
        conn = sqlite3.connect(self.db)
        # P003 開了最多罰單，但它的 sort_order 在最後 → 仍須排在最後
        for i in range(3):
            conn.execute(
                "INSERT INTO Document_Ticket(doc_id,create_date,register_date,"
                "sender_id,issuer_id,ticket_no) "
                "VALUES(?,?,?,?,?,?)",
                (str(100 + i), "2026-07-20", "2026-07-20", "P001", "P003",
                 f"AA{i}"))
        conn.commit()
        rows = conn.execute(
            "SELECT staff_id FROM Ref_Personnel WHERE is_active=1 "
            "ORDER BY sort_order,staff_id").fetchall()
        conn.close()
        expected = [r[0] for r in rows]
        tab = self._make_tab()
        actual = [tab._candidateStaffId(tab.ticket_candidates_list.item(i))
                  for i in range(tab.ticket_candidates_list.count())]
        self.assertEqual(actual, expected)


class TestTicketDelete(TicketTabBase):
    def _submit_one(self, tab):
        self._set_self_service(True)
        self._fill(tab)
        tab._submit()
        return tab._session_doc_ids[0]

    def test_delete_requires_confirmation_mentioning_irreversible_and_reuse(self):
        tab = self._make_tab()
        doc_id = self._submit_one(tab)
        with patch("tabs.tab_ticket.confirmBox", return_value=False) as ask:
            tab._deleteByDocId(doc_id)
            ask.assert_called_once()
            text = " ".join(str(a) for a in ask.call_args.args) + \
                " ".join(str(v) for v in ask.call_args.kwargs.values())
        self.assertIn("不可還原", text)
        self.assertIn("重新登錄", text)
        self.assertEqual(len(self._rows()), 1)   # 取消＝不刪

    def test_delete_soft_deletes_and_frees_ticket_no(self):
        tab = self._make_tab()
        doc_id = self._submit_one(tab)
        with patch("tabs.tab_ticket.confirmBox", return_value=True):
            tab._deleteByDocId(doc_id)
        rows = self._rows()
        self.assertEqual(len(rows), 1)           # 軟刪除：保留 doc_id 空殼
        self.assertEqual(rows[0][0], doc_id)
        self.assertIsNone(rows[0][2])            # register_date NULL
        self.assertIsNone(rows[0][5])            # ticket_no 清空
        self.assertEqual(tab.ticket_table.rowCount(), 0)
        self.assertEqual(tab._session_doc_ids, [])
        # 同編號可重新登錄
        self._fill(tab)
        tab._submit()
        self.assertEqual(len(self._rows()), 2)

    def test_delete_writes_audit_row(self):
        tab = self._make_tab()
        doc_id = self._submit_one(tab)
        with patch("tabs.tab_ticket.confirmBox", return_value=True):
            tab._deleteByDocId(doc_id)
        conn = sqlite3.connect(self.db)
        rows = conn.execute(
            "SELECT action,target_table,target_id FROM Audit_Log "
            "ORDER BY log_id").fetchall()
        conn.close()
        # 只有刪除留紀錄；新增那筆不寫
        self.assertEqual(rows, [("DELETE", "Document_Ticket", doc_id)])


class TestTicketInputLock(TicketTabBase):
    """跨年度唯讀鎖（input_lock_ticket）：只擋一般使用者新增，不擋 admin／archive，
    不擋既有資料 edit／delete。反灰＋紅橫幅＋_submit 硬性 guard 多層防護。"""

    def setUp(self):
        super().setUp()
        self._set_self_service(True)   # 免發文者欄，聚焦鎖行為
        self._extra_tabs = []
        from lib.auth_manager import AuthManager
        AuthManager.instance()._role = "user"

    def tearDown(self):
        for t in self._extra_tabs:
            t.deleteLater()
        # 還原單例身分（不 emit，避免波及其他測試殘留的 tab wrapper）
        from lib.auth_manager import AuthManager
        AuthManager.instance()._role = "user"
        super().tearDown()

    def _make_tab(self):
        # 每個 tab 自帶 QTabWidget，避免同一測試建多個 tab 撞到同一 widget(0)。
        from tabs.tab_ticket import TabTicket
        tabs = QTabWidget()
        tabs.addTab(QWidget(), "罰單登錄")
        self._extra_tabs.append(tabs)
        tab = TabTicket(tabs, self.db)
        tab.setup(0)
        return tab

    def _make_multi_tab(self):
        """兩個分頁的 QTabWidget（本頁在 index 1），供真的 emit currentChanged
        做切頁往返；單一分頁的 widget 切不動、測不出切回頁時的復活。"""
        from tabs.tab_ticket import TabTicket
        tabs = QTabWidget()
        tabs.addTab(QWidget(), "其他頁")
        tabs.addTab(QWidget(), "罰單登錄")
        self._extra_tabs.append(tabs)
        tab = TabTicket(tabs, self.db)
        tab.setup(1)
        return tabs, tab

    def _set_lock(self, on):
        conn = sqlite3.connect(self.db)
        conn.execute("INSERT OR REPLACE INTO App_Settings(key,value) "
                     "VALUES('input_lock_ticket',?)", ("1" if on else "",))
        conn.commit()
        conn.close()

    def _set_role(self, role, *, emit=False):
        from lib.auth_manager import AuthManager
        am = AuthManager.instance()
        am._role = role
        if emit:
            am.role_changed.emit(role)

    def test_locked_blocks_regular_submit_but_allows_admin_and_archive(self):
        self._set_lock(True)
        self._set_role("user")
        regular = self._make_tab()
        self._fill(regular)
        with patch("tabs.tab_ticket.msgWarning"):
            regular._submit()
        self.assertEqual(len(self._rows()), 0)
        for role in ("admin", "archive"):
            with self.subTest(role=role):
                self._set_role(role)
                manager = self._make_tab()
                self._fill(manager, ticket_no=f"MG{role[:2].upper()}01")
                manager._submit()
        self.assertEqual(len(self._rows()), 2)

    def test_locked_regular_user_disables_inputs_and_shows_banner(self):
        self._set_role("user")
        tab = self._make_tab()
        self._set_lock(True)
        tab._onShown(0)   # 切回本頁重套
        self.assertFalse(tab.ticket_add.isEnabled())
        self.assertFalse(tab.ticket_no.isEnabled())
        self.assertFalse(tab.ticket_issuer.isEnabled())
        self.assertFalse(tab.ticket_candidates_list.isEnabled())
        # offscreen 無 show()：以 isHidden 判斷本身可見旗標（isVisible 受祖鏈影響）
        self.assertFalse(tab._readonly_banner.isHidden())

    def test_manager_never_locked_and_banner_hidden(self):
        self._set_lock(True)
        self._set_role("admin")
        tab = self._make_tab()
        self.assertTrue(tab.ticket_add.isEnabled())
        self.assertTrue(tab.ticket_candidates_list.isEnabled())
        self.assertTrue(tab._readonly_banner.isHidden())

    def test_submit_hard_guard_blocks_even_when_inputs_bypassed(self):
        # 反灰可被替代路徑繞過；hard guard 是保底。移除 guard 此測試須轉紅。
        self._set_lock(True)
        self._set_role("user")
        tab = self._make_tab()
        self._fill(tab)
        with patch("tabs.tab_ticket.msgWarning") as warn, \
             patch("tabs.tab_ticket.createTicket") as create:
            tab._submit()
            warn.assert_called_once()
            create.assert_not_called()
        self.assertEqual(len(self._rows()), 0)

    def test_manager_downgrade_clears_preview(self):
        # 管理身分登錄後降權：清除本次登錄預覽，避免保留管理身分建立的入口。
        self._set_role("admin")
        tab = self._make_tab()
        self._fill(tab)
        tab._submit()
        self.assertEqual(tab.ticket_table.rowCount(), 1)
        self._set_role("user", emit=True)
        self.assertEqual(tab.ticket_table.rowCount(), 0)

    def test_manager_downgrade_clears_preview_persistently_across_tab_switch(self):
        """降權清空必須具持續性：切頁往返後仍是 0 列。

        ⚠️ 只斷言降權當下 `rowCount()==0` 是假保證：`_onRoleClearList` 若只清
        表格 widget、不清 `self._session_doc_ids`，`_onShown`（無條件
        `on_activated()→reload()`）會把整份清單從 DB 重建回來，降權後的一般
        使用者就取得「編輯／刪除管理身分建立之罰單」的入口（同一筆在瀏覽頁
        是僅 admin 可改）。必須真的 emit `currentChanged`，直接呼叫
        `reload()`／`on_activated()` 也測得到，但不代表實際掛鉤點有生效。
        """
        self._set_role("admin")
        tabs, tab = self._make_multi_tab()
        self._fill(tab)
        tab._submit()
        doc_id = tab._session_doc_ids[0]
        self.assertEqual(tab.ticket_table.rowCount(), 1)

        self._set_role("user", emit=True)
        self.assertEqual(tab.ticket_table.rowCount(), 0)

        # 真的切走再切回（emit currentChanged→_onShown→on_activated→reload）
        tabs.setCurrentIndex(0)
        tabs.setCurrentIndex(1)

        self.assertEqual(tab.ticket_table.rowCount(), 0)
        self.assertEqual(tab._session_doc_ids, [])
        # 表格 0 列＝編輯／刪除進入點取不到 doc_id（清的是入口，不是資料）
        rows = self._rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][0], doc_id)
        self.assertEqual(rows[0][5], "D4RD15263")   # 資料仍在，未被清空

    def test_lock_does_not_block_delete_of_existing(self):
        # 先以未鎖狀態建一筆，再上鎖，一般使用者仍可刪除既有資料。
        self._set_role("user")
        tab = self._make_tab()
        self._fill(tab)
        tab._submit()
        doc_id = tab._session_doc_ids[0]
        self.assertEqual(len(self._rows()), 1)
        self._set_lock(True)
        tab._onShown(0)
        with patch("tabs.tab_ticket.confirmBox", return_value=True):
            tab._deleteByDocId(doc_id)
        rows = self._rows()
        self.assertEqual(len(rows), 1)          # 軟刪除保留空殼
        self.assertIsNone(rows[0][5])           # ticket_no 已清空
        self.assertEqual(tab.ticket_table.rowCount(), 0)


class TestTicketCrossPageRefresh(TicketTabBase):
    """切回罰單登錄頁必須反映其他頁的異動（瀏覽頁 admin 編輯／自助結算）。

    ⚠️ 真正的刷新掛鉤點是 `tab_widget.currentChanged→_onShown`（`main.
    _onTabChanged` 不會對本頁呼叫 `on_activated`，見 DEVELOPER「刷新時機」）；
    `_onShown` 若未覆寫成呼叫 `on_activated()`，本頁只會重套唯讀鎖，預覽表
    形同凍結——直接呼叫 `tab.reload()`／`tab.on_activated()` 測不出這個雷，
    必須真的 emit `currentChanged` 訊號。"""

    def _make_multi_tab(self):
        from tabs.tab_ticket import TabTicket
        tabs = QTabWidget()
        tabs.addTab(QWidget(), "其他頁")
        tabs.addTab(QWidget(), "罰單登錄")
        self._extra_tabs = getattr(self, "_extra_tabs", [])
        self._extra_tabs.append(tabs)
        tab = TabTicket(tabs, self.db)
        tab.setup(1)
        return tabs, tab

    def tearDown(self):
        for t in getattr(self, "_extra_tabs", []):
            t.deleteLater()
        super().tearDown()

    def test_switching_back_via_signal_reflects_external_settlement(self):
        # 比照自助結算：外部直接 UPDATE register_date/sender_id（settle_selected
        # 的效果），模擬另一頁（列印頁「結算發文」）幫這筆罰單補了發文日期。
        self._set_self_service(True)
        tabs, tab = self._make_multi_tab()
        self._fill(tab)
        tab._submit()
        doc_id = tab._session_doc_ids[0]
        self.assertEqual(tab.ticket_table.item(0, 3).text(), "未發文")

        conn = sqlite3.connect(self.db)
        conn.execute(
            "UPDATE Document_Ticket SET register_date=?, sender_id=? "
            "WHERE doc_id=?", ("2026-07-23", "P002", doc_id))
        conn.commit()
        conn.close()

        # 真的切走再切回（emit currentChanged），不直接呼叫 reload()/on_activated()。
        tabs.setCurrentIndex(0)
        tabs.setCurrentIndex(1)

        self.assertEqual(tab.ticket_table.item(0, 3).text(), "2026-07-23")

    def test_switching_back_via_signal_reflects_browse_admin_edit(self):
        self._set_self_service(False)
        tabs, tab = self._make_multi_tab()
        self._fill(tab, sender="P002")
        tab._submit()
        doc_id = tab._session_doc_ids[0]

        from lib.ticket_utils import updateTicketFromBrowse
        conn = sqlite3.connect(self.db)
        original_values = conn.execute(
            "SELECT create_date,register_date,sender_id,issuer_id,ticket_no "
            "FROM Document_Ticket WHERE doc_id=?", (doc_id,)
        ).fetchone()
        updateTicketFromBrowse(
            conn, doc_id=doc_id, create_date="2026-07-01",
            register_date="2026-07-01", sender_id="P002",
            issuer_id="P003", ticket_no="ZZ9999", role="admin",
            original_values=original_values)
        conn.commit()
        conn.close()

        tabs.setCurrentIndex(0)
        tabs.setCurrentIndex(1)

        self.assertEqual(tab.ticket_table.item(0, 4).text(), "ZZ9999")


class TestTicketEdit(TicketTabBase):
    def test_edit_updates_issuer_and_ticket_no_only(self):
        self._set_self_service(False)
        tab = self._make_tab()
        self._fill(tab, sender="P002")
        tab._submit()
        doc_id = tab._session_doc_ids[0]
        before = self._rows()[0]
        from ui_utils.ticket_dialog import TicketEditDialog
        dlg = TicketEditDialog(self.db, doc_id)
        dlg.w_issuer.setCurrentIndex(dlg.w_issuer.findData("P003"))
        dlg.w_ticket_no.setText("aa99")
        dlg._on_save()
        after = self._rows()[0]
        self.assertEqual(after[1], before[1])    # create_date 不變
        self.assertEqual(after[2], before[2])    # register_date 不變
        self.assertEqual(after[3], before[3])    # sender_id 不變
        self.assertEqual(after[4], "P003")
        self.assertEqual(after[5], "AA99")
        dlg.deleteLater()

    def test_edit_writes_no_audit_row(self):
        self._set_self_service(False)
        tab = self._make_tab()
        self._fill(tab, sender="P002")
        tab._submit()
        doc_id = tab._session_doc_ids[0]
        from ui_utils.ticket_dialog import TicketEditDialog
        dlg = TicketEditDialog(self.db, doc_id)
        dlg.w_issuer.setCurrentIndex(dlg.w_issuer.findData("P003"))
        dlg.w_ticket_no.setText("aa99")
        dlg._on_save()
        dlg.deleteLater()
        conn = sqlite3.connect(self.db)
        rows = conn.execute(
            "SELECT action,target_table,target_id FROM Audit_Log "
            "ORDER BY log_id").fetchall()
        conn.close()
        self.assertEqual(rows, [])   # 新增與修改皆不寫，只有刪除寫

    def test_edit_reloads_preview_row(self):
        self._set_self_service(True)
        tab = self._make_tab()
        self._fill(tab)
        tab._submit()
        conn = sqlite3.connect(self.db)
        conn.execute("UPDATE Document_Ticket SET ticket_no='ZZ1' "
                     "WHERE doc_id=?", (tab._session_doc_ids[0],))
        conn.commit()
        conn.close()
        tab.reload()
        self.assertEqual(tab.ticket_table.item(0, 4).text(), "ZZ1")


if __name__ == "__main__":
    unittest.main()
