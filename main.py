import sys
import os
import traceback
import logging

# 壓掉 Qt DirectWrite 字型警告（MS Sans Serif 找不到屬正常現象，不影響功能）
os.environ.setdefault("QT_LOGGING_RULES", "qt.qpa.fonts.warning=false")

# ──────────────────────────────────────────────
# 全域錯誤處理：寫入 error.log + Windows 事件檢視器
# ──────────────────────────────────────────────
_LOG_MAX_BYTES = 1 * 1024 * 1024   # error.log 超過 1MB 即輪替（保留一份 .old）

def _setup_error_handler():
    log_path = os.path.join(
        os.path.dirname(sys.executable if getattr(sys, 'frozen', False) else __file__),
        'error.log'
    )
    # 單檔輪替：超過上限就把現檔改名 .old（只留一份），避免長期現場無限增長。
    # 全程靜默——輪替失敗絕不能擋住錯誤記錄本身。
    try:
        if os.path.getsize(log_path) > _LOG_MAX_BYTES:
            old = log_path + '.old'
            if os.path.exists(old):
                os.remove(old)
            os.replace(log_path, old)
    except OSError:
        pass
    logging.basicConfig(
        filename=log_path,
        level=logging.ERROR,
        format='%(asctime)s %(levelname)s\n%(message)s\n' + '-'*60,
        encoding='utf-8',
    )

    def _handle_exception(exc_type, exc_value, exc_tb):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_tb)
            return
        msg = ''.join(traceback.format_exception(exc_type, exc_value, exc_tb))

        # 1. 寫入 error.log
        logging.error(msg)

        # 2. 寫入 Windows 事件檢視器（僅 Windows 且有 pywin32）
        try:
            import win32evtlog
            import win32evtlogutil
            win32evtlogutil.ReportEvent(
                '公文管理系統',
                1,
                eventType=win32evtlog.EVENTLOG_ERROR_TYPE,
                strings=[msg],
            )
        except Exception:
            pass  # 沒有 pywin32 或非 Windows 時靜默跳過

        # 3. 彈出錯誤視窗（QApplication 存在時）
        try:
            from PySide6.QtWidgets import QApplication
            from ui_utils import msgCritical as _msgCritical
            from lib.db_utils import friendlyErrorMessage as _friendly
            if QApplication.instance():
                _msgCritical("系統錯誤", _friendly(exc_type, exc_value))
        except Exception:
            pass

    sys.excepthook = _handle_exception

_setup_error_handler()

from PySide6.QtWidgets import QApplication, QDialog
from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QFont

from lib.theme import APPLE_STYLE
from lib.version import __version__
from lib.db_utils import getResourcePath
from ui_utils import loadUi, msgInfo
from lib.auth_manager import AuthManager
from tabs import (TabDispatch, TabReceive, TabReport, TabReward,
                  TabTicketPlaceholder, TabPrint, TabDBBrowse, TabArchive,
                  TabSettings, TabAudit)
from res import resources_rc  # 註冊 Qt resource（arrow.svg）


# ──────────────────────────────────────────────
# DocumentManager：視窗容器，管理所有 Tab
# ──────────────────────────────────────────────
class DocumentManager:
    """
    新增 Tab 只需：
      1. 在 tabs/ 新增 tab_xxx.py 並實作 BaseTab
      2. 在 tabs/__init__.py 加入 import
      3. 在 TAB_CLASSES 登記 {index: TabClass}
    """
    TAB_CLASSES = {
        0: TabDispatch,
        1: TabReceive,
        2: TabReport,
        3: TabReward,
        4: TabTicketPlaceholder,
        5: TabPrint,
        6: TabDBBrowse,
        7: TabArchive,
        8: TabSettings,
        9: TabAudit,
    }

    def __init__(self, tab_index=0, prefetch=None, progress=None):
        self.db_path   = getResourcePath("dbfile.db")
        self.window    = loadUi(getResourcePath("layouts/Layout1.ui"))
        if not self.window:
            return

        self.tab_widget = getattr(self.window, 'tabWidget', None)

        self.tabs = {}
        for idx, TabClass in self.TAB_CLASSES.items():
            tab = TabClass(self.tab_widget, self.db_path)
            tab._manager = self          # 供 Tab 取得其他 Tab（如還原後清快取）
            tab.setup(idx)
            self.tabs[idx] = tab

        # 瀏覽頁三表：用啟動預查資料分段建表，逐表更新載入進度條（65~100%）。
        # 建表必須在主執行緒，故放在此處（非背景 worker）；processEvents 讓進度條即時重繪。
        from PySide6.QtWidgets import QApplication
        from lib.loading_screen import BUILD_STEPS
        browse = self.tabs.get(self._IDX_DBBROWSE)
        if browse and hasattr(browse, 'buildInitial'):
            bdata = (prefetch or {}).get('browse', {})
            for key, label, pct in BUILD_STEPS:
                if progress:
                    progress(label, pct)
                    QApplication.processEvents()
                browse.buildInitial(key, rows=bdata.get(key))
            browse.markLoaded()
            if progress:
                progress("完成", 100)
                QApplication.processEvents()

        if self.tab_widget:
            self.tab_widget.setCurrentIndex(tab_index)
            self.tab_widget.currentChanged.connect(self._onTabChanged)
            self._prev_tab_index = tab_index
            # 分頁列右上角 ? 鈕（依當前頁開說明）＋ 各欄位 tooltip
            from ui_utils import attachHelpButton
            attachHelpButton(self.tab_widget, self.window)

        # 標題隨身份切換
        self._base_title = "公文管理系統"
        self._updateTitle(AuthManager.instance().current_role)
        AuthManager.instance().role_changed.connect(self._updateTitle)

        # 閒置逾時（分）可於設定頁「系統設定」調整，存 App_Settings；
        # 啟動時讀一次（改值須重啟生效），讀不到／不合法走預設（登出 10、關閉 14.5），
        # 0＝停用該機制（不啟動計時器）。自動登出：僅管理者／歸檔管理計時。
        from lib.db_utils import getIdleTimeoutsMs
        logout_ms, close_ms = getIdleTimeoutsMs(self.db_path)
        self._IDLE_TIMEOUT_MS = logout_ms
        self._idle_timer = QTimer(self.window)
        self._idle_timer.setSingleShot(True)
        self._idle_timer.timeout.connect(self._onIdleTimeout)
        # 閒置自動關閉整支程式（不分身分，一律計時）。
        # ⚠️ 預設 14.5 分刻意設在 Windows（AD 部署）15 分鐘鎖螢幕之前：DB／鎖檔在
        # SMB 網路碟，本程式須趕在系統把畫面切回登入前先關閉、清掉 dbfile.lock，
        # 否則 A 的程式在鎖螢幕後仍於背景續跑並更新心跳，會一直卡住別台電腦的 B 登入。
        # 現場調整此值時務必維持「低於該單位鎖螢幕時間」（此約束不放 UI，維護者默契）；
        # 設 0 停用時同樣要自行承擔上述 SMB 鎖檔風險。
        self._CLOSE_TIMEOUT_MS = close_ms
        # 閒置關閉分兩段：關閉前 _CLOSE_WARN_MS 先亮紅色橫幅並每秒倒數，歸零才真正
        # 關閉，給使用者搶救未送出輸入的機會（任何操作即取消）。關閉「總時限」不變，
        # 故不影響搶在鎖螢幕前關閉的鐵則（見 _onIdleClose 註解）。
        self._close_timer = QTimer(self.window)      # 前段：計到「開始警示」
        self._close_timer.setSingleShot(True)
        self._close_timer.timeout.connect(self._onIdleWarn)
        self._countdown_timer = QTimer(self.window)  # 後段：每秒倒數
        self._countdown_timer.setInterval(1000)
        self._countdown_timer.timeout.connect(self._onCountdownTick)
        self._buildIdleBanner()
        if self._CLOSE_TIMEOUT_MS > 0:
            self._resetCloseTimer()
        self._installIdleFilter()

    _CLOSE_WARN_MS = 90 * 1000   # 關閉前多久開始倒數警示（技術參數，不放 UI）

    def _buildIdleBanner(self):
        """在主視窗中央 layout 頂端（QTabWidget 之上）插一條隱藏紅色橫幅。
        置於分頁之外＝應用程式層級，不論停在哪個 Tab 都看得見。"""
        from PySide6.QtWidgets import QLabel
        self._idle_banner = QLabel("")
        self._idle_banner.setStyleSheet(
            "QLabel { background-color: #fdecea; color: #c0392b; "
            "border: 1px solid #e74c3c; border-radius: 6px; "
            "padding: 8px 12px; font-weight: 600; }")
        self._idle_banner.setAlignment(Qt.AlignCenter)
        self._idle_banner.setVisible(False)
        central = self.window.centralWidget()
        lay = central.layout() if central else None
        if lay:
            lay.insertWidget(0, self._idle_banner)

    def _resetCloseTimer(self):
        """使用者有操作時重設閒置關閉：停倒數、藏橫幅、重新計到警示點。0＝停用。"""
        self._countdown_timer.stop()
        if getattr(self, "_idle_banner", None):
            self._idle_banner.setVisible(False)
        if self._CLOSE_TIMEOUT_MS > 0:
            pre = max(0, self._CLOSE_TIMEOUT_MS - self._CLOSE_WARN_MS)
            self._close_timer.start(pre)

    def _onIdleWarn(self):
        """前段到點：亮橫幅並啟動每秒倒數。倒數秒數＝警示視窗長度
        （關閉總時限＝前段＋警示段，維持不變）。"""
        warn_portion = min(self._CLOSE_WARN_MS, self._CLOSE_TIMEOUT_MS)
        self._countdown_remaining = max(1, round(warn_portion / 1000))
        self._updateIdleBanner()
        if getattr(self, "_idle_banner", None):
            self._idle_banner.setVisible(True)
        self._countdown_timer.start()

    def _onCountdownTick(self):
        self._countdown_remaining -= 1
        if self._countdown_remaining <= 0:
            self._countdown_timer.stop()
            self._onIdleClose()
            return
        self._updateIdleBanner()

    def _updateIdleBanner(self):
        if getattr(self, "_idle_banner", None):
            self._idle_banner.setText(
                f"閒置過久，系統將於 {self._countdown_remaining} 秒後自動關閉，"
                "移動滑鼠或按任意鍵即可繼續使用。")

    def _updateTitle(self, role):
        suffix = {'admin': '管理者模式', 'archive': '歸檔管理'}.get(role, '一般使用者')
        self.window.setWindowTitle(f"{self._base_title}  [{suffix}]  - v{__version__}")
        # 登入時啟動計時，登出時停掉（管理者與歸檔管理皆計時）；0＝停用
        if hasattr(self, '_idle_timer'):
            if role in ('admin', 'archive') and self._IDLE_TIMEOUT_MS > 0:
                self._idle_timer.start(self._IDLE_TIMEOUT_MS)
            else:
                self._idle_timer.stop()

    def _installIdleFilter(self):
        """安裝全域事件過濾器，監聽使用者操作以重設閒置計時。"""
        from PySide6.QtCore import QObject, QEvent

        mgr = self
        class _IdleFilter(QObject):
            def eventFilter(self, obj, ev):
                t = ev.type()
                if t in (QEvent.MouseButtonPress, QEvent.MouseMove,
                         QEvent.KeyPress, QEvent.Wheel):
                    # 任何操作都重設「自動關閉」計時（含停倒數／藏橫幅；0＝停用不計時）
                    if mgr._CLOSE_TIMEOUT_MS > 0:
                        mgr._resetCloseTimer()
                    # 「自動登出」計時僅管理者／歸檔管理
                    if AuthManager.instance().is_manager() and mgr._IDLE_TIMEOUT_MS > 0:
                        mgr._idle_timer.start(mgr._IDLE_TIMEOUT_MS)
                return False

        self._idle_filter = _IdleFilter()
        from PySide6.QtWidgets import QApplication
        QApplication.instance().installEventFilter(self._idle_filter)

    def _onIdleTimeout(self):
        if AuthManager.instance().is_manager():
            AuthManager.instance().logout()
            mins = self._IDLE_TIMEOUT_MS / 60000  # 分鐘數可設定，訊息須帶實際值（勿寫死）
            msgInfo("自動登出",
                    f"閒置已超過 {mins:g} 分鐘，已自動登出，請重新登入。", self.window)

    def _onIdleClose(self):
        # 閒置 14 分半自動關閉整支程式（靜默，僅 error.log 留痕）。
        # 用 os._exit 硬關，不走 app.quit()：若此刻有 modal exec()（HELP／確認框／
        # 編輯彈窗／原生檔案對話框）開著，quit() 只會退掉最內層那個迴圈、關不掉主程式
        # （且 _close_timer 為 single-shot、已觸發過不再重啟＝自動關閉就此失效）。
        # os._exit 不受巢狀事件迴圈影響，一定結束；但 aboutToQuit／atexit 不會跑到，
        # 故結束前先手動清掉自己的鎖檔。
        import os
        _mins = self._CLOSE_TIMEOUT_MS / 60000  # 分鐘數可設定，log 帶實際值（勿寫死）
        logging.error(f"閒置已超過 {_mins:g} 分鐘，自動關閉程式。")
        cb = getattr(self, "_cleanup_lock_cb", None)
        if cb:
            try:
                cb()
            except Exception:
                pass
        logging.shutdown()
        os._exit(0)

    _IDX_SETTINGS = 8          # 資料庫設定 Tab index
    _IDX_DBBROWSE = 6          # 資料庫瀏覽 Tab index
    _IDX_AUDIT    = 9          # 操作紀錄 Tab index

    def _onTabChanged(self, index):
        from ui_utils import autoResizeTable
        tab_obj = self.tabs.get(index)
        if not tab_obj:
            self._prev_tab_index = index
            return

        # 從設定 Tab 切出來：先處理未儲存的排序變更（D3c）
        settings_tab = self.tabs.get(self._IDX_SETTINGS)
        if (self._prev_tab_index == self._IDX_SETTINGS
                and settings_tab
                and hasattr(settings_tab, '_promptUnsaved')):
            settings_tab._promptUnsaved(context="leave")

        # 只有「從設定 Tab 切出來 且 有實際改過資料」才刷新參照表
        # 一次刷新所有 Tab，避免之後切其他 Tab 時 dirty 已被清掉
        if (self._prev_tab_index == self._IDX_SETTINGS
                and settings_tab
                and getattr(settings_tab, '_ref_dirty', False)):
            for idx, t in self.tabs.items():
                if idx != self._IDX_SETTINGS:
                    # 通知瀏覽/歸檔頁：參照表改過 → on_activated 內就地輕量刷 ref 欄
                    setattr(t, "_ref_changed", True)
                    t.on_activated()
            settings_tab._ref_dirty = False

        # 切「到」設定 Tab：重載當前子頁（放棄未存排序、與 DB 同步）
        if (index == self._IDX_SETTINGS
                and settings_tab
                and hasattr(settings_tab, 'on_activated')):
            settings_tab.on_activated()

        # 切到資料庫瀏覽／操作紀錄：前者比對各表資料指紋，後者重載稽核紀錄，
        # 讓其他頁的新增、修改、刪除在切頁後立即反映。
        if (index in (self._IDX_DBBROWSE, self._IDX_AUDIT)
                and tab_obj
                and hasattr(tab_obj, 'on_activated')):
            tab_obj.on_activated()

        self._prev_tab_index = index

        def _resize():
            # 150ms 內若已切到別的 Tab，放棄（避免 resize 到舊 Tab）
            if self.tab_widget.currentIndex() != index:
                return
            for t in tab_obj.get_tables():
                if t and t.columnCount() > 0:
                    autoResizeTable(t)

        def _setFocus():
            # 同上守門：延遲期間切走則不搶焦點
            if self.tab_widget.currentIndex() != index:
                return
            w = tab_obj.get_focus_widget()
            if w:
                w.setFocus()

        QTimer.singleShot(150, _resize)
        QTimer.singleShot(50, _setFocus)


# ──────────────────────────────────────────────
# MainMenu：主選單
# ──────────────────────────────────────────────
class MainMenu:
    BTN_MAP = {
        'btn_report_assignment':  0,
        'btn_receive_assignment': 1,
        'btn_report_case':        2,
        'btn_reward':             3,
        'btn_ticket':             4,
        'btn_generate_receipt':   5,
        'btn_dbbrowse':           6,
        'btn_archive':            7,
        'btn_settings':           8,
        'btn_audit':              9,
    }

    # 各功能磚格圖示（qrc 別名 :/menu/，於程式內套用以免 QUiLoader 解析 resource 問題）
    ICON_MAP = {
        'btn_report_assignment':  ':/menu/dispatch.svg',
        'btn_receive_assignment': ':/menu/receive.svg',
        'btn_report_case':        ':/menu/report.svg',
        'btn_reward':             ':/menu/reward.svg',
        'btn_ticket':             ':/menu/ticket.svg',
        'btn_generate_receipt':   ':/menu/print.svg',
        'btn_dbbrowse':           ':/menu/browse.svg',
        'btn_archive':            ':/menu/archive.svg',
        'btn_settings':           ':/menu/settings.svg',
        'btn_audit':              ':/menu/audit.svg',
    }

    def __init__(self):
        from PySide6.QtGui import QIcon
        from PySide6.QtCore import QSize

        self.ui = loadUi(getResourcePath("layouts/main_menu.ui"))
        if not self.ui:
            sys.exit(1)

        self.selected_tab = -1

        # 版本號顯示（單一來源 lib/version.py）
        version_label = getattr(self.ui, 'versionLabel', None)
        if version_label:
            version_label.setText(f"Ver: {__version__}")

        for btn_name, idx in self.BTN_MAP.items():
            btn = getattr(self.ui, btn_name, None)
            if btn:
                icon_path = self.ICON_MAP.get(btn_name)
                if icon_path:
                    btn.setIcon(QIcon(icon_path))
                    btn.setIconSize(QSize(30, 30))
                btn.clicked.connect(lambda checked=False, i=idx: self._onSelect(i))

        btn_exit = getattr(self.ui, 'btn_exit', None)
        if btn_exit:
            btn_exit.clicked.connect(self.ui.reject)

    def _onSelect(self, index):
        if index not in DocumentManager.TAB_CLASSES:
            msgInfo("提示", "此功能尚未開放，敬請期待")
            return
        self.selected_tab = index
        self.ui.accept()


# ──────────────────────────────────────────────
# 進入點
# ──────────────────────────────────────────────
if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setFont(QFont("Microsoft JhengHei", 14))
    app.setStyleSheet(APPLE_STYLE)

    from PySide6.QtGui import QIcon
    icon_path = getResourcePath("res/buttons/police_badge.svg")
    app.setWindowIcon(QIcon(icon_path))

    db_path = getResourcePath("dbfile.db")

    # ── 磁碟空間檢查（純勸導，不擋死）：暫存碟（onefile 解壓）＋ DB 碟（本體與備份）
    #    兩者可能不同顆（DB 常在網路碟），各查各的門檻；訊息帶實際磁碟代號。
    import shutil as _shutil
    from lib.db_utils import diskSpaceChecks as _diskSpaceChecks
    from ui_utils import confirmBox as _confirmBox
    _low_disks = []
    for _root, _need in _diskSpaceChecks(db_path):
        try:
            _free = _shutil.disk_usage(_root).free
        except OSError:
            continue   # 讀不到（如網路碟瞬斷）不勸導，交後續錯誤處理
        if _free < _need:
            _drive = os.path.splitdrive(os.path.abspath(_root))[0] or _root
            _low_disks.append(f"{_drive} 可用空間僅剩 {_free // (1024 * 1024)} MB")
    if _low_disks and not _confirmBox(
            "磁碟空間不足",
            "\n".join(_low_disks),
            confirm_text="仍要開啟", cancel_text="取消離開",
            confirm_danger=True, default_confirm=False,
            informative="空間不足可能導致儲存、備份失敗，且錯誤可能無法留下紀錄。\n"
                        "建議清理磁碟空間後再開啟。"):
        sys.exit(0)

    # ── APP 層軟性互斥：開啟時偵測是否已有人在用（純勸導，不擋 DB）──
    from datetime import datetime as _dt
    from lib import app_lock as _lock
    _lock_path = _lock.lock_file_path(db_path)
    _machine, _user, _pid = _lock.current_identity()
    _opened_iso = _dt.now().isoformat(timespec="seconds")

    _existing = _lock.read_lock(_lock_path)
    if _existing and not _lock.is_stale(
            _existing.get("heartbeat", ""), _dt.now().isoformat(timespec="seconds")):
        _who = _existing.get("user") or "其他使用者"
        _mc = _existing.get("machine") or "其他電腦"
        _since = (_existing.get("opened") or "").replace("T", " ")[:16]
        # 自動關閉分鐘數撈 DB（idle_close_min，可設定；勿寫死）；設 0＝停用則不顯示該句
        from lib.db_utils import getIdleTimeoutsMs as _getIdleMs
        _close_min = _getIdleMs(db_path)[1] / 60000
        _idle_info = (f"\n開啟後若閒置約 {_close_min:g} 分鐘，程式將自動關閉。"
                      if _close_min > 0 else "")
        if not _confirmBox(
                "系統使用中",
                f"{_who}（電腦 {_mc}）自 {_since} 起正在使用本系統。",
                confirm_text="仍要開啟", cancel_text="取消離開",
                confirm_danger=True, default_confirm=False,
                informative="多人同時編輯可能造成資料毀損，建議稍後再開。" + _idle_info):
            sys.exit(0)

    # 寫入自己的鎖檔並啟動心跳；正常結束時清掉（含閒置自動關）。
    _lock.write_lock(_lock_path, _machine, _user, _opened_iso,
                     _dt.now().isoformat(timespec="seconds"), _pid)

    # ── 資料庫損毀早期偵測（quick_check）＋平時自動備份 ──
    # ⚠️ 業界慣例：先驗完整性、再做結構遷移（ensureSchema）——
    #   任何 DDL 寫入都以「檔案結構健康」為前提；對已 malformed 的檔做 CREATE/ALTER，
    #   最壞情況會改寫部分頁面、增加後續搶救難度。
    # ⚠️ 檢查亦在備份「之前」：DB 若已損毀仍去備份，會把壞檔輪替進 GFS、擠掉還好的
    #   舊備份。偵測到損毀即「跳過當日備份」（保住好備份），並在載入之前跳開機救援
    #   對話框讓使用者還原——「備份還原」子頁在程式內，DB 壞到開不了時進不去，故把
    #   還原路徑前移到此。不論還原與否都不繼續載入壞 DB（硬繼續只會在載入階段二次崩潰）。
    from lib import db_backup as _backup
    if not _backup.quick_check(db_path) or not _backup.deep_check_if_due(db_path):
        from ui_utils.rescue_dialog import runStartupRescue
        runStartupRescue(db_path)   # 內部處理還原＋提示；不論結果都結束程式
        sys.exit(0)

    # ── 冪等確保附加式結構（建表／加欄，只增不改；失敗不擋開程式）──
    from lib import db_schema as _schema
    _schema.ensureSchema(db_path)

    # ── 平時自動備份（GFS 輪替，純靜默）──
    from lib.db_utils import getBackupSecondDir as _getBackupSecondDir
    _second = _getBackupSecondDir(db_path)
    _backup.run_auto_backup(db_path, extra_dirs=[_second] if _second else None)

    def _heartbeat():
        _lock.write_lock(_lock_path, _machine, _user, _opened_iso,
                         _dt.now().isoformat(timespec="seconds"), _pid)

    _hb_timer = QTimer()
    _hb_timer.timeout.connect(_heartbeat)
    _hb_timer.start(_lock.HEARTBEAT_MS)

    # 清鎖檔：aboutToQuit 蓋正常關窗/自動關閉；atexit 補蓋 sys.exit（主選單離開、
    # 建表失敗）等不經 Qt quit 的路徑。當機/斷電兩者皆蓋不到，靠心跳失效自癒。
    def _cleanup_lock():
        _lock.remove_lock(_lock_path, machine=_machine, pid=_pid)
    app.aboutToQuit.connect(_cleanup_lock)
    import atexit
    atexit.register(_cleanup_lock)

    from lib.loading_screen import LoadingScreen

    # _refs 持有 menu / loading / mgr 引用，防止被 GC 回收導致閃退
    _refs = []

    def _on_data_ready(results):
        # 進度條期間就把整個主視窗建好（含三表建表）；建完才出主選單，選完秒進。
        mgr = DocumentManager(tab_index=0, prefetch=results, progress=loading.setStep)
        _refs.append(mgr)
        mgr._cleanup_lock_cb = _cleanup_lock   # 閒置自動關閉 os._exit 前用它清鎖檔
        loading.finishAndClose()
        if not (hasattr(mgr, 'window') and mgr.window):
            sys.exit(1)
        mgr.window.setWindowIcon(QIcon(icon_path))

        # 一切就緒後才顯示主選單，使用者選功能後直接切到該頁
        menu = MainMenu()
        _refs.append(menu)
        # 打包版偶爾因 Windows 前景鎖，主選單被壓到別的視窗後面：
        # exec() 進事件迴圈、dialog 顯示後立刻清最小化狀態並搶到最前。
        def _bringMenuFront():
            w = menu.ui
            w.setWindowState((w.windowState() & ~Qt.WindowMinimized) | Qt.WindowActive)
            w.raise_()
            w.activateWindow()
        QTimer.singleShot(0, _bringMenuFront)
        if menu.ui.exec() != QDialog.Accepted or menu.selected_tab < 0:
            sys.exit(0)
        mgr.tab_widget.blockSignals(True)
        mgr.tab_widget.setCurrentIndex(menu.selected_tab)
        mgr.tab_widget.blockSignals(False)
        mgr.window.show()
        QTimer.singleShot(50, lambda: mgr._onTabChanged(menu.selected_tab))

    def _on_load_failed(exc_type, exc_value):
        # 背景載入執行緒例外（如磁碟空間不足）：乾淨顯示訊息再結束，不讓程式悶死無聲消失。
        from lib.db_utils import friendlyErrorMessage as _friendly
        logging.error("".join(traceback.format_exception(exc_type, exc_value, exc_value.__traceback__)))
        from ui_utils import msgCritical as _msgCritical
        _msgCritical("系統錯誤", _friendly(exc_type, exc_value))
        sys.exit(1)

    loading = LoadingScreen(db_path)
    _refs.append(loading)
    loading.dataReady.connect(_on_data_ready)
    loading.loadFailed.connect(_on_load_failed)
    loading.show()
    # 開機前景：LOADING 已不掛 always-on-top（否則會壓住載入/建表階段的錯誤 modal），
    # 改以 raise_()+activateWindow() 拉到最前（比照主選單前景鎖，見 DEVELOPER §1）。
    loading.raise_()
    loading.activateWindow()

    sys.exit(app.exec())
