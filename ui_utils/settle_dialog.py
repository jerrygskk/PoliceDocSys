"""
settle_dialog.py — 自助取號模式「結算發文」彈窗

功能：
  - 顯示所有「已取號、未發文」的刑案／一般公文（左右雙欄）
  - 預設全勾；點整列切換勾選，取消勾選列整行灰掉
  - 關鍵字過濾（兩欄同時）、底部即時計數
  - 確認後同一 transaction 批次補 report_date=今日 + sender_id，並寫稽核
  - 確認後回傳 True 供列印頁自動產生簽收表
"""
from datetime import date

from PySide6.QtCore    import Qt, QDate, QObject, QEvent
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QLineEdit, QPushButton, QComboBox,
    QTableWidget, QTableWidgetItem, QAbstractItemView,
    QHeaderView, QSizePolicy, QFrame, QCheckBox, QWidget,
)
from PySide6.QtGui     import QColor, QFont

from lib.db_utils    import getConn
from ui_utils.ui_common import msgWarning, confirmBox, reportError

_ORANGE = QColor("#e67e22")
_GRAY   = QColor("#aeaeb2")

_DLG_SS = """
QDialog, QWidget { background-color: #ffffff; color: #000000; }
QLabel            { color: #1c1c1e; font-size: 13pt; }
QLineEdit {
    background-color: #ffffff; color: #1c1c1e;
    border: 1px solid #c6c6c8; border-radius: 4px;
    padding: 4px 8px; font-size: 13pt;
}
QLineEdit:focus { border-color: #8fa8c8; }
QComboBox {
    background-color: #ffffff; color: #1c1c1e;
    border: 1px solid #c6c6c8; border-radius: 4px;
    padding: 4px 8px; font-size: 13pt;
}
QComboBox:hover { border-color: #8fa8c8; }
QComboBox:disabled { background-color: #f2f2f7; color: #aeaeb2; }
QComboBox QAbstractItemView {
    background-color: #ffffff; border: 1px solid #c6c6c8;
    border-radius: 8px; outline: none;
    selection-background-color: #6e8fac; selection-color: #ffffff;
}
QComboBox QAbstractItemView::item {
    color: #1c1c1e; padding: 4px 8px; min-height: 28px;
}
QComboBox QAbstractItemView::item:hover { background-color: #e5e5ea; }
QComboBox QAbstractItemView::item:selected { background-color: #6e8fac; color: #ffffff; }
QTableWidget {
    background-color: #ffffff; color: #1c1c1e;
    border: 1px solid #d1d1d6; gridline-color: #e5e5ea;
    font-size: 13pt;
}
QTableWidget::item { padding: 2px 4px; }
QTableWidget::item:hover { background-color: transparent; }
QHeaderView::section {
    background-color: #f2f2f7; color: #3a3a3c;
    padding: 4px 6px; border: none;
    border-right: 1px solid #e5e5ea;
    border-bottom: 1px solid #d1d1d6;
    font-size: 12pt; font-weight: 600;
}
QCheckBox { color: #1c1c1e; spacing: 6px; }
QCheckBox::indicator {
    width: 18px; height: 18px;
    border: 1.5px solid #c6c6c8; border-radius: 4px;
    background-color: #ffffff;
}
QCheckBox::indicator:checked {
    background-color: #8fa8c8; border-color: #8fa8c8;
}
QCheckBox:disabled { color: #aeaeb2; }
QCheckBox::indicator:disabled {
    background-color: #e5e5ea; border-color: #d1d1d6;
}
QPushButton {
    background-color: #a1b4cb; color: #ffffff;
    border: none; border-radius: 8px;
    padding: 8px 20px; font-size: 13pt; font-weight: 600;
}
QPushButton:hover    { background-color: #4977b1; }
QPushButton:pressed  { background-color: #39649a; }
QPushButton:disabled { background-color: #d1d9e3; color: #ffffff; }
QPushButton#btn_cancel {
    background-color: #f2f2f7; color: #1c1c1e;
    border: 1px solid #d1d1d6;
}
QPushButton#btn_cancel:hover { background-color: #e5e5ea; }
"""


def _load_unissued(db_path):
    """查兩主表未發文（report_date IS NULL 或 ''）且非軟刪除的列。
    回傳 {"crim": [...], "gen": [...]}，每筆為 dict(doc_id, processor, subject)。"""
    result = {"crim": [], "gen": []}
    conn = getConn(db_path)
    try:
        # 刑案
        rows = conn.execute(
            "SELECT c.doc_id, COALESCE(p.staff_name, c.processor_id) AS processor, "
            "       c.subject_summary AS subject "
            "FROM Document_Criminal c "
            "LEFT JOIN Ref_Personnel p ON c.processor_id = p.staff_id "
            "WHERE (c.report_date IS NULL OR c.report_date = '') "
            "  AND c.subject_summary IS NOT NULL AND c.subject_summary != '' "
            "ORDER BY c.doc_id"
        ).fetchall()
        result["crim"] = [{"doc_id": r[0], "processor": r[1] or "", "subject": r[2] or ""}
                          for r in rows]
        # 一般
        rows = conn.execute(
            "SELECT g.doc_id, COALESCE(p.staff_name, g.processor_id) AS processor, "
            "       g.subject "
            "FROM Document_General g "
            "LEFT JOIN Ref_Personnel p ON g.processor_id = p.staff_id "
            "WHERE (g.report_date IS NULL OR g.report_date = '') "
            "  AND g.subject IS NOT NULL AND g.subject != '' "
            "ORDER BY g.doc_id"
        ).fetchall()
        result["gen"] = [{"doc_id": r[0], "processor": r[1] or "", "subject": r[2] or ""}
                         for r in rows]
    finally:
        conn.close()
    return result


def _load_personnel(db_path):
    """回傳在職人員清單 [(staff_id, staff_name), ...]，按 sort_order。"""
    conn = getConn(db_path)
    try:
        return conn.execute(
            "SELECT staff_id, staff_name FROM Ref_Personnel "
            "WHERE is_active=1 ORDER BY sort_order"
        ).fetchall()
    finally:
        conn.close()


def count_unissued(db_path):
    """快速計算未發文筆數，回傳 (crim_count, gen_count)。供列印頁顯示計數用。"""
    conn = getConn(db_path)
    try:
        crim = conn.execute(
            "SELECT COUNT(*) FROM Document_Criminal "
            "WHERE (report_date IS NULL OR report_date='') "
            "  AND subject_summary IS NOT NULL AND subject_summary != ''"
        ).fetchone()[0]
        gen = conn.execute(
            "SELECT COUNT(*) FROM Document_General "
            "WHERE (report_date IS NULL OR report_date='') "
            "  AND subject IS NOT NULL AND subject != ''"
        ).fetchone()[0]
        return crim, gen
    finally:
        conn.close()


class _DocTable(QTableWidget):
    """單側（刑案或一般）的結算清單表格。"""

    HEADERS = ["✓", "編號", "承辦人", "主旨"]
    COL_CHK, COL_ID, COL_PROC, COL_SUBJ = 0, 1, 2, 3

    def __init__(self, parent=None):
        super().__init__(0, 4, parent)
        self.setHorizontalHeaderLabels(self.HEADERS)
        self.verticalHeader().setVisible(False)
        self.setSelectionMode(QAbstractItemView.NoSelection)
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.setFocusPolicy(Qt.NoFocus)
        hdr = self.horizontalHeader()
        hdr.setSectionResizeMode(self.COL_CHK,  QHeaderView.Fixed)
        hdr.setSectionResizeMode(self.COL_ID,   QHeaderView.Fixed)
        hdr.setSectionResizeMode(self.COL_PROC, QHeaderView.Fixed)
        hdr.setSectionResizeMode(self.COL_SUBJ, QHeaderView.Stretch)
        self.setColumnWidth(self.COL_CHK,  32)
        self.setColumnWidth(self.COL_ID,   60)
        self.setColumnWidth(self.COL_PROC, 120)
        self.setRowHeight(0, 32)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        # 滾輪攔截（踩雷表 #3：滾輪事件在 viewport）
        self._wheel_filter = _WheelFilter(self)
        self.viewport().installEventFilter(self._wheel_filter)

    def _make_chk_widget(self, checked=True):
        """建一個置中的 QCheckBox 容器（視覺用，列點擊才觸發 toggle）。"""
        cont = QWidget()
        cont.setStyleSheet("background: transparent;")
        hl = QHBoxLayout(cont)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setAlignment(Qt.AlignCenter)
        cb = QCheckBox()
        cb.setChecked(checked)
        cb.setAttribute(Qt.WA_TransparentForMouseEvents)  # 滑鼠事件交給列點擊
        cb.setFocusPolicy(Qt.NoFocus)
        hl.addWidget(cb)
        return cont

    def populate(self, rows):
        self.setRowCount(0)
        for r in rows:
            pos = self.rowCount()
            self.insertRow(pos)
            self.setRowHeight(pos, 32)
            # 勾選欄
            self.setCellWidget(pos, self.COL_CHK, self._make_chk_widget(True))
            # 編號
            id_item = QTableWidgetItem(str(r["doc_id"]))
            id_item.setTextAlignment(Qt.AlignCenter)
            self.setItem(pos, self.COL_ID, id_item)
            # 承辦人
            proc_item = QTableWidgetItem(str(r["processor"]))
            proc_item.setTextAlignment(Qt.AlignCenter)
            self.setItem(pos, self.COL_PROC, proc_item)
            # 主旨（截斷 + tooltip）
            subj = str(r["subject"])
            subj_item = QTableWidgetItem(subj)
            subj_item.setToolTip(subj)
            self.setItem(pos, self.COL_SUBJ, subj_item)

    def _row_checked(self, row):
        cont = self.cellWidget(row, self.COL_CHK)
        if not cont:
            return False
        cb = cont.findChild(QCheckBox)
        return cb.isChecked() if cb else False

    def toggle_row(self, row):
        cont = self.cellWidget(row, self.COL_CHK)
        if not cont:
            return
        cb = cont.findChild(QCheckBox)
        if not cb:
            return
        checked = not cb.isChecked()
        cb.setChecked(checked)
        gray = _GRAY if not checked else None
        for c in range(1, self.columnCount()):   # col 0 是 widget，跳過
            it = self.item(row, c)
            if it:
                it.setForeground(gray if gray else QColor("#000000"))

    def checked_ids(self):
        # ⚠️ 不看 isRowHidden：過濾只是「找列」的輔助，勾選狀態才是結算範圍。
        # 若排除隱藏列，使用者打了過濾字直接按確認會把「隱藏但仍勾選」的公文
        # 靜默漏結，且不計入「排除 N 筆」——將結算＋排除必須恆等於總筆數。
        ids = []
        for r in range(self.rowCount()):
            if self._row_checked(r):
                id_item = self.item(r, self.COL_ID)
                if id_item:
                    ids.append(id_item.text())
        return ids

    def excluded_ids(self):
        ids = []
        for r in range(self.rowCount()):
            if not self._row_checked(r):
                id_item = self.item(r, self.COL_ID)
                if id_item:
                    ids.append(id_item.text())
        return ids

    def apply_filter(self, kw):
        kw = kw.strip().lower()
        for r in range(self.rowCount()):
            if not kw:
                self.setRowHidden(r, False)
                continue
            match = False
            for c in (self.COL_ID, self.COL_PROC, self.COL_SUBJ):
                it = self.item(r, c)
                if it and kw in it.text().lower():
                    match = True
                    break
            self.setRowHidden(r, not match)

    def checked_count(self):
        """勾選筆數（不受過濾影響，與 checked_ids 同語意，供底部計數）。"""
        return sum(1 for r in range(self.rowCount()) if self._row_checked(r))


class _WheelFilter(QObject):
    def __init__(self, table):
        super().__init__(table)
        self._table = table

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Wheel:
            sb = self._table.verticalScrollBar()
            if sb:
                sb.setValue(sb.value() - event.angleDelta().y() // 40)
            return True
        return False


class SettleDialog(QDialog):

    def __init__(self, db_path, parent=None):
        super().__init__(parent)
        self.db_path = db_path
        self.setWindowTitle("結算發文")
        self.setMinimumWidth(1000)
        self.setMinimumHeight(620)
        self.setStyleSheet(_DLG_SS)
        self._settled = False
        self._build()
        self._load()

    # ── 建 UI ────────────────────────────────────────────────
    def _build(self):
        root = QVBoxLayout(self)
        root.setSpacing(10)
        root.setContentsMargins(16, 14, 16, 14)

        # ── 第一列：發文日期 + 送文者下拉 ──
        top = QHBoxLayout()
        top.setSpacing(10)

        cap_date = QLabel("發文日期")
        cap_date.setStyleSheet("font-size: 11pt; color: #8e8e93; font-weight: 500;")
        top.addWidget(cap_date)

        chip_date = QLabel(date.today().strftime("%Y/%m/%d"))
        chip_date.setStyleSheet(
            "font-size: 14pt; font-weight: 600; color: #39649a;"
            "background-color: #eef4fb; border: 1px solid #d6e3f0;"
            "border-radius: 13px; padding: 3px 14px;")
        top.addWidget(chip_date)

        top.addSpacing(28)
        cap_sender = QLabel("送文者")
        cap_sender.setStyleSheet("font-size: 11pt; color: #8e8e93; font-weight: 500;")
        top.addWidget(cap_sender)
        self.cmb_sender = QComboBox()
        self.cmb_sender.setMinimumWidth(230)
        top.addWidget(self.cmb_sender)
        top.addStretch()
        root.addLayout(top)

        # ── 第二列：過濾框 ──
        self.edit_kw = QLineEdit()
        self.edit_kw.setPlaceholderText("輸入編號、承辦人或主旨過濾（兩欄同時過濾）")
        self.edit_kw.textChanged.connect(self._on_filter)
        root.addWidget(self.edit_kw)

        # ── 第三列：左右雙欄表格 ──
        tables_frame = QFrame()
        tables_hl = QHBoxLayout(tables_frame)
        tables_hl.setSpacing(12)
        tables_hl.setContentsMargins(0, 0, 0, 0)

        self._tbl_crim = _DocTable()
        self._tbl_gen  = _DocTable()
        self._lbl_crim_title = QLabel("刑案（0 筆）")
        self._lbl_gen_title  = QLabel("一般（0 筆）")
        for lbl in (self._lbl_crim_title, self._lbl_gen_title):
            lbl.setStyleSheet("font-size: 13pt; font-weight: 600; color: #3a3a3c;")

        crim_box = QVBoxLayout()
        crim_box.setSpacing(4)
        crim_box.addWidget(self._lbl_crim_title)
        crim_box.addWidget(self._tbl_crim)
        gen_box = QVBoxLayout()
        gen_box.setSpacing(4)
        gen_box.addWidget(self._lbl_gen_title)
        gen_box.addWidget(self._tbl_gen)

        tables_hl.addLayout(crim_box)
        tables_hl.addLayout(gen_box)
        root.addWidget(tables_frame, 1)

        # 點整列切換勾選
        self._tbl_crim.cellClicked.connect(lambda r, _: self._toggle(self._tbl_crim, r))
        self._tbl_gen.cellClicked.connect(lambda r, _: self._toggle(self._tbl_gen, r))

        # ── 第四列：底部計數 + 按鈕 ──
        bot = QHBoxLayout()
        bot.setSpacing(12)
        self.lbl_count = QLabel("將結算 0 筆（刑案 0／一般 0）｜排除 0 筆")
        self.lbl_count.setStyleSheet("color: #3a3a3c; font-size: 12pt;")
        bot.addWidget(self.lbl_count)
        bot.addStretch()
        self.btn_confirm = QPushButton("確認結算")
        self.btn_cancel  = QPushButton("取消")
        self.btn_cancel.setObjectName("btn_cancel")
        bot.addWidget(self.btn_confirm)
        bot.addWidget(self.btn_cancel)
        root.addLayout(bot)

        self.btn_confirm.clicked.connect(self._on_confirm)
        self.btn_cancel.clicked.connect(self.reject)

    # ── 載入資料 ─────────────────────────────────────────────
    def _load(self):
        data = _load_unissued(self.db_path)
        self._tbl_crim.populate(data["crim"])
        self._tbl_gen.populate(data["gen"])
        nc = len(data["crim"])
        ng = len(data["gen"])
        self._lbl_crim_title.setText(f"刑案（{nc} 筆）")
        self._lbl_gen_title.setText(f"一般（{ng} 筆）")

        personnel = _load_personnel(self.db_path)
        self.cmb_sender.clear()
        self.cmb_sender.addItem("", None)
        for sid, sname in personnel:
            self.cmb_sender.addItem(sname, sid)

        self._refresh_count()

    # ── 事件處理 ─────────────────────────────────────────────
    def _toggle(self, tbl, row):
        tbl.toggle_row(row)
        self._refresh_count()

    def _on_filter(self, kw):
        self._tbl_crim.apply_filter(kw)
        self._tbl_gen.apply_filter(kw)
        self._refresh_count()

    def _refresh_count(self):
        nc = self._tbl_crim.checked_count()
        ng = self._tbl_gen.checked_count()
        excl = (len(self._tbl_crim.excluded_ids())
                + len(self._tbl_gen.excluded_ids()))
        total = nc + ng
        self.lbl_count.setText(
            f"將結算 {total} 筆（刑案 {nc}／一般 {ng}）｜排除 {excl} 筆")

    def _on_confirm(self):
        sender_id = self.cmb_sender.currentData()
        if not sender_id:
            msgWarning("請選擇送文者", "結算前請先選擇送文者。", parent=self)
            return

        crim_ids = self._tbl_crim.checked_ids()
        gen_ids  = self._tbl_gen.checked_ids()
        total    = len(crim_ids) + len(gen_ids)

        if total == 0:
            msgWarning("無可結算項目", "沒有勾選任何公文，無法結算。", parent=self)
            return

        sender_name  = self.cmb_sender.currentText()
        today_str    = date.today().strftime("%Y-%m-%d")
        today_disp   = date.today().strftime("%Y 年 %m 月 %d 日")

        excl_count = len(self._tbl_crim.excluded_ids() + self._tbl_gen.excluded_ids())

        msg = (f"發文日期：{today_disp}\n"
               f"送文者：{sender_name}\n"
               f"將結算 {total} 筆（刑案 {len(crim_ids)}／一般 {len(gen_ids)}）\n"
               f"排除：{excl_count} 筆")

        ok = confirmBox("確認結算", msg,
                        confirm_text="確認結算", cancel_text="取消", parent=self)
        if not ok:
            return

        try:
            conn = getConn(self.db_path)
            try:
                for doc_id in crim_ids:
                    conn.execute(
                        "UPDATE Document_Criminal SET report_date=?, sender_id=? "
                        "WHERE doc_id=?",
                        (today_str, sender_id, doc_id))
                for doc_id in gen_ids:
                    conn.execute(
                        "UPDATE Document_General SET report_date=?, sender_id=? "
                        "WHERE doc_id=?",
                        (today_str, sender_id, doc_id))
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()
        except Exception as e:
            reportError("結算失敗", e, parent=self)
            return

        self._settled = True
        self.accept()

    def settled(self):
        """結算是否成功完成。"""
        return self._settled
