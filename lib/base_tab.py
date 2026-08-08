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

    def _rowDocIds(self, table, col=1):
        """回傳 `{列號: doc_id}`，同時涵蓋編號欄的兩種表示法。

        編號欄可點時是 `QLabel` 連結（cellWidget）、不可點時是純文字
        `QTableWidgetItem`，兩者獨立儲存（見 `setDocIdLinkCell`）。逐列重算
        權限時列可能處於任一種狀態，故兩邊都要讀。
        """
        rows = {}
        if not table:
            return rows
        for r in range(table.rowCount()):
            doc_id = self._docIdFromLabel(table.cellWidget(r, col))
            if not doc_id:
                item = table.item(r, col)
                doc_id = item.text() if item else None
            if doc_id:
                rows[r] = str(doc_id)
        return rows

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
         refresh_tables=...)` 完成掛鉤與初次套用。

    參數：
      lock_kind      — 鎖種類字串（dispatch/task/crim/gen），或回傳字串的 callable
                       （陳報頁依當前刑案/一般模式動態決定）。
      lock_widgets   — 反灰元件 list；或 {kind: list} dict（陳報頁依模式取用）。
      refresh_tables — 身分變更時要重算「能不能改、能不能刪」的預覽表清單。

    ⚠️ **2026-08-07 起降權不再清空預覽清單**（原參數名 `clear_tables`、原行為
    `setRowCount(0)`）。清空等於讓一般使用者失去他本來就有的入口——登錄頁對
    三種身分都開放刪改，那是把資料庫瀏覽頁「僅管理者可改」的規則錯套到登錄頁
    上。現在改為**逐列重算權限**，列留著，該鎖的鎖、該開的開，規則單一來源在
    `lib/row_perm.py`。參數一併更名，避免下一個人以為它還會清表。
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

    def _setupInputLock(self, tab_index, *, lock_kind, lock_widgets,
                        refresh_tables):
        self._tab_index = tab_index
        self._lock_kind = lock_kind
        self._lock_widgets = lock_widgets
        self._lock_refresh_tables = refresh_tables
        # main._onTabChanged 不會對輸入頁呼叫 on_activated（只對設定/瀏覽頁），
        # 故自掛 currentChanged：切回本頁時重套唯讀狀態（比照 tab_print._onShown）。
        try:
            self.tab_widget.currentChanged.connect(self._onShown)
        except Exception:
            pass
        # 降權時就地重算每一列的可改／可刪狀態（不再清空清單）。
        from lib.auth_manager import AuthManager
        try:
            AuthManager.instance().role_changed.connect(self._onRoleRefresh)
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
        locked = (kind is not None and isInputLocked(self.db_path, kind))
        widgets = getattr(self, "_lock_widgets", None)
        if isinstance(widgets, dict):
            widgets = widgets.get(kind, [])
        for w in (widgets or []):
            w.setEnabled(not locked)
        if getattr(self, "_readonly_banner", None):
            self._readonly_banner.setVisible(locked)
        self._syncRowPermsOnLockChange(locked)

    def _syncRowPermsOnLockChange(self, locked):
        """唯讀狀態真的變了才重算預覽列（由 `_applyInputLock` 末尾呼叫）。

        管理者在設定頁開／關唯讀後切回本頁，`_onShown` 只重套表單反灰與橫幅，
        預覽列的 ✕ 與編號欄連結外觀不會跟著變——按下去仍會被
        `_rowActionBlockReason` 擋下（防線在那裡，不在外觀），但畫面上看起來
        還能點，與橫幅寫的「本功能目前無法使用」互相矛盾。故在此補一次重算。

        ⚠️ **刻意只在狀態變化時做，不是每次 `_applyInputLock` 都做**：
        `_applyInputLock` 每次切頁都會跑，而 `reward`／`ticket` 的
        `_refreshRowPermissions` 是整表重建（`_refresh_session_rows`／
        `reload`），無條件刷等於每次切頁多重建一次預覽表。

        首次呼叫（`_setupInputLock` 期間）只記錄不刷新：此時各頁 `setup()`
        尚未跑完，預覽表可能還沒建好，重建會炸。
        """
        prev = getattr(self, "_lock_last_locked", None)
        self._lock_last_locked = locked
        if prev is None or prev == locked:
            return
        self._refreshRowPermissions(
            getattr(self, "_lock_refresh_tables", None) or [])

    def _onShown(self, idx):
        """切回本頁時重套唯讀狀態。"""
        if idx == getattr(self, "_tab_index", -1):
            self._applyInputLock()

    def _onRoleRefresh(self, *_):
        """身分變更時就地重算預覽清單每一列的可改／可刪狀態。

        ⚠️ **只處理降權方向**：升權一定發生在資料庫設定頁（登入在那裡），回到
        本頁必然觸發 `on_activated` 而整份重刷；降權則可能在原地發生（手動登出、
        閒置自動登出），所以降權這一側必須自己重刷。

        ⚠️ 對管理身分 early return **不是因為唯讀鎖只鎖一般使用者**——唯讀鎖
        自 2026-08-07 起三種身分一律擋（PITFALLS PRM-6），別再拿舊規則推理。
        真正的理由是上一段：升權必經設定頁、回本頁必重刷，這裡不做也不會漏。
        唯讀狀態本身的變化由 `_syncRowPermsOnLockChange` 負責，與身分無關。
        """
        from lib.auth_manager import AuthManager
        if AuthManager.instance().is_manager():
            return
        self._refreshRowPermissions(
            getattr(self, "_lock_refresh_tables", None) or [])

    def _rowPermContext(self, page, doc_ids):
        """一次查回這批 doc_id 的權限判斷素材。

        回傳 `(states, kwargs)`：
          states — `{doc_id: dispatched}`，值取自 DB 真值（查不到＝該列已不在）
          kwargs — 直接展開餵給 `row_perm.canEditRow` / `canDeleteRow` 的
                   `is_admin` / `is_manager` / `input_locked`
        """
        from lib import row_perm
        from lib.auth_manager import AuthManager
        from lib.db_utils import isInputLocked
        am = AuthManager.instance()
        kwargs = {
            "is_admin": am.is_admin(),
            "is_manager": am.is_manager(),
            "input_locked": isInputLocked(self.db_path, page),
        }
        ids = [d for d in doc_ids if d]
        if not ids:
            return {}, kwargs
        sql, params = row_perm.rowStateSql(page, ids)
        try:
            conn = self._getConn()
            try:
                rows = conn.execute(sql, params).fetchall()
            finally:
                conn.close()
        except Exception:
            # 讀不到 DB 時一律當成「已發文」，寧可多鎖不可誤放
            return {d: True for d in ids}, kwargs
        states = {}
        for doc_id, date_value, live_value in rows:
            if not row_perm.isLiveRow(page, live_value):
                continue    # 軟刪除空殼：該列已不在，不給任何入口
            states[str(doc_id)] = row_perm.isDispatched(date_value)
        return states, kwargs

    def _rowActionBlockReason(self, page, doc_id, *, delete):
        """動作進入時的入口複核：重查 DB 現值再問一次權限。

        放行回 `None`；擋下回 `(標題, 訊息)`，**由呼叫端自己彈**。

        ⚠️ **這一層才是防線，視覺層只是提示**：舊行為清空清單時「列不存在」
        本身就是防線；改成留列之後，畫面上只剩刪除鈕反灰與編號欄純文字化，
        而 CLAUDE.md 明列「反灰擋不住替代路徑」，且降權與使用者操作之間存在
        時間差。故每一個動作進入點都要自己再檢查一次。

        ⚠️ **本函式刻意不呼叫 `msgWarning`**：訊息框必須由各分頁模組自己的
        `msgWarning` 名稱發出，測試才 patch 得掉（`patch("tabs.tab_reward.
        msgWarning")` 換不掉別的模組 import 進去的參考，見 PITFALLS TST-7）。
        在這裡直接彈，離線測試會卡在無人可按的 modal 上。
        """
        from lib import row_perm
        from lib.db_utils import ROW_GONE_MSG, ROW_GONE_TITLE
        states, perm = self._rowPermContext(page, [doc_id])
        if str(doc_id) not in states:
            return ROW_GONE_TITLE, ROW_GONE_MSG
        check = row_perm.canDeleteRow if delete else row_perm.canEditRow
        if not check(page, dispatched=states[str(doc_id)], **perm):
            return ("權限不足",
                    f"目前身分無法{'刪除' if delete else '修改'}「{doc_id}」。")
        return None

    def _refreshRowPermissions(self, tables):
        """各頁覆寫：重算 `tables` 內每一列的刪除鈕與編號欄可點狀態。

        預設 no-op，讓還沒實作的頁不會壞。實作範本見 `tabs/tab_dbbrowse.py`
        的 `_onRolePerm`；判斷一律呼叫 `lib/row_perm.py`，不得在迴圈裡自己
        拼權限條件，也不得讀表格上的顯示字串判斷發文狀態（畫面上「未發文」與
        「已刪除」都是空白，從 cell 文字在原理上分不出三態）。
        """
        return None

