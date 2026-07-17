"""
trash_panel.py — 資源回收筒面板（誤刪還原，僅 admin）

自 tab_settings 抽出的獨立子頁控制器：封裝回收筒表格的初始化、載入、
過濾與還原。tab_settings 只需以既有 .ui 元件建立本面板，並在子頁被顯示時
呼叫 load()；還原後需通知瀏覽／歸檔頁重載者，由建構時的 sibling_reload
callback 傳入（table_name → key 的對應在此面板內完成）。
"""
from PySide6.QtCore    import Qt
from PySide6.QtWidgets import QTableWidget, QTableWidgetItem, QHeaderView

from lib.auth_manager import AuthManager
from lib.db_utils import getConn, writeAudit, buildDetail, restoreFromTrash

from .ui_common import (
    msgWarning, msgCritical, confirmBox, BTN_CONFIRM, BTN_CANCEL,
)

# 回收筒 table_name → 類別中文
_TRASH_CAT = {
    "Document_Task":     "交辦",
    "Document_Criminal": "刑案",
    "Document_General":  "一般",
    "Document_Reward":   "敘獎",
}
# 還原後需通知重載的 sibling Tab（瀏覽／歸檔）key
_SIBLING_KEY = {
    "Document_Task":     "task",
    "Document_Criminal": "crim",
    "Document_General":  "gen",
    "Document_Reward":   "reward",
}
_ROLE_ZH = {"admin": "管理者", "archive": "歸檔管理", "user": "一般使用者"}

_TABLE_SS = """
    QTableWidget {
        background-color: #ffffff;
        alternate-background-color: #f2f2f7;
        border: none; border-top: 1px solid #c6c6c8;
        font-size: 13pt;
    }
    QHeaderView::section {
        background-color: #f2f2f7; color: #3a3a3c;
        font-weight: 600; font-size: 13pt; padding: 4px 4px;
        border: none; border-bottom: 2px solid #c6c6c8;
        border-right: 1px solid #e5e5ea;
    }
    QTableWidget::item { padding: 2px 6px; border-bottom: 1px solid #e5e5ea; }
    QTableWidget::item:selected { background-color: #d6e3f5; color: #1c3d5a; }
"""


class TrashPanel:
    """資源回收筒子頁控制器（持有 .ui 元件參照，非 QWidget 子類）。"""

    def __init__(self, *, db_path, table, filter_edit, restore_btn, reload_btn,
                 count_label, hint_label, parent, sibling_reload=None):
        self.db_path         = db_path
        self.table           = table
        self.filter_edit     = filter_edit
        self.restore_btn     = restore_btn
        self.reload_btn      = reload_btn
        self.count_label     = count_label
        self.hint_label      = hint_label
        self.parent          = parent
        self._sibling_reload = sibling_reload
        # 與 table 列 1:1：每筆 {trash_id, doc_id, cat, subject, person, role, ts}
        self._rows = []
        self._init_table()
        self._wire()

    # ── 表格初始化 ──────────────────────────────────────────────
    def _init_table(self):
        t = self.table
        if not t:
            return
        vh = t.verticalHeader()
        vh.setVisible(False)
        vh.setDefaultSectionSize(30)        # 固定列高，比照資料庫瀏覽頁
        t.setWordWrap(False)                # 不換行（單行省略＋tooltip）
        t.setShowGrid(False)
        t.setFocusPolicy(Qt.NoFocus)        # 去焦點虛線框（選取仍可用）
        t.setAlternatingRowColors(True)
        t.setStyleSheet(_TABLE_SS)
        hdr = t.horizontalHeader()
        # 0 刪除時間 / 1 文號 / 2 類別 / 3 主旨 / 4 對象人 / 5 刪除身分
        for c in (0, 1, 2, 4, 5):
            hdr.setSectionResizeMode(c, QHeaderView.ResizeToContents)
        hdr.setSectionResizeMode(3, QHeaderView.Stretch)

    def _wire(self):
        if self.hint_label:
            self.hint_label.setText("還原後資料回填原文號。回收筒於跨年度重置時清空。")
            self.hint_label.setStyleSheet("color: #8e8e93; font-size: 11pt;")
        if self.count_label:
            self.count_label.setStyleSheet("color: #8e8e93; font-size: 11pt;")
        if self.restore_btn:
            self.restore_btn.setStyleSheet(BTN_CONFIRM)
            self.restore_btn.clicked.connect(self._restore)
        if self.reload_btn:
            self.reload_btn.setStyleSheet(BTN_CANCEL)
            self.reload_btn.clicked.connect(lambda _=False: self.load())
        if self.filter_edit:
            self.filter_edit.textChanged.connect(lambda _=None: self._render())

    @staticmethod
    def _role_zh(role):
        return _ROLE_ZH.get(role, role or "")

    # ── 載入／繪製 ──────────────────────────────────────────────
    def load(self):
        if not self.table:
            return
        rows = []
        try:
            conn = getConn(self.db_path)
            try:
                cur = conn.execute(
                    "SELECT trash_id, table_name, doc_id, subject, doc_person, "
                    "deleted_role, deleted_ts FROM Trash_Documents "
                    "ORDER BY trash_id DESC")
                for tid, tbl, doc_id, subj, person, role, ts in cur.fetchall():
                    rows.append({
                        "trash_id": tid,
                        "doc_id":   str(doc_id or ""),
                        "cat":      _TRASH_CAT.get(tbl, tbl or ""),
                        "subject":  subj or "",
                        "person":   person or "",
                        "role":     self._role_zh(role),
                        "ts":       (ts or "").replace("T", " ")[:16],
                    })
            finally:
                conn.close()
        except Exception:
            rows = []   # 缺 Trash_Documents 的舊 DB → 空清單
        self._rows = rows
        self._render()

    def _render(self):
        t = self.table
        if not t:
            return
        kw = (self.filter_edit.text() if self.filter_edit else "").strip().lower()
        t.setRowCount(0)
        shown = 0
        for r in self._rows:
            if kw and kw not in r["subject"].lower() and kw not in r["person"].lower():
                continue
            row = t.rowCount()
            t.insertRow(row)
            for c, text in enumerate(
                    (r["ts"], r["doc_id"], r["cat"],
                     r["subject"], r["person"], r["role"])):
                it = QTableWidgetItem(text)
                it.setData(Qt.UserRole, r["trash_id"])
                if c == 3 and text:
                    it.setToolTip(text)
                t.setItem(row, c, it)
            shown += 1
        if self.count_label:
            self.count_label.setText(f"顯示 {shown}／共 {len(self._rows)} 筆")

    # ── 還原 ────────────────────────────────────────────────────
    def _restore(self):
        if not AuthManager.instance().is_admin():
            return
        t = self.table
        row = t.currentRow() if t else -1
        if row < 0:
            msgWarning("請選擇項目", "請先選取要還原的紀錄", self.parent)
            return
        cell = t.item(row, 0)
        if not cell:
            return
        trash_id = cell.data(Qt.UserRole)
        subj = t.item(row, 3).text() if t.item(row, 3) else ""
        cat  = t.item(row, 2).text() if t.item(row, 2) else ""
        if not confirmBox(
                "還原誤刪", "確定還原此筆紀錄？資料將回填原文號。",
                confirm_text="還原", cancel_text="取消",
                informative=(f"{cat}　{subj}" if subj else None)):
            return
        ret = None
        conn = None
        try:
            conn = getConn(self.db_path)
            ret = restoreFromTrash(conn, trash_id)
            if ret:
                tbl, doc_id = ret
                writeAudit(conn,
                           role=AuthManager.instance().current_role,
                           action="還原", target_table=tbl,
                           target_id=str(doc_id), operator=None,
                           detail=buildDetail(
                               _TRASH_CAT.get(tbl, ""), "還原", subj))
            conn.commit()
        except Exception:
            msgCritical("還原失敗", "還原時發生錯誤，請稍後再試。", self.parent)
            return
        finally:
            if conn:
                conn.close()
        if not ret:
            msgWarning("無法還原", "此筆紀錄已不存在或無法還原。", self.parent)
        elif self._sibling_reload:
            # 標記被還原的那張表：瀏覽／歸檔頁切過去時於 on_activated 走 _forceReload
            # （runWithBusy「更新中」popup → 全量重建），遵循既有重載慣例。
            self._sibling_reload(_SIBLING_KEY.get(ret[0]))
        self.load()
