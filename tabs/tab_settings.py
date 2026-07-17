"""
tab_settings.py — 資料庫設定 Tab

流程：
  1. 進入 Tab → 顯示密碼驗證畫面（QStackedWidget index 0）
  2. 輸入正確密碼 → 切換到設定主畫面（index 1）
  3. 離開 Tab → 自動 logout，切回密碼驗證畫面
"""
import os
import sys
import shutil
import subprocess
from datetime import datetime

from PySide6.QtCore    import Qt, QProcess, QObject, QEvent, QRegularExpression
from PySide6.QtGui     import QColor, QPen, QRegularExpressionValidator
from PySide6.QtWidgets import (
    QVBoxLayout, QStackedWidget,
    QLabel, QLineEdit, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView,
    QWidget, QApplication, QFileDialog,
    QStyledItemDelegate, QStyle,
)

from lib.base_tab import BaseTab
from lib.auth_manager import AuthManager
from lib.db_backup import formatDocCounts
from lib.db_utils import (
    getResourcePath,
    performYearEndReset, getSetting, ARCHIVE_ROOT_KEY,
    getConn, writeAudit, writeAuditSafe, buildDetail,
)
from ui_utils import (
    msgInfo, msgWarning, msgCritical, confirmBox, reportError,
    BTN_CONFIRM, BTN_CANCEL, loadUi,
)
from ui_utils import (
    RefItemDialog, REF_PERSONNEL, REF_DEPT, REF_CASETYPE,
    ChangePasswordDialog, ResetDialog,
    ArchiveRootPanel, PrintTitlePanel, IdleTimeoutPanel, InputLockPanel, BackupPanel,
    InputModePanel,
    preserveScroll,
)
from ui_utils.settings_dialogs import _parseSeqMoveTarget
from ui_utils.trash_panel import TrashPanel
from ui_utils.backup_restore_panel import BackupRestorePanel

# ── 左側導航按鈕樣式 ────────────────────────────────────────────
_NAV_ACTIVE = (
    "QPushButton { background-color: #8fa8c8; color: #ffffff; "
    "border: none; border-radius: 8px; padding: 10px 14px; "
    "font-weight: 600; font-size: 14pt; text-align: left; }"
)
_NAV_INACTIVE = (
    "QPushButton { background-color: transparent; color: #1c1c1e; "
    "border: none; border-radius: 8px; padding: 10px 14px; "
    "font-weight: 500; font-size: 14pt; text-align: left; }"
    "QPushButton:hover { background-color: #e5e5ea; }"
    "QPushButton:disabled { color: #c5c5c9; background-color: transparent; }"
)
_NAV_BOTTOM = (
    "QPushButton { background-color: transparent; color: #636366; "
    "border: none; border-radius: 8px; padding: 10px 14px; "
    "font-weight: 500; font-size: 14pt; text-align: left; }"
    "QPushButton:hover { background-color: #e5e5ea; }"
)
_NAV_DANGER = (
    "QPushButton { background-color: transparent; color: #c0392b; "
    "border: none; border-radius: 8px; padding: 10px 14px; "
    "font-weight: 500; font-size: 14pt; text-align: left; }"
    "QPushButton:hover { background-color: #f8e4e1; }"
    "QPushButton:disabled { color: #c5c5c9; background-color: transparent; }"
)


class _NoFocusDelegate(QStyledItemDelegate):
    """移除「目前儲存格」焦點外框（Windows 樣式點擊後會在該格畫框）。
    僅去焦點框，保留列選取底色（拖拉排序需要 currentRow）。"""
    def paint(self, painter, option, index):
        if option.state & QStyle.State_HasFocus:
            option.state &= ~QStyle.State_HasFocus
        super().paint(painter, option, index)


class _SeqEditDelegate(_NoFocusDelegate):
    """序號欄專用 delegate：editor 限定只能打數字；
    paint 疊一層淺色虛線框，常駐提示「這格可以點來改」（呼應 ⠿ 把手欄的提示風格）。"""

    def createEditor(self, parent, option, index):
        editor = QLineEdit(parent)
        editor.setValidator(QRegularExpressionValidator(
            QRegularExpression(r"[0-9]*"), editor))
        editor.setAlignment(Qt.AlignCenter)
        # 全域 theme.py 對所有 QLineEdit 套 padding: 6px 10px，疊上字級後在固定 36px 列高
        # 裡可能擠到下緣被裁切；padding/margin 歸零騰出空間。border 不覆寫，沿用
        # theme.py 原本的數字（平常 1px、focus 2px，cascade 自動接回來）
        editor.setStyleSheet("font-size: 13pt; padding: 0px; margin: 0px;")
        return editor

    def paint(self, painter, option, index):
        super().paint(painter, option, index)
        painter.save()
        pen = QPen(QColor("#9bb0c9"))
        pen.setStyle(Qt.DashLine)
        painter.setPen(pen)
        painter.drawRect(option.rect.adjusted(2, 2, -3, -3))
        painter.restore()


class _RowDragFilter(QObject):
    """攔截 QTableWidget viewport 的 Drop 事件，實作整列拖拉（Qt InternalMove 只移格，不移列）。"""
    def __init__(self, tbl, callback):
        super().__init__(tbl)
        self._tbl = tbl
        self._cb  = callback  # callback(src_row, dst_row)

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Drop:
            src = self._tbl.currentRow()
            dst = self._tbl.rowAt(int(event.position().y()))
            if dst < 0:
                dst = self._tbl.rowCount() - 1
            if src >= 0 and src != dst:
                self._cb(src, dst)
            return True   # 阻止 Qt 的預設錯位行為
        return False


# ── 表格樣式 ────────────────────────────────────────────────────
_TABLE_SS = """
    QTableWidget {
        background-color: #ffffff;
        alternate-background-color: #f2f2f7;
        border: none;
        border-top: 1px solid #c6c6c8;
        font-size: 13pt;
        outline: 0;
    }
    QHeaderView::section {
        background-color: #f2f2f7;
        color: #3a3a3c;
        font-weight: 600;
        font-size: 13pt;
        padding: 4px 8px;
        border: none;
        border-bottom: 2px solid #c6c6c8;
        border-right: 1px solid #e5e5ea;
    }
    QTableWidget::item {
        padding: 4px 8px;
        border-bottom: 1px solid #e5e5ea;
    }
    QTableWidget::item:selected {
        background-color: #ccdaeb;
    }
"""

# 停用列灰字
_COLOR_INACTIVE = "#aeaeb2"

# 儲存排序鈕樣式（含 disabled 灰色狀態）
_SAVE_BTN_SS = """
    QPushButton {
        background-color: #D0ECF5;
        color: #000000;
        border: 1px solid #b0d4e0;
        border-radius: 6px;
        padding: 6px 16px;
        font-size: 13pt;
    }
    QPushButton:hover    { background-color: #B8D8E8; }
    QPushButton:disabled {
        background-color: #e8e8ed;
        color: #aeaeb2;
        border: 1px solid #d1d1d6;
    }
"""


def _resetDocCounts(conn):
    """跨年度重置前的 active 主表筆數；排除軟刪除空殼。"""
    queries = {
        "task": "SELECT COUNT(*) FROM Document_Task WHERE receive_date IS NOT NULL",
        "crim": "SELECT COUNT(*) FROM Document_Criminal WHERE report_date IS NOT NULL",
        "gen": "SELECT COUNT(*) FROM Document_General WHERE report_date IS NOT NULL",
        "reward": "SELECT COUNT(*) FROM Document_Reward WHERE register_date IS NOT NULL",
    }
    return {key: conn.execute(sql).fetchone()[0] for key, sql in queries.items()}


def _resetSummary(counts):
    """重置確認與 Audit 共用的正式筆數摘要。"""
    return formatDocCounts(counts)


class TabSettings(BaseTab):
    """資料庫設定 Tab"""

    _PAGE_PERSONNEL = 0
    _PAGE_DEPT      = 1
    _PAGE_CASETYPE  = 2
    _PAGE_SYSTEM    = 3
    _PAGE_TRASH     = 4
    _PAGE_BACKUP    = 5

    def setup(self, tab_index):
        tab = self.tab_widget.widget(tab_index)
        if not tab:
            return

        self._my_tab_index = tab_index
        self._ref_dirty    = False
        # 排序暫存狀態：每頁一份 {鍵: {'rows': [...], 'dirty': bool, 'save_btn': btn, 'table': tbl}}
        self._sort_state = {}

        # ── 載入 .ui 靜態骨架 ──
        ui = loadUi(getResourcePath("layouts/Layout7.ui"))
        if not ui:
            return
        inner = ui.centralWidget()
        lay   = QVBoxLayout(tab)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(inner)

        # ── 抓元件 ──
        self._outer_stack = inner.findChild(QStackedWidget, "outer_stack")
        self._inner_stack = inner.findChild(QStackedWidget, "inner_stack")

        # 密碼驗證頁
        self._login_card    = inner.findChild(QWidget,     "login_card")
        self._lbl_login_ttl = inner.findChild(QLabel,      "lbl_login_title")
        self.w_password     = inner.findChild(QLineEdit,   "w_password")
        self.lbl_login_err  = inner.findChild(QLabel,      "lbl_login_err")
        btn_login           = inner.findChild(QPushButton, "btn_login")

        # 左側導航
        self._nav_panel  = inner.findChild(QWidget, "nav_panel")
        self._nav_btns   = [
            inner.findChild(QPushButton, "btn_nav_personnel"),
            inner.findChild(QPushButton, "btn_nav_dept"),
            inner.findChild(QPushButton, "btn_nav_casetype"),
            inner.findChild(QPushButton, "btn_nav_system"),
            inner.findChild(QPushButton, "btn_nav_trash"),
            inner.findChild(QPushButton, "btn_nav_backup"),
        ]
        btn_change_pwd = inner.findChild(QPushButton, "btn_change_pwd")
        btn_year_reset = inner.findChild(QPushButton, "btn_year_reset")
        self._btn_year_reset = btn_year_reset
        btn_logout     = inner.findChild(QPushButton, "btn_logout")

        # 三子頁的表格、新增/修改/儲存排序按鈕
        self.tbl_personnel = inner.findChild(QTableWidget, "tbl_personnel")
        self.tbl_dept      = inner.findChild(QTableWidget, "tbl_dept")
        self.tbl_casetype  = inner.findChild(QTableWidget, "tbl_casetype")

        # 資源回收筒（僅 admin）
        self.tbl_trash         = inner.findChild(QTableWidget, "tbl_trash")
        self.w_trash_filter    = inner.findChild(QLineEdit,    "w_trash_filter")
        self.btn_restore_trash = inner.findChild(QPushButton,  "btn_restore_trash")
        self.btn_reload_trash  = inner.findChild(QPushButton,  "btn_reload_trash")
        self.lbl_trash_count   = inner.findChild(QLabel,       "lbl_trash_count")
        self._lbl_hint_trash   = inner.findChild(QLabel,       "lbl_hint_trash")

        self.btn_add_personnel  = inner.findChild(QPushButton, "btn_add_personnel")
        self.btn_edit_personnel = inner.findChild(QPushButton, "btn_edit_personnel")
        self.btn_save_personnel = inner.findChild(QPushButton, "btn_save_personnel")
        self.btn_add_dept       = inner.findChild(QPushButton, "btn_add_dept")
        self.btn_edit_dept      = inner.findChild(QPushButton, "btn_edit_dept")
        self.btn_save_dept      = inner.findChild(QPushButton, "btn_save_dept")
        self.btn_add_casetype   = inner.findChild(QPushButton, "btn_add_casetype")
        self.btn_edit_casetype  = inner.findChild(QPushButton, "btn_edit_casetype")
        self.btn_save_casetype  = inner.findChild(QPushButton, "btn_save_casetype")

        # ── 套樣式（動態狀態樣式留在 code，比照其他 Tab 慣例） ──
        self._applyStaticStyles()
        btn_login.setStyleSheet(
            "QPushButton { background-color: #D0ECF5; color: #000000; "
            "border-radius: 8px; padding: 8px 16px; font-weight: bold; }"
            "QPushButton:hover { background-color: #B8D8E8; }"
        )
        btn_change_pwd.setStyleSheet(_NAV_BOTTOM)
        btn_year_reset.setStyleSheet(_NAV_DANGER)
        btn_logout.setStyleSheet(_NAV_BOTTOM)

        # ── 綁定 signal ──
        self.w_password.returnPressed.connect(self._doLogin)
        btn_login.clicked.connect(self._doLogin)
        for i, btn in enumerate(self._nav_btns):
            btn.clicked.connect(lambda _=False, idx=i: self._switchPage(idx))
        btn_change_pwd.clicked.connect(self._changePassword)
        btn_year_reset.clicked.connect(self._doReset)
        btn_logout.clicked.connect(self._doLogout)

        # ── 初始化三頁的表格與排序暫存狀態 ──
        self._initRefPage("personnel", self.tbl_personnel,
                          self.btn_add_personnel, self.btn_edit_personnel,
                          self.btn_save_personnel)
        self._initRefPage("dept", self.tbl_dept,
                          self.btn_add_dept, self.btn_edit_dept,
                          self.btn_save_dept)
        self._initRefPage("casetype", self.tbl_casetype,
                          self.btn_add_casetype, self.btn_edit_casetype,
                          self.btn_save_casetype)

        # 提示字（用 inner 查找，避免 btn.parent() 在 QUiLoader 環境觸發 GC 刪 C++ widget）
        for _key in ("personnel", "dept", "casetype"):
            _lbl = inner.findChild(QLabel, f"lbl_hint_{_key}")
            if _lbl:
                _lbl.setText("可拖拉列或點序號欄數字調整排序，完成後按「儲存排序」")
                _lbl.setStyleSheet("color: #8e8e93; font-size: 11pt;")

        # ── 資源回收筒：抽成獨立面板（ui_utils/trash_panel.py）──
        self._trash_panel = TrashPanel(
            db_path=self.db_path,
            table=self.tbl_trash,
            filter_edit=self.w_trash_filter,
            restore_btn=self.btn_restore_trash,
            reload_btn=self.btn_reload_trash,
            count_label=self.lbl_trash_count,
            hint_label=self._lbl_hint_trash,
            parent=self.tab_widget,
            sibling_reload=self._flagSiblingReload)

        # ── 系統設定子頁：三個嵌入面板掛進捲動容器（ui_utils/settings_panels.py）──
        scroll = inner.findChild(QWidget, "system_scroll")
        if scroll:
            # 捲動區透明化，沿用頁面底色（QScrollArea 預設灰底會突兀）
            scroll.setStyleSheet(
                "QScrollArea { background: transparent; border: none; }"
                "QScrollArea > QWidget > QWidget { background: transparent; }")
        sys_content = inner.findChild(QWidget, "system_scroll_content")
        self._panel_archive_root = ArchiveRootPanel(self.db_path, sys_content)
        self._panel_print_title  = PrintTitlePanel(self.db_path, sys_content)
        self._panel_idle         = IdleTimeoutPanel(self.db_path, sys_content)
        self._panel_input_lock   = InputLockPanel(self.db_path, sys_content)
        self._panel_backup       = BackupPanel(self.db_path, sys_content)
        self._panel_input_mode   = InputModePanel(self.db_path, sys_content)
        if sys_content and sys_content.layout():
            sys_lay = sys_content.layout()
            sys_lay.addWidget(self._panel_archive_root)
            sys_lay.addWidget(self._panel_print_title)
            sys_lay.addWidget(self._panel_idle)
            sys_lay.addWidget(self._panel_input_lock)
            sys_lay.addWidget(self._panel_backup)
            sys_lay.addWidget(self._panel_input_mode)
            sys_lay.addStretch()

        # ── 備份還原子頁（僅 admin；內容於程式建立、掛進 page_backup 的 backupLayout）──
        backup_content = inner.findChild(QWidget, "backup_content")
        self._panel_restore = None
        if backup_content and backup_content.layout():
            self._panel_restore = BackupRestorePanel(
                self.db_path, restart_cb=self._restartApp, parent=backup_content)
            backup_content.layout().addWidget(self._panel_restore)

        self._outer_stack.setCurrentIndex(0)

        # 監聽身份變化：登出時自動回到密碼驗證畫面
        AuthManager.instance().role_changed.connect(self._onRoleChanged)
        # 啟動時若已登入（理論上不會），直接顯示主畫面
        if AuthManager.instance().is_manager():
            self._applyRolePermissions()
            self._outer_stack.setCurrentIndex(1)
            self._switchPage(self._PAGE_PERSONNEL)

    # ── 套用靜態樣式到 .ui 元件 ──────────────────────────────────
    def _applyStaticStyles(self):
        self._login_card.setStyleSheet(
            "QWidget#login_card { background-color: #ffffff; border-radius: 12px; }"
        )
        self._lbl_login_ttl.setStyleSheet(
            "font-size: 16pt; font-weight: 700; color: #1c1c1e; background: transparent;"
        )
        self.w_password.setStyleSheet(
            "QLineEdit { background:#f2f2f7; border:1px solid #c6c6c8; "
            "border-radius:8px; padding:8px 12px; color:#1c1c1e; "
            "qproperty-alignment: AlignCenter; }"
            "QLineEdit:focus { border:2px solid #8fa8c8; }"
        )
        self.lbl_login_err.setStyleSheet(
            "color: #e74c3c; background: transparent; font-size: 12pt;"
        )
        # 登入鈕沿用全域 BTN 樣式
        self._nav_panel.setStyleSheet("QWidget#nav_panel { background-color: #f2f2f7; }")
        # 變更密碼 / 登出（底部 nav）
        # 三個導航鈕的選中/未選中樣式由 _switchPage 動態切換

    # ── 初始化單一參照頁（表格樣式 + 動作鈕綁定 + 排序暫存） ──────
    def _initRefPage(self, key, tbl, btn_add, btn_edit, btn_save):
        # 表格樣式與行為
        tbl.verticalHeader().setVisible(False)
        tbl.setEditTriggers(QTableWidget.NoEditTriggers)
        tbl.setSelectionBehavior(QTableWidget.SelectRows)
        tbl.setSelectionMode(QTableWidget.SingleSelection)
        tbl.setAlternatingRowColors(True)
        tbl.setShowGrid(False)
        tbl.verticalHeader().setDefaultSectionSize(36)
        tbl.setStyleSheet(_TABLE_SS)
        # 去掉點擊後「目前儲存格」焦點外框（保留列選取底色，拖拉需 currentRow）
        tbl.setItemDelegate(_NoFocusDelegate(tbl))
        hdr = tbl.horizontalHeader()
        name_c, alias_c, status_c = self._refCols(key)
        hdr.setSectionResizeMode(self._HANDLE_COL, QHeaderView.Fixed)
        tbl.setColumnWidth(self._HANDLE_COL, 36)
        hdr.setSectionResizeMode(self._SEQ_COL, QHeaderView.Fixed)
        tbl.setColumnWidth(self._SEQ_COL, 64)
        hdr.setSectionResizeMode(status_c, QHeaderView.Fixed)
        tbl.setColumnWidth(status_c, 80)
        hdr.setSectionResizeMode(name_c, QHeaderView.Stretch)
        if alias_c is not None:
            hdr.setSectionResizeMode(alias_c, QHeaderView.Stretch)
        # 序號欄：單擊即進行內編輯（呼應框中數字「可點改位置」的視覺提示）
        tbl.cellClicked.connect(
            lambda row, col, t=tbl, k=key: self._onCellClicked(t, row, col, k))
        # 名稱等其餘欄：雙擊開修改對話框
        tbl.cellDoubleClicked.connect(
            lambda row, col, t=tbl, k=key: self._onCellDoubleClicked(t, row, col, k))

        # 拖拉排序（event filter 攔截 Drop，阻止 Qt 的逐格移動行為，改成整列記憶體操作）
        from PySide6.QtWidgets import QAbstractItemView
        tbl.setDragDropMode(QAbstractItemView.InternalMove)
        tbl.setDefaultDropAction(Qt.MoveAction)
        tbl.setAutoScrollMargin(90)
        drag_filter = _RowDragFilter(tbl, lambda s, d, k=key: self._onDragDrop(k, s, d))
        tbl.viewport().installEventFilter(drag_filter)

        # 序號欄可編輯（打數字搬移），delegate 限定只能輸入數字
        seq_delegate = _SeqEditDelegate(tbl)
        tbl.setItemDelegateForColumn(self._SEQ_COL, seq_delegate)
        tbl.itemChanged.connect(lambda item, k=key: self._onSeqItemChanged(k, item))

        # 動作鈕樣式與綁定
        btn_add.setStyleSheet(BTN_CONFIRM)
        btn_edit.setStyleSheet(BTN_CANCEL)
        btn_save.setStyleSheet(_SAVE_BTN_SS)
        btn_add.clicked.connect(lambda _=False, k=key: self._addRef(k))
        btn_edit.clicked.connect(lambda _=False, k=key: self._editRef(k))
        btn_save.setEnabled(False)
        btn_save.clicked.connect(lambda _=False, k=key: self._saveSort(k))

        self._sort_state[key] = {
            "rows": [], "dirty": False, "save_btn": btn_save, "table": tbl,
            "drag_filter": drag_filter, "seq_delegate": seq_delegate}  # 防 GC

    def _onDragDrop(self, key, src_row, dst_row):
        """整列移動：記憶體 rows 重排，重繪表格，選中移動後的列"""
        self._moveRow(key, src_row, dst_row)

    def _moveRow(self, key, src, dst):
        """共用搬移邏輯：記憶體 rows 重排＋設 dirty＋亮儲存排序鈕＋重繪＋選取目標列。
        拖拉（_onDragDrop）、序號欄編輯（_onSeqItemChanged，Task 3）、
        新增指定位置（_addPersonnel 等，Task 4）共用同一套搬移邏輯。"""
        st   = self._sort_state[key]
        rows = st["rows"]
        rows.insert(dst, rows.pop(src))
        st["dirty"] = True
        st["save_btn"].setEnabled(True)
        self._renderSortTable(key)
        st["table"].selectRow(dst)

    def _onCellClicked(self, tbl, row, col, key):
        """序號欄單擊＝進入行內編輯（框中數字可點改排序位置）。"""
        if col != self._SEQ_COL:
            return
        # 歸檔管理唯讀：不得進序號行內編輯
        # （按鈕 enabled 擋得住按鈕，擋不住點擊，故此處補 gate）
        if not self._refEditable():
            return
        item = tbl.item(row, self._SEQ_COL)
        if item:
            tbl.editItem(item)

    def _onCellDoubleClicked(self, tbl, row, col, key):
        """名稱等欄位雙擊＝開修改對話框；序號欄已由單擊處理，此處略過。"""
        if col == self._SEQ_COL:
            return
        # 歸檔管理唯讀：雙擊不得開修改框（_editRef 亦有 guard，此處提早返回）
        if not self._refEditable():
            return
        self._editRef(key, row)

    def _onSeqItemChanged(self, key, item):
        """序號欄編輯完成（Enter／離焦）：合法則搬移，不合法安靜跳回原數字。"""
        if item.column() != self._SEQ_COL:
            return
        if not self._refEditable():   # 防禦：唯讀身分不得觸發搬移（會亮回儲存排序鈕）
            return
        st     = self._sort_state[key]
        row    = item.row()
        target = _parseSeqMoveTarget(item.text(), len(st["rows"]))
        if target is None:
            st["table"].blockSignals(True)
            item.setText(str(row + 1))
            st["table"].blockSignals(False)
            return
        if target == row:
            return
        self._moveRow(key, row, target)

    def _item(self, text, color=None):
        it = QTableWidgetItem(str(text) if text is not None else "")
        it.setTextAlignment(Qt.AlignCenter)
        it.setForeground(QColor(color if color else "#1c1c1e"))
        return it

    def _handleItem(self):
        """拖拉把手格（⠿）：灰色、置中、提示可拖拉整列。"""
        it = QTableWidgetItem("⠿")
        it.setTextAlignment(Qt.AlignCenter)
        it.setForeground(QColor("#8e8e93"))   # 次要灰，把手用色（非 disabled 淡灰）
        it.setToolTip("按住可拖拉整列以調整排序")
        return it

    def _selected_row(self, table):
        sel = table.selectedItems()
        return table.row(sel[0]) if sel else -1

    # ── 左側導航切換 ────────────────────────────────────────────
    def _switchPage(self, idx):
        # 切子頁前：若有未儲存排序，先詢問。取消則不切頁、保留排序（回原狀）
        if hasattr(self, "_sort_state") and self._sort_state:
            if not self._promptUnsaved(context="switch"):
                return
        self._inner_stack.setCurrentIndex(idx)
        for i, btn in enumerate(self._nav_btns):
            btn.setStyleSheet(_NAV_ACTIVE if i == idx else _NAV_INACTIVE)
        loaders = [self._loadPersonnel, self._loadDept,
                   self._loadCaseType, self._loadSystem, self._loadTrash,
                   self._loadBackup]
        loaders[idx]()

    def on_activated(self):
        """被切回設定 Tab 時重載當前子頁，確保畫面與 DB 一致
        （未存排序會被 DB 真實順序蓋掉 = 離開即放棄）。
        未登入（停在驗證頁）時不動作。"""
        if not hasattr(self, "_inner_stack"):
            return
        if not hasattr(self, "_outer_stack") or self._outer_stack.currentIndex() == 0:
            return  # 還在密碼驗證頁

        # 歸檔根目錄未設定時，每次登入後進入設定頁彈出一次警示
        self._maybeWarnArchiveRoot()

        idx = self._inner_stack.currentIndex()
        loaders = [self._loadPersonnel, self._loadDept,
                   self._loadCaseType, self._loadSystem, self._loadTrash,
                   self._loadBackup]
        if 0 <= idx < len(loaders):
            loaders[idx]()

    # ── 登入 ────────────────────────────────────────────────────
    def _doLogin(self):
        pwd = self.w_password.text()
        if not pwd:
            return
        ok = AuthManager.instance().login(pwd, self.db_path)
        if ok:
            self.lbl_login_err.setText("")
            self.w_password.clear()
            self._applyRolePermissions()
            self._outer_stack.setCurrentIndex(1)
            self._switchPage(self._PAGE_PERSONNEL)
            # 登入成功即檢查（登入不走 on_activated，否則重置後首次登入不會提示）
            self._maybeWarnArchiveRoot()
        else:
            # 登入失敗稽核（不記輸入內容）
            writeAuditSafe(self.db_path,
                           role=AuthManager.instance().current_role,
                           action="LOGIN_FAIL", operator=None,
                           detail=buildDetail("系統", "登入失敗", ""))
            self.lbl_login_err.setText("密碼錯誤，請再試一次")
            self.w_password.clear()
            self.w_password.setFocus()

    # ── 參照表維護權限：僅最高權限管理者（歸檔管理唯讀，含雙擊） ──
    def _refEditable(self):
        return AuthManager.instance().is_admin()

    # ── 依登入身分套用功能可用性 ────────────────────────────────
    def _applyRolePermissions(self):
        """歸檔管理：參照表維護（新增／修改／儲存排序＋拖拉）與跨年度重置停用；
        變更密碼／歸檔資料夾／登出／子頁查看仍可用。管理者全開。"""
        from PySide6.QtWidgets import QAbstractItemView
        is_admin = AuthManager.instance().is_admin()

        # 參照表動作鈕（新增／修改／儲存排序）
        for btn in (self.btn_add_personnel, self.btn_edit_personnel,
                    self.btn_add_dept, self.btn_edit_dept,
                    self.btn_add_casetype, self.btn_edit_casetype):
            if btn:
                btn.setEnabled(is_admin)
        # 儲存排序鈕：管理者由 dirty 狀態決定，歸檔管理一律停用
        for st in self._sort_state.values():
            if not is_admin:
                st["save_btn"].setEnabled(False)
            # 拖拉排序：歸檔管理關閉，管理者開啟
            st["table"].setDragDropMode(
                QAbstractItemView.InternalMove if is_admin
                else QAbstractItemView.NoDragDrop)

        # 跨年度重置（破壞性，僅管理者）
        if self._btn_year_reset:
            self._btn_year_reset.setEnabled(is_admin)

        # 資源回收筒：admin 可用；歸檔管理可見但停用（反灰，與其他維護功能一致）
        if self._nav_btns[self._PAGE_TRASH]:
            self._nav_btns[self._PAGE_TRASH].setVisible(True)
            self._nav_btns[self._PAGE_TRASH].setEnabled(is_admin)

        # 備份還原：破壞性，僅 admin；歸檔管理可見但停用（反灰）
        if self._nav_btns[self._PAGE_BACKUP]:
            self._nav_btns[self._PAGE_BACKUP].setVisible(True)
            self._nav_btns[self._PAGE_BACKUP].setEnabled(is_admin)

        # 系統設定子頁：兩身分都可進；簽收表標題／閒置逾時面板僅 admin
        # （setEnabled(False) 停用整塊含所有輸入路徑；面板 _save 另有權限 guard 保底）
        # 歸檔資料夾面板維持 admin/archive 皆可改（比照原 Dialog 開放範圍）
        if getattr(self, "_panel_print_title", None):
            self._panel_print_title.setEnabled(is_admin)
        if getattr(self, "_panel_idle", None):
            self._panel_idle.setEnabled(is_admin)
        if getattr(self, "_panel_input_lock", None):
            self._panel_input_lock.setEnabled(is_admin)
        if getattr(self, "_panel_backup", None):
            self._panel_backup.setEnabled(is_admin)
        if getattr(self, "_panel_input_mode", None):
            self._panel_input_mode.setEnabled(is_admin)

    # ── 身份切換監聽：登出時回到密碼驗證畫面 ─────────────────────
    def _onRoleChanged(self, role):
        if role in ('admin', 'archive'):
            self._applyRolePermissions()
            self._outer_stack.setCurrentIndex(1)
            self._switchPage(self._PAGE_PERSONNEL)
        else:
            self._outer_stack.setCurrentIndex(0)
            self.w_password.clear()
            self.lbl_login_err.setText("")
            self._arch_warn_shown = False  # 重置，下次登入仍會檢查
            # 登出＝放棄系統設定面板未存變更（殘留 dirty 會卡住下次登入的切頁提示）
            for p in self._dirtyPanels():
                p.reload()

    # ── 變更密碼 ────────────────────────────────────────────────
    def _changePassword(self):
        dlg = ChangePasswordDialog(self.db_path, self.tab_widget)
        if dlg.exec():
            # 密碼已變更，登出當前身分，要求以新密碼重新登入
            AuthManager.instance().logout()
            msgInfo("完成", "密碼已成功變更，請以新密碼重新登入。", self.tab_widget)

    # ── 歸檔資料夾設定 ──────────────────────────────────────────
    def _maybeWarnArchiveRoot(self):
        """歸檔根目錄未設定時，登入後彈出一次警示（每次登入最多一次）。"""
        if getattr(self, "_arch_warn_shown", False):
            return
        if getSetting(self.db_path, ARCHIVE_ROOT_KEY, "").strip():
            return
        self._arch_warn_shown = True
        if confirmBox(
            "歸檔資料夾未設定",
            "歸檔根目錄尚未設定。\n是否現在前往「系統設定」更新？",
            confirm_text="前往設定", cancel_text="稍後",
            default_confirm=True, parent=self.tab_widget
        ):
            self._switchPage(self._PAGE_SYSTEM)

    # ── 系統設定子頁（歸檔資料夾／簽收表標題／閒置逾時／唯讀設定四面板）──────
    def _loadSystem(self):
        """切入系統設定子頁時重讀各面板的 DB 值，確保畫面與 DB 一致。"""
        for p in (getattr(self, "_panel_archive_root", None),
                  getattr(self, "_panel_print_title", None),
                  getattr(self, "_panel_idle", None),
                  getattr(self, "_panel_input_lock", None),
                  getattr(self, "_panel_backup", None),
                  getattr(self, "_panel_input_mode", None)):
            if p:
                p.reload()

    # ── 備份還原子頁 ────────────────────────────────────────────
    def _loadBackup(self):
        """切入備份還原子頁時重新掃描候選備份清單。"""
        if getattr(self, "_panel_restore", None):
            self._panel_restore.reload()

    # ── 跨年度重置 ──────────────────────────────────────────────
    def _doReset(self):
        conn = None
        try:
            conn = getConn(self.db_path)
            doc_counts = _resetDocCounts(conn)
        except Exception as e:
            reportError("無法讀取重置資料", e, self.tab_widget)
            return
        finally:
            if conn:
                conn.close()

        # 1. 確認彈窗（輸入 RESET、列出待清停用項目、防誤按）
        dlg = ResetDialog(
            self.db_path, self.tab_widget,
            doc_summary=_resetSummary(doc_counts))
        if not dlg.exec():
            return

        # 1.5 先寫稽核紀錄（在備份之前，使歷史 log 隨備份保存；
        #     performYearEndReset 會清空當前庫的 Audit_Log）
        conn = None
        try:
            conn = getConn(self.db_path)
            m_off = sum(conn.execute(
                          f"SELECT COUNT(*) FROM {t} WHERE is_active=0").fetchone()[0]
                        for t in ("Ref_Personnel", "Ref_Departments", "Ref_CaseTypes"))
            writeAudit(conn, role=AuthManager.instance().current_role,
                       action="RESET", operator=AuthManager.instance().actor_name(),
                       detail=buildDetail("系統", "重置",
                                          f"清空主表（{_resetSummary(doc_counts)}）、"
                                          f"刪除停用項 {m_off} 筆、"
                                          f"重編參照表 id、歸零文號、清空歸檔路徑"))
            conn.commit()
        except Exception:
            pass
        finally:
            if conn:
                conn.close()

        # 2. 自動備份至 dbfile 同目錄
        try:
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            db_dir = os.path.dirname(os.path.abspath(self.db_path))
            auto_backup = os.path.join(db_dir, f"dbfile_backup_{ts}.db")
            shutil.copy2(self.db_path, auto_backup)
            # 修剪舊重置留底（保留最新 RESET_KEEP 份）
            from lib.db_backup import _prune_timestamped, _RESET_RE, RESET_PREFIX, RESET_KEEP
            _prune_timestamped(db_dir, _RESET_RE, RESET_PREFIX, RESET_KEEP)
        except Exception as e:
            msgCritical("備份失敗", f"自動備份失敗，已中止重置：\n{e}", self.tab_widget)
            return

        # 3. 詢問是否另存一份至使用者指定位置
        if confirmBox(
            "另存備份",
            "已於資料庫目錄建立自動備份。\n是否另存一份備份至其他位置？",
            confirm_text="另存", cancel_text="略過",
            confirm_danger=False, default_confirm=True,
            parent=self.tab_widget
        ):
            dest, _ = QFileDialog.getSaveFileName(
                self.tab_widget, "另存備份",
                f"dbfile_backup_{ts}.db", "SQLite 資料庫 (*.db)")
            if dest:
                try:
                    shutil.copy2(self.db_path, dest)
                except Exception as e:
                    msgWarning("另存失敗",
                               f"另存備份失敗（自動備份仍存在）：\n{e}", self.tab_widget)

        # 4. 執行重置（破壞性，transaction 保護）
        try:
            performYearEndReset(self.db_path)
        except Exception as e:
            msgCritical("重置失敗",
                        f"重置過程發生錯誤，資料已還原至重置前狀態：\n{e}",
                        self.tab_widget)
            return

        # 5. 完成提示 → 按確定後重啟程式
        #    （歸檔資料夾已清空，重啟後首次登入設定頁時 _maybeWarnArchiveRoot
        #      會提示並導向「系統設定」重新指定，此處不再另開設定流程）
        msgInfo("重置完成",
                "跨年度重置已完成，歸檔資料夾已清空，"
                "請於重新啟動後至設定頁「系統設定」重新指定。\n\n"
                "按下確定後，程式將自動關閉並重新啟動，重啟前畫面會短暫消失，"
                "屬正常現象。", self.tab_widget)
        self._restartApp()

    def _restartApp(self):
        """
        重啟程式。

        打包(onefile)情境的關鍵問題：
          PyInstaller 6.x bootloader 預設把經由 sys.executable 啟動的新程序
          視為「同一 app 的 worker 子程序」，會沿用繼承來的 _MEI 環境（指向
          舊程序正在清理的 _MEIxxxxx 暫存目錄）。新程序因而到舊的、已被刪除的
          目錄找 python3xx.dll / 標準庫，導致：
            - Failed to load Python DLL（_MEIxxxxx 下的 python3xx.dll）
            - ModuleNotFoundError: unicodedata
          （延遲啟動無法解決，反而讓舊 _MEI 清得更乾淨、DLL 更確定不存在。）
        解法（官方機制，PyInstaller 6.10+）：
          啟動新程序前設環境變數 PYINSTALLER_RESET_ENVIRONMENT=1，令新程序的
          bootloader 忽略繼承的 _MEI、解壓全新的暫存目錄，DLL 從新 _MEI 載入。
        開發情境（非 frozen）：
          沿用 QProcess 帶 sys.argv 重啟直譯器即可，無 _MEI 問題。
        """
        if getattr(sys, "frozen", False):
            try:
                env = os.environ.copy()
                env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
                subprocess.Popen([sys.executable], env=env)
            except Exception:
                msgWarning("請手動重啟",
                           "自動重啟失敗，請手動重新開啟程式。", self.tab_widget)
                # 即使啟動失敗仍關閉本程序，避免停留在已重置但未重載的狀態
        else:
            QProcess.startDetached(sys.executable, sys.argv)

        QApplication.quit()

    # ── 登出 ────────────────────────────────────────────────────
    def _doLogout(self):
        if not confirmBox(
            "登出",
            "確定要登出管理者身份？",
            confirm_text="登出", confirm_danger=False, default_confirm=True,
            parent=self.tab_widget
        ):
            return
        AuthManager.instance().logout()

    # ════════════════════════════════════════════════════════════
    # 人員管理
    # ════════════════════════════════════════════════════════════
    # ════════════════════════════════════════════════════════════
    # 排序 — 泛型核心（人員/部門/案類共用）
    # ════════════════════════════════════════════════════════════
    # 每頁的 DB 對應：table 名、id 欄、name 欄、啟用詞、停用詞
    _REF_CFG = {
        "personnel": ("Ref_Personnel",   "staff_id",     "staff_name",     "在職", "離職"),
        "dept":      ("Ref_Departments",  "dept_id",      "dept_name",      "啟用", "停用"),
        "casetype":  ("Ref_CaseTypes",    "case_type_id", "case_type_name", "啟用", "停用"),
    }

    # 新增／修改對話框：key → (RefItemDialog 設定常數, 警告用名詞)
    _REF_DIALOG = {
        "personnel": (REF_PERSONNEL, "人員"),
        "dept":      (REF_DEPT,      "部門"),
        "casetype":  (REF_CASETYPE,  "案件類型"),
    }

    # 排序表固定前兩欄：col0＝拖拉把手、col1＝序號（顯示排序位置）
    _HANDLE_COL = 0
    _SEQ_COL    = 1

    def _refCols(self, key):
        """回傳該頁的欄索引 (name, alias, status)；alias 為 None 表無別名欄。
        前兩欄固定為把手(0)／序號(1)，故名稱欄自 2 起算。
        人員頁：  把手0 / 序號1 / 姓名2       / 別名3 / 狀態4
        案類頁：  把手0 / 序號1 / 案件類型名稱2 / 別名3 / 狀態4
        部門頁：  把手0 / 序號1 / 部門名稱2     / 狀態3"""
        if key in ("personnel", "casetype"):
            return 2, 3, 4
        return 2, None, 3

    def _loadRefGeneric(self, key):
        """從 DB 依 sort_order 撈進記憶體，清掉暫存 dirty，重繪表格"""
        tbl_name, idc, namec, _, _ = self._REF_CFG[key]
        want_alias = key in ("personnel", "casetype")
        conn = None
        try:
            conn = self._getConn()
            if want_alias:
                # alias 欄可能尚未套補丁 → 偵測，缺欄則以 NULL 補位，整頁照常顯示（別名空白）
                has_alias = any(
                    c[1] == "alias"
                    for c in conn.execute(f"PRAGMA table_info({tbl_name})"))
                acol = "alias" if has_alias else "NULL"
                rows = conn.execute(
                    f"SELECT {idc}, {namec}, is_active, {acol} FROM {tbl_name} "
                    f"ORDER BY sort_order"
                ).fetchall()
            else:
                rows = conn.execute(
                    f"SELECT {idc}, {namec}, is_active FROM {tbl_name} "
                    f"ORDER BY sort_order"
                ).fetchall()
        except Exception as e:
            reportError("DB錯誤", e)
            return
        finally:
            if conn:
                conn.close()
        st = self._sort_state[key]
        st["rows"]  = [list(r) for r in rows]   # [id, name, is_active(, alias)]
        st["dirty"] = False
        st["save_btn"].setEnabled(False)
        self._renderSortTable(key)

    def _renderSortTable(self, key):
        """依記憶體 rows 重繪整張表（含停用灰字）"""
        _, _, _, word_on, word_off = self._REF_CFG[key]
        name_c, alias_c, status_c = self._refCols(key)
        st  = self._sort_state[key]
        tbl = st["table"]

        def _build():
            tbl.blockSignals(True)   # 重建表格時不要讓 itemChanged 誤判成使用者手動改序號
            try:
                tbl.setRowCount(0)
                for r, row in enumerate(st["rows"]):
                    rname, active = row[1], row[2]
                    tbl.insertRow(r)
                    color  = None if active else _COLOR_INACTIVE
                    status = word_on if active else word_off
                    # col0 拖拉把手；col1 顯示「序號」＝目前列位置（r+1），非內部 PK；rid 仍存記憶體供存檔
                    tbl.setItem(r, self._HANDLE_COL, self._handleItem())
                    seq_item = self._item(r + 1, color)
                    seq_item.setBackground(QColor("#F5F7FA"))
                    tbl.setItem(r, self._SEQ_COL, seq_item)
                    tbl.setItem(r, name_c,   self._item(rname,  color))
                    if alias_c is not None:
                        alias = (row[3] if len(row) > 3 and row[3] else "")
                        tbl.setItem(r, alias_c, self._item(alias, color))
                    tbl.setItem(r, status_c, self._item(status, color))
            finally:
                tbl.blockSignals(False)

        # 重繪前後保留捲動位置（新增／修改後不跳回頂端）
        preserveScroll(tbl, _build)

    def _saveSort(self, key):
        """把記憶體順序寫回 DB sort_order（連續整數），清 dirty，設 _ref_dirty。
        成功後鈕反灰即表示已存，不另跳「已儲存」提示。"""
        tbl_name, idc, _, _, _ = self._REF_CFG[key]
        st = self._sort_state[key]
        conn = None
        try:
            conn = self._getConn()
            for i, row in enumerate(st["rows"], start=1):
                conn.execute(
                    f"UPDATE {tbl_name} SET sort_order=? WHERE {idc}=?",
                    (i, row[0]))
            conn.commit()
        except Exception as e:
            reportError("儲存失敗", e)
            return
        finally:
            if conn:
                conn.close()
        st["dirty"] = False
        st["save_btn"].setEnabled(False)
        self._ref_dirty = True

    def _hasUnsavedSort(self):
        return any(s["dirty"] for s in self._sort_state.values())

    def _reloadPreservingOrder(self, key):
        """新增／修改後重載：取 DB 最新資料，但把進動作前的記憶體暫存順序
        重新套回去（新增的列＝不在舊順序中 → 排到最前），dirty 狀態原樣保留。

        如此拖拉排序撐得過新增／修改、不被重載洗掉（原 bug：新項以 MIN-1 插最前、
        重載丟棄未存順序，已拖好的前一新項被擠回上方）；且因沒寫 DB、沒清 dirty，
        沒按「儲存排序」前離開頁面仍可放棄（反悔路徑保留）。"""
        st = self._sort_state[key]
        old_order = [r[0] for r in st["rows"]]      # 動作前的暫存 id 順序
        was_dirty = st["dirty"]
        self._loadRefGeneric(key)                    # 取最新資料（含新列/改後值），會清 dirty
        pos = {rid: i for i, rid in enumerate(old_order)}
        st["rows"].sort(key=lambda r: pos.get(r[0], -1))   # 新 id 不在舊順序→-1 排最前
        st["dirty"] = was_dirty
        st["save_btn"].setEnabled(was_dirty)
        self._renderSortTable(key)

    def _dirtyPanels(self):
        """系統設定子頁各面板中有未存變更者（切頁/離開提示用）。"""
        return [p for p in (getattr(self, "_panel_archive_root", None),
                            getattr(self, "_panel_print_title", None),
                            getattr(self, "_panel_idle", None),
                            getattr(self, "_panel_input_lock", None),
                            getattr(self, "_panel_backup", None),
                            getattr(self, "_panel_input_mode", None))
                if p and p.isDirty()]

    def _promptUnsaved(self, context="edit"):
        """有未存排序或未存系統設定時詢問（兩者不會同時發生：
        排序 dirty 在切離該子頁時就被本函式擋下處理）。
        context='edit'  ：取消=保留變更、中止動作（回 False）
        context='switch'：同 edit，文字為切換頁面
        context='leave' ：一律回傳 True(按離開=放棄變更、按儲存=存檔)"""
        sort_dirty   = self._hasUnsavedSort()
        dirty_panels = self._dirtyPanels()
        if not sort_dirty and not dirty_panels:
            return True
        noun = "排序" if sort_dirty else "設定"
        if context == "leave":
            title, msg, confirm, cancel = f"{noun}未儲存", f"離開將遺失{noun}資料", "儲存", "離開"
        elif context == "switch":
            title, msg, confirm, cancel = f"{noun}未儲存", f"儲存目前{noun}後切換頁面？", "儲存", "取消"
        else:
            title, msg, confirm, cancel = f"{noun}未儲存", f"儲存目前{noun}後繼續編輯？", "儲存", "取消"
        ret = confirmBox(
            title, msg,
            confirm_text=confirm, cancel_text=cancel, parent=self.tab_widget)
        if ret:
            for k, s in self._sort_state.items():
                if s["dirty"]:
                    self._saveSort(k)
            # 面板存檔（成功即儲存鈕回灰，無成功彈窗）；
            # 任一存檔被擋（驗證失敗/必填空白）→ 中止切換、留在頁面修正
            for p in dirty_panels:
                if not p._save():
                    if context != "leave":
                        return False
            return True
        # 按了取消 / 離開
        if context == "leave":
            for s in self._sort_state.values():
                s["dirty"] = False
                s["save_btn"].setEnabled(False)
            for p in dirty_panels:
                p.reload()      # 放棄變更＝重讀 DB 值、重設 dirty 基準
            return True
        # edit / switch 取消：保留變更、回報中止
        return False

    # ════════════════════════════════════════════════════════════
    # 人員管理
    # ════════════════════════════════════════════════════════════
    def _loadPersonnel(self):
        self._loadRefGeneric("personnel")

    def _loadDept(self):
        self._loadRefGeneric("dept")

    def _loadCaseType(self):
        self._loadRefGeneric("casetype")

    # ════════════════════════════════════════════════════════════
    # 參照項新增／修改（人員／部門／案類三頁共用，差異查 _REF_DIALOG）
    # ════════════════════════════════════════════════════════════
    def _addRef(self, key):
        if not self._refEditable():
            return
        cfg, _noun = self._REF_DIALOG[key]
        dlg = RefItemDialog(cfg, self.db_path, parent=self.tab_widget)
        if dlg.exec():
            self._ref_dirty = True
            self._reloadPreservingOrder(key)        # 保留未存拖拉順序
            pos = dlg.get_target_position()
            if pos is not None:
                self._moveRow(key, 0, pos)          # 新增後預設在最前，搬到指定位置

    def _editRef(self, key, row=None):
        if not self._refEditable():
            return
        if row is None:
            row = self._selected_row(self._sort_state[key]["table"])
        cfg, noun = self._REF_DIALOG[key]
        if row < 0:
            msgWarning("請選擇項目", f"請先點選要修改的{noun}", self.tab_widget)
            return
        srow = self._sort_state[key]["rows"][row]   # [id(真 PK), name, is_active(, alias)]
        dlg = RefItemDialog(cfg, self.db_path,
                            existing=(srow[0], row + 1, srow[1], bool(srow[2])),
                            parent=self.tab_widget)
        if dlg.exec() and dlg.get_result():
            self._ref_dirty = True
            self._reloadPreservingOrder(key)        # 保留未存拖拉順序
            pos = dlg.get_target_position()
            if pos is not None and pos != row:
                self._moveRow(key, row, pos)

    # ── 資源回收筒（誤刪還原，僅 admin）：面板見 ui_utils/trash_panel.py ──
    def _loadTrash(self):
        """子頁被顯示時（_switchPage／on_activated 依 index 呼叫）重載回收筒。"""
        panel = getattr(self, "_trash_panel", None)
        if panel:
            panel.load()

    def _flagSiblingReload(self, key):
        """標記其他 Tab 下次顯示時重載；敘獎頁另重算名條／預覽。"""
        if not key:
            return
        try:
            mgr = getattr(self, "_manager", None)
            for t in getattr(mgr, "tabs", {}).values():
                if t is self:
                    continue
                # 回收筒還原的敘獎不屬於本次登錄 session；只標 dirty，
                # 讓 TabReward 進頁時回查既有 session 並重算名條。
                if key == "reward" and hasattr(t, "reward_data_dirty"):
                    t.reward_data_dirty = True
                if hasattr(t, "_forceReload"):
                    pend = getattr(t, "_pending_reload_keys", None) or set()
                    pend.add(key)
                    t._pending_reload_keys = pend
        except Exception:
            pass
