import re
from datetime import datetime
from lib.db_utils import getConn
from ui_utils import msgCritical
from lib.archive_text import _trimName as _archiveTrimName


class BaseTab:
    """
    所有 Tab 的共用基礎介面。

    子類別必須實作：
        setup(tab_index: int) -> None
            在 tabWidget 對應的 tab 上建立 UI 與綁定事件。

    子類別可 override：
        get_tables()       -> list[QTableWidget]  供 _onTabChanged 自動 resize 用
        get_focus_widget() -> QWidget | None       供 _onTabChanged 自動 setFocus 用
    """

    def __init__(self, tab_widget, db_path):
        self.tab_widget = tab_widget   # QTabWidget
        self.db_path    = db_path

    def setup(self, tab_index):
        raise NotImplementedError

    # ── Tab 切換時由 DocumentManager 呼叫 ───────────────────
    def get_tables(self):
        """回傳此 Tab 所有預覽表格，供切換時自動 resize。"""
        return []

    def get_focus_widget(self):
        """回傳此 Tab 預設取得焦點的元件，切換時自動 setFocus。"""
        return None

    def on_activated(self):
        """Tab 被切換到時呼叫，子類別可 override 以刷新參照表等。"""
        pass

    # ── DB 工具 ─────────────────────────────────────────────
    def _getConn(self):
        """回傳新的 sqlite3 連線，呼叫端負責 close()（統一走 db_utils.getConn）"""
        return getConn(self.db_path)

    def _dbNow(self):
        """資料庫端當前時間字串，與 trigger 寫入的 last_modified 同基準。"""
        conn = self._getConn()
        try:
            return conn.execute("SELECT datetime('now','localtime')").fetchone()[0]
        finally:
            conn.close()

    def _loadRef(self):
        """
        載入人員與部門對照表。
        回傳 (personnel_list, dept_list)，各為 [(id, name), ...] 格式。
        """
        conn = None
        try:
            conn = self._getConn()
            personnel = conn.execute(
                "SELECT staff_id, staff_name FROM Ref_Personnel "
                "WHERE is_active=1 ORDER BY sort_order"
            ).fetchall()
            depts = conn.execute(
                "SELECT dept_id, dept_name FROM Ref_Departments "
                "WHERE is_active=1 ORDER BY sort_order"
            ).fetchall()
            return personnel, depts
        except Exception as e:
            msgCritical("DB錯誤", f"載入對照表失敗: {e}")
            return [], []
        finally:
            if conn:
                conn.close()

    # ── 共用資料轉換 helper ──────────────────────────────────
    @staticmethod
    def _trimName(name):
        """去掉 -／－ 後綴，例如 王小明-19.06 → 王小明（收斂至 archive_text._trimName，
        統一處理半形 - 與全形 －）"""
        return _archiveTrimName(name)

    @staticmethod
    def _fmtDate(d):
        """YYYY-MM-DD → MM-DD-YYYY（僅預覽顯示用）"""
        if not d:
            return ""
        try:
            return datetime.strptime(str(d), "%Y-%m-%d").strftime("%m-%d-%Y")
        except Exception:
            return str(d)

    @staticmethod
    def _docIdFromLabel(lbl):
        """從 QLabel HTML 取出 href 中的 doc_id，找不到回傳 None。"""
        if not lbl:
            return None
        m = re.search(r'href="([^"]+)"', lbl.text())
        return m.group(1) if m else None

    # ── 共用：刷新交辦單預覽表的業務組 / 承辦人欄 ────────────────
    def _refreshTaskPreviewNames(self, table, dept_col=3, proc_col=4, docid_col=1):
        """
        掃 table 每一列，用 doc_id 反查 Document_Task 最新的
        業務組名稱與承辦人名稱並更新顯示。
        發文（tab_dispatch）與收文（tab_receive）共用。
        """
        if not table:
            return
        conn = None
        try:
            conn = self._getConn()
            for r in range(table.rowCount()):
                doc_item = table.item(r, docid_col)
                if not doc_item:
                    continue
                row = conn.execute("""
                    SELECT d.dept_name, p.staff_name
                    FROM Document_Task t
                    LEFT JOIN Ref_Departments d ON t.dept_id      = d.dept_id
                    LEFT JOIN Ref_Personnel   p ON t.processor_id = p.staff_id
                    WHERE t.doc_id = ?
                """, (doc_item.text(),)).fetchone()
                if not row:
                    continue
                dept_name, processor_name = row
                if dept_name is not None and table.item(r, dept_col):
                    table.item(r, dept_col).setText(dept_name)
                if processor_name is not None and table.item(r, proc_col):
                    table.item(r, proc_col).setText(self._trimName(processor_name))
        except Exception as e:
            msgCritical("DB錯誤", f"刷新預覽列失敗: {e}")
        finally:
            if conn:
                conn.close()

    # ── 類別互轉後刷新其他頁 ─────────────────────────────────
    def _flagConvertReload(self, keys):
        """類別互轉（刑案↔一般）後：標記其他頁（瀏覽／歸檔）下次顯示時強制
        重載指定表。來源表與目標表都變了，keys 兩個類別都要傳（('crim','gen')）。
        比照 tab_settings._flagSiblingReload，但支援多 key。"""
        try:
            mgr = getattr(self, "_manager", None)
            for t in getattr(mgr, "tabs", {}).values():
                if t is self or not hasattr(t, "_forceReload"):
                    continue
                pend = getattr(t, "_pending_reload_keys", None) or set()
                for k in keys:
                    pend.add(k)
                t._pending_reload_keys = pend
        except Exception:
            pass


class InputLockMixin:
    """三個輸入頁（交辦收文／發文／公文陳報）共用的『跨年度後唯讀』行為。

    差異以 `_setupInputLock` 的參數注入，避免三頁各抄一份紅色橫幅、反灰迴圈、
    切入分頁/登出重套的樣板（原本各約 40 行、改一處易漏改另兩處）。

    子類別於 setup() 內：
      1. 用 `_makeReadonlyBanner()` 建橫幅後自行 `lay.insertWidget(0, banner)`；
         發文頁表單直接掛在 tabLayout 上（會吃到左右內距而變窄），改呼叫
         `_wrapLayoutWithBanner(outer_layout)` 讓橫幅滿版。
      2. 呼叫 `_setupInputLock(tab_index, lock_kind=..., lock_widgets=...,
         clear_tables=...)` 完成掛鉤與初次套用。

    參數：
      lock_kind    — 鎖種類字串（dispatch/task/crim/gen），或回傳字串的 callable
                     （陳報頁依當前刑案/一般模式動態決定）。
      lock_widgets — 反灰元件 list；或 {kind: list} dict（陳報頁依模式取用）。
      clear_tables — 登出降回一般使用者時要清空（setRowCount(0)）的預覽表清單。
    """

    _READONLY_TEXT = "唯讀模式：本功能目前無法使用，僅供瀏覽"
    _READONLY_CSS = (
        "background-color: #fdecea; color: #c0392b; border: 1px solid #e74c3c;"
        "border-radius: 8px; padding: 8px 12px; font-weight: 600;")

    def _makeReadonlyBanner(self):
        """建立（並存成 self._readonly_banner）預設隱藏的紅色唯讀橫幅並回傳。"""
        from PySide6.QtWidgets import QLabel
        banner = QLabel(self._READONLY_TEXT)
        banner.setStyleSheet(self._READONLY_CSS)
        banner.setVisible(False)
        self._readonly_banner = banner
        return banner

    def _wrapLayoutWithBanner(self, outer):
        """把 outer 現有內容包進 inner 容器承接邊距、outer 邊距歸零，橫幅插最上層
        橫向滿版（表單/表格位置不變）。spacer/stretch 一併保留（勿漏搬）。"""
        from PySide6.QtWidgets import QWidget, QVBoxLayout
        banner = self._makeReadonlyBanner()
        inner = QWidget()
        inner_lay = QVBoxLayout(inner)
        inner_lay.setContentsMargins(*outer.getContentsMargins())
        inner_lay.setSpacing(outer.spacing())
        while outer.count():
            it = outer.takeAt(0)
            if it.widget() is not None:
                inner_lay.addWidget(it.widget())
            elif it.layout() is not None:
                inner_lay.addLayout(it.layout())
            else:
                inner_lay.addItem(it)   # spacer/stretch，保留避免版面塌陷
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(banner)
        outer.addWidget(inner)

    def _setupInputLock(self, tab_index, *, lock_kind, lock_widgets, clear_tables):
        self._tab_index = tab_index
        self._lock_kind = lock_kind
        self._lock_widgets = lock_widgets
        self._lock_clear_tables = clear_tables
        # main._onTabChanged 不會對輸入頁呼叫 on_activated（只對設定/瀏覽頁），
        # 故自掛 currentChanged：切回本頁時重套唯讀狀態（比照 tab_print._onShown）。
        try:
            self.tab_widget.currentChanged.connect(self._onShown)
        except Exception:
            pass
        # 登出降回一般使用者時清空預覽清單（不在原頁做即時反灰）。
        from lib.auth_manager import AuthManager
        try:
            AuthManager.instance().role_changed.connect(self._onRoleClearList)
        except Exception:
            pass
        self._applyInputLock()

    def _resolveLockKind(self):
        k = getattr(self, "_lock_kind", None)
        return k() if callable(k) else k

    def _applyInputLock(self):
        """一般使用者遇對應表被鎖 → 表單全反灰＋顯示紅色橫幅；
        admin/archive 或未鎖 → 正常可填、橫幅隱藏。"""
        from lib.auth_manager import AuthManager
        from lib.db_utils import isInputLocked
        kind = self._resolveLockKind()
        locked = (kind is not None
                  and not AuthManager.instance().is_manager()
                  and isInputLocked(self.db_path, kind))
        widgets = getattr(self, "_lock_widgets", None)
        if isinstance(widgets, dict):
            widgets = widgets.get(kind, [])
        for w in (widgets or []):
            w.setEnabled(not locked)
        if getattr(self, "_readonly_banner", None):
            self._readonly_banner.setVisible(locked)

    def _onShown(self, idx):
        """切回本頁時重套唯讀狀態。"""
        if idx == getattr(self, "_tab_index", -1):
            self._applyInputLock()

    def _onRoleClearList(self, *_):
        """登出降回一般使用者時清空預覽清單（取代原頁即時反灰）。"""
        from lib.auth_manager import AuthManager
        if AuthManager.instance().is_manager():
            return
        for t in (getattr(self, "_lock_clear_tables", None) or []):
            if t:
                t.setRowCount(0)

