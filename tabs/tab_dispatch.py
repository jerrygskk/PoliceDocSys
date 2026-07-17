from datetime import datetime

from PySide6.QtCore import Qt, QDate
from PySide6.QtGui  import QColor
from PySide6.QtWidgets import QTableWidgetItem

from lib.base_tab import BaseTab, InputLockMixin
from lib.db_utils import DEBUG_MODE, isInputLocked
from ui_utils import msgInfo, msgWarning, msgCritical, confirmBox, reportError
from lib.auth_manager import AuthManager
from ui_utils import (
    setupPreviewTable, autoResizeTable, makeDeleteBtn, refreshDeleteBtns, setDocIdLinkCell,
    TaskEditDialog,
    setupFilterCombo, setupDateEditToToday, refreshFilterCombo,
    calcOverdue, colorForStatus, attachStickyScroll,
)


# 發文日期欄已有資料時的橘色提醒（與狀態橘一致）
_DISPATCH_DATE_COLOR = "#e67e22"

# 「尚未發文」提醒條：淺琥珀底＋深琥珀棕字（待辦提醒語意，非錯誤；
# 與表格內橘色文字以「色塊 vs 文字」形式區隔）
_PENDING_BANNER_CSS = (
    "background-color: #fdf3e0; color: #8a5c14; border: 1px solid #f0d9a8;"
    "border-radius: 7px; padding: 6px 14px; font-weight: 600;")


class TabDispatch(BaseTab, InputLockMixin):
    """交辦單發文：掃入文號 → 預覽清單 → 批次發文"""

    HEADERS   = ["", "交辦單編號", "交辦事由", "業務組", "所承辦人", "限辦日期", "發文日期", "狀態"]
    DB_COLS   = ["編號", "交辦事由", "業務組", "所承辦人", "限辦日期", "發文日期"]
    VIEW      = "View_Task_Full"
    KEY       = "編號"
    DOC_TABLE = "Document_Task"

    def setup(self, tab_index):
        tab = self.tab_widget.widget(tab_index)
        if not tab:
            return

        mw = self.tab_widget.window()
        self.lineEdit        = getattr(mw, 'lineEdit_docNum', None)
        self.table           = getattr(mw, 'tableWidget',     None)
        self.dispatch_date   = getattr(mw, 'dispatch_date',   None)
        self.dispatch_sender = getattr(mw, 'dispatch_sender', None)
        btn_send             = getattr(mw, 'btn_send',        None)
        btn_clear            = getattr(mw, 'btn_clear_all',   None)

        if self.table:
            setupPreviewTable(self.table, self.HEADERS, stretch_col=2,
                              fixed_overrides={'狀態': 210})
            attachStickyScroll(self.table)

        if self.dispatch_date:
            self.dispatch_date.setDate(QDate.currentDate())
            setupDateEditToToday(self.dispatch_date)

        if self.dispatch_sender:
            personnel, _ = self._loadRef()
            setupFilterCombo(self.dispatch_sender, personnel)

        if self.lineEdit:
            self.lineEdit.setPlaceholderText("輸入文號後按 Enter 或右側按鈕")
            self.lineEdit.returnPressed.connect(self.handleQuery)
            self.lineEdit.setFocus()
        btn_input = getattr(mw, 'btn_input_docnum', None)
        if btn_input:
            btn_input.clicked.connect(self.handleQuery)
        if btn_send:  btn_send.clicked.connect(self.handleDispatch)
        if btn_clear: btn_clear.clicked.connect(self.handleClearAll)

        # 身分切換時即時更新刪除鈕可用狀態
        AuthManager.instance().role_changed.connect(self._onRolePerm)

        # 「尚未發文」提醒條：掃入後未按發文的筆數提示（純視覺、零彈窗）。
        # 插在按鈕列與預覽表之間；先插再 _wrapLayoutWithBanner，一併搬進 inner。
        from PySide6.QtWidgets import QLabel
        self._pending = set()          # 掃入後尚未發文的 doc_id
        self._pending_banner = QLabel("")
        self._pending_banner.setStyleSheet(_PENDING_BANNER_CSS)
        self._pending_banner.setWordWrap(True)
        self._pending_banner.setVisible(False)
        _tl0 = tab.layout()
        if _tl0 is not None:
            _tl0.insertWidget(1, self._pending_banner)   # index 0=輸入列 grid

        # 唯讀橫幅＋唯讀鎖定行為（共用 InputLockMixin）。
        # 發文頁表單/表格直接放在 tabLayout，若把橫幅插進去會吃到該 layout 的
        # 左右內距而較窄，故改用 _wrapLayoutWithBanner 讓橫幅滿版（與收文/陳報一致）。
        _tl = tab.layout()
        if _tl is not None:
            self._wrapLayoutWithBanner(_tl)
        self._setupInputLock(
            tab_index,
            # 發文動作屬交辦表 task 鎖範圍（在既有交辦單上補登發文資訊），
            # 但為交辦頁專屬開關，故用 dispatch key。
            lock_kind="dispatch",
            lock_widgets=[w for w in (
                self.lineEdit, btn_input, self.dispatch_date,
                self.dispatch_sender, btn_send, btn_clear) if w],
            clear_tables=[self.table],
        )

    def _onRolePerm(self, _role=None):
        """身分變更即時生效：逐列切換刪除鈕停用/啟用，並重算編號欄可點狀態
        （admin 永遠可點，含已發文；一般使用者已發文鎖住）。"""
        if not self.table:
            return
        is_admin = AuthManager.instance().is_admin()
        # X 為「刪除佇列」（removeRow，不碰 DB），一般使用者亦可用 → 恆啟用
        refreshDeleteBtns(self.table, True)
        for r in range(self.table.rowCount()):
            # 編號欄（col 1）：依目前身分與發文狀態重算可點，即時切換連結/純文字
            lbl = self.table.cellWidget(r, 1)
            id_item = self.table.item(r, 1)
            doc_id = self._docIdFromLabel(lbl) if lbl else (id_item.text() if id_item else "")
            if not doc_id:
                continue
            disp_item = self.table.item(r, 6)
            dispatch_str = disp_item.text() if disp_item else ""
            clickable = is_admin or not dispatch_str or DEBUG_MODE
            setDocIdLinkCell(self.table, r, 1, doc_id, self._onEditRow, clickable=clickable)

    # ── BaseTab 介面 ──────────────────────────────────────
    def get_tables(self):
        return [self.table] if self.table else []

    def get_focus_widget(self):
        return self.lineEdit

    def on_activated(self):
        personnel, _ = self._loadRef()
        if self.dispatch_sender:
            refreshFilterCombo(self.dispatch_sender, personnel)
        self._refreshTaskPreviewNames(self.table)
        self._applyInputLock()
        self._updatePendingBanner()   # 表格可能被外部清空（登出降權），對齊提示


    # ── 「尚未發文」提醒條 ─────────────────────────────────
    def _tableDocIds(self):
        """回傳目前表格內全部 doc_id（widget 與純文字兩種欄型都涵蓋）。"""
        ids = set()
        if not self.table:
            return ids
        for r in range(self.table.rowCount()):
            lbl = self.table.cellWidget(r, 1)
            doc_id = self._docIdFromLabel(lbl) if lbl else None
            if not doc_id:
                item = self.table.item(r, 1)
                doc_id = item.text() if item else None
            if doc_id:
                ids.add(doc_id)
        return ids

    def _updatePendingBanner(self):
        """依 _pending 更新提醒條。先與表格現況對齊（列可能被外部清空，
        如登出降權時 InputLockMixin 的 clear_tables），避免殘留提示。"""
        if not getattr(self, "_pending_banner", None):
            return
        self._pending &= self._tableDocIds()
        n = len(self._pending)
        if n:
            self._pending_banner.setText(
                f"⚠ 尚有 {n} 筆已輸入未發文，確認清單後請按「確認發文」")
        self._pending_banner.setVisible(bool(n))

    # ── 查詢單筆 ──────────────────────────────────────────
    def handleQuery(self):
        if not self.lineEdit:
            return
        serial = self.lineEdit.text().strip()
        if not serial:
            return

        col_str = ", ".join([f'"{c}"' for c in self.DB_COLS])
        sql     = f'SELECT {col_str} FROM "{self.VIEW}" WHERE "{self.KEY}" = ?'
        try:
            conn = self._getConn()
            row  = conn.execute(sql, (serial,)).fetchone()
            conn.close()
        except Exception as e:
            reportError("SQL 錯誤", e)
            return

        if row:
            # 另外查 receive_date 判斷是否已刪除
            try:
                conn2  = self._getConn()
                rd_row = conn2.execute(
                    "SELECT receive_date FROM Document_Task WHERE doc_id=?", (serial,)
                ).fetchone()
                conn2.close()
            except Exception:
                rd_row = None

            recv_date = rd_row[0] if rd_row else None
            if recv_date is None:
                msgWarning("查無資料", f"找不到文號「{serial}」，可能已被刪除")
                self.lineEdit.clear()
                return

            if self._rowExists(str(row[0])):
                msgInfo("提示", f"「{serial}」已在清單中")
            else:
                # DB_COLS = ["編號", "交辦事由", "業務組", "所承辦人", "限辦日期", "發文日期"]
                missing = []
                if not row[2]: missing.append("業務組")
                if not row[1]: missing.append("交辦事由")
                if not row[3]: missing.append("所承辦人")
                if missing:
                    if not confirmBox(
                        "資料不完整",
                        f"此文號資料不完整（缺少：{'、'.join(missing)}），仍可發文，確認加入清單？",
                        confirm_text="仍要加入", default_confirm=True
                    ):
                        self.lineEdit.clear()
                        return
                self._insertRow(row)
            self.lineEdit.clear()
        else:
            msgWarning("查無資料", f"找不到：{serial}")

    def _rowExists(self, doc_id):
        """檢查 doc_id 是否已在表格中（從 QLabel widget 讀取）"""
        if not self.table:
            return False
        for r in range(self.table.rowCount()):
            lbl = self.table.cellWidget(r, 1)
            if lbl and self._docIdFromLabel(lbl) == doc_id:
                return True
        # fallback：純文字 item（已發文且非 DEBUG_MODE）
        for r in range(self.table.rowCount()):
            item = self.table.item(r, 1)
            if item and item.text() == doc_id:
                return True
        return False

    def _insertRow(self, data):
        if not self.table:
            return
        pos = self.table.rowCount()
        self.table.insertRow(pos)

        doc_id       = str(data[0]) if data[0] else ""
        deadline_str = str(data[4]) if data[4] else ""
        dispatch_str = str(data[5]) if data[5] else ""

        is_admin = AuthManager.instance().is_admin()

        # 刪除按鈕（col 0）：以 doc_id 為準，不用 row index
        # X 為「刪除佇列」（removeRow，不寫 DB），一般使用者亦可移除誤掃入的列 → 恆啟用
        container, del_btn = makeDeleteBtn(lambda _, d=doc_id: self._deleteByDocId(d))
        self.table.setCellWidget(pos, 0, container)

        # 編號欄（col 1）：admin 永遠可點（含已發文）；一般使用者僅未發文可點，已發文鎖住。DEBUG_MODE 一律可點
        clickable = is_admin or not dispatch_str or DEBUG_MODE
        setDocIdLinkCell(self.table, pos, 1, doc_id, self._onEditRow, clickable=clickable)

        # 其他欄位（col 2~4）
        for i in range(1, 4):
            item = QTableWidgetItem(str(data[i]) if data[i] else "")
            item.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(pos, i + 1, item)

        for col, val in [(5, deadline_str), (6, dispatch_str)]:
            item = QTableWidgetItem(val)
            item.setTextAlignment(Qt.AlignCenter)
            # 發文日期欄已有資料 → 橘色提醒（發文後將被覆蓋）
            if col == 6 and val:
                item.setForeground(QColor(_DISPATCH_DATE_COLOR))
            self.table.setItem(pos, col, item)

        status      = calcOverdue(deadline_str, dispatch_str)
        status_item = QTableWidgetItem(status)
        status_item.setTextAlignment(Qt.AlignCenter)
        color = colorForStatus(status)
        if color:
            status_item.setForeground(color)
        self.table.setItem(pos, 7, status_item)
        autoResizeTable(self.table)
        if doc_id:
            self._pending.add(doc_id)
            self._updatePendingBanner()

    def _onEditRow(self, row, doc_id):
        """點擊超連結 → 開啟 EditDialog（一般使用者只可改承辦人）"""
        restricted = not AuthManager.instance().is_admin()
        # 硬 gate：一般使用者不可改已發文的單（以 DB 為準，不信任連結殘留
        # 的可點狀態——顯示層漏重算時這裡仍擋得住）
        if restricted and not DEBUG_MODE:
            try:
                conn = self._getConn()
                row_db = conn.execute(
                    "SELECT dispatch_date FROM Document_Task WHERE doc_id=?",
                    (doc_id,)).fetchone()
                conn.close()
            except Exception:
                row_db = None
            if row_db and row_db[0]:
                msgInfo("已發文", f"「{doc_id}」已發文，一般使用者不可再修改。")
                return
        dlg = TaskEditDialog(self.db_path, doc_id, self.table,
                             restricted=restricted, source='dispatch')
        if dlg.exec():
            updated = dlg.get_updated()
            if updated:
                # updated = (編號, 交辦事由, 業務組, 所承辦人, 限辦日期, 發文日期, 狀態)
                _, subject, dept, proc, deadline, dispatch, status = updated
                for col, val in enumerate([subject, dept, proc], start=2):
                    item = QTableWidgetItem(str(val) if val else "")
                    item.setTextAlignment(Qt.AlignCenter)
                    self.table.setItem(row, col, item)
                for col, val in [(5, deadline), (6, dispatch)]:
                    item = QTableWidgetItem(str(val) if val else "")
                    item.setTextAlignment(Qt.AlignCenter)
                    if col == 6 and val:
                        item.setForeground(QColor(_DISPATCH_DATE_COLOR))
                    self.table.setItem(row, col, item)
                status_item = QTableWidgetItem(str(status) if status else "")
                status_item.setTextAlignment(Qt.AlignCenter)
                color = colorForStatus(str(status) if status else "")
                if color:
                    status_item.setForeground(color)
                self.table.setItem(row, 7, status_item)

    # ── 刪除（第1點：doc_id 驅動，不需重新綁定）────────────
    def _deleteByDocId(self, doc_id):
        """從 doc_id 找到對應列並移除，不操作 row index。"""
        if not self.table:
            return
        for r in range(self.table.rowCount()):
            # 先找 QLabel（超連結欄）
            lbl = self.table.cellWidget(r, 1)
            if lbl and self._docIdFromLabel(lbl) == doc_id:
                self.table.removeRow(r)
                self._updatePendingBanner()
                return
            # fallback：純文字 item
            item = self.table.item(r, 1)
            if item and item.text() == doc_id:
                self.table.removeRow(r)
                self._updatePendingBanner()
                return

    # ── 全部清除 ──────────────────────────────────────────
    def handleClearAll(self):
        if not self.table or self.table.rowCount() == 0:
            msgInfo("提示", "清單已經是空的")
            return
        if confirmBox("確認清除", f"確定要清除全部 {self.table.rowCount()} 筆資料？",
                      confirm_text="清除", confirm_danger=True, default_confirm=True):
            self.table.setRowCount(0)
            self._updatePendingBanner()

    # ── 批次發文 ──────────────────────────────────────────
    def handleDispatch(self):
        # 唯讀 gate：交辦表被鎖時一般使用者不可發文（真正防線，涵蓋按鈕與所有觸發）
        if not AuthManager.instance().is_manager() and isInputLocked(self.db_path, "dispatch"):
            msgWarning("唯讀模式", "本功能目前為唯讀模式無法使用。")
            return
        if not self.table or self.table.rowCount() == 0:
            msgInfo("提示", "清單是空的，請先掃入文號")
            return

        today = datetime.now().strftime("%Y-%m-%d")

        # 收集所有列的 doc_id（從 widget 或 item 讀取）
        pending = []
        for r in range(self.table.rowCount()):
            lbl = self.table.cellWidget(r, 1)
            doc_id = self._docIdFromLabel(lbl) if lbl else None
            if not doc_id:
                item = self.table.item(r, 1)
                doc_id = item.text() if item else None
            if doc_id:
                pending.append((r, doc_id))

        dispatch_day = (
            self.dispatch_date.date().toString("yyyy-MM-dd")
            if self.dispatch_date else today
        )
        sender_id   = self.dispatch_sender.currentData() if self.dispatch_sender else None
        sender_name = self.dispatch_sender.currentText() if self.dispatch_sender else "未選擇"

        # 發文人員必填（比照刑案／一般陳報；避免寫出無送件人的簽收表）
        if not sender_id:
            msgWarning("欄位未填", "請選擇發文人員。")
            return

        # 計算已有發文日期的筆數
        try:
            conn = self._getConn()
            already = 0
            for _, doc_id in pending:
                row = conn.execute(
                    f'SELECT dispatch_date FROM "{self.DOC_TABLE}" WHERE doc_id=?', (doc_id,)
                ).fetchone()
                if row and row[0]:
                    already += 1
            conn.close()
        except Exception:
            already = 0

        overwrite_note = f"（其中 {already} 筆將覆蓋原發文日期）" if already else ""
        if not confirmBox(
            "確認發文",
            f"發文日期：{dispatch_day}\n發文人員：{sender_name}\n"
            f"共 {len(pending)} 筆交辦單{overwrite_note}\n確認送出？",
            confirm_text="發文", default_confirm=True
        ):
            return

        sql = (
            f'UPDATE "{self.DOC_TABLE}" '
            f'SET dispatch_date=?, sender_id=?, timestamp=? '
            f'WHERE doc_id=?'
        )
        conn = None
        try:
            conn = self._getConn()
            for seq, (row_idx, doc_id) in enumerate(pending):
                ts     = datetime.now()
                us     = (ts.microsecond + seq) % 1_000_000
                ts_str = ts.strftime("%Y-%m-%d %H:%M:%S.") + f"{us:06d}"
                conn.execute(sql, (dispatch_day, sender_id, ts_str, doc_id))

                item = QTableWidgetItem(dispatch_day)
                item.setTextAlignment(Qt.AlignCenter)
                item.setForeground(QColor(_DISPATCH_DATE_COLOR))
                self.table.setItem(row_idx, 6, item)

                deadline_item = self.table.item(row_idx, 5)
                deadline_val  = deadline_item.text() if deadline_item else ""
                status        = calcOverdue(deadline_val, dispatch_day)
                status_item   = QTableWidgetItem(status)
                status_item.setTextAlignment(Qt.AlignCenter)
                color = colorForStatus(status)
                if color:
                    status_item.setForeground(color)
                self.table.setItem(row_idx, 7, status_item)

                # 列已從未發文轉為已發文：重算編號欄可點狀態，
                # 一般使用者的連結須即時鎖住（admin／DEBUG 仍可點）
                clickable = AuthManager.instance().is_admin() or DEBUG_MODE
                setDocIdLinkCell(self.table, row_idx, 1, doc_id,
                                 self._onEditRow, clickable=clickable)

            conn.commit()
            self._pending.clear()          # 整表已送出，提醒解除
            self._updatePendingBanner()
            msgInfo("完成", f"已成功更新 {len(pending)} 筆發文日期（{dispatch_day}）")
        except Exception as e:
            reportError("更新失敗", e)
        finally:
            if conn:
                conn.close()
