from datetime import datetime

from PySide6.QtCore import QDate, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QLabel, QLineEdit, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout,
)

from lib.base_tab import BaseTab
from lib.db_utils import REWARD_ACTIVE_SQL, getResourcePath, rewardState
from ui_utils import (
    attachStickyScroll, autoResizeTable, confirmBox, loadUi, makeDeleteBtn,
    msgInfo, msgWarning, refreshFilterCombo, reportError, setupDateEditToToday,
    setupFilterCombo, setupPreviewTable,
)


_ISSUE_DATE_COLOR = "#e67e22"

_PENDING_BANNER_CSS = (
    "background-color: #fdf3e0; color: #8a5c14; border: 1px solid #f0d9a8;"
    "border-radius: 7px; padding: 6px 14px; font-weight: 600;")


class TabRewardIssue(BaseTab):
    """敘獎發文：輸入編號加入清單，再批次設定發文日期與人員。"""

    HEADERS = ["", "編號", "登錄日期", "發文日期", "敘獎事由", "敘獎人員"]

    def setup(self, tab_index):
        tab = self.tab_widget.widget(tab_index)
        if not tab:
            return
        loaded = loadUi(getResourcePath("layouts/Layout10.ui"))
        if not loaded:
            return
        inner = loaded.centralWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(inner)
        self._loaded_ui = loaded

        self.lineEdit = inner.findChild(QLineEdit, "lineEdit_reward_num")
        self.table = inner.findChild(QTableWidget, "reward_issue_table")
        self.issue_date = getattr(loaded, "reward_issue_date", None)
        self.issue_sender = getattr(loaded, "reward_issue_sender", None)
        btn_input = inner.findChild(QPushButton, "btn_reward_input")
        btn_issue = inner.findChild(QPushButton, "btn_reward_issue")
        btn_clear = inner.findChild(QPushButton, "btn_reward_issue_clear")

        if self.table:
            setupPreviewTable(
                self.table,
                self.HEADERS,
                stretch_col=4,
                fixed_overrides={
                    "編號": 100,
                    "登錄日期": 120,
                    "發文日期": 120,
                    "敘獎人員": 260,
                },
            )
            self.table.setEditTriggers(QTableWidget.NoEditTriggers)
            attachStickyScroll(self.table)

        if self.issue_date:
            self.issue_date.setDate(QDate.currentDate())
            setupDateEditToToday(self.issue_date)

        if self.issue_sender:
            personnel, _ = self._loadRef()
            setupFilterCombo(self.issue_sender, personnel)

        if self.lineEdit:
            self.lineEdit.setPlaceholderText("輸入編號後按 Enter 或右側按鈕")
            self.lineEdit.returnPressed.connect(self.handleQuery)
            self.lineEdit.setFocus()
        if btn_input:
            btn_input.clicked.connect(self.handleQuery)
        if btn_issue:
            btn_issue.clicked.connect(self.handleIssue)
        if btn_clear:
            btn_clear.clicked.connect(self.handleClearAll)

        self._pending = set()
        self._pending_banner = QLabel("")
        self._pending_banner.setStyleSheet(_PENDING_BANNER_CSS)
        self._pending_banner.setWordWrap(True)
        self._pending_banner.setVisible(False)
        inner_layout = inner.layout()
        if inner_layout is not None:
            inner_layout.insertWidget(1, self._pending_banner)

    def get_tables(self):
        table = getattr(self, "table", None)
        return [table] if table else []

    def get_focus_widget(self):
        return getattr(self, "lineEdit", None)

    def on_activated(self):
        if getattr(self, "_ref_changed", False):
            personnel, _ = self._loadRef()
            if getattr(self, "issue_sender", None):
                refreshFilterCombo(self.issue_sender, personnel)
            self._ref_changed = False
        self._updatePendingBanner()

    def _tableDocIds(self):
        ids = set()
        table = getattr(self, "table", None)
        if not table:
            return ids
        for row in range(table.rowCount()):
            item = table.item(row, 1)
            if item and item.text():
                ids.add(item.text())
        return ids

    def _updatePendingBanner(self):
        banner = getattr(self, "_pending_banner", None)
        if banner is None:
            return
        self._pending &= self._tableDocIds()
        count = len(self._pending)
        if count:
            banner.setText(
                f"⚠ 尚有 {count} 筆已輸入未發文，確認清單後請按「確認發文」")
        banner.setVisible(bool(count))

    def _rowExists(self, doc_id):
        return doc_id in self._tableDocIds()

    def handleQuery(self):
        if not getattr(self, "lineEdit", None):
            return
        serial = self.lineEdit.text().strip()
        if not serial:
            return

        conn = None
        try:
            conn = self._getConn()
            row = conn.execute(
                "SELECT doc_id, create_date, register_date, reason, recipients "
                "FROM Document_Reward WHERE doc_id=?",
                (serial,),
            ).fetchone()
        except Exception as exc:
            reportError("SQL 錯誤", exc)
            return
        finally:
            if conn:
                conn.close()

        if row is None:
            msgWarning("查無資料", f"找不到編號「{serial}」")
        elif rewardState(row[2]) == "deleted":
            msgWarning("查無資料", f"編號「{serial}」已被刪除")
        elif self._rowExists(str(row[0])):
            msgInfo("提示", f"「{serial}」已在清單中")
        else:
            self._insertRow(row)

        self.lineEdit.clear()
        self.lineEdit.setFocus()

    @staticmethod
    def _centeredItem(value):
        item = QTableWidgetItem(str(value) if value is not None else "")
        item.setTextAlignment(Qt.AlignCenter)
        return item

    def _insertRow(self, data):
        if not getattr(self, "table", None):
            return
        row_index = self.table.rowCount()
        self.table.insertRow(row_index)
        doc_id = str(data[0]) if data[0] is not None else ""

        container, _ = makeDeleteBtn(
            lambda _checked=False, value=doc_id: self._deleteByDocId(value))
        self.table.setCellWidget(row_index, 0, container)
        self.table.setItem(row_index, 1, self._centeredItem(doc_id))
        self.table.setItem(row_index, 2, self._centeredItem(data[1]))

        issue_item = self._centeredItem(data[2])
        if data[2]:
            issue_item.setForeground(QColor(_ISSUE_DATE_COLOR))
            issue_item.setToolTip("原發文日期，發文後將被覆蓋")
        self.table.setItem(row_index, 3, issue_item)
        self.table.setItem(row_index, 4, self._centeredItem(data[3]))
        self.table.setItem(row_index, 5, self._centeredItem(data[4]))
        autoResizeTable(self.table)

        if doc_id:
            self._pending.add(doc_id)
            self._updatePendingBanner()

    def _deleteByDocId(self, doc_id):
        if not getattr(self, "table", None):
            return
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 1)
            if item and item.text() == doc_id:
                self.table.removeRow(row)
                self._pending.discard(doc_id)
                self._updatePendingBanner()
                return

    def handleClearAll(self):
        if not getattr(self, "table", None) or self.table.rowCount() == 0:
            msgInfo("提示", "清單已經是空的")
            return
        if confirmBox(
                "確認清除", f"確定要清除全部 {self.table.rowCount()} 筆資料？",
                confirm_text="清除", confirm_danger=True, default_confirm=True):
            self.table.setRowCount(0)
            self._pending.clear()
            self._updatePendingBanner()

    def handleIssue(self):
        table = getattr(self, "table", None)
        if not table or table.rowCount() == 0:
            msgInfo("提示", "清單是空的，請先輸入編號")
            return

        # 比照交辦發文：送出清單中「全部」列（不限本 session 新掃入的 _pending），
        # 讓已發文列重新加入後可再次發文（退件重發）。
        pending = []
        for row_index in range(table.rowCount()):
            item = table.item(row_index, 1)
            if item and item.text():
                pending.append((row_index, item.text()))
        if not pending:
            msgInfo("提示", "目前沒有待發資料")
            return

        sender_id = self.issue_sender.currentData() if self.issue_sender else None
        sender_name = self.issue_sender.currentText() if self.issue_sender else "未選擇"
        if not sender_id:
            msgWarning("欄位未填", "請選擇發文人員。")
            return

        issue_day = (
            self.issue_date.date().toString("yyyy-MM-dd")
            if self.issue_date else datetime.now().strftime("%Y-%m-%d"))

        conn = None
        try:
            conn = self._getConn()
            already = 0
            for _, doc_id in pending:
                row = conn.execute(
                    "SELECT register_date FROM Document_Reward WHERE doc_id=?",
                    (doc_id,),
                ).fetchone()
                if row and rewardState(row[0]) == "issued":
                    already += 1
        except Exception as exc:
            reportError("預查失敗", exc)
            return
        finally:
            if conn:
                conn.close()

        overwrite_note = f"（其中 {already} 筆將覆蓋原發文日期）" if already else ""
        if not confirmBox(
                "確認發文",
                f"發文日期：{issue_day}\n發文人員：{sender_name}\n"
                f"共 {len(pending)} 筆敘獎{overwrite_note}\n確認送出？",
                confirm_text="發文", default_confirm=True):
            return

        conn = None
        settled = 0
        updated_rows = []
        try:
            conn = self._getConn()
            for row_index, doc_id in pending:
                cursor = conn.execute(
                    "UPDATE Document_Reward SET register_date=?, sender_id=? "
                    f"WHERE doc_id=? AND {REWARD_ACTIVE_SQL}",
                    (issue_day, sender_id, doc_id),
                )
                settled += cursor.rowcount
                if cursor.rowcount:
                    updated_rows.append(row_index)
            conn.commit()

            for row_index in updated_rows:
                item = self._centeredItem(issue_day)
                item.setForeground(QColor(_ISSUE_DATE_COLOR))
                self.table.setItem(row_index, 3, item)

            skipped = len(pending) - settled
            self._pending.clear()
            self._updatePendingBanner()
            self._flagConvertReload(("reward",))
            for tab in getattr(getattr(self, "_manager", None), "tabs", {}).values():
                if hasattr(tab, "reward_data_dirty"):
                    tab.reward_data_dirty = True
            if skipped:
                msgWarning(
                    "部分未更新", f"有 {skipped} 筆在發文前已被刪除，本次未變動")
            msgInfo("完成", f"已成功更新 {settled} 筆發文日期（{issue_day}）")
        except Exception as exc:
            if conn:
                conn.rollback()
            reportError("更新失敗", exc)
        finally:
            if conn:
                conn.close()
