# -*- coding: utf-8 -*-
"""罰單登錄（Tab）：新增／修改／刪除罰單，版面與操作節奏比照敘獎登錄。

界線（重要）：
  - 所有寫入一律走 `lib.ticket_utils` 的 domain helper，本檔不自組業務 SQL；
    唯一的 SELECT 是預覽表刷新與候選人員排序，走 `Document_Ticket_Full` View。
  - 兩種模式（`isSelfServiceMode`）：發文結算模式下發文人員欄**保留位置但反灰**
    （不隱藏，避免版面跳動），並顯示可見的提示 QLabel——不可只靠 tooltip，
    深色模式下 tooltip 整塊黑（PITFALLS QSS-7）。提交時強制 `sender_id=None`，
    **不得讀取反灰欄的殘留 UI 值**。
  - 開立人員只有一位：不解析逗號／頓號多人（那是敘獎的行為），右側候選人員
    點下去是**直接取代**目前開立人員。人員一律以 `currentData()`／UserRole 的
    `staff_id` 為準，不用畫面姓名字串反查。
    - 本頁所有已登入身分皆可新增／修改／刪除（含已發文資料），不設角色 gate；
      跨年度唯讀鎖由 `_setupInputLock()` 接上。
  - 模式與唯讀狀態不可只在 `setup()` 判斷一次：`_onShown()`／`on_activated()`
    重新進入分頁時都要重套。
"""
from PySide6.QtCore import Qt, QDate
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QComboBox, QGroupBox, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout,
)

from lib.auth_manager import AuthManager
from lib.base_tab import BaseTab, InputLockMixin
from lib.db_utils import (
    getResourcePath, isInputLocked, isSelfServiceMode, loadActivePersonnel,
)
from lib.ticket_utils import (
    TICKET_ACTIVE_SQL, TICKET_NO_MAX_LEN, TicketDuplicateError,
    TicketNotFoundError, TicketValidationError, createTicket, deleteTicket,
)
from ui_utils import (
    TicketEditDialog, attachStickyScroll, confirmBox, loadUi,
    makeDeleteBtn, msgWarning, refreshFilterCombo, reportError,
    setDocIdLinkCell, setupFilterCombo, setupPreviewTable,
)
from lib.archive_text import _trimName


# 未發文（發文結算模式）在預覽表的橘字提示，與敘獎登錄一致
_UNISSUED_COLOR = "#e67e22"

_SENDER_HINT = "發文結算模式"


class TabTicket(BaseTab, InputLockMixin):
    """罰單登錄：左側輸入表單＋本次登錄預覽，右側候選人員。"""

    # 尾端空白欄當 stretch（罰單編號改固定寬，與開立人員同寬，不再讓罰單編號自撐）
    PREVIEW_HEADERS = ["", "編號", "登錄日期", "發文日期", "罰單編號", "開立人員", ""]

    def __init__(self, tab_widget, db_path):
        super().__init__(tab_widget, db_path)
        self._session_doc_ids = []      # 本次登錄清單（比照敘獎登錄）
        self._personnel = []           # [(staff_id, staff_name, sort_order), ...]

    # ── 建置 ────────────────────────────────────────────────
    def setup(self, tab_index):
        tab = self.tab_widget.widget(tab_index)
        if not tab:
            return
        loaded = loadUi(getResourcePath("layouts/Layout11.ui"))
        if not loaded:
            return
        inner = loaded.centralWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(inner)
        self._tab_index = tab_index

        self.ticket_sender = inner.findChild(QComboBox, "ticket_sender")
        self.ticket_sender_hint = inner.findChild(QLabel, "ticket_sender_hint")
        self.ticket_issuer = inner.findChild(QComboBox, "ticket_issuer")
        self.ticket_clear_issuer = inner.findChild(QPushButton,
                                                   "ticket_clear_issuer")
        self.ticket_no = inner.findChild(QLineEdit, "ticket_no")
        self.ticket_no.setMaxLength(TICKET_NO_MAX_LEN)
        self.ticket_table = inner.findChild(QTableWidget, "ticket_table")
        self.ticket_add = inner.findChild(QPushButton, "ticket_add")
        self.ticket_candidates = inner.findChild(QGroupBox, "ticket_candidates")
        self.ticket_candidates_list = inner.findChild(QListWidget,
                                                      "ticket_candidates_list")

        self._setupPersonnelCombos()
        self._setupCandidateButtons()
        self._setupTable()
        self._connectSignals()
        self.reload()

        # 唯讀橫幅（預設隱藏）＋跨年度唯讀鎖（共用 InputLockMixin）。
        # 外層 layout 邊距為 0 → banner 直接插最上層即滿版。
        banner = self._makeReadonlyBanner()
        layout.insertWidget(0, banner)
        self._setupInputLock(
            tab_index,
            lock_kind="ticket",
            lock_widgets=[
                self.ticket_sender,
                self.ticket_issuer,
                self.ticket_clear_issuer,
                self.ticket_no,
                self.ticket_add,
                self.ticket_candidates_list,
            ],
            clear_tables=[self.ticket_table],
        )
        self.ticket_no.setFocus()

    def _setupPersonnelCombos(self):
        """發文人員／開立人員兩個可輸入下拉；候選來源與敘獎登錄共用
        `loadActivePersonnel`（在職人員＋別名，姓名已去 `-19.06` 後綴）。

        ⚠️ 單一人名下拉一律**比照陳報頁的發文人員**：只掛 `setupFilterCombo`，
        第 0 項維持空字串、不加提示文字（維護者指示）。提示文字那套
        （`attachComboHint`）只給陳報頁的案類用，勿再套回本頁。"""
        self._personnel, self._alias_map = loadActivePersonnel(self.db_path)
        pairs = [(sid, name) for sid, name, _sort in self._personnel]
        setupFilterCombo(self.ticket_sender, pairs, alias_map=self._alias_map)
        setupFilterCombo(self.ticket_issuer, pairs, alias_map=self._alias_map)

    def _setupCandidateButtons(self):
        """右側候選人員清單：點一下＝直接取代目前開立人員（不附加、不確認）。"""
        self._rebuildCandidates()

    def _setupTable(self):
        setupPreviewTable(
            self.ticket_table,
            self.PREVIEW_HEADERS,
            stretch_col=6,
            fixed_overrides={
                "編號": 70,
                "登錄日期": 120,
                "發文日期": 120,
                "罰單編號": 160,
                "開立人員": 160,
            },
        )
        attachStickyScroll(self.ticket_table)

    def _connectSignals(self):
        self.ticket_add.clicked.connect(lambda _=False: self._submit())
        self.ticket_clear_issuer.clicked.connect(lambda _=False: self._clearIssuer())
        self.ticket_no.returnPressed.connect(self._submit)
        self.ticket_candidates_list.itemClicked.connect(self._onCandidateClicked)
        # 切頁重套（模式／唯讀）改由 InputLockMixin._setupInputLock 統一掛
        # currentChanged→_onShown，此處不得再自掛，否則每次切頁 _applyInputLock
        # 會跑兩遍（含兩次 isSelfServiceMode DB 讀取）。

    # ── BaseTab 介面 ────────────────────────────────────────
    def get_tables(self):
        return [self.ticket_table] if getattr(self, "ticket_table", None) else []

    def get_focus_widget(self):
        return getattr(self, "ticket_no", None)

    def _onShown(self, idx):
        """切回本頁重套。

        `main._onTabChanged` 只對設定/瀏覽/操作紀錄頁呼叫 `on_activated`
        （見 DEVELOPER §「刷新時機」），本頁靠 `_setupInputLock` 掛的
        `currentChanged→_onShown` 是唯一的切頁掛鉤點；基底 `_onShown`
        只重套唯讀鎖，不會重載預覽表／候選清單／參照下拉。覆寫成呼叫
        `on_activated()`（內含 `_applyInputLock()`），比照 `tab_reward`
        的做法，讓跨頁異動（瀏覽頁 admin 編輯／刪除、發文結算）在切回本頁
        時反映。⚠️ `_connectSignals` 不得再自行 `connect(currentChanged)`，
        否則 `_setupInputLock` 的既有連線會重複觸發本方法。
        """
        if idx == getattr(self, "_tab_index", -1):
            self.on_activated()

    def on_activated(self):
        if getattr(self, "_ref_changed", False):
            self._personnel, self._alias_map = loadActivePersonnel(self.db_path)
            pairs = [(sid, name) for sid, name, _sort in self._personnel]
            refreshFilterCombo(self.ticket_sender, pairs, alias_map=self._alias_map)
            refreshFilterCombo(self.ticket_issuer, pairs, alias_map=self._alias_map)
            self._rebuildCandidates()
            self._ref_changed = False
        self.reload()
        self._applyInputLock()

    def _onRoleClearList(self, *args):
        """降權清空必須具『持續性』，故連本次登錄清單一併清掉。

        基底 `InputLockMixin._onRoleClearList` 只把預覽表 widget 清成 0 列、
        不動 `self._session_doc_ids`。本頁 `_onShown` 是**無條件** `reload()`
        （見上；`tab_reward.on_activated` 有 dirty-flag 守衛故無此問題），
        只清 widget 的話切頁往返就會把整份清單從 DB 重建回來——降權後的一般
        使用者因此拿到一條「編輯／刪除管理身分建立之罰單」的路徑，而同一筆
        資料在資料庫瀏覽頁是僅 admin 可改（設計 §7.2）。實測過的權限回歸，
        勿只還原 widget。清 `_session_doc_ids` 不動 DB：資料仍在，只是不再
        留在本頁的操作入口內（設計 §8「管理身分登出或降權後清除本次登錄
        預覽，避免保留管理身分建立的操作入口」）。
        """
        super()._onRoleClearList(*args)
        if AuthManager.instance().is_manager():
            return
        self._session_doc_ids = []

    # ── 模式／唯讀 ──────────────────────────────────────────
    def _inputEditable(self):
        """輸入區目前是否可用（唯讀鎖未生效）。

        由 `_setupInputLock(lock_kind="ticket", ...)` 設定後，依目前鎖定狀態判定。
        """
        kind = self._resolveLockKind()
        if kind is None:
            return True
        return (AuthManager.instance().is_manager()
                or not isInputLocked(self.db_path, kind))

    def _applyInputLock(self):
        """唯讀鎖套用後必須再套一次發文結算模式，否則反灰的發文人員欄會被解鎖回可用。"""
        super()._applyInputLock()
        self._applySelfServiceMode()

    def _applySelfServiceMode(self):
        self_service = isSelfServiceMode(self.db_path, "ticket")
        self.ticket_sender.setEnabled(
            self._inputEditable() and not self_service
        )
        self.ticket_sender.setToolTip(
            _SENDER_HINT if self_service else ""
        )
        # 提示以可見 QLabel 呈現（tooltip 在深色模式整塊黑，QSS-7）
        self.ticket_sender_hint.setVisible(self_service)

    # ── 人員選擇 ────────────────────────────────────────────
    def _rebuildCandidates(self):
        """候選人員清單：一律照人員清單（`Ref_Personnel` 的 sort_order）排。

        ⚠️ 不再依開立次數重排（維護者要求改回資料庫順序）：清單順序只跟設定頁
        的人員排序走，登錄／刪除罰單都不會讓名條跳位，也省掉每次重建時的全表
        統計查詢。
        """
        self.ticket_candidates_list.clear()
        for staff_id, name, _sort in self._personnel:
            if not name:
                continue
            item = QListWidgetItem(name)
            # staff_id 存進 UserRole：點選一律取 id，不以畫面姓名字串反查
            item.setData(Qt.UserRole, staff_id)
            self.ticket_candidates_list.addItem(item)

    @staticmethod
    def _candidateStaffId(item):
        return item.data(Qt.UserRole) if item else None

    def _onCandidateClicked(self, item):
        """候選人員＝直接取代目前開立人員（不跳確認、不附加多人）。"""
        staff_id = self._candidateStaffId(item)
        if staff_id is None:
            return
        idx = self.ticket_issuer.findData(staff_id)
        if idx >= 0:
            self.ticket_issuer.setCurrentIndex(idx)

    def _clearIssuer(self):
        """「清空」只清開立人員欄（發文人員與罰單編號不動）。"""
        self.ticket_issuer.setCurrentIndex(0)
        self.ticket_issuer.clearEditText()
        self.ticket_issuer.setFocus()

    # ── 驗證 ────────────────────────────────────────────────
    def _missingFields(self):
        """回傳未填欄位名稱清單（純函式，不彈視窗，供送出流程與測試共用）。"""
        missing = []
        if (not isSelfServiceMode(self.db_path, "ticket")
                and not self.ticket_sender.currentData()):
            missing.append("發文人員")
        if not self.ticket_issuer.currentData():
            missing.append("開立人員")
        if not self.ticket_no.text().strip():
            missing.append("罰單編號")
        return missing

    def _validateInput(self):
        """必填欄位是否齊備（不含編號格式與唯一性，那些由資料層把關）。"""
        return not self._missingFields()

    # ── 新增 ────────────────────────────────────────────────
    def _submit(self):
        # 硬性 guard：反灰只擋 UI 觸發，Enter／程式路徑仍會進來。
        if (not AuthManager.instance().is_manager()
                and isInputLocked(self.db_path, "ticket")):
            msgWarning("目前為唯讀", "此年度的罰單登錄已鎖定，無法新增資料。")
            return
        missing = self._missingFields()
        if missing:
            msgWarning("欄位未填", f"請填寫以下必填欄位：\n{'、'.join(missing)}")
            self._focusFirstMissing(missing)
            return
        self_service = isSelfServiceMode(self.db_path, "ticket")
        # 發文結算模式一律送 None：反灰欄可能有殘留值，此處不得讀取。
        sender_id = None if self_service else self.ticket_sender.currentData()
        conn = None
        try:
            conn = self._getConn()
            doc_id = createTicket(
                conn,
                issuer_id=self.ticket_issuer.currentData(),
                ticket_no=self.ticket_no.text(),
                self_service=self_service,
                sender_id=sender_id,
                create_date=QDate.currentDate().toString("yyyy-MM-dd"),
                role=AuthManager.instance().current_role,
            )
            conn.commit()
        except (TicketDuplicateError, TicketValidationError) as exc:
            conn.rollback()
            self._warnTicketNo(exc)
            return
        except Exception as exc:
            if conn:
                conn.rollback()
            reportError("新增失敗", exc)
            return
        finally:
            if conn:
                conn.close()
        self._session_doc_ids.append(doc_id)
        self.reload()
        # 連續登錄同一人的多張罰單是常態 → 只清編號欄，人員留著；
        # 要換人另按「清空」。
        self.ticket_no.clear()
        self.ticket_no.setFocus()

    def _focusFirstMissing(self, missing):
        widget = {
            "發文人員": self.ticket_sender,
            "開立人員": self.ticket_issuer,
            "罰單編號": self.ticket_no,
        }.get(missing[0])
        if widget is not None:
            widget.setFocus()

    def _warnTicketNo(self, exc):
        """編號重複／格式錯誤：正式提示＋焦點移回罰單編號欄。

        ⚠️ 這兩種例外的訊息是資料層自寫的白話字串，可直接顯示；其餘例外
        （含 SQLite CHECK 違規，`str(exc)` 含 constraint SQL 全文）一律走
        `reportError`，不得直接顯示原文。
        """
        title = ("罰單編號重複" if isinstance(exc, TicketDuplicateError)
                 else "資料有誤")
        msgWarning(title, str(exc))
        self.ticket_no.setFocus()
        self.ticket_no.selectAll()

    # ── 修改 ────────────────────────────────────────────────
    def _onEditRow(self, _row, doc_id):
        dlg = TicketEditDialog(self.db_path, doc_id, self.ticket_table)
        dlg.exec()
        # 併發刪除與正常儲存都以重讀 DB 為準（不信任畫面殘值）
        self.reload()

    # ── 刪除 ────────────────────────────────────────────────
    def _deleteByDocId(self, doc_id):
        if not confirmBox(
                "確認刪除",
                f"確定刪除編號 {doc_id} 的罰單登錄資料？",
                informative=("刪除後不可還原，本筆文號將被廢棄不再使用；\n"
                             "原罰單編號日後可重新登錄。"),
                confirm_text="刪除", confirm_danger=True, default_confirm=False):
            return
        conn = None
        try:
            conn = self._getConn()
            deleteTicket(conn, doc_id=doc_id,
                         role=AuthManager.instance().current_role)
            conn.commit()
        except TicketNotFoundError as exc:
            conn.rollback()
            msgWarning("資料已刪除", str(exc))
        except Exception as exc:
            if conn:
                conn.rollback()
            reportError("刪除失敗", exc)
            return
        finally:
            if conn:
                conn.close()
        self.reload()

    # ── 預覽表 ──────────────────────────────────────────────
    def reload(self):
        """以 DB 為準重建本次登錄預覽（失效列自動移除，比照敘獎登錄）。"""
        self.ticket_table.setRowCount(0)
        if not self._session_doc_ids:
            return
        marks = ",".join("?" for _ in self._session_doc_ids)
        conn = self._getConn()
        try:
            rows = conn.execute(
                "SELECT doc_id, create_date, register_date, ticket_no, "
                "issuer_name FROM Document_Ticket_Full "
                f"WHERE doc_id IN ({marks}) AND {TICKET_ACTIVE_SQL}",
                self._session_doc_ids).fetchall()
        finally:
            conn.close()
        by_id = {str(r[0]): r for r in rows}
        self._session_doc_ids = [d for d in self._session_doc_ids if d in by_id]
        for doc_id in self._session_doc_ids:
            self._appendPreview(by_id[doc_id])

    def _appendPreview(self, row):
        doc_id, create_date, register_date, ticket_no, issuer_name = row
        pos = self.ticket_table.rowCount()
        self.ticket_table.insertRow(pos)
        container, _ = makeDeleteBtn(lambda _=False, d=doc_id: self._deleteByDocId(d))
        self.ticket_table.setCellWidget(pos, 0, container)
        setDocIdLinkCell(self.ticket_table, pos, 1, str(doc_id), self._onEditRow,
                         clickable=True)
        # issuer_name 是 View 未去後綴原值；預覽表顯示去後綴姓名，與同頁
        # 下拉／候選清單一致（否則同畫面兩種姓名寫法）。
        issuer_display = _trimName(issuer_name) if issuer_name else ""
        values = [str(create_date or ""), None,
                  str(ticket_no or ""), issuer_display]
        for offset, value in enumerate(values):
            col = offset + 2
            if col == 3:
                # register_date 三態：''＝尚未發文（發文結算登錄）→ 橘字提示。
                # 不可用 `if not register_date` 判斷有效性（NULL 是刪除哨兵，
                # 有效列查詢已排除）。
                text = str(register_date) if register_date else "未發文"
                item = QTableWidgetItem(text)
                if not register_date:
                    # 表格文字色一律 setForeground（QSS-1）
                    item.setForeground(QColor(_UNISSUED_COLOR))
            else:
                item = QTableWidgetItem(value)
            item.setTextAlignment(Qt.AlignCenter)
            item.setToolTip(item.text())
            self.ticket_table.setItem(pos, col, item)
