import sys
import os

from PySide6.QtWidgets import QWidget, QLabel, QProgressBar, QVBoxLayout
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QPixmap

from lib.db_utils import getResourcePath


# ── 載入步驟定義（說明, 完成後的 %）──────────────────────────
# 背景執行緒（LoadWorker）負責 0~64%（資源、DB 連線、三表 SQL 讀取）；
# 65~100% 為主執行緒分段建表，由 DocumentManager 經 setStep 驅動（見 BUILD_STEPS）。
LOAD_STEPS = [
    ("偵測暫存區就緒...",            2),
    ("載入資源檔...",                3),
    ("套用介面樣式...",              7),
    ("載入主選單介面...",           11),
    ("連線資料庫...",               15),
    ("載入人員對照表...",           19),
    ("載入部門與案類資料...",       22),
    ("讀取交辦單資料...",           25),
    ("讀取刑案資料...",             30),
    ("讀取一般陳報資料...",         35),
    ("載入操作介面...",             38),
]

# 主執行緒分段建表步驟（DocumentManager 依此回報進度）；完成 100 另由呼叫端送出
BUILD_STEPS = [
    ("task", "建立交辦單清單...",   42),
    ("crim", "建立刑案清單...",     57),
    ("gen",  "建立一般陳報清單...", 68),
]


class LoadWorker(QThread):
    """
    在背景執行緒依序執行載入步驟。
    每個步驟完成後發出 step_done(desc, percent) 信號。
    全部完成後發出 finished(results) 信號，results 包含載入好的物件。
    """
    step_done = Signal(str, int)   # (步驟說明, %)
    finished  = Signal(object)     # 載入完成，回傳結果 dict
    failed    = Signal(object, object)   # (exc_type, exc_value)，背景執行緒例外（如磁碟空間不足）

    def __init__(self, db_path):
        super().__init__()
        self.db_path = db_path

    def run(self):
        # QThread 內未捕捉例外不保證乾淨走到 sys.excepthook（容易把整支程式悶死、
        # 不留任何紀錄），故全段包一層，失敗改用訊號回主執行緒乾淨顯示訊息再結束。
        try:
            self._run()
        except Exception as exc:
            self.failed.emit(type(exc), exc)

    def _run(self):
        import time
        # ⚠️ DEBUG 用：每個步驟至少停 2 秒，方便觀察進度條
        # 正式上線前把 DEBUG_DELAY 改為 0
        DEBUG_DELAY = 0.05

        results = {}

        # 步驟 1：偵測 _MEIPASS 暫存區就緒
        if getattr(sys, 'frozen', False):
            _ = os.path.exists(sys._MEIPASS)
        self.step_done.emit(*LOAD_STEPS[0])
        time.sleep(DEBUG_DELAY)

        # 步驟 2：載入 Qt Resource
        from res import resources_rc  # noqa
        self.step_done.emit(*LOAD_STEPS[1])
        time.sleep(DEBUG_DELAY)

        # 步驟 3：套用樣式（回主執行緒才能真正套，這裡先 import）
        from lib.theme import APPLE_STYLE
        results['style'] = APPLE_STYLE
        self.step_done.emit(*LOAD_STEPS[2])
        time.sleep(DEBUG_DELAY)

        # 步驟 4：載入主選單 UI
        results['menu_ui_path'] = getResourcePath("layouts/main_menu.ui")
        self.step_done.emit(*LOAD_STEPS[3])
        time.sleep(DEBUG_DELAY)

        # 步驟 5：連線 DB
        import sqlite3
        conn = sqlite3.connect(self.db_path)
        self.step_done.emit(*LOAD_STEPS[4])
        time.sleep(DEBUG_DELAY)

        # 步驟 6：載入人員對照表
        results['personnel'] = conn.execute(
            "SELECT staff_id, staff_name FROM Ref_Personnel "
            "WHERE is_active=1 ORDER BY staff_id"
        ).fetchall()
        self.step_done.emit(*LOAD_STEPS[5])
        time.sleep(DEBUG_DELAY)

        # 步驟 7：載入部門、案類（conn 先不關，下面要查三表）
        results['depts'] = conn.execute(
            "SELECT dept_id, dept_name FROM Ref_Departments ORDER BY dept_id"
        ).fetchall()
        results['case_types'] = conn.execute(
            "SELECT case_type_id, case_type_name FROM Ref_CaseTypes ORDER BY case_type_id"
        ).fetchall()
        self.step_done.emit(*LOAD_STEPS[6])
        time.sleep(DEBUG_DELAY)

        # 步驟 8~10：背景預讀三張瀏覽表的完整資料（純 SQL，不碰 Qt）。
        # 主執行緒之後用這份資料直接建表，免再查 DB。
        from tabs.tab_dbbrowse import queryBrowseRows
        browse = {}
        for i, key in enumerate(("task", "crim", "gen")):
            try:
                browse[key] = queryBrowseRows(conn, key)
            except Exception:
                browse[key] = None   # 預讀失敗 → 主執行緒 fallback 就地查
            self.step_done.emit(*LOAD_STEPS[7 + i])
            time.sleep(DEBUG_DELAY)
        results['browse'] = browse
        conn.close()

        # 步驟 11：預熱 Tab 類別 import + Layout 路徑
        from tabs import TabDispatch, TabReceive, TabReport  # noqa
        results['tabs'] = (TabDispatch, TabReceive, TabReport)
        results['layout1_path'] = getResourcePath("layouts/Layout1.ui")
        self.step_done.emit(*LOAD_STEPS[10])
        time.sleep(DEBUG_DELAY)

        # 背景階段完成 → 交主執行緒分段建表（65~100% 由 DocumentManager 驅動）
        self.finished.emit(results)


class LoadingScreen(QWidget):
    """
    Loading 橫幅視窗。
    - 置中於螢幕
    - 上方橫幅圖片（等比例縮放至寬 700px）
    - 下方進度區 40px：說明文字、百分比、進度條
    - 背景讀取完成後發出 dataReady（不自動關閉），由主執行緒分段建表；
      建表期間呼叫 setStep 更新進度條，全部完成後呼叫 finishAndClose 關閉。
    """
    dataReady = Signal(object)
    loadFailed = Signal(object, object)   # (exc_type, exc_value)，背景載入失敗轉發給呼叫端

    WIN_W = 700
    WIN_H = 319   # 圖片等比例高度 279 + 進度區 40

    def __init__(self, db_path):
        super().__init__()
        self.db_path = db_path
        self._setup_ui()
        self._start_worker()

    def _setup_ui(self):
        from PySide6.QtWidgets import QHBoxLayout, QApplication

        self.setFixedSize(self.WIN_W, self.WIN_H)
        # ⚠️ 不掛 WindowStaysOnTopHint：splash 不應凌駕自己程式的 modal 錯誤視窗。
        # 載入/建表階段若冒錯（excepthook 或各 Tab setup 的 DB 錯誤 modal），置頂的
        # LOADING 會把錯誤視窗壓在後面、使用者看不到也點不到。開機前景改由 main.py
        # show() 後 raise_()+activateWindow() 保證（比照主選單前景鎖，見 DEVELOPER §1）。
        self.setWindowFlags(Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground, False)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ── 橫幅圖片 ──────────────────────────────────────
        self.banner_label = QLabel()
        self.banner_label.setFixedSize(self.WIN_W, 279)
        self.banner_label.setAlignment(Qt.AlignCenter)
        self.banner_label.setStyleSheet("background-color: #dde7f7;")

        banner_path = getResourcePath("res/buttons/banner.png")
        if os.path.exists(banner_path):
            pix = QPixmap(banner_path).scaled(
                self.WIN_W, 279,
                Qt.IgnoreAspectRatio,
                Qt.SmoothTransformation
            )
            self.banner_label.setPixmap(pix)
        else:
            self.banner_label.setText("公文收發管理系統")
            self.banner_label.setStyleSheet(
                "background-color: #5b8db8; color: white; font-size: 22pt; font-weight: 700;"
            )
        layout.addWidget(self.banner_label)

        # ── 進度區 ────────────────────────────────────────
        progress_widget = QWidget()
        progress_widget.setFixedHeight(40)
        progress_widget.setStyleSheet("background-color: #dde7f7;")
        p_layout = QVBoxLayout(progress_widget)
        p_layout.setContentsMargins(20, 5, 20, 5)
        p_layout.setSpacing(2)

        row = QWidget()
        row.setStyleSheet("background: transparent;")
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)

        self.status_label = QLabel("啟動中...")
        self.status_label.setStyleSheet("color: #4a6fa5; font-size: 10pt;")

        self.pct_label = QLabel("2%")
        self.pct_label.setStyleSheet("color: #4a6fa5; font-size: 10pt; font-weight: 600;")
        self.pct_label.setAlignment(Qt.AlignRight)

        row_layout.addWidget(self.status_label)
        row_layout.addWidget(self.pct_label)
        p_layout.addWidget(row)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(2)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setFixedHeight(6)
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                background-color: #c5d5ea;
                border-radius: 3px;
                border: none;
            }
            QProgressBar::chunk {
                background-color: #4a6fa5;
                border-radius: 3px;
            }
        """)
        p_layout.addWidget(self.progress_bar)
        layout.addWidget(progress_widget)

        # ── 置中螢幕 ──────────────────────────────────────
        screen = QApplication.primaryScreen().geometry()
        self.move(
            (screen.width()  - self.WIN_W) // 2,
            (screen.height() - self.WIN_H) // 2,
        )

    def _start_worker(self):
        self.worker = LoadWorker(self.db_path)
        self.worker.step_done.connect(self._on_step)
        self.worker.finished.connect(self._on_finished)
        self.worker.failed.connect(self._on_failed)
        self.worker.start()

    def _on_failed(self, exc_type, exc_value):
        self.close()
        self.loadFailed.emit(exc_type, exc_value)

    def _on_step(self, desc, percent):
        self.progress_bar.setValue(percent)
        self.status_label.setText(desc)
        self.pct_label.setText(f"{percent}%")

    # 供主執行緒建表階段更新進度條（與背景步驟共用同一條）
    def setStep(self, desc, percent):
        self._on_step(desc, percent)

    def finishAndClose(self):
        self.close()

    def _on_finished(self, results):
        # 背景讀取完成：不關閉，交主執行緒分段建表
        self.dataReady.emit(results)
