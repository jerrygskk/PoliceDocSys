from PySide6.QtCore import Qt, QDate
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QComboBox, QDateEdit, QLabel, QLineEdit, QListWidget, QPushButton,
    QTableWidget, QTableWidgetItem, QVBoxLayout,
)

from lib.auth_manager import AuthManager
from lib.base_tab import BaseTab, InputLockMixin
from lib.db_utils import (
    REWARD_ACTIVE_SQL, getResourcePath, isInputLocked, isSelfServiceMode,
    loadActivePersonnel, nextDocId, softDeleteDoc,
)
from ui_utils import (
    RecipientCombo, RewardEditDialog, attachStickyScroll, confirmBox,
    loadUi, makeDeleteBtn, msgWarning, parse_recipient_names,
    refreshFilterCombo, refreshRecipientComboItems, reportError,
    setDocIdLinkCell, setupDateEditToToday, setupFilterCombo,
    setupPreviewTable, setupRecipientCombo,
)
from ui_utils.date_guard import confirmDateGap


_SELF_SERVICE_HINT = "發文結算模式"


class TabReward(BaseTab, InputLockMixin):
    PREVIEW_HEADERS = ["", "編號", "發文日期", "敘獎事由", "敘獎人員"]

    def __init__(self, tab_widget, db_path):
        super().__init__(tab_widget, db_path)
        self._session_doc_ids = []
        self.reward_data_dirty = False

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
        self.reward_sender = inner.findChild(QComboBox, "reward_sender")
        self.reward_sender_hint = inner.findChild(QLabel, "reward_sender_hint")
        self.reward_reason = inner.findChild(QLineEdit, "reward_reason")
        self.reward_recipients = inner.findChild(RecipientCombo, "reward_recipients")
        self.reward_personnel_list = inner.findChild(QListWidget, "reward_personnel_list")
        self.reward_table = inner.findChild(QTableWidget, "reward_tableWidget")
        self.btn_submit = inner.findChild(QPushButton, "btn_reward_submit")
        self.btn_clear = inner.findChild(QPushButton, "btn_reward_clear")
        self.reward_date.setDate(QDate.currentDate())
        setupDateEditToToday(self.reward_date)
        self._personnel, self._personnel_alias_map = loadActivePersonnel(self.db_path)
        setupFilterCombo(self.reward_sender, self._senderChoices(),
                         alias_map=self._personnel_alias_map)
        # 敘獎人員：可編輯下拉（比照修改彈窗；下拉選取＝附加姓名，打字有 completer）。
        setupRecipientCombo(self.reward_recipients, self._personnel,
                            alias_map=self._personnel_alias_map)
        le = self.reward_recipients.lineEdit()
        if le is not None:
            le.setPlaceholderText("請輸入或點選人員")
        self._setup_table()
        self._rebuild_personnel_list()
        self.btn_submit.clicked.connect(self._submit)
        self.btn_clear.clicked.connect(self._form_clear)
        self.reward_personnel_list.itemClicked.connect(
            lambda item: self.reward_recipients._recipient_controller.add_person(item.text()))

        # 唯讀橫幅（預設隱藏）＋跨年度唯讀鎖（共用 InputLockMixin）。
        # 外層 layout 邊距為 0 → banner 直接插最上層即滿版。
        # currentChanged→_onShown 由 _setupInputLock 統一掛（本頁 _onShown 覆寫成
        # 呼叫 on_activated，內含 _applyInputLock），此處不得再自掛以免重複觸發。
        banner = self._makeReadonlyBanner()
        layout.insertWidget(0, banner)
        self._setupInputLock(
            tab_index,
            lock_kind="reward",
            lock_widgets=[
                self.reward_date,
                self.reward_sender,
                self.reward_reason,
                self.reward_recipients,
                self.reward_personnel_list,
                self.btn_submit,
                self.btn_clear,
            ],
            clear_tables=[self.reward_table],
        )
        self.reward_reason.setFocus()
        self._applySelfServiceMode()

    def _senderChoices(self):
        """把 loadActivePersonnel 的 (staff_id, name, sort_order) 三元組轉成
        setupFilterCombo 需要的 (id, name) 二元組（姓名已去後綴）。"""
        return [(sid, name) for sid, name, _ in self._personnel]

    def _applyInputLock(self):
        """覆寫：先套唯讀設定鎖，再疊加發文結算模式的欄位反灰。
        否則發文結算模式下該反灰的兩欄會被唯讀鎖解除時一併解鎖回可用
        （比照 tab_report／tab_ticket）。"""
        super()._applyInputLock()
        self._applySelfServiceMode()

    def _applySelfServiceMode(self):
        """發文結算模式：發文日期與發文人員兩欄一起反灰，改由結算時自動填入；
        切回送文者模式清哨兵並還原今天（照 tab_report._applySelfServiceMode 精神）。

        提示以可見 QLabel（`reward_sender_hint`）呈現、比照罰單登錄頁：tooltip
        在深色模式整塊黑、也要滑過才看得到（PITFALLS QSS-7）。

        日期用 specialValueText 哨兵顯示空白：僅在反灰（不可互動）狀態下，無鍵盤／
        滑鼠路徑，不踩 QDateEdit 可編輯空白欄的雷；widgets.setupDateEditToToday
        已對此哨兵放行。送出值與此無關（發文結算模式 _submit 一律帶 register_date=''、
        sender_id NULL）。"""
        if not getattr(self, "reward_date", None):
            return
        is_self = isSelfServiceMode(self.db_path, "reward")
        tip = _SELF_SERVICE_HINT if is_self else ""
        self.reward_date.setToolTip(tip)
        if getattr(self, "reward_sender", None):
            self.reward_sender.setToolTip(tip)
            if is_self:
                self.reward_sender.setEnabled(False)
        if getattr(self, "reward_sender_hint", None):
            self.reward_sender_hint.setVisible(is_self)
        if is_self:
            self.reward_date.setEnabled(False)
            self.reward_date.setSpecialValueText(" ")
            self.reward_date.setDate(self.reward_date.minimumDate())
        elif self.reward_date.specialValueText():
            # 從發文結算模式切回送文者模式：清哨兵、還原今天（僅切換當下做一次）
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
            refreshRecipientComboItems(self.reward_recipients, self._personnel)
            refreshFilterCombo(self.reward_sender, self._senderChoices(),
                               alias_map=self._personnel_alias_map)
            self._ref_changed = False
        if data_dirty:
            self._refresh_session_rows()
            self.reward_data_dirty = False
        if ref_changed:
            # 人員清單本身變了（改名／停用／排序）才需要重建候選名條。
            self._rebuild_personnel_list()
        # 切回本頁一律重讀唯讀設定並重套（唯讀狀態可能在他頁被改）。
        self._applyInputLock()

    def _onRoleClearList(self, *args):
        """降權清空必須具『持續性』，故連本次登錄清單一併清掉。

        基底 `InputLockMixin._onRoleClearList` 只把預覽表 widget 清成 0 列、
        不動 `self._session_doc_ids`。本頁 `on_activated` 的 dirty-flag 守衛
        只是「掩蓋」而非防線：`reward_data_dirty` 會被其他不設角色 gate 的路徑
        （如列印頁結算發文、瀏覽頁還原）設為 True，一般使用者走得到；
        旗標一開，切回本頁就會
        `_refresh_session_rows()` 依殘留的 `_session_doc_ids` 把整份清單從 DB
        重建回來——降權後的一般使用者因此拿到「編輯（`_onEditRow`）／刪除
        （`_deleteByDocId`）管理身分建立之敘獎」的入口，而同一筆資料在資料庫
        瀏覽頁是僅 admin 可改（DEVELOPER §10 權限矩陣）。實測過的權限回歸，
        勿只還原 widget。清 `_session_doc_ids` 不動 DB：資料仍在，只是不再
        留在本頁的操作入口內（比照 `tab_ticket._onRoleClearList`）。
        """
        super()._onRoleClearList(*args)
        if AuthManager.instance().is_manager():
            return
        self._session_doc_ids = []

    def _rebuild_personnel_list(self):
        """候選人員名條：一律照人員清單（`Ref_Personnel` 的 sort_order）排。

        ⚠️ 不再依歷來敘獎次數重排（維護者要求改回資料庫順序）：清單順序只跟
        設定頁的人員排序走，敘獎登錄／刪除都不會讓名條跳位。
        """
        self.reward_personnel_list.clear()
        for row in self._personnel:
            name = row[1]
            if name:
                self.reward_personnel_list.addItem(name)

    def _form_clear(self):
        self.reward_reason.clear()
        self.reward_recipients.setCurrentText("")   # 只清輸入文字、不清下拉項目
        self.reward_reason.setFocus()

    def _submit(self):
        # 硬性 guard：反灰只擋 UI 觸發，Enter／程式路徑仍會進來。
        if (not AuthManager.instance().is_manager()
                and isInputLocked(self.db_path, "reward")):
            msgWarning("目前為唯讀", "此年度的敘獎登錄已鎖定，無法新增資料。")
            return
        # 發文結算模式：發文日期留空哨兵（''）、發文人員 NULL，事後由列印頁結算
        # 補發文日期與送文者；送文者模式則兩者當下填入（發文人員必填）。
        # ⚠️ 登錄日期 create_date 與模式無關，兩模式一律帶今天。
        is_self = isSelfServiceMode(self.db_path, "reward")
        if is_self:
            # 發文結算模式一律送空值：反灰欄可能有殘留值，此處不得讀取。
            register_date = ""
            sender_id = None
        else:
            register_date = self.reward_date.date().toString("yyyy-MM-dd")
            sender_id = self.reward_sender.currentData() if self.reward_sender else None
        create_date = QDate.currentDate().toString("yyyy-MM-dd")
        reason = self.reward_reason.text().strip()
        names = parse_recipient_names(self.reward_recipients.currentText())
        missing = []
        if not reason:
            missing.append("敘獎事由")
        if not names:
            missing.append("敘獎人員")
        if missing:
            msgWarning("欄位未填", f"請填寫以下必填欄位：\n{'、'.join(missing)}")
            return
        # 發文人員必填（僅送文者模式；發文結算模式由結算補填），比照 tab_dispatch。
        if not is_self and not sender_id:
            msgWarning("欄位未填", "請選擇發文人員。")
            return
        # 日期防呆：連續登錄時日期欄共用，被誤改會一路錯下去（見 ui_utils/date_guard）
        if not is_self and not confirmDateGap(
                register_date, "發文日期", scope="reward",
                parent=self.tab_widget):
            return
        recipients = ",".join(names)
        conn = None
        try:
            conn = self._getConn()
            doc_id = nextDocId(conn, "Document_Reward")
            conn.execute(
                "INSERT INTO Document_Reward(doc_id,create_date,register_date,sender_id,reason,recipients) "
                "VALUES(?,?,?,?,?,?)",
                (doc_id, create_date, register_date, sender_id, reason, recipients))
            conn.commit()
        except Exception as exc:
            reportError("寫入失敗", exc)
            return
        finally:
            if conn:
                conn.close()
        self._session_doc_ids.append(doc_id)
        self._append_preview(doc_id, register_date, reason, recipients)
        self._flag_browse_dirty()
        self._form_clear()

    def _append_preview(self, doc_id, date, reason, recipients):
        row = self.reward_table.rowCount()
        self.reward_table.insertRow(row)
        container, _ = makeDeleteBtn(lambda _=False, d=doc_id: self._deleteByDocId(d))
        self.reward_table.setCellWidget(row, 0, container)
        setDocIdLinkCell(self.reward_table, row, 1, doc_id, self._onEditRow, clickable=True)
        # 發文日期（col2）：尚未發文時為空 → 橘字「未發文」置中。
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
                f"WHERE doc_id IN ({marks}) AND {REWARD_ACTIVE_SQL}",
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
            # 併發刪除：該列已不存在，重整預覽移除失效列。
            self._refresh_session_rows()
            return
        if updated:
            self._refresh_session_rows()
            self._flag_browse_dirty()

    def _flag_browse_dirty(self):
        """標記資料庫瀏覽的敘獎子頁，下次顯示時重載（收斂至 BaseTab 共用迴圈）。"""
        self._flagConvertReload(("reward",))

    def _deleteByDocId(self, doc_id):
        row = self._row_for_doc_id(doc_id)
        if not confirmBox(
                "確認刪除",
                "刪除後，本筆敘獎登錄及文號將被廢棄不再使用，如有需要請重新輸入取號。",
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
        self._flag_browse_dirty()
