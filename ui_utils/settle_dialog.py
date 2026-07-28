"""
settle_dialog.py — 自助取號模式「結算發文」彈窗

功能：
  - 單一表格列出所有「已取號、未發文」公文（刑案／一般），依 SETTLE_META
    順序分組，組內編號升冪；預設全勾，點整列切換勾選、取消勾選列整行灰掉
  - 類型 chip 過濾（互斥）＋關鍵字過濾（AND 疊加）；兩者只影響顯示、不動勾選
  - 全選核取方塊：三態顯示「顯示中列」全勾/部分/全不勾，點擊只勾/取消顯示中列
  - 底部即時計數（將結算 N 筆｜排除 m 筆）
  - 確認後同一 transaction 逐類別批次 UPDATE：刑案／一般補
    report_date=選定發文日期+sender_id；任一步失敗則 rollback
  - 送文者僅在勾選中含「需送文者」型態時才必填
  - 開放擴充（open-closed）：日後新增類別只需再加一筆 SETTLE_META
"""
from PySide6.QtCore    import Qt, QObject, QEvent, QDate, QRect, Signal
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QComboBox,
    QTableWidget, QTableWidgetItem, QAbstractItemView,
    QHeaderView, QSizePolicy, QFrame, QCheckBox, QWidget, QButtonGroup, QDateEdit,
    QStyle, QStyleOptionButton,
)
from PySide6.QtGui     import QColor

from lib.db_utils    import getConn, loadActivePersonnel
from lib.archive_text import _trimName
from ui_utils.ui_common import (
    BTN_CANCEL, BTN_CONFIRM, confirmBox, msgInfo, msgWarning, reportError,
)
from ui_utils.widgets import setupDateEditToToday

_ORANGE = QColor("#e67e22")
_GRAY   = QColor("#aeaeb2")
_BLACK  = QColor("#000000")

# ── 結算類別 registry（順序即顯示順序；新增類別只加一筆）─────────────
# 每筆：
#   key         內部識別（存入列 UserRole、計數 dict 鍵）
#   label       類型欄顯示文字
#   color       類型欄前景色
#   query       查未發文列 SQL，回三欄 (doc_id, 承辦人, 主旨)
#   update      結算補值 SQL（with_sender 帶 (issue_date, sender_id, doc_id)，否則 (issue_date, doc_id)）
#   with_sender 結算時是否需選送文者（現行三型態皆需；False 分支留給日後不需送文者的型態）
#   strict      rowcount!=1 是否視為併發衝突並整批 rollback（罰單為 True；
#               刑案／一般沿用既有「部分結算」語意，預設 False）
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
        "count_query": (
            "SELECT COUNT(*) FROM Document_Criminal "
            "WHERE (report_date IS NULL OR report_date = '') "
            "  AND subject_summary IS NOT NULL AND subject_summary != ''"
        ),
        "update": ("UPDATE Document_Criminal SET report_date=?, sender_id=? "
                   "WHERE doc_id=? AND (report_date IS NULL OR report_date='') "
                   "AND subject_summary IS NOT NULL AND subject_summary != ''"),
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
        "count_query": (
            "SELECT COUNT(*) FROM Document_General "
            "WHERE (report_date IS NULL OR report_date = '') "
            "  AND subject IS NOT NULL AND subject != ''"
        ),
        "update": ("UPDATE Document_General SET report_date=?, sender_id=? "
                   "WHERE doc_id=? AND (report_date IS NULL OR report_date='') "
                   "AND subject IS NOT NULL AND subject != ''"),
        "with_sender": True,
    },
    {
        "key": "ticket",
        "label": "罰單",
        "color": "#6b4fa3",
        "query": (
            "SELECT doc_id, issuer_name, ticket_no "
            "FROM Document_Ticket_Full "
            "WHERE register_date='' "
            "  AND ticket_no IS NOT NULL AND ticket_no != '' "
            "ORDER BY issuer_sort_order, ticket_no COLLATE NOCASE"
        ),
        "count_query": (
            "SELECT COUNT(*) FROM Document_Ticket "
            "WHERE register_date='' "
            "  AND ticket_no IS NOT NULL AND ticket_no != ''"
        ),
        "update": ("UPDATE Document_Ticket SET register_date=?, sender_id=? "
                   "WHERE doc_id=? AND register_date=''"),
        "with_sender": True,
        # 罰單三態嚴格（'' 唯一代表未發文，NULL＝軟刪除），rowcount!=1 即代表他機
        # 已搶先發文或刪除；不比照刑案／一般靜默略過，而是整批 rollback。
        "strict": True,
    },
)

_META_BY_KEY = {m["key"]: m for m in SETTLE_META}

_SURFACE_SS = """
QDialog, QWidget {
    background-color: #ffffff;
    color: #000000;
}
"""

_TABLE_SS = """
QTableWidget {
    background-color: #ffffff; color: #1c1c1e;
    border: 1px solid #d1d1d6; gridline-color: #e5e5ea;
}
QTableWidget::item { padding: 2px 4px; }
QTableWidget::item:hover { background-color: transparent; }
QHeaderView::section {
    background-color: #f2f2f7; color: #3a3a3c;
    padding: 4px 6px; border: none;
    border-right: 1px solid #e5e5ea;
    border-bottom: 1px solid #d1d1d6;
    font-size: 13pt; font-weight: 600;
}
QCheckBox::indicator:indeterminate {
    background-color: #c6d3e2; border-color: #8fa8c8;
}
"""

_CHIP_SS = """
QPushButton#chip {
    background-color: #eef2f7; color: #3a3a3c;
    border: 1px solid #d1d9e3; border-radius: 13px;
    padding: 4px 14px; font-weight: 500;
}
QPushButton#chip:hover   { background-color: #e0e7f0; }
QPushButton#chip:checked {
    background-color: #4977b1; color: #ffffff; border-color: #4977b1;
}
"""


def load_unissued(db_path):
    """逐 SETTLE_META 查未發文列，回傳 {key: [rows]}。
    每筆為 dict(doc_id, processor, subject)；processor 已去 `-NN` 後綴
    （比照敘獎／罰單登錄頁顯示，`_trimName`），資料庫仍存原值不受影響。
    純 SQL，可單測。"""
    result = {m["key"]: [] for m in SETTLE_META}
    conn = getConn(db_path)
    try:
        for meta in SETTLE_META:
            rows = conn.execute(meta["query"]).fetchall()
            result[meta["key"]] = [
                {"doc_id": r[0], "processor": _trimName(r[1]), "subject": r[2] or ""}
                for r in rows
            ]
    finally:
        conn.close()
    return result


def count_unissued(db_path):
    """以各類別主表的 COUNT 查未發文筆數，回傳 {key: int}。"""
    result = {m["key"]: 0 for m in SETTLE_META}
    conn = getConn(db_path)
    try:
        for meta in SETTLE_META:
            result[meta["key"]] = conn.execute(meta["count_query"]).fetchone()[0]
    finally:
        conn.close()
    return result


def visible_chip_keys(modes, counts):
    """回傳自助模式已啟用或仍有未發文資料的類型 chip key 集合。"""
    return {
        meta["key"]
        for meta in SETTLE_META
        if modes.get(meta["key"], False) or counts.get(meta["key"], 0) > 0
    }


def settle_entry_visible(db_path, counts=None):
    """判斷指定資料庫是否應顯示結算發文入口。"""
    from lib.db_utils import anySelfServiceMode

    try:
        if anySelfServiceMode(db_path):
            return True
        if counts is None:
            counts = count_unissued(db_path)
        return sum(counts.values()) > 0
    except Exception:
        return False


class SettlementConflict(Exception):
    """結算時偵測到 `strict` 型態已由他機搶先發文或刪除（rowcount!=1）。

    由 `settle_selected()` 內部整批 rollback 後重拋。這是多機共用 DB 下的
    正常併發事件，不是程式異常：呼叫端（對話框）接住後應以 `msgWarning`
    顯示本例外訊息本身（已是白話、含編號），並重新載入清單，而不是走
    `reportError`（`reportError` 會寫 error.log，且顯示成泛用當機訊息）。"""
    pass


def settle_selected(conn, selected, issue_date_str, sender_id):
    """依 SETTLE_META 逐類別批次執行結算 UPDATE，回傳實際結算筆數。

    - `selected`：{key: [doc_id, ...]}（通常為 `_DocTable.checked_by_key()` 結果）
    - 單一 transaction：成功則 `conn.commit()`；任何例外（含 `SettlementConflict`）
      一律 `conn.rollback()` 後重拋，交易邊界完全由本函式持有，呼叫端不得自行
      commit／rollback，也不得針對特定 key 另開分支——擴充新型態只需在
      `SETTLE_META` 加一筆（可選 `strict=True`）。
    - 非 `strict` 型態沿用既有「部分結算」語意：他機已搶先發文/刪除的列
      （rowcount=0）靜默略過，不影響其餘列結算，也不 rollback。
    - `strict` 型態（目前為罰單）：rowcount!=1 視為併發衝突，拋
      `SettlementConflict`，觸發整批 rollback（含已寫入但尚未 commit 的
      刑案／一般更新）。
    """
    try:
        settled_n = 0
        for meta in SETTLE_META:
            for doc_id in selected.get(meta["key"], []):
                if meta["with_sender"]:
                    cur = conn.execute(meta["update"], (issue_date_str, sender_id, doc_id))
                else:
                    cur = conn.execute(meta["update"], (issue_date_str, doc_id))
                if meta.get("strict") and cur.rowcount != 1:
                    raise SettlementConflict(
                        f"{meta['label']}（編號 {doc_id}）已由其他電腦發文或刪除，"
                        "本次結算已全部取消，請重新開啟結算視窗。")
                settled_n += cur.rowcount
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return settled_n


class _CheckableHeader(QHeaderView):
    """在第一欄 section 內原生繪製三態核取方塊的表頭。"""

    clicked = Signal(bool)

    def __init__(self, orientation, parent=None):
        super().__init__(orientation, parent)
        self._check_state = Qt.Unchecked
        # 只借用 QCheckBox 的 theme metrics／繪製器，不顯示也不疊在表頭上。
        # 如此表頭與資料列 indicator 的尺寸、顏色仍完全一致。
        self._indicator_style = QCheckBox()
        self._indicator_style.setStyleSheet("QCheckBox { spacing: 0px; }")
        self.setSectionsClickable(True)

    def checkState(self):
        return self._check_state

    def setCheckState(self, state):
        if self._check_state == state:
            return
        self._check_state = state
        self.updateSection(0)

    def _section_rect(self, logical_index):
        return QRect(
            self.sectionViewportPosition(logical_index),
            0,
            self.sectionSize(logical_index),
            self.height(),
        )

    def indicatorRect(self, logical_index=0):
        """回傳 indicator 在 header viewport 內的實際繪製範圍。"""
        section_rect = self._section_rect(logical_index)
        option = QStyleOptionButton()
        option.initFrom(self._indicator_style)
        native_rect = self._indicator_style.style().subElementRect(
            QStyle.SE_CheckBoxIndicator, option, self._indicator_style)
        indicator_rect = QRect(0, 0, native_rect.width(), native_rect.height())
        indicator_rect.moveCenter(section_rect.center())
        return indicator_rect

    def paintSection(self, painter, rect, logical_index):
        super().paintSection(painter, rect, logical_index)
        if logical_index != 0:
            return

        option = QStyleOptionButton()
        option.initFrom(self._indicator_style)
        option.rect = self.indicatorRect(logical_index)
        option.state &= ~(
            QStyle.State_On | QStyle.State_Off | QStyle.State_NoChange)
        if self._check_state == Qt.Checked:
            option.state |= QStyle.State_On
        elif self._check_state == Qt.PartiallyChecked:
            option.state |= QStyle.State_NoChange
        else:
            option.state |= QStyle.State_Off
        self._indicator_style.style().drawPrimitive(
            QStyle.PE_IndicatorCheckBox, option, painter,
            self._indicator_style)

    def mouseReleaseEvent(self, event):
        if (event.button() == Qt.LeftButton
                and self.logicalIndexAt(event.position().toPoint()) == 0):
            self.clicked.emit(self._check_state != Qt.Checked)
            event.accept()
            return
        super().mouseReleaseEvent(event)


class _DocTable(QTableWidget):
    """單一結算清單表格（刑案／一般混列，依 SETTLE_META 分組）。"""

    HEADERS = ["", "類型", "編號", "承辦人", "主旨"]
    COL_CHK, COL_TYPE, COL_ID, COL_PROC, COL_SUBJ = 0, 1, 2, 3, 4

    def __init__(self, parent=None):
        super().__init__(0, 5, parent)
        self.setStyleSheet(_TABLE_SS)
        self.setHorizontalHeader(_CheckableHeader(Qt.Horizontal, self))
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
        # 保留 SettleDialog 對 chk_all 的三態／clicked 使用契約；實體就是表頭，
        # 不再於 header viewport 上疊加 QWidget/QCheckBox。
        self.chk_all = hdr

    def _make_chk_widget(self, checked=True):
        """建一個置中的 QCheckBox 容器（視覺用，列點擊才觸發 toggle）。"""
        cont = QWidget()
        cont.setStyleSheet("background: transparent;")
        hl = QHBoxLayout(cont)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setAlignment(Qt.AlignCenter)
        cb = QCheckBox()
        cb.setStyleSheet("QCheckBox { spacing: 0px; }")
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
        self.setStyleSheet(_SURFACE_SS)
        self._settled = False
        self._settled_date = None
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
        cap_date.setStyleSheet("color: #8e8e93; font-weight: 500;")
        top.addWidget(cap_date)

        self.issue_date = QDateEdit()
        self.issue_date.setDate(QDate.currentDate())
        self.issue_date.setDisplayFormat("yyyy-MM-dd")
        self.issue_date.setCalendarPopup(True)
        self.issue_date.setMinimumWidth(220)
        setupDateEditToToday(self.issue_date)
        top.addWidget(self.issue_date)

        top.addSpacing(28)
        cap_sender = QLabel("送文者")
        cap_sender.setStyleSheet("color: #8e8e93; font-weight: 500;")
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
        chip_all.setStyleSheet(_CHIP_SS)
        chip_all.setCheckable(True)
        chip_all.setChecked(True)
        chip_all.setCursor(Qt.PointingHandCursor)
        self._chips["all"] = chip_all
        self._chip_group.addButton(chip_all)
        chip_row.addWidget(chip_all)
        for meta in SETTLE_META:
            b = QPushButton(f"{meta['label']} 0")
            b.setObjectName("chip")
            b.setStyleSheet(_CHIP_SS)
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
        self.lbl_count.setStyleSheet("color: #3a3a3c;")
        bot.addWidget(self.lbl_count)
        bot.addStretch()
        self.btn_confirm = QPushButton("確認結算")
        self.btn_cancel  = QPushButton("取消")
        self.btn_confirm.setStyleSheet(BTN_CONFIRM)
        self.btn_cancel.setStyleSheet(BTN_CANCEL)
        bot.addWidget(self.btn_confirm)
        bot.addWidget(self.btn_cancel)
        root.addLayout(bot)

        self.btn_confirm.clicked.connect(self._on_confirm)
        self.btn_cancel.clicked.connect(self.reject)

    # ── 載入資料 ─────────────────────────────────────────────
    def _load(self):
        data = load_unissued(self.db_path)
        self._tbl.populate(data)
        self._update_chip_labels()

        personnel, _alias = loadActivePersonnel(self.db_path)
        self.cmb_sender.clear()
        self.cmb_sender.addItem("", None)
        for sid, sname, _so in personnel:
            self.cmb_sender.addItem(sname, sid)

        # 程式性 setChecked 不會發出 buttonClicked，必須緊接重套過濾條件。
        self._apply_filters()

    def _visible_keys(self):
        """目前該出現的類型 key（自助模式開啟或仍有未發文殘留）。

        chip、底部計數與確認訊息共用同一份判斷：只開罰單的所裡不該在任何一處
        看到「刑案 0／一般 0」。
        """
        from lib.db_utils import isSelfServiceMode

        counts = self._tbl.type_counts()
        modes = {
            meta["key"]: isSelfServiceMode(self.db_path, meta["key"])
            for meta in SETTLE_META
        }
        return visible_chip_keys(modes, counts)

    def _count_parts(self, counts):
        """「刑案 3／罰單 1」這段文字；隱藏的類型不列入。"""
        return "／".join(f"{m['label']} {counts[m['key']]}"
                         for m in SETTLE_META if m["key"] in self._visible_keys())

    def _update_chip_labels(self):
        counts = self._tbl.type_counts()
        visible = self._visible_keys()
        for meta in SETTLE_META:
            chip = self._chips[meta["key"]]
            chip.setVisible(meta["key"] in visible)
            if meta["key"] not in visible and chip.isChecked():
                self._chips["all"].setChecked(True)
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
        parts = self._count_parts(counts)
        self.lbl_count.setText(
            (f"將結算 {total} 筆（{parts}）｜排除 {excl} 筆" if parts
             else f"將結算 {total} 筆｜排除 {excl} 筆"))

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
        issue_date = self.issue_date.date()
        issue_date_str = issue_date.toString("yyyy-MM-dd")
        issue_date_disp = issue_date.toString("yyyy 年 MM 月 dd 日")
        excl_count  = self._tbl.excluded_count()
        parts = self._count_parts(counts)

        msg_lines = [f"發文日期：{issue_date_disp}"]
        if need_sender:
            msg_lines.append(f"送文者：{sender_name}")
        msg_lines.append(f"將結算 {total} 筆（{parts}）" if parts
                         else f"將結算 {total} 筆")
        msg_lines.append(f"排除：{excl_count} 筆")
        msg = "\n".join(msg_lines)

        ok = confirmBox("確認結算", msg,
                        confirm_text="確認結算", cancel_text="取消", parent=self)
        if not ok:
            return

        try:
            conn = getConn(self.db_path)
            try:
                settled_n = settle_selected(conn, by, issue_date_str, sender_id)
            finally:
                conn.close()
        except SettlementConflict as e:
            # 多機共用 DB 下的正常併發事件，不是程式異常：顯示白話訊息、
            # 重載清單讓使用者看到最新狀態，不寫 error.log
            msgWarning("結算衝突", str(e), parent=self)
            self._load()
            return
        except Exception as e:
            reportError("結算失敗", e, parent=self)
            return

        if settled_n == 0:
            msgWarning(
                "沒有公文完成結算",
                "勾選的公文在確認前已由其他電腦發文或刪除，"
                "沒有任何公文完成結算，請確認最新清單後再試。",
                parent=self)
            self._load()
            return

        skipped = total - settled_n
        if skipped > 0:
            msgInfo("部分公文未結算",
                    f"有 {skipped} 筆公文在結算前已由其他電腦發文或刪除，本次未變動；"
                    f"實際結算 {settled_n} 筆。")

        self._settled = True
        self._settled_date = QDate(issue_date)
        self.accept()

    def settled(self):
        """結算是否成功完成。"""
        return self._settled

    def settledDate(self):
        """回傳成功結算時實際寫入的日期快照；未成功則為 None。"""
        return QDate(self._settled_date) if self._settled_date is not None else None
