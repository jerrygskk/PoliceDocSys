"""
settle_dialog.py — 自助取號模式「結算發文」彈窗

功能：
  - 單一表格列出所有「已取號、未發文」公文（刑案／一般），依 SETTLE_META
    順序分組，組內編號升冪；預設全勾，點整列切換勾選、取消勾選列整行灰掉
  - 類型 chip 過濾（互斥）＋關鍵字過濾（AND 疊加）；兩者只影響顯示、不動勾選
  - 全選核取方塊：三態顯示「顯示中列」全勾/部分/全不勾，點擊只勾/取消顯示中列
  - 底部即時計數（將結算 N 筆｜排除 m 筆）
  - 確認後同一 transaction 逐類別批次 UPDATE：刑案／一般補
    report_date=今日+sender_id；任一步失敗則 rollback
  - 送文者僅在勾選中含「需送文者」型態時才必填
  - 開放擴充（open-closed）：日後新增類別只需再加一筆 SETTLE_META
"""
from datetime import date

from PySide6.QtCore    import Qt, QObject, QEvent
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QComboBox,
    QTableWidget, QTableWidgetItem, QAbstractItemView,
    QHeaderView, QSizePolicy, QFrame, QCheckBox, QWidget, QButtonGroup,
)
from PySide6.QtGui     import QColor

from lib.db_utils    import getConn, loadActivePersonnel
from ui_utils.ui_common import msgInfo, msgWarning, confirmBox, reportError

_ORANGE = QColor("#e67e22")
_GRAY   = QColor("#aeaeb2")
_BLACK  = QColor("#000000")

# ── 結算類別 registry（順序即顯示順序；新增類別只加一筆）─────────────
# 每筆：
#   key         內部識別（存入列 UserRole、計數 dict 鍵）
#   label       類型欄顯示文字
#   color       類型欄前景色
#   query       查未發文列 SQL，回三欄 (doc_id, 承辦人, 主旨)
#   update      結算補值 SQL（with_sender 帶 (today, sender_id, doc_id)，否則 (today, doc_id)）
#   with_sender 結算時是否需選送文者（現行兩型態皆需；False 分支留給日後不需送文者的型態）
SETTLE_META = (
    {
        "key": "crim",
        "label": "刑案",
        "color": "#993c1d",
        "query": (
            "SELECT c.doc_id, COALESCE(p.staff_name, c.processor_id) AS processor, "
            "       c.subject_summary AS subject "
            "FROM Document_Criminal c "
            "LEFT JOIN Ref_Personnel p ON c.processor_id = p.staff_id "
            "WHERE (c.report_date IS NULL OR c.report_date = '') "
            "  AND c.subject_summary IS NOT NULL AND c.subject_summary != '' "
            "ORDER BY c.doc_id"
        ),
        "update": ("UPDATE Document_Criminal SET report_date=?, sender_id=? "
                   "WHERE doc_id=? AND (report_date IS NULL OR report_date='')"),
        "with_sender": True,
    },
    {
        "key": "gen",
        "label": "一般",
        "color": "#185fa5",
        "query": (
            "SELECT g.doc_id, COALESCE(p.staff_name, g.processor_id) AS processor, "
            "       g.subject "
            "FROM Document_General g "
            "LEFT JOIN Ref_Personnel p ON g.processor_id = p.staff_id "
            "WHERE (g.report_date IS NULL OR g.report_date = '') "
            "  AND g.subject IS NOT NULL AND g.subject != '' "
            "ORDER BY g.doc_id"
        ),
        "update": ("UPDATE Document_General SET report_date=?, sender_id=? "
                   "WHERE doc_id=? AND (report_date IS NULL OR report_date='')"),
        "with_sender": True,
    },
)

_META_BY_KEY = {m["key"]: m for m in SETTLE_META}

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
QCheckBox::indicator:indeterminate {
    background-color: #c6d3e2; border-color: #8fa8c8;
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
QPushButton#chip {
    background-color: #eef2f7; color: #3a3a3c;
    border: 1px solid #d1d9e3; border-radius: 13px;
    padding: 4px 14px; font-size: 12pt; font-weight: 500;
}
QPushButton#chip:hover   { background-color: #e0e7f0; }
QPushButton#chip:checked {
    background-color: #4977b1; color: #ffffff; border-color: #4977b1;
}
"""


def _load_unissued(db_path):
    """逐 SETTLE_META 查未發文列，回傳 {key: [rows]}。
    每筆為 dict(doc_id, processor, subject)。純 SQL，可單測。"""
    result = {m["key"]: [] for m in SETTLE_META}
    conn = getConn(db_path)
    try:
        for meta in SETTLE_META:
            rows = conn.execute(meta["query"]).fetchall()
            result[meta["key"]] = [
                {"doc_id": r[0], "processor": r[1] or "", "subject": r[2] or ""}
                for r in rows
            ]
    finally:
        conn.close()
    return result


def count_unissued(db_path):
    """快速計算各類別未發文筆數，回傳 {key: int}。供列印頁顯示計數用。"""
    return {k: len(v) for k, v in _load_unissued(db_path).items()}


class _DocTable(QTableWidget):
    """單一結算清單表格（刑案／一般混列，依 SETTLE_META 分組）。"""

    HEADERS = ["", "類型", "編號", "承辦人", "主旨"]
    COL_CHK, COL_TYPE, COL_ID, COL_PROC, COL_SUBJ = 0, 1, 2, 3, 4

    def __init__(self, parent=None):
        super().__init__(0, 5, parent)
        self.setHorizontalHeaderLabels(self.HEADERS)
        self.verticalHeader().setVisible(False)
        self.setSelectionMode(QAbstractItemView.NoSelection)
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.setFocusPolicy(Qt.NoFocus)
        hdr = self.horizontalHeader()
        hdr.setSectionResizeMode(self.COL_CHK,  QHeaderView.Fixed)
        hdr.setSectionResizeMode(self.COL_TYPE, QHeaderView.Fixed)
        hdr.setSectionResizeMode(self.COL_ID,   QHeaderView.Fixed)
        hdr.setSectionResizeMode(self.COL_PROC, QHeaderView.Fixed)
        hdr.setSectionResizeMode(self.COL_SUBJ, QHeaderView.Stretch)
        self.setColumnWidth(self.COL_CHK,  32)
        self.setColumnWidth(self.COL_TYPE, 64)
        self.setColumnWidth(self.COL_ID,   64)
        self.setColumnWidth(self.COL_PROC, 120)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        # 滾輪攔截（踩雷表 #3：滾輪事件在 viewport）
        self._wheel_filter = _WheelFilter(self)
        self.viewport().installEventFilter(self._wheel_filter)
        # 全選核取方塊：直接放在表頭勾選欄上（免文字說明，tooltip 補充）。
        # 與列內勾選框同一置中方式（容器＋AlignCenter，容器鋪滿該欄），
        # 確保與資料列的勾選框水平垂直皆對齊；勿改回 sizeHint 手算位移
        # （QCheckBox 無文字時 sizeHint 含 spacing 留白，indicator 會偏左上）。
        self._chk_all_cont = QWidget(hdr)
        self._chk_all_cont.setStyleSheet("background: transparent;")
        _hl = QHBoxLayout(self._chk_all_cont)
        _hl.setContentsMargins(0, 0, 0, 0)
        _hl.setAlignment(Qt.AlignCenter)
        self.chk_all = QCheckBox()
        self.chk_all.setTristate(True)
        self.chk_all.setFocusPolicy(Qt.NoFocus)
        _hl.addWidget(self.chk_all)
        hdr.installEventFilter(self)
        hdr.sectionResized.connect(lambda *_: self._place_header_chk())
        self._place_header_chk()

    def _place_header_chk(self):
        hdr = self.horizontalHeader()
        self._chk_all_cont.setGeometry(
            hdr.sectionViewportPosition(self.COL_CHK), 0,
            self.columnWidth(self.COL_CHK), hdr.height())

    def eventFilter(self, obj, event):
        if (obj is self.horizontalHeader()
                and event.type() in (QEvent.Resize, QEvent.Show)):
            self._place_header_chk()
        return super().eventFilter(obj, event)

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

    def populate(self, data):
        """data = {key: [dict(doc_id, processor, subject), ...]}；依 SETTLE_META
        順序分組建列，組內順序即 query 回傳順序（編號升冪）。"""
        self.setRowCount(0)
        for meta in SETTLE_META:
            key = meta["key"]
            for r in data.get(key, []):
                pos = self.rowCount()
                self.insertRow(pos)
                self.setRowHeight(pos, 32)
                # 勾選欄
                self.setCellWidget(pos, self.COL_CHK, self._make_chk_widget(True))
                # 類型（該 meta 色前景）
                type_item = QTableWidgetItem(meta["label"])
                type_item.setTextAlignment(Qt.AlignCenter)
                type_item.setForeground(QColor(meta["color"]))
                self.setItem(pos, self.COL_TYPE, type_item)
                # 編號（Qt.UserRole 存 key）
                id_item = QTableWidgetItem(str(r["doc_id"]))
                id_item.setTextAlignment(Qt.AlignCenter)
                id_item.setData(Qt.UserRole, key)
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

    def _row_key(self, row):
        it = self.item(row, self.COL_ID)
        return it.data(Qt.UserRole) if it else None

    def _row_checked(self, row):
        cont = self.cellWidget(row, self.COL_CHK)
        if not cont:
            return False
        cb = cont.findChild(QCheckBox)
        return cb.isChecked() if cb else False

    def _apply_row_color(self, row, checked):
        """勾選 → 類型欄回該 meta 色、其餘黑；取消 → 整列灰。"""
        meta = _META_BY_KEY.get(self._row_key(row), {})
        for c in range(1, self.columnCount()):   # col 0 是 widget，跳過
            it = self.item(row, c)
            if not it:
                continue
            if not checked:
                it.setForeground(_GRAY)
            elif c == self.COL_TYPE:
                it.setForeground(QColor(meta.get("color", "#000000")))
            else:
                it.setForeground(_BLACK)

    def set_row_checked(self, row, checked):
        cont = self.cellWidget(row, self.COL_CHK)
        cb = cont.findChild(QCheckBox) if cont else None
        if not cb:
            return
        cb.setChecked(checked)
        self._apply_row_color(row, checked)

    def toggle_row(self, row):
        self.set_row_checked(row, not self._row_checked(row))

    def checked_by_key(self):
        # ⚠️ 不看 isRowHidden：過濾（關鍵字／類型 chip）只是「找列」的輔助，
        # 勾選狀態才是結算範圍。若排除隱藏列，使用者打了過濾字直接按確認會把
        # 「隱藏但仍勾選」的公文靜默漏結，且不計入「排除 N 筆」——將結算＋排除
        # 必須恆等於總筆數（此不變式絕不能破壞）。
        out = {m["key"]: [] for m in SETTLE_META}
        for r in range(self.rowCount()):
            if self._row_checked(r):
                it = self.item(r, self.COL_ID)
                key = self._row_key(r)
                if it and key in out:
                    out[key].append(it.text())
        return out

    def excluded_count(self):
        return sum(1 for r in range(self.rowCount()) if not self._row_checked(r))

    def type_counts(self):
        """各類別總列數（不受過濾影響），供 chip 標籤。"""
        out = {m["key"]: 0 for m in SETTLE_META}
        for r in range(self.rowCount()):
            key = self._row_key(r)
            if key in out:
                out[key] += 1
        return out

    def apply_filter(self, kw, active_types):
        """套用關鍵字＋類型過濾（AND）；只影響顯示、不動勾選。
        active_types=None 代表全部類型。"""
        kw = (kw or "").strip().lower()
        for r in range(self.rowCount()):
            key = self._row_key(r)
            if active_types is not None and key not in active_types:
                self.setRowHidden(r, True)
                continue
            if not kw:
                self.setRowHidden(r, False)
                continue
            match = False
            for c in (self.COL_TYPE, self.COL_ID, self.COL_PROC, self.COL_SUBJ):
                it = self.item(r, c)
                if it and kw in it.text().lower():
                    match = True
                    break
            self.setRowHidden(r, not match)

    def visible_rows(self):
        return [r for r in range(self.rowCount()) if not self.isRowHidden(r)]


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

        # ── 第二列：類型 chip（全選核取方塊移至表格表頭勾選欄）──
        chip_row = QHBoxLayout()
        chip_row.setSpacing(8)
        self._chip_group = QButtonGroup(self)
        self._chip_group.setExclusive(True)
        self._chips = {}
        chip_all = QPushButton("全部 0")
        chip_all.setObjectName("chip")
        chip_all.setCheckable(True)
        chip_all.setChecked(True)
        chip_all.setCursor(Qt.PointingHandCursor)
        self._chips["all"] = chip_all
        self._chip_group.addButton(chip_all)
        chip_row.addWidget(chip_all)
        for meta in SETTLE_META:
            b = QPushButton(f"{meta['label']} 0")
            b.setObjectName("chip")
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            self._chips[meta["key"]] = b
            self._chip_group.addButton(b)
            chip_row.addWidget(b)
        chip_row.addStretch()
        self._chip_group.buttonClicked.connect(lambda _b: self._apply_filters())
        root.addLayout(chip_row)

        # ── 第三列：關鍵字過濾框 ──
        self.edit_kw = QLineEdit()
        self.edit_kw.setPlaceholderText("輸入類型、編號、承辦人或主旨過濾")
        self.edit_kw.textChanged.connect(lambda _t: self._apply_filters())
        root.addWidget(self.edit_kw)

        # ── 第四列：單一表格 ──
        tables_frame = QFrame()
        tables_vl = QVBoxLayout(tables_frame)
        tables_vl.setSpacing(4)
        tables_vl.setContentsMargins(0, 0, 0, 0)
        self._tbl = _DocTable()
        tables_vl.addWidget(self._tbl)
        root.addWidget(tables_frame, 1)

        # 點整列切換勾選；表頭全選核取方塊
        self._tbl.cellClicked.connect(self._toggle)
        self.chk_all = self._tbl.chk_all
        self.chk_all.clicked.connect(self._on_selectall_clicked)

        # ── 第五列：底部計數 + 按鈕 ──
        bot = QHBoxLayout()
        bot.setSpacing(12)
        self.lbl_count = QLabel("將結算 0 筆｜排除 0 筆")
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
        self._tbl.populate(data)
        self._update_chip_labels()

        personnel, _alias = loadActivePersonnel(self.db_path)
        self.cmb_sender.clear()
        self.cmb_sender.addItem("", None)
        for sid, sname, _so in personnel:
            self.cmb_sender.addItem(sname, sid)

        self._apply_filters()

    def _update_chip_labels(self):
        counts = self._tbl.type_counts()
        total = sum(counts.values())
        self._chips["all"].setText(f"全部 {total}")
        for meta in SETTLE_META:
            self._chips[meta["key"]].setText(
                f"{meta['label']} {counts[meta['key']]}")

    # ── 事件處理 ─────────────────────────────────────────────
    def _active_types(self):
        """目前選中的類型 chip → 類型集合；「全部」回 None（不限類型）。"""
        for key, b in self._chips.items():
            if b.isChecked():
                return None if key == "all" else {key}
        return None

    def _apply_filters(self):
        self._tbl.apply_filter(self.edit_kw.text(), self._active_types())
        self._refresh_selectall_state()
        self._refresh_count()

    def _toggle(self, row, _col):
        self._tbl.toggle_row(row)
        self._refresh_selectall_state()
        self._refresh_count()

    def _on_selectall_clicked(self, _checked=False):
        """點全選：顯示中列全勾 → 全部取消；否則 → 全部勾選（隱藏列不動）。"""
        visible = self._tbl.visible_rows()
        all_checked = bool(visible) and all(
            self._tbl._row_checked(r) for r in visible)
        target = not all_checked
        for r in visible:
            if self._tbl._row_checked(r) != target:
                self._tbl.set_row_checked(r, target)
        self._refresh_selectall_state()
        self._refresh_count()

    def _refresh_selectall_state(self):
        """依「顯示中列」勾選比例更新全選三態顯示。"""
        visible = self._tbl.visible_rows()
        checked = sum(1 for r in visible if self._tbl._row_checked(r))
        cb = self.chk_all
        cb.blockSignals(True)
        if not visible or checked == 0:
            cb.setCheckState(Qt.Unchecked)
        elif checked == len(visible):
            cb.setCheckState(Qt.Checked)
        else:
            cb.setCheckState(Qt.PartiallyChecked)
        cb.blockSignals(False)

    def _refresh_count(self):
        by = self._tbl.checked_by_key()
        counts = {k: len(v) for k, v in by.items()}
        total = sum(counts.values())
        excl = self._tbl.excluded_count()
        parts = "／".join(
            f"{m['label']} {counts[m['key']]}" for m in SETTLE_META)
        self.lbl_count.setText(
            f"將結算 {total} 筆（{parts}）｜排除 {excl} 筆")

    def _on_confirm(self):
        by = self._tbl.checked_by_key()
        counts = {k: len(v) for k, v in by.items()}
        total = sum(counts.values())

        if total == 0:
            msgWarning("無可結算項目", "沒有勾選任何公文，無法結算。", parent=self)
            return

        # 送文者僅在勾選中含「需送文者」型態時才必填（現行三型態皆是）
        need_sender = any(counts[m["key"]] > 0
                          for m in SETTLE_META if m["with_sender"])
        sender_id = self.cmb_sender.currentData()
        if need_sender and not sender_id:
            msgWarning("請選擇送文者", "結算前請先選擇送文者。", parent=self)
            return

        sender_name = self.cmb_sender.currentText()
        today_str   = date.today().strftime("%Y-%m-%d")
        today_disp  = date.today().strftime("%Y 年 %m 月 %d 日")
        excl_count  = self._tbl.excluded_count()
        parts = "／".join(
            f"{m['label']} {counts[m['key']]}" for m in SETTLE_META)

        msg_lines = [f"發文日期：{today_disp}"]
        if need_sender:
            msg_lines.append(f"送文者：{sender_name}")
        msg_lines.append(f"將結算 {total} 筆（{parts}）")
        msg_lines.append(f"排除：{excl_count} 筆")
        msg = "\n".join(msg_lines)

        ok = confirmBox("確認結算", msg,
                        confirm_text="確認結算", cancel_text="取消", parent=self)
        if not ok:
            return

        try:
            conn = getConn(self.db_path)
            try:
                settled_n = 0
                for meta in SETTLE_META:
                    ids = by[meta["key"]]
                    for doc_id in ids:
                        if meta["with_sender"]:
                            cur = conn.execute(meta["update"],
                                               (today_str, sender_id, doc_id))
                        else:
                            cur = conn.execute(meta["update"], (today_str, doc_id))
                        settled_n += cur.rowcount
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()
        except Exception as e:
            reportError("結算失敗", e, parent=self)
            return

        skipped = total - settled_n
        if skipped > 0:
            msgInfo("部分公文未結算",
                    f"有 {skipped} 筆公文在結算前已由其他電腦發文或刪除，本次未變動；"
                    f"實際結算 {settled_n} 筆。")

        self._settled = True
        self.accept()

    def settled(self):
        """結算是否成功完成。"""
        return self._settled
