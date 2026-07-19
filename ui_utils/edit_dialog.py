"""
EditDialog — 通用修改彈窗
動態產生表單，目前支援：
  - task：Document_Task（交辦單）
"""

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLabel, QLineEdit, QComboBox, QDateEdit, QCheckBox,
    QPushButton, QRadioButton, QGroupBox,
)
from PySide6.QtCore import Qt, QDate
from PySide6.QtGui import QFontMetrics

from lib.db_utils import (getConn,
                          writeAudit, buildDetail, auditStaffName)
from .ui_common import BTN_CONFIRM, BTN_CANCEL, confirmBox
from lib.auth_manager import AuthManager
from ui_utils.widgets import setupFilterCombo, NullableDateEdit


class _ElidingLabel(QLabel):
    """顯示時隨寬度自動中段省略（ElideMiddle），不撐破版面。"""
    def __init__(self, text="", parent=None):
        super().__init__(parent)
        self._full = text
        self.setMinimumWidth(40)
        self.setText(text)

    def setFullText(self, text):
        self._full = text or ""
        self._relayout()

    def fullText(self):
        return self._full

    def _relayout(self):
        fm = QFontMetrics(self.font())
        self.setText(fm.elidedText(self._full, Qt.ElideMiddle, max(self.width(), 40)))

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._relayout()


# 歸檔狀態區塊樣式（沿用系統 Apple 基準色）
_ARCH_GROUP_QSS = (
    "QGroupBox { font-weight:600; color:#1c1c1e; border:1px solid #d1d1d6;"
    " border-radius:8px; margin-top:10px; padding:10px 12px 12px 12px; background:#fafafa; }"
    " QGroupBox::title { subcontrol-origin:margin; left:12px; padding:0 4px; }"
)
_ARCH_CLEAR_QSS = (
    "QPushButton { background:#f2f2f7; color:#c0392b; border:1px solid #e0c0bc;"
    " border-radius:6px; padding:3px 12px; }"
    " QPushButton:hover { background:#fbe9e7; }"
    " QPushButton:disabled { background:#f2f2f7; color:#c7c7cc; border-color:#e5e5ea; }"
)


def _build_archive_group(dlg):
    """建立『歸檔狀態』區塊並掛到 dlg。僅 admin 呼叫。
    產生：dlg.w_arch_reported（QCheckBox）、dlg._arch_clear_pending（bool）、
          dlg._arch_fname（原電子檔名）、內部 label/btn 引用。
    """
    g = QGroupBox("歸檔狀態")
    g.setStyleSheet(_ARCH_GROUP_QSS)
    v = QVBoxLayout(g)
    v.setSpacing(10)

    dlg.w_arch_reported = QCheckBox("已陳報紙本")
    # 取消紙本須連動取消 PDF 歸檔；用 clicked（僅 user 操作觸發，load 的 setChecked 不觸發）
    dlg.w_arch_reported.clicked.connect(lambda checked: _on_paper_toggled(dlg, checked))
    v.addWidget(dlg.w_arch_reported)

    row = QHBoxLayout()
    row.setSpacing(8)
    row.addWidget(QLabel("電子檔："))
    dlg._arch_name_lbl = _ElidingLabel("")
    row.addWidget(dlg._arch_name_lbl, 1)
    dlg._arch_clear_btn = QPushButton("清除")
    dlg._arch_clear_btn.setStyleSheet(_ARCH_CLEAR_QSS)
    dlg._arch_clear_btn.clicked.connect(lambda: _on_arch_clear(dlg))
    row.addWidget(dlg._arch_clear_btn)
    v.addLayout(row)

    dlg._arch_clear_pending = False
    dlg._arch_fname = ""
    return g


def _refresh_arch_name(dlg):
    """依目前 fname / pending 狀態更新電子檔顯示與清除鈕。"""
    if dlg._arch_clear_pending:
        dlg._arch_name_lbl.setFullText("（已標記清除，儲存後生效）")
        dlg._arch_name_lbl.setStyleSheet("color:#aeaeb2;")
        dlg._arch_clear_btn.setEnabled(False)
    elif dlg._arch_fname:
        dlg._arch_name_lbl.setFullText(dlg._arch_fname)
        dlg._arch_name_lbl.setStyleSheet("color:#1c1c1e;")
        dlg._arch_clear_btn.setEnabled(True)
    else:
        dlg._arch_name_lbl.setFullText("（未歸檔）")
        dlg._arch_name_lbl.setStyleSheet("color:#aeaeb2;")
        dlg._arch_clear_btn.setEnabled(False)


def _on_arch_clear(dlg):
    # 按下清除：當下只標記 pending、清掉檔名顯示（不跳框）。
    # 二次確認移至儲存時（_confirm_arch_clear），符合「按確認才提醒」流程。
    dlg._arch_clear_pending = True
    _refresh_arch_name(dlg)


def _on_paper_toggled(dlg, checked):
    """紙本 checkbox 連動：取消紙本（該筆仍有電子檔歸檔）須同步取消 PDF。
    勾選當下純警告告知（不給選擇），動作照做：自動標記清除 PDF（檔名顯示一併清掉）。
    儲存時仍會跳一次確認（重大操作，刻意保留二次確認）。"""
    if checked:
        return  # 重新勾選紙本不擾民
    if not dlg._arch_fname or dlg._arch_clear_pending:
        return  # 無電子檔、或 PDF 已標記清除 → 無需連動
    from .ui_common import msgWarning
    msgWarning("取消紙本歸檔", "取消紙本將同步取消 PDF 歸檔。")
    dlg._arch_clear_pending = True
    _refresh_arch_name(dlg)


def _confirm_arch_clear(dlg):
    """儲存時呼叫：依本次「取消歸檔」方向的實際變更動態提醒。
    取消方向 = PDF 被標記清除、或紙本由已勾改為取消勾（與載入原值比對）。
    回傳 True=可繼續儲存（無取消動作時恆 True）；取消則回 False，呼叫端中止儲存。"""
    cb = getattr(dlg, "w_arch_reported", None)
    if cb is None:
        return True
    pdf_cleared   = getattr(dlg, "_arch_clear_pending", False)
    paper_removed = getattr(dlg, "_arch_reported_orig", False) and not cb.isChecked()
    if not pdf_cleared and not paper_removed:
        return True

    parts = []
    if paper_removed:
        parts.append("紙本")
    if pdf_cleared:
        parts.append("PDF")
    label = "與".join(parts)

    msg = f"取消本筆{label}歸檔，退回未歸檔清單。"
    return confirmBox(f"取消{label}歸檔", msg)


def _load_arch_status(dlg, reported, electronic):
    """_load_data 末端呼叫：把 DB 值填入歸檔狀態區塊（僅 admin 有建立）。"""
    if getattr(dlg, "w_arch_reported", None) is None:
        return
    dlg.w_arch_reported.setChecked(bool(reported))
    dlg._arch_reported_orig = bool(reported)
    dlg._arch_fname = str(electronic) if electronic else ""
    dlg._arch_clear_pending = False
    _refresh_arch_name(dlg)


def _audit_arch_cancel(dlg, conn, category, table, subject):
    """歸檔取消稽核：電子＝退回未歸、紙本＝取消勾選。用同一 conn，呼叫端 commit。"""
    am = AuthManager.instance()
    subject = subject or ""
    if getattr(dlg, "_arch_clear_pending", False):
        writeAudit(conn, role=am.current_role, action="ARCHIVE",
                   target_table=table, target_id=dlg.doc_id,
                   operator=am.actor_name(),
                   detail=buildDetail("歸檔", "取消", f"[電子]主旨：{subject}"))
    if getattr(dlg, "_arch_reported_orig", False) \
            and not dlg.w_arch_reported.isChecked():
        writeAudit(conn, role=am.current_role, action="ARCHIVE",
                   target_table=table, target_id=dlg.doc_id,
                   operator=am.actor_name(),
                   detail=buildDetail("歸檔", "取消", f"[紙本]主旨：{subject}"))


def _get_conn(db_path):
    return getConn(db_path)


def _load_combo(conn, sql):
    """回傳 [(id, display), ...]"""
    return conn.execute(sql).fetchall()


def _set_combo_value(combo, value):
    """
    依 data（id）設定 ComboBox 選項；找不到時在最前面插入原始值並標示異常。
    三個 EditDialog 共用。
    """
    if not value:
        # 空值：若下拉首項為空白哨兵（data=None）則停在該項，忠實顯示「未設定」；
        # 無空白項的必填下拉維持原樣（不動游標），由 _on_save 必填檢查擋下。
        if combo.count() and combo.itemData(0) is None:
            combo.setCurrentIndex(0)
        return
    for i in range(combo.count()):
        if combo.itemData(i) == value:
            combo.setCurrentIndex(i)
            return
    combo.insertItem(0, f'⚠ {value}（不在清單）', value)
    combo.setCurrentIndex(0)


# ── Task EditDialog ────────────────────────────────────────────
_CRIMGEN_QSS = """
            QDialog, QWidget {
                background-color: #FFFFFF;
                color: #000000;
            }
            QLineEdit, QComboBox, QDateEdit {
                background-color: #FFFFFF;
                color: #000000;
                border: 1px solid #CCCCCC;
                border-radius: 4px;
                padding: 4px 8px;
            }
            QCheckBox, QRadioButton { color: #000000; }
            QLabel { color: #000000; }
        """


# 「轉換類別」鈕樣式（§5.1：低調紅框白底，比儲存重、比刪除溫和）
_CONVERT_BTN_QSS = (
    "QPushButton { background:#fff; color:#a8442e; border:1.5px solid #e6b9ad;"
    " border-radius:7px; padding:6px 14px; }"
    " QPushButton:hover { background:#fdf2f0; }"
    " QPushButton:disabled { background:#f2f2f7; color:#c7c7cc; border-color:#e5e5ea; }"
)


def _on_convert_clicked(dlg, src_kind):
    """開類別互轉補填視窗（僅 is_manager）；成功則關閉父修改彈窗並回傳結果。
    父彈窗顯示的已是作廢舊號，留著無意義，故 accept() 一併關閉。"""
    if not AuthManager.instance().is_manager():
        return
    from .convert_dialog import ConvertDialog
    cdlg = ConvertDialog(dlg.db_path, src_kind, dlg.doc_id, dlg)
    if cdlg.exec():
        dlg.converted        = True
        dlg.convert_new_id   = cdlg.new_doc_id
        dlg.convert_dst_kind = cdlg.dst_kind
        dlg.accept()


def _make_convert_button(dlg, src_kind):
    """建立「⇄ 轉換類別」鈕（呼叫端已 is_manager guard）。"""
    btn = QPushButton("⇄ 轉換類別")
    btn.setStyleSheet(_CONVERT_BTN_QSS)
    btn.clicked.connect(lambda _=False: _on_convert_clicked(dlg, src_kind))
    return btn


class _BaseEditDialog(QDialog):
    """三個編輯彈窗共用基底：版面常數（子類以 self._LABEL_W 等引用，零改）。"""
    _LABEL_W = 120   # label 區寬度
    _FIELD_W = 340   # 輸入元件總寬度
    _MARGIN  = 40    # 左右 margin

    def _set_combo(self, combo, value):
        _set_combo_value(combo, value)


class TaskEditDialog(_BaseEditDialog):
    """交辦單修改彈窗（Tab 0 / Tab 1 共用）"""

    def __init__(self, db_path, doc_id, parent=None, restricted=False, source=None):
        super().__init__(parent)
        self.db_path = db_path
        self.doc_id  = doc_id
        self.restricted = restricted   # True：一般使用者，只可改承辦人
        self.source  = source          # 'dispatch'＝發文頁觸發（僅此來源記「修改承辦」稽核）
        self.setWindowTitle('交辦單修改')

        # ── 版面常數 ──────────────────────────────────────────
        self._CHECKBOX_W = 130   # 免覆 checkbox 寬度
        self._SPACING_W  = 30    # DateEdit 與 checkbox 間距
        self._DATE_W     = self._FIELD_W - self._SPACING_W - self._CHECKBOX_W  # = 260

        self.setMinimumWidth(self._LABEL_W + self._FIELD_W + self._MARGIN)  # = 580
        self.setStyleSheet("""
            QDialog, QWidget {
                background-color: #FFFFFF;
                color: #000000;
            }
            QLineEdit, QComboBox, QDateEdit {
                background-color: #FFFFFF;
                color: #000000;
                border: 1px solid #CCCCCC;
                border-radius: 4px;
                padding: 4px 8px;
            }
            QLineEdit:disabled, QComboBox:disabled, QDateEdit:disabled {
                background-color: #e5e5ea;
                color: #aeaeb2;
                border-color: #d1d1d6;
            }
            QCheckBox { color: #000000; }
            QCheckBox:disabled { color: #aeaeb2; }
            QCheckBox::indicator:disabled {
                background-color: #e5e5ea;
                border-color: #d1d1d6;
            }
            QLabel { color: #000000; }
        """)
        self._build_ui()
        self._load_data()
        if self.restricted:
            self._apply_restricted()

    def _apply_restricted(self):
        """一般使用者：保留 DB 原值顯示，鎖定除承辦人外所有欄位。"""
        for w in (self.w_recv_date, self.w_recv_id, self.w_dept,
                  self.w_subject, self.w_deadline, self.w_no_deadline):
            w.setEnabled(False)
        self.w_proc.setFocus()

    def _build_ui(self):
        conn = _get_conn(self.db_path)

        # 參照資料
        self._personnel = _load_combo(conn,
            "SELECT staff_id, staff_name FROM Ref_Personnel WHERE is_active=1 ORDER BY sort_order")
        self._depts = _load_combo(conn,
            "SELECT dept_id, dept_name FROM Ref_Departments WHERE is_active=1 ORDER BY sort_order")
        conn.close()

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight)
        form.setSpacing(10)

        # 編號（鎖定）
        lbl_id = QLabel(str(self.doc_id))
        lbl_id.setStyleSheet("font-weight: bold;")
        form.addRow("交辦單編號：", lbl_id)

        # 收文日期
        self.w_recv_date = QDateEdit()
        self.w_recv_date.setCalendarPopup(True)
        self.w_recv_date.setDisplayFormat("yyyy-MM-dd")
        form.addRow("收文日期：", self.w_recv_date)

        # 收文人員
        self.w_recv_id = QComboBox()
        for sid, sname in self._personnel:
            self.w_recv_id.addItem(sname, sid)
        form.addRow("收文人員：", self.w_recv_id)

        # 業務組
        self.w_dept = QComboBox()
        for did, dname in self._depts:
            self.w_dept.addItem(dname, did)
        form.addRow("業務組：", self.w_dept)

        # 交辦事由
        self.w_subject = QLineEdit()
        self.w_subject.setPlaceholderText("請輸入交辦事由")
        form.addRow("交辦事由：", self.w_subject)

        # 承辦人
        self.w_proc = QComboBox()
        for sid, sname in self._personnel:
            self.w_proc.addItem(sname, sid)
        form.addRow("承辦人：", self.w_proc)

        # 限辦日期 + 免覆
        from PySide6.QtWidgets import QStackedWidget

        self.w_no_deadline = QCheckBox("免覆")
        self.w_no_deadline.setFixedWidth(self._CHECKBOX_W)

        # 限辦日期欄：QStackedWidget 切換 DateEdit（index 0）和免覆提示（index 1）
        self._deadline_stack = QStackedWidget()
        self._deadline_stack.setFixedWidth(self._DATE_W)

        self.w_deadline = QDateEdit()
        self.w_deadline.setCalendarPopup(True)
        self.w_deadline.setDisplayFormat("yyyy-MM-dd")
        self._deadline_stack.addWidget(self.w_deadline)   # index 0：有日期

        lbl_exempt = QLabel("")
        lbl_exempt.setAlignment(Qt.AlignCenter)
        lbl_exempt.setStyleSheet(
            "background-color: #e5e5ea; border: 1px solid #d1d1d6; border-radius: 4px; padding: 4px 8px;"
        )
        self._deadline_stack.addWidget(lbl_exempt)         # index 1：免覆

        def _onNoDeadlineToggled(checked):
            self._deadline_stack.setCurrentIndex(1 if checked else 0)
            if not checked:
                self.w_deadline.setDate(QDate.currentDate())

        self.w_no_deadline.toggled.connect(_onNoDeadlineToggled)

        deadline_row = QHBoxLayout()
        deadline_row.setContentsMargins(0, 0, 0, 0)
        deadline_row.addWidget(self._deadline_stack)
        deadline_row.addSpacing(self._SPACING_W)
        deadline_row.addWidget(self.w_no_deadline)
        form.addRow("限辦日期：", deadline_row)

        # 按鈕
        btn_save   = QPushButton("儲存")
        btn_cancel = QPushButton("取消")
        btn_save.setStyleSheet(BTN_CONFIRM)
        btn_cancel.setStyleSheet(BTN_CANCEL)
        btn_save.clicked.connect(self._on_save)
        btn_cancel.clicked.connect(self.reject)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_row.addWidget(btn_save)
        btn_row.addWidget(btn_cancel)

        root = QVBoxLayout(self)
        root.addLayout(form)
        root.addSpacing(8)
        root.addLayout(btn_row)

        self.w_subject.returnPressed.connect(self._on_save)
        self.w_subject.setFocus()

    def _load_data(self):
        """從 DB 撈原始資料填入欄位"""
        conn = _get_conn(self.db_path)
        row = conn.execute("""
            SELECT receive_date, receive_id, dept_id, subject,
                   processor_id, deadline, dispatch_date
            FROM Document_Task WHERE doc_id=?
        """, (self.doc_id,)).fetchone()
        conn.close()
        if not row:
            return

        recv_date, recv_id, dept_id, subject, proc_id, deadline, dispatch_date = row
        self._dispatch_date = dispatch_date  # 已發文時不再提示逾期

        # 收文日期
        if recv_date:
            self.w_recv_date.setDate(QDate.fromString(str(recv_date), "yyyy-MM-dd"))
        else:
            self.w_recv_date.setDate(QDate.currentDate())

        # 收文人員
        self._set_combo(self.w_recv_id, recv_id)

        # 業務組
        self._set_combo(self.w_dept, dept_id)

        # 交辦事由
        self.w_subject.setText(str(subject) if subject else "")

        # 承辦人
        self._set_combo(self.w_proc, proc_id)

        # 限辦日期
        if deadline:
            self.w_deadline.setDate(QDate.fromString(str(deadline), "yyyy-MM-dd"))
            self.w_no_deadline.setChecked(False)
            self._deadline_stack.setCurrentIndex(0)
        else:
            self.w_deadline.setDate(QDate.currentDate())
            self.w_no_deadline.setChecked(True)
            self._deadline_stack.setCurrentIndex(1)

    def _on_save(self):
        from .ui_common import msgWarning, msgCritical, reportError
        recv_date = self.w_recv_date.date().toString("yyyy-MM-dd")
        recv_id   = self.w_recv_id.currentData()
        dept_id   = self.w_dept.currentData()
        subject   = self.w_subject.text().strip()
        proc_id   = self.w_proc.currentData()
        no_deadline = self.w_no_deadline.isChecked()
        deadline  = None if no_deadline \
                    else self.w_deadline.date().toString("yyyy-MM-dd")

        errors = []
        if not recv_id:  errors.append("收文人員")
        if not dept_id:  errors.append("業務組")
        if not subject:  errors.append("交辦事由")
        if not proc_id:  errors.append("承辦人")
        if errors:
            msgWarning("欄位未填", f"請填寫以下必填欄位：\n{'、'.join(errors)}")
            return

        # 已發文的交辦單不再提示逾期
        if not no_deadline and not getattr(self, '_dispatch_date', None):
            dl    = self.w_deadline.date()
            today = QDate.currentDate()
            if dl == today:
                if not confirmBox("限辦日期確認",
                                  f"限辦日期為今天（{deadline}），確定要儲存嗎？",
                                  confirm_text="確認儲存", default_confirm=True):
                    return
            elif dl < today:
                if not confirmBox("限辦日期已逾期",
                                  f"限辦日期（{deadline}）早於今天，儲存後將立即逾期，確定要儲存嗎？",
                                  confirm_text="確認儲存", confirm_danger=True, default_confirm=True):
                    return

        try:
            conn = _get_conn(self.db_path)
            # 發文頁觸發且承辦人有變動時，記稽核（operator＝送文者）
            old_proc = old_sender = None
            if self.source == 'dispatch':
                r = conn.execute(
                    "SELECT processor_id, sender_id FROM Document_Task WHERE doc_id=?",
                    (self.doc_id,)).fetchone()
                if r:
                    old_proc, old_sender = r[0], r[1]
            conn.execute("""
                UPDATE Document_Task
                SET receive_date=?, receive_id=?, dept_id=?,
                    subject=?, processor_id=?, deadline=?
                WHERE doc_id=?
            """, (recv_date, recv_id, dept_id, subject, proc_id, deadline, self.doc_id))
            if self.source == 'dispatch' and old_proc != proc_id:
                writeAudit(conn,
                           role=AuthManager.instance().current_role,
                           action="UPDATE", target_table="Document_Task",
                           target_id=self.doc_id,
                           operator=auditStaffName(conn, old_sender),
                           detail=buildDetail(
                               "交辦", "修改",
                               f"{auditStaffName(conn, old_proc)} → "
                               f"{auditStaffName(conn, proc_id)}"))
            conn.commit()
            conn.close()
        except Exception as e:
            reportError("儲存失敗", e)
            return

        self.accept()

    def get_updated(self):
        """儲存後回傳更新後的顯示值，供表格刷新用"""
        conn = _get_conn(self.db_path)
        row = conn.execute("""
            SELECT 編號, 交辦事由, 業務組, 所承辦人,
                   限辦日期, 發文日期, 狀態
            FROM View_Task_Full
            WHERE 編號=?
        """, (self.doc_id,)).fetchone()
        conn.close()
        return row

# ── Criminal EditDialog ────────────────────────────────────────
class CriminalEditDialog(_BaseEditDialog):
    """刑案陳報修改彈窗（Tab 2）"""

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

    # Radio 對應表：(db_value, display_label)
    STATUS_OPTIONS = [
        ('CS01', '現行'),
        ('CS02', '到案'),
        ('CS03', '未到'),
    ]

    def __init__(self, db_path, doc_id, parent=None, disable_convert=False):
        super().__init__(parent)
        self.db_path = db_path
        self.doc_id  = doc_id
        self._disable_convert = disable_convert
        self.setWindowTitle('刑案陳報修改')


        self.setMinimumWidth(self._LABEL_W + self._FIELD_W + self._MARGIN)
        self.setStyleSheet(_CRIMGEN_QSS)
        self._build_ui()
        self._load_data()

    def _build_ui(self):
        from PySide6.QtWidgets import QButtonGroup
        conn = _get_conn(self.db_path)
        self._personnel  = _load_combo(conn,
            "SELECT staff_id, staff_name FROM Ref_Personnel WHERE is_active=1 ORDER BY sort_order")
        _ct_rows = conn.execute(
            "SELECT case_type_id, case_type_name, alias "
            "FROM Ref_CaseTypes WHERE is_active=1 ORDER BY sort_order"
        ).fetchall()
        self._case_types = [(r[0], r[1]) for r in _ct_rows]
        self._casetype_alias_map = {
            r[1]: [a.strip() for a in (r[2] or "").split(",") if a.strip()]
            for r in _ct_rows if r[2]
        }
        conn.close()

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight)
        form.setSpacing(10)

        # 編號（鎖定）
        lbl_id = QLabel(str(self.doc_id))
        lbl_id.setStyleSheet("font-weight: bold;")
        form.addRow("陳報編號：", lbl_id)

        # 陳報日期（可空白＝未發文哨兵；填日期＝發文，此時發文人員必填）
        self.w_report_date = NullableDateEdit()
        self.w_report_date.setPlaceholderText("未發文")
        form.addRow("陳報日期：", self.w_report_date)

        # 發文人員（保留空白項：未發文列 sender=NULL 忠實顯示「未設定」，
        # 且填日期發文時可由必填檢查擋下未選發文人員）
        self.w_sender = QComboBox()
        self.w_sender.addItem("", None)
        for sid, sname in self._personnel:
            self.w_sender.addItem(sname, sid)
        form.addRow("發文人員：", self.w_sender)

        # 案件分類（可輸入關鍵字篩選，預設帶入資料庫值）
        self.w_casetype = QComboBox()
        self.w_casetype.setEditable(True)
        setupFilterCombo(self.w_casetype, self._case_types,
                         alias_map=self._casetype_alias_map)
        form.addRow("案件分類：", self.w_casetype)

        # 發文分類（Radio）
        radio_row = QHBoxLayout()
        radio_row.setContentsMargins(0, 0, 0, 0)
        self._status_radios = []
        self._status_group  = QButtonGroup(self)
        for i, (val, label) in enumerate(self.STATUS_OPTIONS):
            rb = QRadioButton(label)
            rb.setStyleSheet(self.RADIO_STYLE)
            rb.setMinimumWidth(65)   # 比照 Layout3.ui：125% 下 sizeHint 算不準會切字
            self._status_group.addButton(rb, i)
            self._status_radios.append((val, rb))
            radio_row.addWidget(rb)
        radio_row.addStretch()
        form.addRow("發文分類：", radio_row)

        # 承辦人
        self.w_processor = QComboBox()
        for sid, sname in self._personnel:
            self.w_processor.addItem(sname, sid)
        form.addRow("承辦人：", self.w_processor)

        # 受理人
        self.w_receiver = QComboBox()
        self.w_receiver.addItem("", None)   # 受理人非必填，保留空白項忠實顯示「未設定」
        for sid, sname in self._personnel:
            self.w_receiver.addItem(sname, sid)
        form.addRow("受理人：", self.w_receiver)

        # 陳報主旨
        self.w_subject = QLineEdit()
        self.w_subject.setPlaceholderText("請輸入陳報主旨")
        form.addRow("陳報主旨：", self.w_subject)

        # 查獲日期（可空白；可手打 yyyy-MM-dd 或下拉月曆挑日）
        self.w_occ_date = NullableDateEdit()
        self.w_occ_date.setPlaceholderText("下拉選擇日期")
        form.addRow("查獲日期：", self.w_occ_date)

        # 報案人
        self.w_reporter = QLineEdit()
        self.w_reporter.setPlaceholderText("請輸入報案人")
        form.addRow("報案人：", self.w_reporter)

        # 按鈕
        btn_save   = QPushButton("儲存")
        btn_cancel = QPushButton("取消")
        btn_save.setStyleSheet(BTN_CONFIRM)
        btn_cancel.setStyleSheet(BTN_CANCEL)
        btn_save.clicked.connect(self._on_save)
        btn_cancel.clicked.connect(self.reject)

        btn_row = QHBoxLayout()
        # 轉換類別鈕：最左側，之後 stretch 隔開儲存/取消（§5.1）
        if AuthManager.instance().is_manager():
            _cbtn = _make_convert_button(self, "crim")
            if getattr(self, "_disable_convert", False):
                _cbtn.setEnabled(False)
                _cbtn.setToolTip("已陳報之公文不可變更類別")
            btn_row.addWidget(_cbtn)
        btn_row.addStretch()
        btn_row.addWidget(btn_save)
        btn_row.addWidget(btn_cancel)

        root = QVBoxLayout(self)
        root.addLayout(form)
        root.addSpacing(8)

        # 歸檔狀態區塊（管理者／歸檔管理）
        self.w_arch_reported = None
        if AuthManager.instance().is_manager():
            root.addWidget(_build_archive_group(self))
            root.addSpacing(4)

        root.addLayout(btn_row)

        self.w_subject.returnPressed.connect(self._on_save)
        self.w_reporter.returnPressed.connect(self._on_save)
        self.w_subject.setFocus()

    def _load_data(self):
        conn = _get_conn(self.db_path)
        row = conn.execute("""
            SELECT report_date, sender_id, case_type, case_status,
                   processor_id, receiver_id, subject_summary,
                   occurrence_date, reporter_name, is_reported, is_electronic
            FROM Document_Criminal WHERE doc_id=?
        """, (self.doc_id,)).fetchone()
        conn.close()
        if not row:
            return

        report_date, sender_id, case_type, case_status, \
            proc_id, recv_id, subject, occ_date, reporter, \
            is_reported, is_electronic = row

        # 有值＝已發文；NULL＝未發文（自助取號未結算列）→ 留空，不填今日
        if report_date:
            self.w_report_date.setDate(QDate.fromString(str(report_date), "yyyy-MM-dd"))
        else:
            self.w_report_date.clear()

        self._set_combo(self.w_sender,    sender_id)
        self._set_combo(self.w_casetype,  case_type)
        self._set_combo(self.w_processor, proc_id)
        self._set_combo(self.w_receiver,  recv_id)

        # Radio：從 DB 的 case_status 對應
        # DB 存的是 Ref_Case_Status 的 status_id（CS01/CS02/CS03）
        matched = False
        for val, rb in self._status_radios:
            if val == case_status:
                rb.setChecked(True)
                matched = True
                break
        if not matched:
            self._status_radios[0][1].setChecked(True)

        self.w_subject.setText(str(subject) if subject else "")

        if occ_date:
            self.w_occ_date.setDate(QDate.fromString(str(occ_date), "yyyy-MM-dd"))
        else:
            self.w_occ_date.clear()

        self.w_reporter.setText(str(reporter) if reporter else "")

        _load_arch_status(self, is_reported, is_electronic)

    def _on_save(self):
        from .ui_common import msgWarning, msgCritical, reportError
        # 陳報日期：空白＝未發文（report_date/sender 皆存 NULL）；填有效日期＝發文，
        # 此時發文人員必填。格式錯（非空非法）先擋下亮紅框。
        self.w_report_date.validateNow()
        if self.w_report_date.hasError():
            msgWarning("日期格式錯誤",
                       "陳報日期格式須為 yyyy-MM-dd，或留空表示未發文。")
            return
        rpt_d       = self.w_report_date.getDate()
        issued      = rpt_d is not None
        report_date = rpt_d.toString("yyyy-MM-dd") if issued else None
        sender_id   = self.w_sender.currentData() if issued else None
        case_type   = self.w_casetype.currentData()
        proc_id     = self.w_processor.currentData()
        recv_id     = self.w_receiver.currentData()
        subject     = self.w_subject.text().strip()
        self.w_occ_date.validateNow()   # 送出前再驗一次（非法即亮紅框）
        occ_blank   = self.w_occ_date.isBlank()
        occ_err     = self.w_occ_date.hasError()
        occ_d       = self.w_occ_date.getDate()
        occ_date    = occ_d.toString("yyyy-MM-dd") if occ_d else None
        reporter    = self.w_reporter.text().strip()

        status_id = 'CS01'
        for val, rb in self._status_radios:
            if rb.isChecked():
                status_id = val
                break

        errors = []
        if issued and not sender_id: errors.append("發文人員")
        if not case_type: errors.append("案類")
        if not proc_id:   errors.append("承辦人員")
        if not subject:   errors.append("陳報主旨")
        if occ_blank:     errors.append("查獲日期")
        elif occ_err:     errors.append("查獲日期格式（請用 yyyy-MM-dd）")
        if errors:
            msgWarning("欄位未填", f"請填寫以下必填欄位：\n{'、'.join(errors)}")
            return

        if not _confirm_arch_clear(self):
            return
        try:
            conn = _get_conn(self.db_path)
            conn.execute("""
                UPDATE Document_Criminal
                SET report_date=?, sender_id=?, case_type=?, case_status=?,
                    processor_id=?, receiver_id=?, subject_summary=?,
                    occurrence_date=?, reporter_name=?
                WHERE doc_id=?
            """, (report_date, sender_id, case_type, status_id,
                  proc_id, recv_id, subject, occ_date, reporter or None,
                  self.doc_id))
            if self.w_arch_reported is not None:
                conn.execute(
                    "UPDATE Document_Criminal SET is_reported=? WHERE doc_id=?",
                    (1 if self.w_arch_reported.isChecked() else 0, self.doc_id))
                if self._arch_clear_pending:
                    conn.execute(
                        "UPDATE Document_Criminal SET is_electronic='' WHERE doc_id=?",
                        (self.doc_id,))
                _audit_arch_cancel(self, conn, "刑案", "Document_Criminal", subject)
            conn.commit()
            conn.close()
        except Exception as e:
            reportError("儲存失敗", e)
            return

        self.accept()

    def get_updated(self):
        """儲存後回傳更新後的顯示值，供表格刷新用"""
        conn = _get_conn(self.db_path)
        row = conn.execute("""
            SELECT 送文編號, 發文分類, 案類, 嫌疑人_案由,
                   主承辦人, 受理人, 受理日期, 報案人
            FROM View_Criminal_Full WHERE 送文編號=?
        """, (self.doc_id,)).fetchone()
        conn.close()
        return row


# ── General EditDialog ─────────────────────────────────────────
class GeneralEditDialog(_BaseEditDialog):
    """一般陳報修改彈窗（Tab 2）"""

    RADIO_STYLE = CriminalEditDialog.RADIO_STYLE

    CAT_OPTIONS = [
        ('GC01', '業務'),
        ('GC03', '其他'),
        ('GC02', '相驗'),
    ]

    def __init__(self, db_path, doc_id, parent=None, disable_convert=False):
        super().__init__(parent)
        self.db_path = db_path
        self.doc_id  = doc_id
        self._disable_convert = disable_convert
        self.setWindowTitle('一般陳報修改')


        self.setMinimumWidth(self._LABEL_W + self._FIELD_W + self._MARGIN)
        self.setStyleSheet(_CRIMGEN_QSS)
        self._build_ui()
        self._load_data()

    def _build_ui(self):
        from PySide6.QtWidgets import QButtonGroup
        conn = _get_conn(self.db_path)
        self._personnel = _load_combo(conn,
            "SELECT staff_id, staff_name FROM Ref_Personnel WHERE is_active=1 ORDER BY sort_order")
        self._depts = _load_combo(conn,
            "SELECT dept_id, dept_name FROM Ref_Departments WHERE is_active=1 ORDER BY sort_order")
        conn.close()

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight)
        form.setSpacing(10)

        # 編號（鎖定）
        lbl_id = QLabel(str(self.doc_id))
        lbl_id.setStyleSheet("font-weight: bold;")
        form.addRow("陳報編號：", lbl_id)

        # 陳報日期（可空白＝未發文哨兵；填日期＝發文，此時發文人員必填）
        self.w_report_date = NullableDateEdit()
        self.w_report_date.setPlaceholderText("未發文")
        form.addRow("陳報日期：", self.w_report_date)

        # 發文人員（保留空白項：未發文列 sender=NULL 忠實顯示「未設定」，
        # 且填日期發文時可由必填檢查擋下未選發文人員）
        self.w_sender = QComboBox()
        self.w_sender.addItem("", None)
        for sid, sname in self._personnel:
            self.w_sender.addItem(sname, sid)
        form.addRow("發文人員：", self.w_sender)

        # 業務單位
        self.w_dept = QComboBox()
        self.w_dept.addItem("", None)   # 業務單位非必填，保留空白項忠實顯示「未設定」
        for did, dname in self._depts:
            self.w_dept.addItem(dname, did)
        form.addRow("業務單位：", self.w_dept)

        # 發文分類（Radio）
        radio_row = QHBoxLayout()
        radio_row.setContentsMargins(0, 0, 0, 0)
        self._cat_radios = []
        self._cat_group  = QButtonGroup(self)
        for i, (val, label) in enumerate(self.CAT_OPTIONS):
            rb = QRadioButton(label)
            rb.setStyleSheet(self.RADIO_STYLE)
            rb.setMinimumWidth(65)   # 比照 Layout3.ui：125% 下 sizeHint 算不準會切字
            self._cat_group.addButton(rb, i)
            self._cat_radios.append((val, rb))
            radio_row.addWidget(rb)
        radio_row.addStretch()
        form.addRow("發文分類：", radio_row)

        # 陳報主旨
        # 承辦人
        self.w_processor = QComboBox()
        for sid, sname in self._personnel:
            self.w_processor.addItem(sname, sid)
        form.addRow("陳報人：", self.w_processor)

        self.w_subject = QLineEdit()
        self.w_subject.setPlaceholderText("請輸入陳報主旨")
        form.addRow("陳報主旨：", self.w_subject)

        # 按鈕
        btn_save   = QPushButton("儲存")
        btn_cancel = QPushButton("取消")
        btn_save.setStyleSheet(BTN_CONFIRM)
        btn_cancel.setStyleSheet(BTN_CANCEL)
        btn_save.clicked.connect(self._on_save)
        btn_cancel.clicked.connect(self.reject)

        btn_row = QHBoxLayout()
        # 轉換類別鈕：最左側，之後 stretch 隔開儲存/取消（§5.1）
        if AuthManager.instance().is_manager():
            _cbtn = _make_convert_button(self, "gen")
            if getattr(self, "_disable_convert", False):
                _cbtn.setEnabled(False)
                _cbtn.setToolTip("已陳報之公文不可變更類別")
            btn_row.addWidget(_cbtn)
        btn_row.addStretch()
        btn_row.addWidget(btn_save)
        btn_row.addWidget(btn_cancel)

        root = QVBoxLayout(self)
        root.addLayout(form)
        root.addSpacing(8)

        # 歸檔狀態區塊（管理者／歸檔管理）
        self.w_arch_reported = None
        if AuthManager.instance().is_manager():
            root.addWidget(_build_archive_group(self))
            root.addSpacing(4)

        root.addLayout(btn_row)

        self.w_subject.returnPressed.connect(self._on_save)
        self.w_subject.setFocus()

    def _load_data(self):
        conn = _get_conn(self.db_path)
        row = conn.execute("""
            SELECT report_date, sender_id, dept_id, gen_cat_id,
                   subject, processor_id, is_reported, is_electronic
            FROM Document_General WHERE doc_id=?
        """, (self.doc_id,)).fetchone()
        conn.close()
        if not row:
            return

        report_date, sender_id, dept_id, gen_cat_id, subject, proc_id, \
            is_reported, is_electronic = row

        # 有值＝已發文；NULL＝未發文（自助取號未結算列）→ 留空，不填今日
        if report_date:
            self.w_report_date.setDate(QDate.fromString(str(report_date), "yyyy-MM-dd"))
        else:
            self.w_report_date.clear()

        self._set_combo(self.w_sender,    sender_id)
        self._set_combo(self.w_dept,      dept_id)
        self._set_combo(self.w_processor, proc_id)

        matched = False
        for val, rb in self._cat_radios:
            if val == gen_cat_id:
                rb.setChecked(True)
                matched = True
                break
        if not matched:
            self._cat_radios[0][1].setChecked(True)

        self.w_subject.setText(str(subject) if subject else "")

        _load_arch_status(self, is_reported, is_electronic)

    def _on_save(self):
        from .ui_common import msgWarning, msgCritical, reportError
        # 陳報日期：空白＝未發文（report_date/sender 皆存 NULL）；填有效日期＝發文，
        # 此時發文人員必填。格式錯（非空非法）先擋下亮紅框。
        self.w_report_date.validateNow()
        if self.w_report_date.hasError():
            msgWarning("日期格式錯誤",
                       "陳報日期格式須為 yyyy-MM-dd，或留空表示未發文。")
            return
        rpt_d       = self.w_report_date.getDate()
        issued      = rpt_d is not None
        report_date = rpt_d.toString("yyyy-MM-dd") if issued else None
        sender_id   = self.w_sender.currentData() if issued else None
        dept_id     = self.w_dept.currentData()
        subject     = self.w_subject.text().strip()
        proc_id     = self.w_processor.currentData()

        cat_id = 'GC01'
        for val, rb in self._cat_radios:
            if rb.isChecked():
                cat_id = val
                break

        errors = []
        if issued and not sender_id: errors.append("發文人員")
        if not proc_id:   errors.append("陳報人")
        if not subject:   errors.append("陳報主旨")
        if errors:
            msgWarning("欄位未填", f"請填寫以下必填欄位：\n{'、'.join(errors)}")
            return

        if not _confirm_arch_clear(self):
            return
        try:
            conn = _get_conn(self.db_path)
            conn.execute("""
                UPDATE Document_General
                SET report_date=?, sender_id=?, dept_id=?, gen_cat_id=?,
                    subject=?, processor_id=?
                WHERE doc_id=?
            """, (report_date, sender_id, dept_id, cat_id,
                  subject, proc_id, self.doc_id))
            if self.w_arch_reported is not None:
                conn.execute(
                    "UPDATE Document_General SET is_reported=? WHERE doc_id=?",
                    (1 if self.w_arch_reported.isChecked() else 0, self.doc_id))
                if self._arch_clear_pending:
                    conn.execute(
                        "UPDATE Document_General SET is_electronic='' WHERE doc_id=?",
                        (self.doc_id,))
                _audit_arch_cancel(self, conn, "一般", "Document_General", subject)
            conn.commit()
            conn.close()
        except Exception as e:
            reportError("儲存失敗", e)
            return

        self.accept()

    def get_updated(self):
        """儲存後回傳更新後的顯示值，供表格刷新用"""
        conn = _get_conn(self.db_path)
        row = conn.execute("""
            SELECT 送文編號, 業務單位, 陳報主旨, 陳報人, 分類
            FROM View_General_Full WHERE 送文編號=?
        """, (self.doc_id,)).fetchone()
        conn.close()
        return row
