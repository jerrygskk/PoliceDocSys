from PySide6.QtCore import Qt, QDate, QTimer
from PySide6.QtWidgets import (
    QTableWidgetItem, QRadioButton, QVBoxLayout, QHBoxLayout,
    QGridLayout, QTabBar, QSizePolicy, QWidget,
    QDateEdit, QComboBox, QLineEdit, QLabel,
    QTableWidget, QPushButton
)

from lib.base_tab import BaseTab, InputLockMixin
from lib.db_utils import (getResourcePath, nextDocId, DEBUG_MODE,
                          softDeleteDoc, isInputLocked, isSelfServiceMode)
from ui_utils import loadUi, msgWarning, msgCritical, confirmBox, reportError
from lib.auth_manager import AuthManager
from ui_utils import (
    setupPreviewTable, autoResizeTable, makeDeleteBtn, setDocIdLinkCell,
    setupFilterCombo, setupDateEditToToday, setupNullableDateEdit, refreshFilterCombo,
    NullableDateEdit, CriminalEditDialog, GeneralEditDialog, attachStickyScroll,
    attachComboHint,
)

CRIM_HEADERS = ["", "編號", "狀態", "案類", "陳報主旨", "承辦人", "受理人", "日期", "報案人"]
GEN_HEADERS  = ["", "編號", "業務單位", "陳報主旨", "承辦人", "分類"]

# Radio 圓點縮小，選中用較細 border 呈現
RADIO_STYLE = """
QRadioButton {
    spacing: 6px;
    color: #1c1c1e;
    font-size: 14pt;
}
QRadioButton::indicator {
    width: 14px;
    height: 14px;
    border: 2px solid #c6c6c8;
    border-radius: 7px;
    background-color: #ffffff;
}
QRadioButton::indicator:checked {
    background-color: #8fa8c8;
    border: 4px solid #ffffff;
    outline: 2px solid #8fa8c8;
}
QRadioButton:checked {
    color: #8fa8c8;
}
"""


class TabReport(BaseTab, InputLockMixin):
    """公文陳報：刑案 / 一般陳報，左右並列預覽"""

    def setup(self, tab_index):
        tab = self.tab_widget.widget(tab_index)
        if not tab:
            return

        rpt_widget = loadUi(getResourcePath("layouts/Layout3.ui"))
        if not rpt_widget:
            return

        inner = rpt_widget.centralWidget()
        lay = QVBoxLayout(tab)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(inner)
        self._inner = inner

        # ── 頂部共用欄位 ──────────────────────────────────
        self.rpt_date   = inner.findChild(QDateEdit, 'rpt_date')
        self.rpt_sender = inner.findChild(QComboBox, 'rpt_sender')

        # ── mainGrid 參照（供 _switchFormType 調整列高） ────
        self._mainGrid = inner.findChild(QGridLayout, 'mainGrid')

        # ── 獨立 QTabBar：插到 layout 最頂端 ──────────────
        _TAB_SS = """
            QTabBar {
                border: none;
                background: transparent;
            }
            QTabBar::tab {
                background-color: transparent;
                color: #636366;
                border: none;
                border-bottom: 2px solid transparent;
                padding: 8px 18px;
                margin-right: 4px;
                font-weight: 500;
            }
            QTabBar::tab:selected {
                color: #8fa8c8;
                border-bottom: 2px solid #8fa8c8;
                font-weight: 600;
            }
            QTabBar::tab:hover:!selected {
                color: #3a3a3c;
            }
        """
        self.type_tabbar = QTabBar()
        self.type_tabbar.addTab("❐ 刑案陳報")
        self.type_tabbar.addTab("❏ 一般陳報")
        self.type_tabbar.setExpanding(False)
        self.type_tabbar.setDocumentMode(True)
        self.type_tabbar.setDrawBase(False)   # 關掉貫穿基準線（滿版橫線/框），只留選中頁籤底線
        self.type_tabbar.setStyleSheet(_TAB_SS)
        # 清除/確認鈕與子頁籤同列（右端），釋出 mainGrid 右側寬度；
        # objectName 沿用原 .ui 名稱：theme.py 套色、下方 findChild 綁定都靠它
        btn_clear = QPushButton("清除表單")
        btn_clear.setObjectName("btn_rpt_clear")
        btn_submit = QPushButton("確認陳報")
        btn_submit.setObjectName("btn_rpt_submit")
        for b in (btn_clear, btn_submit):
            b.setFixedWidth(110)
        topbar = QHBoxLayout()
        topbar.setContentsMargins(0, 0, 0, 0)
        topbar.setSpacing(8)
        topbar.addWidget(self.type_tabbar)
        topbar.addStretch()
        topbar.addWidget(btn_clear)
        topbar.addWidget(btn_submit)
        inner.layout().insertLayout(0, topbar)
        self.type_tabbar.currentChanged.connect(self._switchFormType)

        # ── 刑案欄位（rows 1-3） ──────────────────────────
        self.radio_status_a = inner.findChild(QRadioButton, 'radio_status_a')  # CS01 現行犯
        self.radio_status_b = inner.findChild(QRadioButton, 'radio_status_b')  # CS02 到案
        self.radio_status_c = inner.findChild(QRadioButton, 'radio_status_c')  # CS03 未到案
        for rb in [self.radio_status_a, self.radio_status_b, self.radio_status_c]:
            if rb:
                rb.setStyleSheet(RADIO_STYLE)
        self.crim_status_group = inner.findChild(QWidget, 'crim_status_group')
        self.crim_casetype  = inner.findChild(QComboBox, 'crim_casetype')
        self.crim_processor = inner.findChild(QComboBox, 'crim_processor')
        self.crim_receiver  = inner.findChild(QComboBox, 'crim_receiver')
        self.crim_subject   = inner.findChild(QLineEdit, 'crim_subject')
        self.crim_occdate   = inner.findChild(NullableDateEdit, 'crim_occdate')
        self.crim_reporter  = inner.findChild(QLineEdit, 'crim_reporter')

        # ── 一般欄位（rows 4-5） ──────────────────────────
        self.radio_gen_cat_a = inner.findChild(QRadioButton, 'radio_gen_cat_a')  # GC01 業務陳報
        self.radio_gen_cat_b = inner.findChild(QRadioButton, 'radio_gen_cat_b')  # GC03 其他
        self.radio_gen_cat_c = inner.findChild(QRadioButton, 'radio_gen_cat_c')  # GC02 司法相驗
        for rb in [self.radio_gen_cat_a, self.radio_gen_cat_b, self.radio_gen_cat_c]:
            if rb:
                rb.setStyleSheet(RADIO_STYLE)
        self.gen_cat_group  = inner.findChild(QWidget, 'gen_cat_group')
        self.gen_dept       = inner.findChild(QComboBox, 'gen_dept')
        self.gen_processor  = inner.findChild(QComboBox, 'gen_processor')
        self.gen_subject    = inner.findChild(QLineEdit, 'gen_subject')

        # ── 統一輸入/下拉欄位高度（含發文/確認鈕） ────────
        FIELD_H = 38
        for w in [self.rpt_date, self.rpt_sender,
                  self.crim_status_group, self.crim_casetype, self.crim_occdate,
                  self.crim_subject, self.crim_receiver, self.crim_processor,
                  self.crim_reporter,
                  self.gen_cat_group, self.gen_dept, self.gen_processor,
                  self.gen_subject]:
            if w:
                w.setFixedHeight(FIELD_H)

        # ── 固定結構性欄寬，切換刑案/一般時欄位位置與寬度一致 ──
        # col0 以最寬標籤「查獲/受理」為基準（一般模式此標籤隱藏，否則 col0 會縮）
        # col4/col5 為受理人員(242)/同承辦鈕(60)寬，一般模式無此錨點，需強制
        # （col4=242 使陳報主旨=col4+8+col5=310，即原 248 的 ×1.25；col1 同步 240→300 在 Layout3.ui）
        if self._mainGrid:
            occ_lbl = inner.findChild(QLabel, 'lbl_crim_occdate')
            if occ_lbl:
                self._mainGrid.setColumnMinimumWidth(0, occ_lbl.sizeHint().width())
            self._mainGrid.setColumnMinimumWidth(4, 242)
            self._mainGrid.setColumnMinimumWidth(5, 60)

        # ── show/hide widget 列表（供 _switchFormType） ───
        self._crim_row_widgets = [
            inner.findChild(QLabel, 'lbl_crim_status'), self.crim_status_group,
            inner.findChild(QLabel, 'lbl_crim_subject'), self.crim_subject,
            inner.findChild(QLabel, 'lbl_crim_casetype'), self.crim_casetype,
            inner.findChild(QLabel, 'lbl_crim_receiver'), self.crim_receiver,
            inner.findChild(QPushButton, 'btn_copy_to_receiver'),
            inner.findChild(QLabel, 'lbl_crim_occdate'), self.crim_occdate,
            inner.findChild(QLabel, 'lbl_crim_processor'), self.crim_processor,
            inner.findChild(QPushButton, 'btn_copy_to_processor'),
            inner.findChild(QLabel, 'lbl_crim_reporter'), self.crim_reporter,
        ]
        self._gen_row_widgets = [
            inner.findChild(QLabel, 'lbl_gen_cat'), self.gen_cat_group,
            inner.findChild(QLabel, 'lbl_gen_dept'), self.gen_dept,
            inner.findChild(QLabel, 'lbl_gen_processor'), self.gen_processor,
            inner.findChild(QLabel, 'lbl_gen_subject'), self.gen_subject,
        ]

        # ── 預覽表格 ──────────────────────────────────────
        self.crim_table = inner.findChild(QTableWidget, 'crim_tableWidget')
        self.gen_table  = inner.findChild(QTableWidget, 'gen_tableWidget')

        if self.crim_table:
            self.crim_table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        if self.gen_table:
            self.gen_table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        # 依名稱定位（頂端另有 topbar QHBoxLayout，不能拿「第一個 HBox」當預覽列）
        preview_layout = None
        for i in range(inner.layout().count()):
            item = inner.layout().itemAt(i)
            if (item and isinstance(item.layout(), QHBoxLayout)
                    and item.layout().objectName() == "previewLayout"):
                preview_layout = item.layout()
                break
        if preview_layout and preview_layout.count() >= 2:
            preview_layout.setStretch(0, 8)
            preview_layout.setStretch(1, 5)

        # ── 預覽標題樣式 ──────────────────────────────────
        for lbl_name, color in [('lbl_criminal_title', '#5b8db8'), ('lbl_general_title', '#c0a080')]:
            lbl = inner.findChild(QLabel, lbl_name)
            if lbl:
                lbl.setStyleSheet(
                    f"background-color: {color}; color: white; font-weight: 600;"
                    f"padding: 6px; border-radius: 4px;"
                )

        # ── 日期初始化 ────────────────────────────────────
        if self.rpt_date:
            self.rpt_date.setDate(QDate.currentDate())
            setupDateEditToToday(self.rpt_date)
        if self.crim_occdate:
            setupNullableDateEdit(self.crim_occdate, "下拉選擇日期")

        # ── 載入參照表 ────────────────────────────────────
        self._personnel, self._depts = self._loadRef()
        self._case_types, self._casetype_alias_map = self._loadCaseTypes()

        # ── 填入下拉選單 ──────────────────────────────────
        setupFilterCombo(self.rpt_sender,     self._personnel)
        setupFilterCombo(self.crim_casetype,  self._case_types,
                         alias_map=self._casetype_alias_map)
        attachComboHint(self.crim_casetype, "輸入或下拉選擇")
        self.crim_casetype.currentIndexChanged.connect(
            lambda idx: self.crim_casetype.setStyleSheet(
                "QComboBox { color: #a0a0a0; }" if idx == 0
                else "QComboBox { color: #1c1c1e; }"
            )
        )
        self.crim_casetype.setStyleSheet("QComboBox { color: #a0a0a0; }")
        setupFilterCombo(self.crim_processor, self._personnel)
        setupFilterCombo(self.crim_receiver,  self._personnel)
        setupFilterCombo(self.gen_dept,       self._depts)
        setupFilterCombo(self.gen_processor,  self._personnel)

        # ── 預覽表格初始化 ────────────────────────────────
        if self.crim_table:
            setupPreviewTable(self.crim_table, CRIM_HEADERS, cap_mode=True,
                              stretch_col=8, fixed_overrides={"陳報主旨": 184})
            attachStickyScroll(self.crim_table)
        if self.gen_table:
            setupPreviewTable(self.gen_table, GEN_HEADERS, cap_mode=True,
                              stretch_col=5, fixed_overrides={"陳報主旨": 184})
            attachStickyScroll(self.gen_table)

        # ── 信號綁定 ──────────────────────────────────────
        btn_clear  = inner.findChild(QPushButton, 'btn_rpt_clear')
        btn_submit = inner.findChild(QPushButton, 'btn_rpt_submit')
        if btn_clear:  btn_clear.setFixedHeight(38); btn_clear.clicked.connect(self._formClear)
        if btn_submit: btn_submit.setFixedHeight(38); btn_submit.clicked.connect(self._submit)
        if self.crim_subject: self.crim_subject.setFocus()

        # ── 互填按鈕 ──────────────────────────────────────

        btn_copy_to_receiver  = inner.findChild(QPushButton, 'btn_copy_to_receiver')
        btn_copy_to_processor = inner.findChild(QPushButton, 'btn_copy_to_processor')
        for btn in [btn_copy_to_receiver, btn_copy_to_processor]:
            if btn:
                btn.setStyleSheet("font-size: 11pt; padding: 2px 4px;")
        if btn_copy_to_receiver:
            btn_copy_to_receiver.clicked.connect(self._copyProcessorToReceiver)
        if btn_copy_to_processor:
            btn_copy_to_processor.clicked.connect(self._copyReceiverToProcessor)

        # ── 唯讀橫幅＋表單鎖定（共用 InputLockMixin）────────
        lay.insertWidget(0, self._makeReadonlyBanner())
        shared = [self.rpt_date, self.rpt_sender]
        self._setupInputLock(
            tab_index,
            lock_kind=self._currentLockKind,   # 依當前刑案/一般模式動態決定
            lock_widgets={
                "crim": [w for w in (shared + [
                    self.crim_casetype, self.crim_processor, self.crim_receiver,
                    self.crim_subject, self.crim_occdate, self.crim_reporter,
                    self.radio_status_a, self.radio_status_b, self.radio_status_c,
                    btn_copy_to_receiver, btn_copy_to_processor,
                    btn_submit, btn_clear]) if w],
                "gen":  [w for w in (shared + [
                    self.gen_dept, self.gen_processor, self.gen_subject,
                    self.radio_gen_cat_a, self.radio_gen_cat_b, self.radio_gen_cat_c,
                    btn_submit, btn_clear]) if w],
            },
            clear_tables=[self.crim_table, self.gen_table],
        )

        # ── 初始狀態：顯示刑案、隱藏一般 ─────────────────
        self._switchFormType(0)

    # ── 陳報類型切換 ──────────────────────────────────────
    def _switchFormType(self, idx):
        is_crim = (idx == 0)
        for w in self._crim_row_widgets:
            if w:
                w.setVisible(is_crim)
        for w in self._gen_row_widgets:
            if w:
                w.setVisible(not is_crim)
        # verticalSpacing=0，列距全由 row min height 控制；兩模式總高固定 180，
        # 下方 Expanding 預覽表在刑案/一般高度一致。
        # row0（陳報日期/發文人員共用列）兩模式固定 48，避免切換跳動；
        # 清除/確認鈕在 topbar（子頁籤列），不受本 grid 列高影響。
        if self._mainGrid:
            heights = ({0: 48, 1: 44, 2: 44, 3: 44, 4: 0, 5: 0} if is_crim
                       else {0: 48, 1: 0, 2: 0, 3: 0, 4: 66, 5: 66})
            for row, h in heights.items():
                self._mainGrid.setRowMinimumHeight(row, h)
        self._applyInputLock()

    def _currentLockKind(self):
        """陳報頁依當前刑案/一般模式決定鎖種類（供 InputLockMixin 動態取用）。
        模式切換列（type_tabbar）本身不反灰，讓使用者可切到未鎖模式。"""
        idx = self.type_tabbar.currentIndex() if self.type_tabbar else 0
        return "crim" if idx == 0 else "gen"

    def _applyInputLock(self):
        """覆寫：先套唯讀設定鎖，再疊加自助取號模式的欄位反灰。"""
        super()._applyInputLock()
        self._applySelfServiceMode()

    def _applySelfServiceMode(self):
        """自助取號模式：陳報日期／發文人員兩欄反灰（由結算時自動填入）。
        唯讀鎖已停用整個表單時這兩欄已是停用狀態，不衝突。"""
        is_self = isSelfServiceMode(self.db_path)
        tip = "自助取號模式：發文日期與送文者由結算時自動填入" if is_self else ""
        for w in [self.rpt_date, self.rpt_sender]:
            if w:
                if is_self:
                    w.setEnabled(False)
                w.setToolTip(tip)
        # 陳報日期顯示空白：僅在反灰（不可互動）狀態下用 specialValueText 哨兵，
        # 無鍵盤/滑鼠路徑，不會踩 QDateEdit 可編輯空白欄的雷（踩雷表 #3）。
        # 送出值與此無關（自助模式 _submit 一律帶 report_date=None）。
        if self.rpt_date:
            if is_self:
                self.rpt_date.setSpecialValueText(" ")
                self.rpt_date.setDate(self.rpt_date.minimumDate())
            elif self.rpt_date.specialValueText():
                # 從自助切回送文者模式：清哨兵、還原今天（僅切換當下做一次，
                # 平時重複呼叫不動使用者已選的日期）
                self.rpt_date.setSpecialValueText("")
                self.rpt_date.setDate(QDate.currentDate())

    # ── BaseTab 介面 ──────────────────────────────────────
    def get_tables(self):
        return [t for t in [self.crim_table, self.gen_table] if t]

    def get_focus_widget(self):
        return self.crim_subject

    def on_activated(self):
        self._personnel, self._depts = self._loadRef()
        self._case_types, self._casetype_alias_map = self._loadCaseTypes()
        refreshFilterCombo(self.rpt_sender,     self._personnel)
        refreshFilterCombo(self.crim_casetype,  self._case_types,
                           alias_map=self._casetype_alias_map)
        attachComboHint(self.crim_casetype, "輸入或下拉選擇")
        refreshFilterCombo(self.crim_processor, self._personnel)
        refreshFilterCombo(self.crim_receiver,  self._personnel)
        refreshFilterCombo(self.gen_dept,       self._depts)
        refreshFilterCombo(self.gen_processor,  self._personnel)
        self._refreshCrimPreviewNames()
        self._refreshGenPreviewNames()
        self._applyInputLock()

    def _refreshCrimPreviewNames(self):
        """掃刑案預覽表，更新案類/承辦人/受理人欄。"""
        if not self.crim_table:
            return
        conn = None
        try:
            conn = self._getConn()
            for r in range(self.crim_table.rowCount()):
                doc_item = self.crim_table.item(r, 1)
                if not doc_item:
                    continue
                doc_id = doc_item.text()
                row = conn.execute("""
                    SELECT ct.case_type_name,
                           pp.staff_name,
                           pr.staff_name
                    FROM Document_Criminal c
                    LEFT JOIN Ref_CaseTypes ct ON c.case_type    = ct.case_type_id
                    LEFT JOIN Ref_Personnel pp ON c.processor_id = pp.staff_id
                    LEFT JOIN Ref_Personnel pr ON c.receiver_id  = pr.staff_id
                    WHERE c.doc_id = ?
                """, (doc_id,)).fetchone()
                if not row:
                    continue
                ct_name, proc_name, recv_name = row
                if ct_name is not None:
                    self.crim_table.item(r, 3).setText(ct_name)
                if proc_name is not None:
                    self.crim_table.item(r, 5).setText(self._trimName(proc_name))
                if recv_name is not None:
                    self.crim_table.item(r, 6).setText(self._trimName(recv_name))
        except Exception as e:
            msgCritical("DB錯誤", f"刷新刑案預覽列失敗: {e}")
        finally:
            if conn:
                conn.close()

    def _refreshGenPreviewNames(self):
        """掃一般陳報預覽表，更新業務單位/承辦人欄。"""
        if not self.gen_table:
            return
        conn = None
        try:
            conn = self._getConn()
            for r in range(self.gen_table.rowCount()):
                doc_item = self.gen_table.item(r, 1)
                if not doc_item:
                    continue
                doc_id = doc_item.text()
                row = conn.execute("""
                    SELECT d.dept_name, p.staff_name
                    FROM Document_General g
                    LEFT JOIN Ref_Departments d ON g.dept_id      = d.dept_id
                    LEFT JOIN Ref_Personnel   p ON g.processor_id = p.staff_id
                    WHERE g.doc_id = ?
                """, (doc_id,)).fetchone()
                if not row:
                    continue
                dept_name, proc_name = row
                if dept_name is not None:
                    self.gen_table.item(r, 2).setText(dept_name)
                if proc_name is not None:
                    self.gen_table.item(r, 4).setText(self._trimName(proc_name))
        except Exception as e:
            msgCritical("DB錯誤", f"刷新一般陳報預覽列失敗: {e}")
        finally:
            if conn:
                conn.close()

    # ── 輔助：從 DB 載入二元組列表 ──────────────────────────
    def _loadTable(self, sql):
        conn = None
        try:
            conn = self._getConn()
            rows = conn.execute(sql).fetchall()
            return [(r[0], r[1]) for r in rows]
        except Exception as e:
            msgCritical("DB錯誤", f"載入對照表失敗: {e}")
            return []
        finally:
            if conn:
                conn.close()

    def _loadCaseTypes(self):
        """載入案類清單及別名對照表，回傳 (data_list, alias_map)。
        alias_map: {案類名: [別名, ...]}（允許跨案類重複）。"""
        conn = None
        try:
            conn = self._getConn()
            rows = conn.execute(
                "SELECT case_type_id, case_type_name, alias "
                "FROM Ref_CaseTypes WHERE is_active=1 ORDER BY sort_order"
            ).fetchall()
            data_list = [(r[0], r[1]) for r in rows]
            alias_map = {}
            for _, name, alias_str in rows:
                if not alias_str:
                    continue
                aliases = [a.strip() for a in alias_str.split(",") if a.strip()]
                if aliases:
                    alias_map[name] = aliases
            return data_list, alias_map
        except Exception as e:
            msgCritical("DB錯誤", f"載入案類清單失敗: {e}")
            return [], {}
        finally:
            if conn:
                conn.close()

    # ── 互填：同承辦 / 同受理 ────────────────────────────────
    def _copyProcessorToReceiver(self):
        if not self.crim_processor or not self.crim_receiver:
            return
        data = self.crim_processor.currentData()
        text = self.crim_processor.currentText()
        if data:
            for i in range(self.crim_receiver.count()):
                if self.crim_receiver.itemData(i) == data:
                    self.crim_receiver.setCurrentIndex(i)
                    return
            self.crim_receiver.setEditText(text)

    def _copyReceiverToProcessor(self):
        if not self.crim_receiver or not self.crim_processor:
            return
        data = self.crim_receiver.currentData()
        text = self.crim_receiver.currentText()
        if data:
            for i in range(self.crim_processor.count()):
                if self.crim_processor.itemData(i) == data:
                    self.crim_processor.setCurrentIndex(i)
                    return
            self.crim_processor.setEditText(text)

    # ── 清除表單（保留送文日期、發文人員）──────────────────
    def _formClear(self):
        if self.radio_status_a:
            self.radio_status_a.setChecked(True)
        setupFilterCombo(self.crim_casetype,  self._case_types,
                         alias_map=self._casetype_alias_map)
        attachComboHint(self.crim_casetype, "輸入或下拉選擇")
        setupFilterCombo(self.crim_processor, self._personnel)
        setupFilterCombo(self.crim_receiver,  self._personnel)
        if self.crim_subject:  self.crim_subject.clear()
        if self.crim_occdate:  self.crim_occdate.clear()
        if self.crim_reporter: self.crim_reporter.clear()
        if self.radio_gen_cat_a: self.radio_gen_cat_a.setChecked(True)
        setupFilterCombo(self.gen_dept,      self._depts)
        setupFilterCombo(self.gen_processor, self._personnel)
        if self.gen_subject: self.gen_subject.clear()

    # ── 確認陳報 ────────────────────────────────────────────
    def _submit(self):
        if isSelfServiceMode(self.db_path):
            report_date = None
            sender_id   = None
        else:
            report_date = self.rpt_date.date().toString("yyyy-MM-dd") if self.rpt_date else ""
            sender_id   = self.rpt_sender.currentData() if self.rpt_sender else None
        is_criminal = (self.type_tabbar.currentIndex() == 0) if self.type_tabbar else True

        if is_criminal:
            self._submitCriminal(report_date, sender_id)
        else:
            self._submitGeneral(report_date, sender_id)

    def _submitCriminal(self, report_date, sender_id):
        if not AuthManager.instance().is_manager() and isInputLocked(self.db_path, "crim"):
            msgWarning("唯讀模式", "本功能目前為唯讀模式無法使用。")
            return
        # status_name 為預覽顯示用，與 Ref_Case_Status.status_name 一致（皆兩字）
        if self.radio_status_a and self.radio_status_a.isChecked():
            status_id, status_name = 'CS01', '現行'
        elif self.radio_status_b and self.radio_status_b.isChecked():
            status_id, status_name = 'CS02', '到案'
        else:
            status_id, status_name = 'CS03', '未到'
        casetype_id  = self.crim_casetype.currentData()
        processor_id = self.crim_processor.currentData()
        receiver_id  = self.crim_receiver.currentData()
        subject      = self.crim_subject.text().strip()  if self.crim_subject   else ""
        if self.crim_occdate:
            self.crim_occdate.validateNow()   # 送出前再驗一次（非法即亮紅框）
        occ_blank    = self.crim_occdate and self.crim_occdate.isBlank()
        occ_err      = self.crim_occdate and self.crim_occdate.hasError()
        occ_d        = self.crim_occdate.getDate() if self.crim_occdate else None
        occ_date     = occ_d.toString("yyyy-MM-dd") if occ_d else None
        reporter     = self.crim_reporter.text().strip() if self.crim_reporter  else ""

        errors = []
        if not isSelfServiceMode(self.db_path) and not sender_id:
            errors.append("發文人員")
        if not casetype_id:  errors.append("案類")
        if not processor_id: errors.append("承辦人員")
        if not subject:      errors.append("陳報主旨")
        if occ_blank:        errors.append("查獲日期")
        elif occ_err:        errors.append("查獲日期格式（請用 yyyy-MM-dd）")
        if errors:
            msgWarning("欄位未填", f"請填寫以下必填欄位：\n{'、'.join(errors)}")
            return

        conn = None
        try:
            conn       = self._getConn()
            new_doc_id = nextDocId(conn, 'Document_Criminal')
            conn.execute("""
                INSERT INTO Document_Criminal
                    (doc_id, report_date, sender_id, case_type, case_status,
                     processor_id, subject_summary, occurrence_date,
                     reporter_name, receiver_id, is_reported, is_electronic)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, '')
            """, (new_doc_id, report_date, sender_id, casetype_id, status_id,
                  processor_id, subject, occ_date or None,
                  reporter or None, receiver_id))
            conn.commit()

            self._insertCrimRow(
                new_doc_id, status_name,
                self.crim_casetype.currentText(),
                subject,
                self.crim_processor.currentText(),
                self.crim_receiver.currentText(),
                reporter,
                occ_date,
            )
            if not DEBUG_MODE:
                self._formClear()

        except Exception as e:
            reportError("寫入失敗", e)
        finally:
            if conn:
                conn.close()

    def _submitGeneral(self, report_date, sender_id):
        if not AuthManager.instance().is_manager() and isInputLocked(self.db_path, "gen"):
            msgWarning("唯讀模式", "本功能目前為唯讀模式無法使用。")
            return
        # cat_name 為預覽顯示用，與 Ref_General_Category.gen_cat_name 一致（皆兩字）
        if self.radio_gen_cat_a and self.radio_gen_cat_a.isChecked():
            cat_id, cat_name = 'GC01', '業務'
        elif self.radio_gen_cat_b and self.radio_gen_cat_b.isChecked():
            cat_id, cat_name = 'GC03', '其他'
        else:
            cat_id, cat_name = 'GC02', '相驗'
        dept_id      = self.gen_dept.currentData()
        processor_id = self.gen_processor.currentData()
        subject      = self.gen_subject.text().strip() if self.gen_subject else ""

        errors = []
        if not isSelfServiceMode(self.db_path) and not sender_id:
            errors.append("發文人員")
        if not processor_id: errors.append("承辦人")
        if not subject:      errors.append("陳報主旨")
        if errors:
            msgWarning("欄位未填", f"請填寫以下必填欄位：\n{'、'.join(errors)}")
            return

        conn = None
        try:
            conn       = self._getConn()
            new_doc_id = nextDocId(conn, 'Document_General')
            conn.execute("""
                INSERT INTO Document_General
                    (doc_id, report_date, sender_id, dept_id, gen_cat_id,
                     subject, processor_id, is_reported, is_electronic)
                VALUES (?, ?, ?, ?, ?, ?, ?, 0, '')
            """, (new_doc_id, report_date, sender_id, dept_id, cat_id,
                  subject, processor_id))
            conn.commit()

            self._insertGenRow(
                new_doc_id,
                self.gen_dept.currentText(),
                subject,
                self.gen_processor.currentText(),
                cat_name,
            )
            if not DEBUG_MODE:
                self._formClear()

        except Exception as e:
            reportError("寫入失敗", e)
        finally:
            if conn:
                conn.close()

    # ── 插入預覽列 ───────────────────────────────────────────
    def _insertCrimRow(self, doc_id, status, casetype, subject,
                       processor, receiver, reporter, occ_date):
        if not self.crim_table:
            return
        pos = self.crim_table.rowCount()
        self.crim_table.insertRow(pos)

        # 刪除按鈕（col 0）：以 doc_id 為準
        container, _ = makeDeleteBtn(lambda _, d=doc_id: self._deleteCrimByDocId(d))
        self.crim_table.setCellWidget(pos, 0, container)

        # 編號欄（col 1）：超連結
        setDocIdLinkCell(self.crim_table, pos, 1, doc_id, self._onEditCrimRow, clickable=True)

        for col, val in enumerate([
            status, casetype, subject,
            self._trimName(processor), self._trimName(receiver),
            self._fmtDate(occ_date), self._trimName(reporter),
        ], start=2):
            item = QTableWidgetItem(str(val) if val else "")
            item.setTextAlignment(Qt.AlignCenter)
            self.crim_table.setItem(pos, col, item)
        autoResizeTable(self.crim_table)

    def _insertGenRow(self, doc_id, dept, subject, processor, cat):
        if not self.gen_table:
            return
        pos = self.gen_table.rowCount()
        self.gen_table.insertRow(pos)

        # 刪除按鈕（col 0）：以 doc_id 為準
        container, _ = makeDeleteBtn(lambda _, d=doc_id: self._deleteGenByDocId(d))
        self.gen_table.setCellWidget(pos, 0, container)

        # 編號欄（col 1）：超連結
        setDocIdLinkCell(self.gen_table, pos, 1, doc_id, self._onEditGenRow, clickable=True)

        for col, val in enumerate([dept, subject, self._trimName(processor), cat], start=2):
            item = QTableWidgetItem(str(val) if val else "")
            item.setTextAlignment(Qt.AlignCenter)
            self.gen_table.setItem(pos, col, item)
        autoResizeTable(self.gen_table)

    # ── 修改回呼 ────────────────────────────────────────────
    def _onEditCrimRow(self, row, doc_id):
        dlg = CriminalEditDialog(self.db_path, doc_id, self.crim_table, disable_convert=True)
        if dlg.exec():
            if getattr(dlg, "converted", False):
                self._afterConvertReport("crim", doc_id)
                return
            updated = dlg.get_updated()
            if updated:
                # updated = (送文編號, 發文分類, 案類, 嫌疑人_案由, 主承辦人, 受理人, 受理日期, 報案人)
                _, status, casetype, subject, processor, receiver, occ_date, reporter = updated
                # 發文分類顯示名已正規化為兩字（參照表 status_name 即「現行/到案/未到」），直接用
                for col, val in enumerate([
                    status, casetype, subject,
                    self._trimName(processor), self._trimName(receiver),
                    self._fmtDate(occ_date), self._trimName(reporter),
                ], start=2):
                    item = QTableWidgetItem(str(val) if val else "")
                    item.setTextAlignment(Qt.AlignCenter)
                    self.crim_table.setItem(row, col, item)
                autoResizeTable(self.crim_table)

    def _onEditGenRow(self, row, doc_id):
        dlg = GeneralEditDialog(self.db_path, doc_id, self.gen_table, disable_convert=True)
        if dlg.exec():
            if getattr(dlg, "converted", False):
                self._afterConvertReport("gen", doc_id)
                return
            updated = dlg.get_updated()
            if updated:
                # updated = (送文編號, 業務單位, 陳報主旨, 陳報人, 分類)
                _, dept, subject, processor, cat = updated
                # 一般分類顯示名已正規化為兩字（參照表 gen_cat_name 即「業務/其他/相驗」），直接用
                for col, val in enumerate([dept, subject, self._trimName(processor), cat], start=2):
                    item = QTableWidgetItem(str(val) if val else "")
                    item.setTextAlignment(Qt.AlignCenter)
                    self.gen_table.setItem(row, col, item)
                QTimer.singleShot(0, lambda: autoResizeTable(self.gen_table))

    def _afterConvertReport(self, key, doc_id):
        """類別互轉後：移除本頁已作廢的原列（session 預覽無全量重載），
        並標記瀏覽／歸檔頁下次顯示時重載兩類別（新單於彼處呈現）。"""
        table = self.crim_table if key == "crim" else self.gen_table
        if table:
            for r in range(table.rowCount()):
                lbl = table.cellWidget(r, 1)
                if lbl and self._docIdFromLabel(lbl) == doc_id:
                    table.removeRow(r)
                    break
        self._flagConvertReload(("crim", "gen"))

    # ── 刪除（第1點：doc_id 驅動，不需重新綁定）────────────
    def _deleteCrimByDocId(self, doc_id):
        if not self.crim_table:
            return
        # 陳報頁開放一般使用者刪除（更正剛輸入的錯列）；稽核記實際刪除者。
        if not confirmBox("確認刪除",
                          f"本筆資料將被刪除，本文號（{doc_id}）無法再被使用，確認刪除？",
                          confirm_text="刪除", confirm_danger=True, default_confirm=False):
            return
        am = AuthManager.instance()
        conn = None
        try:
            conn = self._getConn()
            softDeleteDoc(conn, table="Document_Criminal", doc_id=doc_id,
                          role=am.current_role, is_admin=am.is_admin())
            conn.commit()
        except Exception as e:
            reportError("刪除失敗", e)
            return
        finally:
            if conn:
                conn.close()
        for r in range(self.crim_table.rowCount()):
            lbl = self.crim_table.cellWidget(r, 1)
            if lbl and self._docIdFromLabel(lbl) == doc_id:
                self.crim_table.removeRow(r)
                return

    def _deleteGenByDocId(self, doc_id):
        if not self.gen_table:
            return
        # 陳報頁開放一般使用者刪除（更正剛輸入的錯列）；稽核記實際刪除者。
        if not confirmBox("確認刪除",
                          f"本筆資料將被刪除，本文號（{doc_id}）無法再被使用，確認刪除？",
                          confirm_text="刪除", confirm_danger=True, default_confirm=False):
            return
        am = AuthManager.instance()
        conn = None
        try:
            conn = self._getConn()
            softDeleteDoc(conn, table="Document_General", doc_id=doc_id,
                          role=am.current_role, is_admin=am.is_admin())
            conn.commit()
        except Exception as e:
            reportError("刪除失敗", e)
            return
        finally:
            if conn:
                conn.close()
        for r in range(self.gen_table.rowCount()):
            lbl = self.gen_table.cellWidget(r, 1)
            if lbl and self._docIdFromLabel(lbl) == doc_id:
                self.gen_table.removeRow(r)
                return
