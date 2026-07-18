from PySide6.QtCore import Qt, QDate
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QDateEdit, QLineEdit, QListWidget, QPushButton,
    QTableWidget, QTableWidgetItem, QVBoxLayout,
)

from lib.auth_manager import AuthManager
from lib.base_tab import BaseTab
from lib.db_utils import (
    getResourcePath, isSelfServiceMode, loadActivePersonnel, nextDocId,
    softDeleteDoc,
)
from ui_utils import (
    RewardEditDialog, attachStickyScroll, confirmBox, count_recipient_names,
    loadUi, makeDeleteBtn, msgWarning, parse_recipient_names, reportError,
    setDocIdLinkCell, setupDateEditToToday, setupPreviewTable,
    setupRecipientLineEdit, sort_personnel_by_counts,
)


class TabReward(BaseTab):
    PREVIEW_HEADERS = ["", "編號", "發文日期", "敘獎事由", "敘獎人員"]

    def __init__(self, tab_widget, db_path):
        super().__init__(tab_widget, db_path)
        self._session_doc_ids = []
        self.reward_data_dirty = False
        self._name_counts = {}   # {完整姓名: 出現次數}；記憶體維護，免每次全表 SELECT

    def setup(self, tab_index):
        tab = self.tab_widget.widget(tab_index)
        if not tab:
            return
        loaded = loadUi(getResourcePath("layouts/Layout9.ui"))
        if not loaded:
            return
        inner = loaded.centralWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(inner)
        self._tab_index = tab_index
        self.reward_date = inner.findChild(QDateEdit, "reward_date")
        self.reward_reason = inner.findChild(QLineEdit, "reward_reason")
        self.reward_recipients = inner.findChild(QLineEdit, "reward_recipients")
        self.reward_personnel_list = inner.findChild(QListWidget, "reward_personnel_list")
        self.reward_table = inner.findChild(QTableWidget, "reward_tableWidget")
        self.btn_submit = inner.findChild(QPushButton, "btn_reward_submit")
        self.btn_clear = inner.findChild(QPushButton, "btn_reward_clear")
        self.reward_date.setDate(QDate.currentDate())
        setupDateEditToToday(self.reward_date)
        self._personnel, self._personnel_alias_map = loadActivePersonnel(self.db_path)
        setupRecipientLineEdit(self.reward_recipients, self._personnel,
                               alias_map=self._personnel_alias_map)
        self._setup_table()
        self._load_counts()
        self._rebuild_personnel_list()
        self.btn_submit.clicked.connect(self._submit)
        self.btn_clear.clicked.connect(self._form_clear)
        self.reward_personnel_list.itemClicked.connect(
            lambda item: self.reward_recipients._recipient_controller.add_person(item.text()))
        self.tab_widget.currentChanged.connect(self._onShown)
        self.reward_reason.setFocus()
        self._applySelfServiceMode()

    def _applySelfServiceMode(self):
        """自助取號模式：發文日期欄反灰，日期改由結算時自動填入；切回送文者模式
        清哨兵並還原今天（照 tab_report._applySelfServiceMode 的哨兵處理精神）。

        用 specialValueText 哨兵顯示空白：僅在反灰（不可互動）狀態下，無鍵盤／
        滑鼠路徑，不踩 QDateEdit 可編輯空白欄的雷；widgets.setupDateEditToToday
        已對此哨兵放行。送出值與此無關（自助模式 _submit 一律帶 register_date=''）。"""
        if not getattr(self, "reward_date", None):
            return
        is_self = isSelfServiceMode(self.db_path)
        tip = "自助取號模式：發文日期由結算時自動填入" if is_self else ""
        self.reward_date.setToolTip(tip)
        if is_self:
            self.reward_date.setEnabled(False)
            self.reward_date.setSpecialValueText(" ")
            self.reward_date.setDate(self.reward_date.minimumDate())
        else:
            self.reward_date.setEnabled(True)
            if self.reward_date.specialValueText():
                # 從自助切回送文者模式：清哨兵、還原今天（僅切換當下做一次）
                self.reward_date.setSpecialValueText("")
                self.reward_date.setDate(QDate.currentDate())

    def _setup_table(self):
        setupPreviewTable(
            self.reward_table,
            self.PREVIEW_HEADERS,
            stretch_col=3,
            fixed_overrides={
                "編號": 70,
                "發文日期": 120,
                "敘獎人員": 320,
            },
        )
        attachStickyScroll(self.reward_table)

    def get_tables(self):
        return [self.reward_table] if getattr(self, "reward_table", None) else []

    def get_focus_widget(self):
        return getattr(self, "reward_reason", None)

    def _onShown(self, index):
        if index == self._tab_index:
            self.on_activated()

    def on_activated(self):
        # 效率：人員清單只在設定頁改過參照表（_ref_changed 旗標）時重載；
        # 敘獎資料異動（還原／瀏覽頁編輯）由 reward_data_dirty 旗標觸發。
        # 一般切頁兩旗標皆假 → 直接 no-op，不再每次全表重讀。
        # 設定頁 _ref_dirty 切走時 main 先呼叫一次、_onShown 再呼一次；
        # 第一次清旗標後第二次自然 no-op。
        ref_changed = getattr(self, "_ref_changed", False)
        data_dirty = self.reward_data_dirty
        if ref_changed:
            self._personnel, self._personnel_alias_map = \
                loadActivePersonnel(self.db_path)
            self.reward_recipients._recipient_controller.update_personnel(
                self._personnel, alias_map=self._personnel_alias_map)
            self._ref_changed = False
        if data_dirty:
            self._refresh_session_rows()
            self.reward_data_dirty = False
        if ref_changed or data_dirty:
            # 人員改名／敘獎資料異動皆可能改變名條計數或姓名 → 重載一次計數。
            self._load_counts()
            self._rebuild_personnel_list()
        # 無條件重套（模式可能於設定頁切換）：不受上方旗標 early-path 影響。
        self._applySelfServiceMode()

    def _load_counts(self):
        """全表載入一次名條計數到 self._name_counts（開機／旗標刷新時呼叫）。"""
        conn = self._getConn()
        try:
            texts = [r[0] for r in conn.execute(
                "SELECT recipients FROM Document_Reward WHERE register_date IS NOT NULL")]
        finally:
            conn.close()
        self._name_counts = count_recipient_names(texts)

    def _rebuild_personnel_list(self):
        """依記憶體中的 self._name_counts 就地重排名條清單（不查資料庫）。"""
        ordered = sort_personnel_by_counts(self._personnel, self._name_counts)
        self.reward_personnel_list.clear()
        for row in ordered:
            name = self._trimName(row[1])
            if name:
                self.reward_personnel_list.addItem(name)

    def _bump_counts(self, names, delta):
        """對指定完整姓名清單的名條計數增減 delta（送出 +1／刪除 -1）。"""
        for name in names:
            new = self._name_counts.get(name, 0) + delta
            if new > 0:
                self._name_counts[name] = new
            else:
                self._name_counts.pop(name, None)

    def _form_clear(self):
        self.reward_reason.clear()
        self.reward_recipients.clear()
        self.reward_reason.setFocus()

    def _submit(self):
        # 自助取號模式：登錄日期留空哨兵（''），事後由列印頁結算補今日日期。
        if isSelfServiceMode(self.db_path):
            date = ""
        else:
            date = self.reward_date.date().toString("yyyy-MM-dd")
        reason = self.reward_reason.text().strip()
        names = parse_recipient_names(self.reward_recipients.text())
        missing = []
        if not reason:
            missing.append("敘獎事由")
        if not names:
            missing.append("敘獎人員")
        if missing:
            msgWarning("欄位未填", f"請填寫以下必填欄位：\n{'、'.join(missing)}")
            return
        recipients = ",".join(names)
        conn = None
        try:
            conn = self._getConn()
            doc_id = nextDocId(conn, "Document_Reward")
            conn.execute("INSERT INTO Document_Reward(doc_id,register_date,reason,recipients) "
                         "VALUES(?,?,?,?)", (doc_id, date, reason, recipients))
            conn.commit()
        except Exception as exc:
            reportError("寫入失敗", exc)
            return
        finally:
            if conn:
                conn.close()
        self._session_doc_ids.append(doc_id)
        self._append_preview(doc_id, date, reason, recipients)
        self._bump_counts(names, +1)
        self._rebuild_personnel_list()
        self._flag_browse_dirty()
        self._form_clear()

    def _append_preview(self, doc_id, date, reason, recipients):
        row = self.reward_table.rowCount()
        self.reward_table.insertRow(row)
        container, _ = makeDeleteBtn(lambda _=False, d=doc_id: self._deleteByDocId(d))
        self.reward_table.setCellWidget(row, 0, container)
        setDocIdLinkCell(self.reward_table, row, 1, doc_id, self._onEditRow, clickable=True)
        # 發文日期（col2）：自助取號模式未結算時為空 → 橘字「未發文」置中。
        if date:
            date_item = QTableWidgetItem(date)
            date_item.setToolTip(date)
        else:
            date_item = QTableWidgetItem("未發文")
            date_item.setForeground(QColor("#e67e22"))
            date_item.setToolTip("未發文")
        date_item.setTextAlignment(Qt.AlignCenter)
        self.reward_table.setItem(row, 2, date_item)
        for col, value in ((3, reason), (4, recipients)):
            item = QTableWidgetItem(value or "")
            item.setTextAlignment(Qt.AlignCenter)
            item.setToolTip(value or "")
            self.reward_table.setItem(row, col, item)

    def _refresh_session_rows(self):
        if not self._session_doc_ids:
            self.reward_table.setRowCount(0)
            return
        conn = self._getConn()
        try:
            marks = ",".join("?" for _ in self._session_doc_ids)
            rows = conn.execute(
                f"SELECT doc_id,register_date,reason,recipients FROM Document_Reward "
                f"WHERE doc_id IN ({marks}) AND register_date IS NOT NULL",
                self._session_doc_ids).fetchall()
        finally:
            conn.close()
        by_id = {str(r[0]): r for r in rows}
        self._session_doc_ids = [d for d in self._session_doc_ids if d in by_id]
        self.reward_table.setRowCount(0)
        for doc_id in self._session_doc_ids:
            row = by_id[doc_id]
            self._append_preview(str(row[0]), row[1], row[2], row[3])

    def _row_for_doc_id(self, doc_id):
        for row in range(self.reward_table.rowCount()):
            widget = self.reward_table.cellWidget(row, 1)
            if self._docIdFromLabel(widget) == str(doc_id):
                return row
        return -1

    def _onEditRow(self, _row, doc_id):
        dlg = RewardEditDialog(self.db_path, doc_id, self.reward_table, source="entry")
        updated = dlg.exec() and dlg.get_updated()
        if getattr(dlg, "_row_missing", False):
            # 併發刪除：該列已不存在，重整預覽移除失效列並同步名條計數。
            self._refresh_session_rows()
            self._load_counts()
            self._rebuild_personnel_list()
            return
        if updated:
            # 編輯後人員可能改變 → 簡單重載一次計數（編輯較少見，可接受）。
            self._refresh_session_rows()
            self._load_counts()
            self._rebuild_personnel_list()
            self._flag_browse_dirty()

    def _flag_browse_dirty(self):
        """標記資料庫瀏覽的敘獎子頁，下次顯示時重載（收斂至 BaseTab 共用迴圈）。"""
        self._flagConvertReload(("reward",))

    def _deleteByDocId(self, doc_id):
        row = self._row_for_doc_id(doc_id)
        reason = self.reward_table.item(row, 3).text() if row >= 0 else ""
        recipients = (self.reward_table.item(row, 4).text()
                      if row >= 0 and self.reward_table.item(row, 4) else "")
        if not confirmBox(
                "確認刪除",
                f"確定刪除編號 {doc_id}（{reason}）？本文號不再使用。",
                confirm_text="刪除", confirm_danger=True, default_confirm=False):
            return
        auth = AuthManager.instance()
        conn = None
        try:
            conn = self._getConn()
            softDeleteDoc(conn, table="Document_Reward", doc_id=str(doc_id),
                          role=auth.current_role, is_admin=auth.is_admin(),
                          audit_operator=False)
            conn.commit()
        except Exception as exc:
            reportError("刪除失敗", exc)
            return
        finally:
            if conn:
                conn.close()
        self._session_doc_ids = [d for d in self._session_doc_ids if d != str(doc_id)]
        if row >= 0:
            self.reward_table.removeRow(row)
        self._bump_counts(parse_recipient_names(recipients), -1)
        self._rebuild_personnel_list()
        self._flag_browse_dirty()
