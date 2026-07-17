"""
backup_restore_panel.py — 設定頁「備份還原」子頁（僅 admin）

災難還原用：把某份備份覆蓋回目前資料庫。備份可能散在多處，故彙整三來源
（主備份 backups/、異地副本第二位置、db 旁重置／還原留底）成單一清單，
另留「從其他位置選擇備份檔…」逃生口涵蓋隨身碟等清單掃不到的情境。

還原前兩道防呆：
  1. verify_backup — 確認是有效 SQLite 且 quick_check 過（不讓損毀檔蓋掉本體）
  2. 選取預覽 — 顯示該備份各主表筆數，供確認「選對份」

流程：他機使用中即擋 → confirm danger → restore_backup（覆蓋前自動留底）
      → 寫還原稽核 → 呼叫 restart_cb 重啟。
"""
import os
from datetime import datetime

from PySide6.QtCore    import Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QFileDialog,
)

from lib.db_backup import formatDocCounts

from .ui_common import msgInfo, msgWarning, msgCritical, confirmBox

_HINT_SS = "color: #8e8e93; font-size: 11pt; font-weight: 400;"
# 選取樣式比照歸檔頁候選列（藍底深藍字）；hover 一律透明（不要滑過就反白）
_TABLE_SS = """
    QTableWidget { background:#ffffff; border:1px solid #d1d1d6;
                   border-radius:8px; gridline-color: transparent; }
    QHeaderView::section { background:#f2f2f7; color:#3a3a3c;
                   border:none; padding:6px 8px; font-weight:600; }
    QTableWidget::item { padding:4px 8px; color:#1c1c1e; }
    QTableWidget::item:hover { background-color: transparent; }
    QTableWidget::item:selected { background-color:#dce8f6; color:#14365f; }
    QTableWidget::item:selected:!active { background-color:#dce8f6; color:#14365f; }
"""
_RESTORE_SS = """
    QPushButton { background-color:#e74c3c; color:#ffffff; border:none;
                  border-radius:8px; padding:8px 24px; font-weight:600; }
    QPushButton:hover    { background-color:#c0392b; }
    QPushButton:disabled { background-color:#e6b8b3; color:#ffffff; }
"""


def _fmt_size(n):
    if n >= 1024 * 1024:
        return f"{n / (1024*1024):.1f} MB"
    if n >= 1024:
        return f"{n / 1024:.0f} KB"
    return f"{n} B"


def _fmt_when(dt):
    if not dt or dt == datetime.min:
        return "—"
    # 每日／每週備份無時分（當日 00:00）→ 只顯示日期；留底有時分 → 帶時分
    if (dt.hour, dt.minute, dt.second) == (0, 0, 0):
        return dt.strftime("%Y-%m-%d")
    return dt.strftime("%Y-%m-%d %H:%M")


def _formatDocCounts(counts):
    """備份內容摘要；None 表示該表不存在或無法讀取。"""
    return formatDocCounts(counts, prefix="此備份內容：", suffix="。")


class BackupRestorePanel(QWidget):
    _COLS = ["時間", "類型", "來源", "大小"]

    def __init__(self, db_path, restart_cb, parent=None):
        super().__init__(parent)
        self.db_path = db_path
        self._restart_cb = restart_cb
        self._entries = []
        self._build()
        self.reload()

    def _build(self):
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(10)

        hint = QLabel(
            "選擇一份備份還原（覆蓋目前資料庫）。清單彙整本機主備份、異地副本，"
            "以及資料庫旁的重置／還原留底。\n"
            "還原前會自動將目前資料庫另存留底；還原完成後程式會自動重新啟動。")
        hint.setStyleSheet(_HINT_SS)
        hint.setWordWrap(True)
        v.addWidget(hint)

        self.table = QTableWidget()
        self.table.setColumnCount(len(self._COLS))
        self.table.setHorizontalHeaderLabels(self._COLS)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.verticalHeader().setDefaultSectionSize(30)
        self.table.setStyleSheet(_TABLE_SS)
        hdr = self.table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.Stretch)
        hdr.setSectionResizeMode(1, QHeaderView.Fixed)
        hdr.setSectionResizeMode(2, QHeaderView.Fixed)
        hdr.setSectionResizeMode(3, QHeaderView.Fixed)
        self.table.setColumnWidth(1, 80)
        self.table.setColumnWidth(2, 120)
        self.table.setColumnWidth(3, 100)
        self.table.itemSelectionChanged.connect(self._onSelect)
        v.addWidget(self.table, 1)

        # 選取預覽（該備份各主表筆數，確認選對份）
        self.lbl_preview = QLabel("")
        self.lbl_preview.setStyleSheet(_HINT_SS)
        self.lbl_preview.setWordWrap(True)
        v.addWidget(self.lbl_preview)

        row = QHBoxLayout()
        btn_pick = QPushButton("從其他位置選擇備份檔")
        btn_pick.clicked.connect(self._pickOther)
        btn_reload = QPushButton("重整")
        btn_reload.clicked.connect(self.reload)
        row.addWidget(btn_pick)
        row.addWidget(btn_reload)
        row.addStretch()
        self.btn_restore = QPushButton("還原")
        self.btn_restore.setStyleSheet(_RESTORE_SS)
        self.btn_restore.setEnabled(False)
        self.btn_restore.clicked.connect(self._restoreSelected)
        row.addWidget(self.btn_restore)
        v.addLayout(row)

    def reload(self):
        from lib.db_backup import list_backups
        from lib.db_utils import getBackupSecondDir
        second = getBackupSecondDir(self.db_path)
        self._entries = list_backups(
            self.db_path, extra_dirs=[second] if second else None)
        self.table.setRowCount(0)
        for e in self._entries:
            r = self.table.rowCount()
            self.table.insertRow(r)
            for c, text in enumerate((
                    _fmt_when(e["when"]), e["kind"], e["source"],
                    _fmt_size(e["size"]))):
                it = QTableWidgetItem(text)
                if c != 0:
                    it.setTextAlignment(Qt.AlignCenter)
                it.setToolTip(e["path"])
                self.table.setItem(r, c, it)
        self.lbl_preview.setText(
            "尚無備份可還原。" if not self._entries else "")
        self.btn_restore.setEnabled(False)

    def _selectedEntry(self):
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return None
        idx = rows[0].row()
        if 0 <= idx < len(self._entries):
            return self._entries[idx]
        return None

    def _onSelect(self):
        e = self._selectedEntry()
        if not e:
            self.lbl_preview.setText("")
            self.btn_restore.setEnabled(False)
            return
        self.btn_restore.setEnabled(True)
        self._showPreview(e["path"])

    def _showPreview(self, path):
        from lib.db_backup import backup_doc_counts
        counts = backup_doc_counts(path)
        if not counts:
            self.lbl_preview.setText("（無法讀取此備份的內容摘要）")
            return
        self.lbl_preview.setText(_formatDocCounts(counts))

    def _pickOther(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "選擇備份檔", "", "SQLite 資料庫 (*.db);;所有檔案 (*.*)")
        if path:
            self._doRestore(path)

    def _restoreSelected(self):
        e = self._selectedEntry()
        if e:
            self._doRestore(e["path"])

    def _doRestore(self, src_path):
        from lib.auth_manager import AuthManager
        from lib.db_backup import verify_backup, restore_backup
        from lib.db_utils import writeAuditSafe, buildDetail
        from lib import app_lock

        # 權限保底（面板僅 admin 可見；防替代觸發路徑）
        if not AuthManager.instance().is_admin():
            return

        # 驗檔：不讓損毀／非資料庫檔蓋掉本體
        ok, msg = verify_backup(src_path)
        if not ok:
            msgWarning("無法還原", msg, self)
            return

        # 他機使用中即擋（best-effort：鎖檔非本實例且未過期）
        try:
            info = app_lock.read_lock(app_lock.lock_file_path(self.db_path))
            machine, _user, pid = app_lock.current_identity()
            now_iso = datetime.now().isoformat(timespec="seconds")
            if (info and not app_lock.is_mine(info, machine, pid)
                    and not app_lock.is_stale(info.get("heartbeat", ""), now_iso)):
                who = info.get("user") or "其他使用者"
                mc = info.get("machine") or "其他電腦"
                msgWarning("無法還原",
                           f"{who}（電腦 {mc}）目前正在使用本系統，"
                           "還原可能造成資料毀損。請待其關閉後再還原。", self)
                return
        except Exception:
            pass   # 鎖檔判斷失敗不阻擋還原（純勸導層）

        if not confirmBox(
                "還原備份",
                "確定以此備份覆蓋目前的資料庫？\n目前資料將被取代（覆蓋前會自動留底）。",
                confirm_text="還原並重啟", cancel_text="取消",
                confirm_danger=True, default_confirm=False,
                informative=f"來源：{os.path.basename(src_path)}\n"
                            "還原完成後程式將自動重新啟動。",
                parent=self):
            return

        ok, msg = restore_backup(self.db_path, src_path)
        if not ok:
            msgCritical("還原失敗", msg, self)
            return

        am = AuthManager.instance()
        writeAuditSafe(self.db_path, role=am.current_role, action="CONFIG",
                       operator=am.actor_name(),
                       detail=buildDetail("系統", "還原",
                                          f"備份還原：{os.path.basename(src_path)}"))
        msgInfo("還原完成",
                "資料庫已還原，程式將重新啟動。\n重啟前畫面會短暫消失，屬正常現象。\n\n"
                "提醒：於備份時間點之後歸檔的電子檔，其歸檔狀態可能與歸檔資料夾不符，"
                "請至「檔案歸檔」頁核對。",
                self)
        if callable(self._restart_cb):
            self._restart_cb()
