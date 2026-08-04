# -*- coding: utf-8 -*-
"""交辦單發文頁（tabs/tab_dispatch.py）的降權行為。

目前只涵蓋一條實際回報的回歸：**降權清空預覽表後，「尚有 N 筆已輸入未發文」
的橘色提醒條沒有跟著消失**。使用者登出時人就停在本頁，`on_activated` 不會
觸發，於是表格空了、橫幅還掛著，要切到別頁再切回來才會消失。

⚠️ 這頁的預覽列權限（降權改成逐列重刷而非整張清空）另有獨立計畫，屆時本檔
要一併改寫——那時「降權後 rowCount()==0」的前提就不成立了。
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

    def _queue_row(self, tab, doc_id="T0001"):
        """在預覽表塞一列並登記為待發文（等同掃入文號後的狀態）。"""
        row = tab.table.rowCount()
        tab.table.insertRow(row)
        tab.table.setItem(row, 1, QTableWidgetItem(doc_id))
        tab._pending.add(doc_id)
        tab._updatePendingBanner()

    def test_downgrade_clears_table_and_hides_pending_banner(self):
        """降權當下橫幅就要消失，不能等到切頁往返才對齊。"""
        tab = self._make_tab()
        self._queue_row(tab)
        self.assertTrue(tab._pending_banner.isVisibleTo(tab._pending_banner.parent()))

        am = AuthManager.instance()
        am._role = "user"
        am.role_changed.emit("user")

        self.assertEqual(tab.table.rowCount(), 0)
        self.assertEqual(tab._pending, set())
        self.assertFalse(tab._pending_banner.isVisibleTo(tab._pending_banner.parent()))

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
