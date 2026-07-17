from PySide6.QtCore import Qt, QTimer, QUrl, QSize, QEvent, QObject
from PySide6.QtWidgets import (
    QVBoxLayout, QTabWidget, QComboBox, QLineEdit, QPushButton,
    QLabel, QTableWidget, QTableWidgetItem, QWidget, QHBoxLayout,
    QAbstractItemView,
)
from PySide6.QtGui import QColor, QIcon, QDesktopServices

from lib.base_tab import BaseTab
from lib.db_utils import (
    getResourcePath,
    resolveArchivedPdf, getSetting, ARCHIVE_ROOT_KEY, softDeleteDoc,
)
from ui_utils import loadUi, msgInfo, msgWarning, msgCritical, confirmBox, reportError
from lib.auth_manager import AuthManager
from ui_utils import (
    setupPreviewTable, autoResizeTable, refreshDeleteBtns, applyLinkStyle,
    TaskEditDialog, CriminalEditDialog, GeneralEditDialog, runWithBusy, preserveScroll,
    LinkCursorFilter,
)
from ui_utils.reward_dialog import RewardEditDialog


class _WatermarkFitter(QObject):
    """貼合浮水印到 viewport：尺寸/顯示變動時，若浮水印正顯示就重新覆滿。

    解決切子頁問題：初次載入時非當前子頁的 viewport size=0，浮水印會縮成
    0×0；切過去（Show/Resize）時在此重新貼合。"""
    def __init__(self, viewport, wm):
        super().__init__(viewport)
        self._wm = wm

    def eventFilter(self, obj, event):
        # 一律重貼尺寸：顯示與否由 _updateFooter 的 show/hide 控制，
        # 隱藏的 widget 重貼尺寸無副作用。不可用 isVisible() 當條件——
        # 切子頁瞬間 Show/Resize 可能早於浮水印可見性傳遞，會被誤跳過。
        if event.type() in (QEvent.Resize, QEvent.Show):
            self._wm.resize(obj.size())
            self._wm.move(0, 0)
        return False  # 不吃事件


# ─────────────────────────────────────────────────────────────
# 切 tab 自動差異更新時，變動列數達此值才跳「更新中」提示（少量重建無感、不閃提示）
_BUSY_ROW_THRESHOLD = 100

# 三張表的欄位定義
#   header  : 表頭顯示文字
#   view_col: View 中的欄位名（用於 SELECT / 搜尋）
#   slim    : True = 精簡模式也顯示；False = 僅完整模式
#   link    : True = 此欄為可點擊編號欄
#   color   : True = 套用狀態顏色（僅交辦單狀態欄）
#   search  : True = 可被關鍵字搜尋（布林欄如紙本/電子檔排除）
#   stretch : True = 此欄自動撐滿剩餘寬度
#   ref_col : True = 值由參照表(人員/部門/案類) join 取得；參照改名後就地刷此欄
# 順序即為顯示由左至右的順序（重要欄在左）。
# ─────────────────────────────────────────────────────────────
TASK_COLS = [
    {"header": "", "delete": True, "slim": True, "w": 32},
    {"header": "編號",     "view_col": "編號",     "slim": True,  "link": True,  "search": True, "w": 64},
    {"header": "承辦人",   "view_col": "所承辦人", "slim": True,  "search": True, "w": 80,  "trim_name": True, "ref_col": True},
    {"header": "交辦事由", "view_col": "交辦事由", "slim": True,  "search": True, "stretch": True, "w": 240},
    {"header": "業務組",   "view_col": "業務組",   "slim": True,  "search": True, "w": 80,  "ref_col": True},
    {"header": "狀態",     "view_col": "狀態",     "slim": True,  "color": True, "search": True, "w": 200},
    {"header": "限辦日期", "view_col": "限辦日期", "slim": True,  "search": True, "w": 140},
    {"header": "發文日期", "view_col": "發文日期", "slim": True,  "search": True, "w": 140},
    {"header": "收文日期", "view_col": "收文日期", "slim": False, "search": True, "w": 140},
    {"header": "收文人員", "view_col": "收文人員", "slim": False, "search": True, "w": 120, "ref_col": True},
    {"header": "送文人員", "view_col": "送文人員", "slim": False, "search": True, "w": 120, "ref_col": True},
    {"header": "紀錄時間", "view_col": "紀錄時間", "slim": False, "search": False, "w": 240, "trunc_sec": True},
]

CRIM_COLS = [
    {"header": "", "delete": True, "slim": True, "w": 32},
    {"header": "編號",        "view_col": "送文編號",    "slim": True,  "link": True,  "search": True, "w": 64},
    {"header": "主承辦人",    "view_col": "主承辦人",    "slim": True,  "search": True, "w": 80,  "trim_name": True, "ref_col": True},
    {"header": "案類",        "view_col": "案類",        "slim": True,  "search": True, "w": 220, "ref_col": True},
    {"header": "嫌疑人/案由", "view_col": "嫌疑人_案由", "slim": True,  "search": True, "stretch": True, "w": 240},
    {"header": "發文分類",    "view_col": "發文分類",    "slim": True,  "search": True, "w": 96},
    {"header": "陳報日期",    "view_col": "陳報日期",    "slim": True,  "search": True, "w": 140},
    {"header": "受理日期",    "view_col": "受理日期",    "slim": True,  "search": True, "w": 140},
    {"header": "送文人員",    "view_col": "送文人員",    "slim": False, "search": True, "w": 120, "ref_col": True},
    {"header": "報案人",      "view_col": "報案人",      "slim": False, "search": True, "w": 130},
    {"header": "受理人",      "view_col": "受理人",      "slim": False, "search": True, "w": 120, "trim_name": True, "ref_col": True},
    {"header": "紙本",        "view_col": "紙本",        "slim": False, "search": False, "w": 56, "bool_col": True},
    {"header": "電子檔",      "view_col": "電子檔",      "slim": False, "search": False, "w": 64, "bool_col": True},
]

GEN_COLS = [
    {"header": "", "delete": True, "slim": True, "w": 32},
    {"header": "編號",     "view_col": "送文編號", "slim": True,  "link": True,  "search": True, "w": 64},
    {"header": "陳報人",   "view_col": "陳報人",   "slim": True,  "search": True, "w": 80,  "trim_name": True, "ref_col": True},
    {"header": "陳報主旨", "view_col": "陳報主旨", "slim": True,  "search": True, "stretch": True, "w": 240},
    {"header": "業務單位", "view_col": "業務單位", "slim": True,  "search": True, "w": 96,  "ref_col": True},
    {"header": "分類",     "view_col": "分類",     "slim": True,  "search": True, "w": 96},
    {"header": "陳報日期", "view_col": "陳報日期", "slim": True,  "search": True, "w": 140},
    {"header": "送文人員", "view_col": "送文人員", "slim": False, "search": True, "w": 120, "ref_col": True},
    {"header": "紙本",     "view_col": "紙本",     "slim": False, "search": False, "w": 56, "bool_col": True},
    {"header": "電子檔",   "view_col": "電子檔",   "slim": False, "search": False, "w": 64, "bool_col": True},
]

REWARD_COLS = [
    {"header": "", "delete": True, "slim": True, "w": 32},
    {"header": "編號", "view_col": "doc_id", "slim": True, "link": True, "search": True, "w": 64},
    {"header": "登錄日期", "view_col": "register_date", "slim": True, "search": True, "w": 140},
    {"header": "敘獎事由", "view_col": "reason", "slim": True, "search": True, "stretch": True, "w": 300},
    {"header": "敘獎人員", "view_col": "recipients", "slim": True, "search": True, "w": 240},
]
BROWSE_KEYS = ("task", "crim", "gen", "reward")
PRELOAD_KEYS = ("task", "crim", "gen")


# 每張表的 View 名、底層表名、底層承辦人欄、View 編號欄、EditDialog
TABLE_META = {
    "task": {
        "cols": TASK_COLS, "view": "View_Task_Full",
        "base": "Document_Task", "proc_fk": "processor_id", "id_col": "編號",
        "dialog": TaskEditDialog,
    },
    "crim": {
        "cols": CRIM_COLS, "view": "View_Criminal_Full",
        "base": "Document_Criminal", "proc_fk": "processor_id", "id_col": "送文編號",
        "dialog": CriminalEditDialog, "archive": True,
    },
    "gen": {
        "cols": GEN_COLS, "view": "View_General_Full",
        "base": "Document_General", "proc_fk": "processor_id", "id_col": "送文編號",
        "dialog": GeneralEditDialog, "archive": True,
    },
    "reward": {
        "cols": REWARD_COLS, "base": "Document_Reward", "id_col": "doc_id",
        "dialog": RewardEditDialog, "raw": True,
        "active_where": "register_date IS NOT NULL", "sort_numeric_desc": True,
    },
}


def queryBrowseRows(conn, key):
    """以既有連線查單表的完整 View 列（dict 列表，含 _proc_active 與歸檔表 _arch_fname）。
    抽成 module 函式，供瀏覽頁主執行緒查詢與啟動 LoadWorker 背景預載共用。
    只用純 sqlite3，不碰 Qt 物件，可安全在背景執行緒呼叫。"""
    meta = TABLE_META[key]
    if meta.get("raw"):
        cur = conn.execute(
            "SELECT doc_id, register_date, reason, recipients, last_modified, "
            "1 AS _proc_active FROM Document_Reward "
            "WHERE register_date IS NOT NULL ORDER BY CAST(doc_id AS INTEGER) DESC")
        names = [d[0] for d in cur.description]
        return [dict(zip(names, row)) for row in cur.fetchall()]
    arch_sel = ", b.is_electronic AS _arch_fname" if meta.get("archive") else ""
    sql = f"""
        SELECT v.*, COALESCE(p.is_active, 1) AS _proc_active{arch_sel}
        FROM {meta['view']} v
        LEFT JOIN {meta['base']} b ON v."{meta['id_col']}" = b.doc_id
        LEFT JOIN Ref_Personnel p ON b.{meta['proc_fk']} = p.staff_id
    """
    cur = conn.execute(sql)
    names = [d[0] for d in cur.description]
    return [dict(zip(names, row)) for row in cur.fetchall()]


def _statusColor(status):
    """交辦單狀態欄顏色，比照陳報頁慣例。"""
    s = status or ""
    if s.startswith("逾期"):
        return QColor("#e74c3c")
    if s.startswith("剩餘") or "今日" in s:
        return QColor("#e67e22")
    if s == "已發文":
        return QColor("#27ae60")
    return None  # 免覆 / 空白 → 預設色


class TabDBBrowse(BaseTab):
    """資料庫瀏覽：交辦單 / 刑案 / 一般陳報，歷史全表瀏覽 + 搜尋。"""

    def setup(self, tab_index):
        tab = self.tab_widget.widget(tab_index)
        if not tab:
            return

        browse_widget = loadUi(getResourcePath("layouts/Layout5.ui"))
        if not browse_widget:
            return

        inner = browse_widget.centralWidget()
        lay = QVBoxLayout(tab)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(inner)
        self._inner = inner

        self.subtabs = inner.findChild(QTabWidget, "browse_subtabs")
        if self.subtabs:
            # 內層子頁籤專屬樣式（只套此 QTabWidget，不動外層大 Tab）：
            # 選中頁籤加底部藍色指示線，與下方白色表格區做出分界。
            self.subtabs.setStyleSheet("""
                QTabWidget#browse_subtabs::pane {
                    border: none;
                }
                QTabWidget#browse_subtabs QTabBar::tab {
                    background-color: transparent;
                    color: #636366;
                    border: none;
                    border-bottom: 2px solid transparent;
                    padding: 8px 18px;
                    margin-right: 4px;
                    font-weight: 500;
                }
                QTabWidget#browse_subtabs QTabBar::tab:selected {
                    color: #8fa8c8;
                    border-bottom: 2px solid #8fa8c8;
                    font-weight: 600;
                }
                QTabWidget#browse_subtabs QTabBar::tab:hover:!selected {
                    color: #3a3a3c;
                }
            """)

        # 每個 key 蒐集自己的元件
        self._ui = {}
        for key in BROWSE_KEYS:
            self._ui[key] = {
                "scope":  inner.findChild(QComboBox, f"{key}_scope"),
                "kw":     inner.findChild(QLineEdit, f"{key}_kw"),
                "search": inner.findChild(QPushButton, f"{key}_search"),
                "full":   inner.findChild(QPushButton, f"{key}_seg_full"),
                "reload": inner.findChild(QPushButton, f"{key}_reload"),
                "table":  inner.findChild(QTableWidget, f"{key}_table"),
                "count":  inner.findChild(QLabel, f"{key}_count"),
                "hint":   inner.findChild(QLabel, f"{key}_hint"),
                "overdue": inner.findChild(QPushButton, f"{key}_overdue"),
            }

        # 歸檔根目錄警示 label（放在 crim/gen filter row 右側，archive_root 空時顯示）
        _ARCH_WARN_SS = ("background-color: #fdecea; color: #c0392b; "
                         "border: 1px solid #e74c3c; border-radius: 8px; "
                         "padding: 8px 12px; font-weight: 600;")
        _ARCH_WARN_TXT = "⚠ 歸檔資料夾未設定，請至設定頁更新"
        self._arch_warn = {}
        for key in ("crim", "gen"):
            lbl = QLabel(_ARCH_WARN_TXT)
            lbl.setStyleSheet(_ARCH_WARN_SS)
            lbl.setVisible(False)
            fl = inner.findChild(QHBoxLayout, f"{key}_filter")
            if fl:
                fl.addWidget(lbl)
            self._arch_warn[key] = lbl

        # 浮水印 QLabel（疊在每張表上）
        self._watermark = {}
        for key in BROWSE_KEYS:
            tbl = self._ui[key]["table"]
            # 唯讀瀏覽：不需選取反白、去點擊焦點黑框（統一為回收筒／操作紀錄的行為）
            tbl.setSelectionMode(QAbstractItemView.NoSelection)
            tbl.setFocusPolicy(Qt.NoFocus)
            wm = QLabel(tbl)
            wm.setAlignment(Qt.AlignCenter)
            wm.setStyleSheet(
                "color:#c7c7cc; font-size:16pt; font-weight:600;"
                "background:transparent;")
            wm.setAttribute(Qt.WA_TransparentForMouseEvents)
            wm.hide()
            self._watermark[key] = wm
            # 切子頁/縮放時，viewport 尺寸改變要重新貼合浮水印
            # （初次載入時非當前子頁的 viewport size=0，否則浮水印縮成 0×0 看不到）
            vp = tbl.viewport()
            fitter = _WatermarkFitter(vp, wm)
            vp.installEventFilter(fitter)
            self._wm_fitters = getattr(self, "_wm_fitters", [])
            self._wm_fitters.append(fitter)   # 存參考防 GC
            # 編號欄滑過顯示手指游標（純 item 頁，零建表成本）
            link_col = next((i for i, c in enumerate(TABLE_META[key]["cols"])
                             if c.get("link")), None)
            if link_col is not None:
                vp.setMouseTracking(True)   # 沒開 tracking 收不到 MouseMove，filter 失效
                lcf = LinkCursorFilter(tbl, link_col)
                vp.installEventFilter(lcf)
                self._link_cursors = getattr(self, "_link_cursors", [])
                self._link_cursors.append(lcf)   # 存參考防 GC

        # 填充範圍下拉、綁定事件
        for key in BROWSE_KEYS:
            self._initScope(key)
            self._bindEvents(key)

        # 初次載入延後到「第一次切到本頁」(on_activated) 才做，並彈「載入中」提示，
        # 避免啟動時即建三表 cellWidget（資料量大時拖慢整個 App 開啟）。
        self._sigs = {}
        self._loaded_keys = set()
        if self.subtabs:
            self.subtabs.currentChanged.connect(self._onBrowseSubtabChanged)

        # 身分切換時即時更新各表的刪除鈕與編號連結可用狀態
        AuthManager.instance().role_changed.connect(self._onRolePerm)

    def _onRolePerm(self, _role=None):
        """身分變更：逐列切換刪除鈕停用/啟用、編號連結可點/純文字。"""
        # 刪除：僅最高權限管理者；編輯（編號連結）：歸檔管理亦可
        can_delete = AuthManager.instance().is_admin()
        can_edit   = AuthManager.instance().is_manager()
        for key in BROWSE_KEYS:
            table = self._ui.get(key, {}).get("table")
            if not table:
                continue
            cols = TABLE_META[key]["cols"]
            del_col  = next((i for i, c in enumerate(cols) if c.get("delete")), None)
            link_col = next((i for i, c in enumerate(cols) if c.get("link")), None)
            order = getattr(self, "_docorder", {}).get(key, [])
            if del_col is not None:
                refreshDeleteBtns(table, can_delete, del_col)
            if link_col is not None:
                for r in range(table.rowCount()):
                    item = table.item(r, link_col)
                    if item is not None:
                        applyLinkStyle(item, can_edit)   # 藍字+底線/還原（單一來源）

    # ── 範圍下拉：全部欄位 + 可搜尋欄位 ──────────────────────
    def _initScope(self, key):
        combo = self._ui[key]["scope"]
        if not combo:
            return
        combo.clear()
        combo.addItem("全部欄位", userData=None)
        for c in TABLE_META[key]["cols"]:
            if c.get("search"):
                combo.addItem(c["header"], userData=c["view_col"])

    def _bindEvents(self, key):
        u = self._ui[key]
        if u["search"]:
            u["search"].clicked.connect(lambda _, k=key: self._applyFilter(k))
        if u["kw"]:
            u["kw"].returnPressed.connect(lambda k=key: self._applyFilter(k))
            # 即時搜尋（防抖 1000ms，打字期間不重算，停手 1 秒才過濾）
            timer = QTimer(u["kw"])
            timer.setSingleShot(True)
            timer.setInterval(1000)
            timer.timeout.connect(lambda k=key: self._applyFilter(k))
            self._ui[key]["_debounce"] = timer
            u["kw"].textChanged.connect(lambda _, t=timer: t.start())
        if u["scope"]:
            u["scope"].currentIndexChanged.connect(lambda _, k=key: self._applyFilter(k))
        if u["full"]:
            u["full"].toggled.connect(lambda _, k=key: self._onToggleFull(k))
            self._styleSegmented(key)
        if u.get("reload"):
            u["reload"].clicked.connect(lambda _=False, k=key: self._forceReload(k))
            self._styleReload(key)
        if u.get("overdue"):
            u["overdue"].toggled.connect(lambda _, k=key: self._applyOverdue(k))
            self._styleOverdue(key)
        # 刪除欄、編號欄（文字型 item）：以 cellClicked 攔截，不建 cellWidget
        del_col  = next((i for i, c in enumerate(TABLE_META[key]["cols"]) if c.get("delete")), None)
        link_col = next((i for i, c in enumerate(TABLE_META[key]["cols"]) if c.get("link")),   None)
        if u["table"]:
            if del_col is not None:
                u["table"].cellClicked.connect(
                    lambda row, col, k=key, dc=del_col: self._onDeleteCell(k, row, col, dc))
            if link_col is not None:
                u["table"].cellClicked.connect(
                    lambda row, col, k=key, lc=link_col: self._onLinkCell(k, row, col, lc))

    # 精簡 / 完整：兩顆獨立膠囊（藥丸形，圓角=高度一半），選中顆藍底白字。
    _SEG_STYLE = """
        QPushButton {
            background-color: #ffffff;
            border: 1px solid #c6c6c8;
            border-radius: 17px;
            padding: 6px 16px;
            color: #636366;
            font-weight: 500;
        }
        QPushButton:checked {
            background-color: #8fa8c8;
            border: 1px solid #8fa8c8;
            color: #ffffff;
            font-weight: 600;
        }
        QPushButton:!checked:hover { background-color: #f2f2f7; }
    """

    def _styleSegmented(self, key):
        full = self._ui[key]["full"]
        if full:
            full.setStyleSheet(self._SEG_STYLE)

    # 重載鈕：中性膠囊（與切換鈕同形，灰邊，hover 淡藍）。
    _RELOAD_STYLE = """
        QPushButton {
            background-color: #ffffff;
            border: 1px solid #c6c6c8;
            border-radius: 17px;
            padding: 6px 16px;
            color: #636366;
            font-weight: 500;
        }
        QPushButton:hover { background-color: #eaf1f8; }
        QPushButton:pressed { background-color: #d8e4f0; }
    """

    def _styleReload(self, key):
        btn = self._ui[key].get("reload")
        if btn:
            btn.setStyleSheet(self._RELOAD_STYLE)

    # 逾期未回篩選膠囊：選中紅底白字（警示語意）。
    _OVERDUE_STYLE = """
        QPushButton {
            background-color: #ffffff;
            border: 1px solid #c6c6c8;
            border-radius: 13px;
            padding: 3px 12px;
            color: #636366;
            font-weight: 500;
            font-size: 12px;
        }
        QPushButton:checked {
            background-color: #e07a72;
            border: 1px solid #e07a72;
            color: #ffffff;
            font-weight: 600;
        }
        QPushButton:!checked:hover { background-color: #f2f2f7; }
    """

    def _styleOverdue(self, key):
        btn = self._ui[key].get("overdue")
        if btn:
            btn.setStyleSheet(self._OVERDUE_STYLE)

    def _today(self):
        """今天日期字串，一次 reload 內快取，避免迴圈重複呼叫。"""
        from datetime import date
        return date.today().isoformat()

    def _applyFilter(self, key):
        """搜尋條件（kw/scope）改變時：重算每列是否命中，更新 _matchedCols，
        再交給 _applyRowVisibility 做 setRowHidden（同時考慮逾期篩選）。"""
        u = self._ui[key]
        meta = TABLE_META[key]
        kw = (u["kw"].text() or "").strip() if u["kw"] else ""
        scope_col = u["scope"].currentData() if u["scope"] else None
        search_cols = [scope_col] if scope_col else [
            c["view_col"] for c in meta["cols"] if c.get("search")]

        all_rows = getattr(self, "_allRows", {}).get(key, [])
        order = getattr(self, "_docorder", {}).get(key, [])
        matched_map = {}
        for row_idx, r in enumerate(all_rows):
            did = order[row_idx] if row_idx < len(order) else ""
            if kw:
                kw_l = kw.lower()  # 不分大小寫（中文不受影響，惠及英數）
                matched = [vc for vc in search_cols
                           if r.get(vc) is not None
                           and kw_l in str(r.get(vc)).lower()]
            else:
                matched = []
            matched_map[did] = matched

        if not hasattr(self, "_matchedCols"):
            self._matchedCols = {}
        self._matchedCols[key] = matched_map
        if not hasattr(self, "_lastSearch"):
            self._lastSearch = {}
        # shown 由 _applyRowVisibility 計算後寫回
        self._lastSearch[key] = (kw, search_cols, 0)
        self._applyRowVisibility(key)

    def _applyOverdue(self, key):
        """逾期未回篩選切換：不重算 matchedCols，直接重跑可見性。"""
        self._applyRowVisibility(key)

    def _applyRowVisibility(self, key):
        """單 pass 同時考慮搜尋 filter 與逾期篩選，setRowHidden，更新 footer。"""
        u = self._ui[key]
        table = u["table"]
        if not table:
            return
        meta = TABLE_META[key]
        btn = u.get("overdue")
        overdue_on = bool(key == "task" and btn and btn.isChecked())

        order = getattr(self, "_docorder", {}).get(key, [])
        matched_map = getattr(self, "_matchedCols", {}).get(key, {})
        if not hasattr(self, "_lastSearch"):
            self._lastSearch = {}
        kw, search_cols, _ = self._lastSearch.get(key, ("", [], 0))

        visible = 0
        table.setUpdatesEnabled(False)
        try:
            for row_idx in range(table.rowCount()):
                did = order[row_idx] if row_idx < len(order) else ""
                matched = matched_map.get(did)
                filter_ok = bool(matched) if kw else True
                if overdue_on:
                    hi = table.verticalHeaderItem(row_idx)
                    overdue_ok = bool(hi and hi.data(Qt.UserRole))
                else:
                    overdue_ok = True
                show = filter_ok and overdue_ok
                table.setRowHidden(row_idx, not show)
                if show:
                    visible += 1
        finally:
            table.setUpdatesEnabled(True)

        # 更新 _lastSearch shown 並刷 footer
        self._lastSearch[key] = (kw, search_cols, visible)
        full = self._isFull(key)
        hit_hidden = False
        if kw:
            visible_view_cols = {
                c["view_col"] for c in meta["cols"]
                if (full or c.get("slim")) and c.get("view_col")
            }
            for did, matched in matched_map.items():
                if matched and not (set(matched) & visible_view_cols):
                    hit_hidden = True
                    break
        self._updateFooter(key, visible, kw, hit_hidden)

    def _onToggleFull(self, key):
        # 切換精簡/完整：資料不變，只改欄位可見性 + 重算欄寬，不重查/不重建
        self._applyMode(key)

    def _forceReload(self, key):
        """手動「重載」：強制整表重建（略過指紋），反映任何外部／跨頁變動。
        使用者主動點擊，可接受一次性重建成本。"""
        def _work():
            self._reload(key)
            if not hasattr(self, "_sigs"):
                self._sigs = {}
            try:
                self._sigs[key] = self._tableSignature(key)
            except Exception:
                pass
        runWithBusy(self._inner, _work)

    def _refreshRefCells(self, key):
        """參照表（人員／部門／案類）改名後就地刷新 ref_col 欄文字。
        只 setText 既有儲存格，不重建列、不動 cellWidget → 700 列亦無感。"""
        table = self._ui[key]["table"]
        if not table:
            return
        order = getattr(self, "_docorder", {}).get(key)
        if not order:
            return
        meta = TABLE_META[key]
        ref_idx = [(i, c) for i, c in enumerate(meta["cols"]) if c.get("ref_col")]
        if not ref_idx:
            return
        id_col = meta["id_col"]
        try:
            rows = {str(r.get(id_col) or ""): r for r in self._query(key)}
        except Exception:
            return
        all_rows = getattr(self, "_allRows", {}).get(key, [])
        for pos, did in enumerate(order):
            r = rows.get(did)
            if r is None:
                continue
            if pos < len(all_rows):
                all_rows[pos] = r
            for ci, c in ref_idx:
                val = r.get(c["view_col"])
                text = "" if val is None else str(val)
                if c.get("trim_name") and text:
                    text = self._trimName(text)
                item = table.item(pos, ci)
                if item is not None:
                    item.setText(text)

    # ── 目前模式要顯示的欄位清單 ────────────────────────────
    def _isFull(self, key):
        btn = self._ui[key]["full"]
        return btn.isChecked() if btn else False

    # ── 主載入（資料變動時才呼叫，建全欄、塞全部 cell）──────
    def _reload(self, key, rows=None):
        meta = TABLE_META[key]
        u = self._ui[key]
        table = u["table"]
        if not table:
            return
        # 整表重建前後保留捲動位置（重載鈕／切回 Tab 不跳回頂端）
        _sb = table.verticalScrollBar()
        _scroll_pos = _sb.value() if _sb else 0
        self._today_cache = self._today()

        # 一律建「完整模式的全部欄位」，精簡模式之後用 setColumnHidden 藏欄，
        # 切換模式就不必重查 DB、重建 700+ 列（避免頓挫）。
        cols = meta["cols"]
        headers = [c["header"] for c in cols]
        stretch_idx = next((i for i, c in enumerate(cols) if c.get("stretch")), None)
        fixed_overrides = {c["header"]: c["w"] for c in cols if c.get("w")}

        setupPreviewTable(
            table, headers,
            stretch_col=stretch_idx if stretch_idx is not None else 1,
            fixed_overrides=fixed_overrides,
            cap_mode=False,
        )

        # 查詢資料（啟動預載時 rows 由外部帶入，免重查）
        if rows is None:
            try:
                rows = self._query(key)
            except Exception as e:
                msgCritical("DB錯誤", f"載入資料失敗：{e}")
                return

        id_col = meta["id_col"]
        table.setRowCount(0)
        order = []
        all_rows = []
        for r in rows:
            # 跳過已清空（軟刪除）的列
            if self._isEmptied(key, r):
                continue
            did = str(r.get(id_col) or "")
            self._appendRow(key, table, cols, r, id_col)
            order.append(did)
            all_rows.append(r)

        # 記住全量資料（供 _applyFilter setRowHidden 用）、doc_id 順序、載入時刻
        if not hasattr(self, "_docorder"):
            self._docorder = {}
        self._docorder[key] = order
        if not hasattr(self, "_allRows"):
            self._allRows = {}
        self._allRows[key] = all_rows
        self._lastLoad = getattr(self, "_lastLoad", {})
        self._lastLoad[key] = self._dbNow()

        # 套用目前模式（藏/顯示欄）+ 欄寬重算
        self._applyMode(key)
        # 套用搜尋過濾（setRowHidden）→ 內部再呼叫 _applyRowVisibility（含逾期）
        self._applyFilter(key)
        if _sb:
            QTimer.singleShot(0, lambda b=_sb, v=_scroll_pos: b.setValue(min(v, b.maximum())))

    def _applyMode(self, key):
        """只改欄位可見性與欄寬，不動資料。精簡↔完整切換走這裡，瞬間完成。"""
        meta = TABLE_META[key]
        table = self._ui[key]["table"]
        if not table:
            return
        full = self._isFull(key)

        # 藏/顯示欄
        for idx, c in enumerate(meta["cols"]):
            hidden = not (full or c.get("slim"))
            table.setColumnHidden(idx, hidden)

        # 欄寬重算（藏欄後 stretch 欄要重新吃掉剩餘空間，避免留白/擠壓）
        QTimer.singleShot(0, lambda t=table: autoResizeTable(t))

        # 欄位可見性改變後，hit_hidden 判斷可能不同，重跑可見性（同時更新 footer）
        self._applyRowVisibility(key)

    def _query(self, key):
        """回傳 dict 列表，含 View 全欄 + _proc_active（+ 歸檔表的 _arch_fname 原始檔名）。"""
        conn = self._getConn()
        try:
            return queryBrowseRows(conn, key)
        finally:
            conn.close()

    def _isEmptied(self, key, r):
        """該筆是否已被清空（軟刪除）。只看真實內容欄是否全空，
        排除：編號(link)、狀態(color，View 補『免覆』)、刪除欄、
        紙本/電子檔(bool_col，清空後 View 補『否』)。"""
        cols = TABLE_META[key]["cols"]
        content_cols = [c for c in cols
                        if not c.get("link") and not c.get("color")
                        and not c.get("delete") and not c.get("bool_col")]
        return not any(r.get(c["view_col"]) for c in content_cols)

    def _diffUpdate(self, key):
        """差異更新：只處理上次載入後變動（last_modified 更新）的列，
        其餘列不動。新增→加列、修改→更新列、清空刪除/不符搜尋→移除列。"""
        meta = TABLE_META[key]
        table = self._ui[key]["table"]
        if not table:
            return
        self._today_cache = self._today()
        since = getattr(self, "_lastLoad", {}).get(key)
        if since is None:
            self._reload(key)
            return

        cols = meta["cols"]
        id_col = meta["id_col"]
        # 查變動筆的 PK
        conn = self._getConn()
        try:
            # 游標採閉區間重疊（>=）：SQLite trigger 與 _dbNow 皆可能落在同秒，
            # 用 > 會永久漏掉邊界上的新增／修改。重疊列由下方 doc_id map
            # 原位覆寫，操作冪等，不會重複插入。
            # 不加 active 過濾：軟刪除的清空 UPDATE 不碰 last_modified，
            # trigger（WHEN NEW.last_modified IS OLD.last_modified）會把它蓋成
            # 當下時間，故被刪列本來就落在 last_modified >= since；無 active
            # 過濾即可抓到，並讓下方 _rebuild 走 removeRow 分支（queryBrowseRows
            # 對 register_date IS NULL 的 reward 列不回傳 → exists=False）。
            # reward 與其餘三表一致（三表本無 active_where，soft-delete 同靠此路徑）。
            changed_ids = [str(row[0]) for row in conn.execute(
                f"SELECT doc_id FROM {meta['base']} WHERE last_modified >= ?",
                (since,)).fetchall()]
        finally:
            conn.close()

        if not changed_ids:
            self._lastLoad[key] = self._dbNow()
            return

        def _rebuild():
            # 取這些 PK 的完整 View 列
            rows_by_id = {}
            for r in self._query(key):
                did = str(r.get(id_col) or "")
                if did in changed_ids:
                    rows_by_id[did] = r

            order = self._docorder.setdefault(key, [])
            matched_map = getattr(self, "_matchedCols", {}).get(key, {})
            all_rows = self._allRows.setdefault(key, [])

            for did in changed_ids:
                r = rows_by_id.get(did)
                in_table = did in order
                emptied = r is not None and self._isEmptied(key, r)
                exists = (r is not None) and (not emptied)

                if exists and not in_table:
                    # reward 的 raw query 採數字 DESC；舊三表維持既有 append 行為。
                    if meta.get("sort_numeric_desc"):
                        def _num(value):
                            try:
                                return int(value)
                            except (TypeError, ValueError):
                                return -1
                        pos = next((i for i, old in enumerate(order)
                                    if _num(did) > _num(old)), len(order))
                    else:
                        pos = len(order)
                    table.insertRow(pos)
                    order.insert(pos, did)
                    all_rows.insert(pos, r)
                    self._fillRow(key, table, cols, r, id_col, pos)
                elif exists and in_table:
                    # 修改：就地更新該列與 _allRows
                    pos = order.index(did)
                    all_rows[pos] = r
                    self._fillRow(key, table, cols, r, id_col, pos)
                elif (not exists) and in_table:
                    # 移除：刪該列
                    pos = order.index(did)
                    table.removeRow(pos)
                    order.pop(pos)
                    all_rows.pop(pos)
                    matched_map.pop(did, None)

            self._lastLoad[key] = self._dbNow()
            # 重算欄寬 + 可見性（含搜尋 filter 與逾期篩選）
            self._applyMode(key)
            self._applyFilter(key)

        # 變動列數達門檻才跳「更新中」提示（重建 cellWidget 才是成本所在）。
        # 包 preserveScroll 保留捲動位置，避免新增/刪除/修改後跳回頂端。
        def _run():
            if len(changed_ids) >= _BUSY_ROW_THRESHOLD:
                runWithBusy(self._inner, _rebuild)
            else:
                _rebuild()
        preserveScroll(table, _run)

    def _appendRow(self, key, table, cols, r, id_col):
        pos = table.rowCount()
        table.insertRow(pos)
        self._fillRow(key, table, cols, r, id_col, pos)

    def _fillRow(self, key, table, cols, r, id_col, pos):
        """在指定列 pos 寫入所有 cell（差異更新與全量載入共用）。"""
        inactive = not r["_proc_active"]

        for c_idx, c in enumerate(cols):
            # 刪除欄（最左）：放 X 鈕，點擊以 doc_id 觸發刪除
            if c.get("delete"):
                item = QTableWidgetItem("✕")
                item.setTextAlignment(Qt.AlignCenter)
                item.setForeground(
                    QColor("#e74c3c") if AuthManager.instance().is_admin()
                    else QColor("#aeaeb2"))
                item.setFlags(Qt.ItemIsEnabled)
                table.setItem(pos, c_idx, item)
                continue

            val = r.get(c["view_col"])
            text = "" if val is None else str(val)

            # 承辦/協辦欄：顯示去 - 後綴（王小明-19.06 → 王小明），比照預覽頁
            if c.get("trim_name") and text:
                text = self._trimName(text)

            # 紀錄時間：去掉秒以下小數（排序用的微秒不顯示），只留到秒
            if c.get("trunc_sec") and "." in text:
                text = text.split(".", 1)[0]

            if c.get("link"):
                doc_id = str(r.get(id_col) or "")
                can_edit = AuthManager.instance().is_manager()
                if table.cellWidget(pos, c_idx) is not None:
                    table.removeCellWidget(pos, c_idx)
                lnk = QTableWidgetItem(doc_id)
                lnk.setTextAlignment(Qt.AlignCenter)
                if can_edit and doc_id:
                    applyLinkStyle(lnk)                 # 藍字+底線（單一來源）
                lnk.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                table.setItem(pos, c_idx, lnk)
                continue

            # 主旨欄：有真實 PDF 檔名才建 cellWidget（圖示鈕 + 文字）；
            # 其餘一律用 item + tooltip，省掉 QWidget 配置成本。
            if c.get("stretch"):
                afn = ""
                if TABLE_META[key].get("archive"):
                    afn = (r.get("_arch_fname") or "").strip()
                    if not afn.lower().endswith(".pdf"):
                        afn = ""
                if afn:
                    if table.item(pos, c_idx) is not None:
                        table.takeItem(pos, c_idx)
                    cont = QWidget()
                    hl = QHBoxLayout(cont)
                    hl.setContentsMargins(6, 0, 6, 0)
                    hl.setSpacing(4)
                    hl.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
                    bo = QPushButton()
                    bo.setIcon(QIcon(":/icon_pdf.svg"))
                    bo.setIconSize(QSize(16, 16))
                    bo.setFixedSize(22, 22)
                    bo.setCursor(Qt.PointingHandCursor)
                    bo.setToolTip("開啟 PDF 檢視")
                    bo.setStyleSheet(
                        "QPushButton{border:1px solid #c6c6c8;border-radius:6px;background:#fff;}"
                        "QPushButton:hover{background:#eaf1f8;}")
                    bo.clicked.connect(
                        lambda _=False, k=key, f=afn: self._openArchivedPdf(k, f))
                    hl.addWidget(bo)
                    lab = QLabel(text)
                    if text:
                        lab.setToolTip(text)
                    if inactive:
                        lab.setStyleSheet("color: #aeaeb2;")
                    hl.addWidget(lab, 1)
                    table.setCellWidget(pos, c_idx, cont)
                else:
                    if table.cellWidget(pos, c_idx) is not None:
                        table.removeCellWidget(pos, c_idx)
                    sit = QTableWidgetItem(text)
                    sit.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
                    if text:
                        sit.setToolTip(text)
                    if inactive:
                        sit.setForeground(QColor("#aeaeb2"))
                    table.setItem(pos, c_idx, sit)
                continue

            # 刑案/一般「陳報日期」欄 NULL（自助取號模式尚未結算）→ 橘字「未發文」
            if (key in ("crim", "gen")
                    and c.get("header") == "陳報日期"
                    and not text):
                item = QTableWidgetItem("未發文")
                item.setTextAlignment(Qt.AlignCenter)
                item.setForeground(QColor("#e67e22"))
                table.setItem(pos, c_idx, item)
                continue

            item = QTableWidgetItem(text)
            item.setTextAlignment(Qt.AlignCenter)

            if c.get("color"):
                col = _statusColor(text)
                if col:
                    item.setForeground(col)
            elif inactive:
                # 承辦人已停用 → 整列文字標灰
                item.setForeground(QColor("#aeaeb2"))

            table.setItem(pos, c_idx, item)

        # 存逾期旗標到該列 vertical header item（toggle 時直接讀，不重算/不重查）
        if key == "task":
            due  = (r.get("限辦日期") or "").strip()
            sent = (r.get("發文日期") or "").strip()
            today = getattr(self, "_today_cache", None) or self._today()
            overdue = bool(due and due < today and not sent)
            hi = table.verticalHeaderItem(pos)
            if hi is None:
                hi = QTableWidgetItem()
                table.setVerticalHeaderItem(pos, hi)
            hi.setData(Qt.UserRole, overdue)

    def _rowOf(self, key, doc_id):
        """以 doc_id 找出目前在表格中的列號（差異更新後仍正確）。"""
        order = getattr(self, "_docorder", {}).get(key, [])
        try:
            return order.index(doc_id)
        except ValueError:
            return -1

    def _updateFooter(self, key, shown, kw, hit_hidden):
        u = self._ui[key]
        if u["count"]:
            u["count"].setText(f"共 {shown} 筆")

        # 浮水印（查無資料時顯示）
        wm = self._watermark.get(key)
        tbl = u["table"]
        if wm and tbl:
            if shown == 0:
                msg = f"查無符合「{kw}」的資料" if kw else "查無資料"
                wm.setText(msg)
                wm.resize(tbl.viewport().size())
                wm.move(0, 0)
                wm.show()
                wm.raise_()
            else:
                wm.hide()

        # footer 右側提示：命中欄位在精簡模式被隱藏
        if u["hint"]:
            if hit_hidden:
                u["hint"].setText("部分結果命中的欄位需切「完整預覽」查看")
                u["hint"].setStyleSheet("color:#e6a23c; font-size:11pt;")
            else:
                u["hint"].setText("")

    # ── 刪除（清空式 UPDATE，與收文/陳報頁共用 db_utils.softDeleteDoc）──────
    def _onDeleteCell(self, key, row, col, del_col):
        """cellClicked handler：攔截文字型 ✕ 欄的點擊觸發刪除。"""
        if col != del_col or not AuthManager.instance().is_admin():
            return
        order = getattr(self, "_docorder", {}).get(key, [])
        if row < len(order):
            self._onDelete(key, order[row])

    def _onLinkCell(self, key, row, col, link_col):
        """cellClicked handler：攔截編號欄點擊開啟編輯視窗。"""
        if col != link_col or not AuthManager.instance().is_manager():
            return
        order = getattr(self, "_docorder", {}).get(key, [])
        if row < len(order):
            self._onEdit(key, row, order[row])

    def _onDelete(self, key, doc_id):
        if not AuthManager.instance().is_admin():
            return
        if not doc_id:
            return
        if not confirmBox(
                "確認刪除",
                f"本筆資料將被刪除，本文號（{doc_id}）無法再被使用，確認刪除？",
                confirm_text="刪除", confirm_danger=True, default_confirm=False):
            return
        am = AuthManager.instance()
        conn = None
        try:
            conn = self._getConn()
            # 瀏覽頁刪除僅 admin、與資料列的人脫鉤 → operator 一律留空
            # （audit_operator=False）；回收筒對象人仍取承辦人（helper 內處理）。
            softDeleteDoc(conn, table=TABLE_META[key]["base"], doc_id=doc_id,
                          role=am.current_role, is_admin=am.is_admin(),
                          audit_operator=False)
            conn.commit()
        except Exception as e:
            reportError("刪除失敗", e)
            return
        finally:
            if conn:
                conn.close()
        # 差異更新：清空後該列會被判定為 emptied → 自動移除。
        # 捲動位置由 _diffUpdate 內的 preserveScroll 保留。
        self._diffUpdate(key)
        if key == "reward":
            self._flagRewardDirty()
        self._sigs = getattr(self, "_sigs", {})
        try:
            self._sigs[key] = self._tableSignature(key)
        except Exception:
            pass

    # ── 點編號開 EditDialog ─────────────────────────────────
    def _onEdit(self, key, row, doc_id):
        if not AuthManager.instance().is_manager():
            return
        dialog_cls = TABLE_META[key]["dialog"]
        kwargs = {"source": "browse"} if key == "reward" else {}
        dlg = dialog_cls(self.db_path, doc_id, self._ui[key]["table"], **kwargs)
        if dlg.exec():
            if getattr(dlg, "converted", False):
                self._afterConvert()      # 類別互轉：兩類別都變了，差異更新
                return
            # 編輯後差異更新，只動到改過的那列
            self._diffUpdate(key)
            self._sigs = getattr(self, "_sigs", {})
            try:
                self._sigs[key] = self._tableSignature(key)
            except Exception:
                pass
            if key == "reward":
                self._flagRewardDirty()

    def _flagRewardDirty(self):
        manager = getattr(self, "_manager", None)
        for target in getattr(manager, "tabs", {}).values():
            if hasattr(target, "reward_data_dirty"):
                target.reward_data_dirty = True

    def _afterConvert(self):
        """類別互轉後：本頁刑案／一般兩表差異更新＋標記歸檔頁下次重載。

        觸發器會蓋 last_modified（作廢舊單的 UPDATE、新單的 INSERT 都會），
        _diffUpdate 只動那兩列，避免兩表整表重載造成的數秒卡頓。
        """
        self._sigs = getattr(self, "_sigs", {})
        for k in ("crim", "gen"):
            if self._ui.get(k, {}).get("table"):
                self._diffUpdate(k)
                try:
                    self._sigs[k] = self._tableSignature(k)
                except Exception:
                    pass
        self._flagConvertReload(("crim", "gen"))

    def _openArchivedPdf(self, key, fname):
        """以 is_electronic 檔名定位並開啟實體 PDF（唯讀檢視）。"""
        # 轉檔前存量資料可能只記占位字串（非真正檔名），無法開啟
        if not fname.lower().endswith(".pdf"):
            msgInfo("無電子檔",
                    "本筆未記錄可開啟的電子檔名稱，可能為轉檔前的存量資料。")
            return
        path, status = resolveArchivedPdf(self.db_path, key, fname)
        if status == "ok":
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))
            return
        if status == "noroot":
            msgWarning("尚未設定歸檔資料夾",
                       "請先於設定頁指定本年度歸檔資料夾後，再開啟電子檔。")
        elif status == "noaccess":
            msgCritical("無法存取歸檔資料夾",
                        "歸檔資料夾目前無法存取，請確認：\n"
                        "1. 網路磁碟機是否已透過 NET USE 連線\n"
                        "2. 設定的歸檔資料夾路徑是否正確")
        else:  # notfound
            msgCritical("找不到電子檔",
                        f"無法定位檔案：{fname}\n\n請確認：\n"
                        "1. 網路磁碟機是否已連線\n"
                        "2. 該 PDF 是否已被移動或刪除")

    # ── 框架掛鉤 ────────────────────────────────────────────
    def get_tables(self):
        return [self._ui[k]["table"] for k in BROWSE_KEYS
                if self._ui.get(k, {}).get("table")]

    def _tableSignature(self, key):
        """回傳該表的變動指紋：(筆數, 最大 last_modified)。
        任一新增/修改/清空刪除都會改變這個指紋（trigger 會更新 last_modified）。"""
        meta = TABLE_META[key]
        conn = self._getConn()
        try:
            where = f" WHERE {meta['active_where']}" if meta.get("active_where") else ""
            row = conn.execute(
                f"SELECT COUNT(*), MAX(last_modified) FROM {meta['base']}{where}"
            ).fetchone()
        finally:
            conn.close()
        return (row[0], row[1])

    def buildInitial(self, key, rows=None):
        """啟動載入畫面期間建單一表（rows 為背景預查資料，None 則就地查 DB）。
        逐表呼叫，呼叫端可在每張表之間更新進度條。"""
        if not hasattr(self, "_sigs"):
            self._sigs = {}
        self._reload(key, rows=rows)
        try:
            self._sigs[key] = self._tableSignature(key)
        except Exception:
            pass
        self._loaded_keys = getattr(self, "_loaded_keys", set())
        self._loaded_keys.add(key)

    def markLoaded(self):
        """三表皆已由 buildInitial 建好後呼叫：標記已載入、更新歸檔根目錄警示。"""
        self._loaded_keys = getattr(self, "_loaded_keys", set())
        self._loaded_keys.update(PRELOAD_KEYS)
        self._refreshArchWarn()

    def _refreshArchWarn(self):
        has_root = bool(getSetting(self.db_path, ARCHIVE_ROOT_KEY, "").strip())
        for key in ("crim", "gen"):
            lbl = self._arch_warn.get(key)
            if lbl:
                lbl.setVisible(not has_root)

    def on_activated(self):
        # 切換進「資料庫瀏覽」時，逐表比對變動指紋：
        # 指紋未變 → 不重載（避免無謂重建 700+ 列造成頓挫）；
        # 指紋改變 → 只重載該表，反映其他頁的增/修/刪。
        if not hasattr(self, "_sigs"):
            self._sigs = {}
        # Fallback 只補建尚未預載的既有三表；reward 仍由切頁 lazy-load。
        missing = [k for k in PRELOAD_KEYS
                   if k not in getattr(self, "_loaded_keys", set())]
        if missing:
            def _first():
                for key in missing:
                    self.buildInitial(key)
            runWithBusy(self._inner, _first, text="載入資料中，請稍候…")
            self._refreshArchWarn()
        # 還原誤刪後被標記的表：走 _forceReload（runWithBusy popup→全量重建），
        # 確保被還原的列出現，並遵循「先 popup 再刷新」慣例。
        pend = getattr(self, "_pending_reload_keys", None)
        if pend:
            self._pending_reload_keys = None
            for k in list(pend):
                if self._ui.get(k, {}).get("table"):
                    self._forceReload(k)
        # 參照表改名（設定頁改過）→ 就地輕量刷新 ref_col 欄，不重建列（零頓）。
        if getattr(self, "_ref_changed", False):
            for key in PRELOAD_KEYS:
                self._refreshRefCells(key)
            self._ref_changed = False
        self._ensureCurrentLoaded()
        for key in BROWSE_KEYS:
            if key not in self._loaded_keys:
                continue
            if not self._ui.get(key, {}).get("table"):
                continue
            try:
                sig = self._tableSignature(key)
            except Exception:
                # 比對失敗時保守重載，確保看到最新資料
                self._reload(key)
                continue
            if self._sigs.get(key) != sig:
                self._diffUpdate(key)
                self._sigs[key] = sig

        # 歸檔根目錄警示
        self._refreshArchWarn()

    def _onBrowseSubtabChanged(self, _index):
        self._ensureCurrentLoaded()

    def _ensureCurrentLoaded(self):
        if not self.subtabs:
            return
        index = self.subtabs.currentIndex()
        if not 0 <= index < len(BROWSE_KEYS):
            return
        key = BROWSE_KEYS[index]
        if key in getattr(self, "_loaded_keys", set()):
            return
        runWithBusy(self._inner, lambda: self.buildInitial(key),
                    text="載入資料中，請稍候…")
