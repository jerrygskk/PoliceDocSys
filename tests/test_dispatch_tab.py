# -*- coding: utf-8 -*-
"""交辦單發文頁（tabs/tab_dispatch.py）的降權行為。

⚠️ **2026-08-07 起降權不再清空預覽表，改為逐列重算權限**（列留著，該鎖的鎖）。
本檔的斷言隨之反轉：原本釘的是「降權後 rowCount()==0、橫幅消失」，那是把
資料庫瀏覽頁「僅管理者可改」的規則錯套到登錄／收發文頁上。

連帶：`3f1d14b` 修的「表格空了、橫幅還掛著『尚有 N 筆已輸入未發文』」不再
可能發生——成因正是清空，清空沒了症狀就不存在，改為釘住「橫幅依實際待發文
筆數重算」。

offscreen 執行；不彈任何 modal。
"""
import os
import sqlite3
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import (
    QApplication, QComboBox, QDateEdit, QLineEdit, QPushButton, QTableWidget,
    QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget)

import res.resources_rc          # 註冊 qrc，勿刪
from lib.auth_manager import AuthManager
from lib.db_schema import applySchema
from lib.db_seed import seedFreshDb

_app = QApplication.instance() or QApplication([])


class TestDispatchDowngrade(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self.db = os.path.join(self._tmp, "t.db")
        conn = sqlite3.connect(self.db)
        applySchema(conn)
        seedFreshDb(conn)
        conn.commit()
        conn.close()
        self._extra_tabs = []
        AuthManager.instance()._role = "admin"

    def tearDown(self):
        import shutil
        AuthManager.instance()._role = "user"
        for t in self._extra_tabs:
            t.deleteLater()
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _make_tab(self):
        """交辦單發文頁的元件掛在主視窗上（`tab_widget.window()` 取屬性），
        不是各自的 .ui，故這裡自備一個帶同名屬性的宿主視窗。"""
        from tabs.tab_dispatch import TabDispatch
        tabs = QTabWidget()
        page = QWidget()
        QVBoxLayout(page)
        tabs.addTab(page, "交辦單發文")
        tabs.lineEdit_docNum   = QLineEdit(tabs)
        tabs.tableWidget       = QTableWidget(0, len(TabDispatch.HEADERS), tabs)
        tabs.dispatch_date     = QDateEdit(tabs)
        tabs.dispatch_sender   = QComboBox(tabs)
        tabs.dispatch_sender.setEditable(True)   # 正式 .ui 即為可編輯，setupFilterCombo 需要
        tabs.btn_send          = QPushButton(tabs)
        tabs.btn_clear_all     = QPushButton(tabs)
        tabs.btn_input_docnum  = QPushButton(tabs)
        self._extra_tabs.append(tabs)
        tab = TabDispatch(tabs, self.db)
        tab.setup(0)
        return tab

    def _queue_row(self, tab, doc_id="T0001", dispatch_date=None):
        """在預覽表塞一列並登記為待發文（等同掃入文號後的狀態）。

        同時在 DB 建出對應的交辦單——逐列重刷一律回查 DB 判斷發文狀態，
        DB 沒有這筆就等於「已被刪除」而不給任何入口。
        """
        conn = sqlite3.connect(self.db)
        conn.execute(
            "INSERT OR REPLACE INTO Document_Task"
            "(doc_id,subject,dispatch_date) VALUES(?,?,?)",
            (doc_id, "測試交辦事由", dispatch_date))
        conn.commit()
        conn.close()
        # 走真正的插入路徑（會建出刪除鈕與編號欄連結），不自己塞 item——
        # 手工塞列測不到 `_insertRow` 內的權限計算。
        tab._insertRow((doc_id, "測試交辦事由", "偵查隊", "承辦員",
                        "2026-08-31", dispatch_date))

    def test_downgrade_keeps_table_and_pending_banner(self):
        """⚠️ 2026-08-07 起降權**不再清空清單**：列留著、橫幅照實際待發文筆數算。

        原本降權整張清掉，等於讓一般使用者失去他本來就有的入口（交辦單發文頁
        的未發文列對所有身分開放，只是一般使用者僅能改承辦人）。
        """
        tab = self._make_tab()
        self._queue_row(tab)
        self.assertTrue(tab._pending_banner.isVisibleTo(tab._pending_banner.parent()))

        am = AuthManager.instance()
        am._role = "user"
        am.role_changed.emit("user")

        self.assertEqual(tab.table.rowCount(), 1)
        self.assertEqual(tab._pending, {"T0001"})
        self.assertTrue(tab._pending_banner.isVisibleTo(tab._pending_banner.parent()))

    def test_downgrade_locks_dispatched_rows_only(self):
        """已發文的列對一般使用者鎖住（編號變純文字），未發文的仍可點。"""
        tab = self._make_tab()
        self._queue_row(tab, "T0001")                       # 未發文
        self._queue_row(tab, "T0002", dispatch_date="2026-08-01")   # 已發文

        am = AuthManager.instance()
        am._role = "user"
        am.role_changed.emit("user")

        # 可點＝連結（cellWidget）；不可點＝純文字 item
        self.assertIsNotNone(tab.table.cellWidget(0, 1))
        self.assertIsNone(tab.table.cellWidget(1, 1))
        self.assertEqual(tab.table.item(1, 1).text(), "T0002")

    def test_downgrade_keeps_queue_remove_button_enabled(self):
        """✕ 是「從待發文佇列移除」（不碰 DB），恆啟用，不隨身分反灰。"""
        tab = self._make_tab()
        self._queue_row(tab, "T0001", dispatch_date="2026-08-01")

        am = AuthManager.instance()
        am._role = "user"
        am.role_changed.emit("user")

        container = tab.table.cellWidget(0, 0)
        self.assertIsNotNone(container)
        for btn in container.findChildren(QPushButton):
            self.assertTrue(btn.isEnabled())

    def test_manager_role_change_keeps_pending_banner(self):
        """升權／管理身分之間切換不清單，橫幅照舊。"""
        tab = self._make_tab()
        self._queue_row(tab)

        am = AuthManager.instance()
        am._role = "archive"
        am.role_changed.emit("archive")

        self.assertEqual(tab.table.rowCount(), 1)
        self.assertTrue(tab._pending_banner.isVisibleTo(tab._pending_banner.parent()))


if __name__ == "__main__":
    unittest.main()
