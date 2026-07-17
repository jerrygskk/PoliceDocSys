"""
settings_panels.py — 設定頁「系統設定」子頁的嵌入式面板

包含（皆為 QGroupBox，掛進 page_system 的 systemLayout，各自帶「儲存」）：
  - ArchiveRootPanel   歸檔資料夾（年度層 UNC + 刑案/一般子夾名；admin/archive 皆可改）
  - PrintTitlePanel    簽收表標題（4 欄自訂文字；僅 admin）
  - IdleTimeoutPanel   閒置逾時（自動登出／強制關閉，分；僅 admin，重啟生效）
  - InputLockPanel     唯讀設定（三表新增鎖；僅 admin；即時生效）
  - BackupPanel        自動備份（第二備份位置／異地副本；僅 admin；下次開啟生效）

由 ArchiveRootDialog / PrintTitleDialog（settings_dialogs.py，已移除）改寫而來，
儲存邏輯與稽核行為不變。面板值以 reload() 重讀 DB（切入子頁時呼叫）。
"""
import os

from PySide6.QtCore    import Qt
from PySide6.QtWidgets import (
    QGroupBox, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QLineEdit, QPushButton, QComboBox, QCheckBox,
    QFileDialog, QSpinBox, QDoubleSpinBox, QAbstractSpinBox,
    QRadioButton, QButtonGroup,
)

from .ui_common import msgWarning

# ── 面板共用樣式 ───────────────────────────────────────────────────
# 白卡片＋標題浮框；子元件顏色皆明設（§2 雷：新 Widget 繼承全域深色會看不見）。
# :disabled 一律給灰（§2 雷：無 :disabled 不會變灰）。
_PANEL_SS = """
    QGroupBox {
        background-color: #ffffff;
        border: 1px solid #d1d1d6;
        border-radius: 10px;
        margin-top: 14px;
        padding-top: 8px;
        font-size: 14pt;
        font-weight: 600;
        color: #1c1c1e;
    }
    QGroupBox::title {
        subcontrol-origin: margin;
        left: 12px;
        padding: 0 6px;
        background-color: #ffffff;
    }
    QGroupBox:disabled { color: #aeaeb2; }
    QLabel { color: #3a3a3c; background: transparent;
             font-size: 13pt; font-weight: 400; }
    QLabel:disabled { color: #c5c5c9; }
    QLineEdit {
        background-color: #ffffff; color: #000000;
        border: 1px solid #cccccc; border-radius: 4px; padding: 4px 8px;
        font-size: 13pt; font-weight: 400;
    }
    QLineEdit:focus { border: 1px solid #8fa8c8; }
    QLineEdit:disabled { background-color: #f2f2f7; color: #aeaeb2; }
    QComboBox {
        background-color: #ffffff; color: #000000;
        border: 1px solid #cccccc; border-radius: 4px; padding: 4px 8px;
        font-size: 13pt; font-weight: 400;
    }
    QComboBox:disabled { background-color: #f2f2f7; color: #aeaeb2; }
    QSpinBox, QDoubleSpinBox {
        background-color: #ffffff; color: #000000;
        border: 1px solid #cccccc; border-radius: 4px; padding: 4px 8px;
        font-size: 13pt; font-weight: 400;
    }
    QSpinBox:focus, QDoubleSpinBox:focus { border: 1px solid #8fa8c8; }
    QSpinBox:disabled, QDoubleSpinBox:disabled {
        background-color: #f2f2f7; color: #aeaeb2;
    }
"""

_HINT_SS = "color: #8e8e93; font-size: 11pt; font-weight: 400;"
_ERR_BORDER_SS = ("border: 1px solid #e74c3c; border-radius: 4px; "
                  "padding: 4px 8px; font-size: 13pt; font-weight: 400;")

# 儲存鈕：比照全 app 主要動作鈕（送出／歸檔）的墨藍樣式（theme.py「送出按鈕」）
_SAVE_SS = """
    QPushButton {
        background-color: #a1b4cb; color: #ffffff;
        border: none; border-radius: 8px;
        padding: 8px 24px; font-weight: 600;
    }
    QPushButton:hover    { background-color: #4977b1; }
    QPushButton:pressed  { background-color: #39649a; }
    QPushButton:disabled { background-color: #d1d9e3; color: #ffffff; }
"""


def _save_row(layout, extra_left=None):
    """底部按鈕列：右對齊「儲存」，可選左側額外按鈕。回傳儲存鈕。
    左側額外鈕不設樣式，沿用 theme.py 通用 QPushButton（白底灰框）。
    儲存鈕平常反灰，有未存變更（isDirty）才亮起；存檔成功即回灰＝完成回饋，
    不另彈成功視窗。"""
    row = QHBoxLayout()
    if extra_left is not None:
        row.addWidget(extra_left)
    row.addStretch()
    btn_save = QPushButton("儲存")
    btn_save.setStyleSheet(_SAVE_SS)
    btn_save.setEnabled(False)
    # 面板嵌在頁面裡（非 Dialog），不設 default，避免頁上 Enter 誤觸存檔
    btn_save.setAutoDefault(False)
    btn_save.setDefault(False)
    row.addWidget(btn_save)
    layout.addLayout(row)
    return btn_save


class _SettingsPanel(QGroupBox):
    """系統設定四面板的共用基底。

    收斂原本各抄一份的 isDirty／_updateSaveBtn／reload 尾段（重設 dirty 基準）。
    子類別只需實作：
        _build()   建立 UI，並把儲存鈕存成 self._btn_save
        _values()  回傳「當前畫面值」（tuple 或 dict 皆可，供 != 比較）
        reload()   重讀 DB 值填入畫面，結尾呼叫 self._markLoaded()
    """

    def __init__(self, title, db_path, parent=None):
        super().__init__(title, parent)
        self.db_path = db_path
        self.setStyleSheet(_PANEL_SS)
        self._build()
        self.reload()

    def _markLoaded(self):
        """把 dirty 基準設為當前畫面值並更新儲存鈕（reload()/存檔成功後呼叫）。"""
        self._loaded = self._values()
        self._updateSaveBtn()

    def isDirty(self):
        """畫面值與最後載入/儲存值不同 → 有未存變更（切頁提示、儲存鈕亮灰用）。"""
        loaded = getattr(self, "_loaded", None)
        return loaded is not None and self._values() != loaded

    def _updateSaveBtn(self, *_):
        btn = getattr(self, "_btn_save", None)
        if not btn:
            return
        dirty = self.isDirty()
        # 存檔成功回灰前先取消按鈕焦點：停用「持有焦點的元件」時
        # Qt 會把焦點自動塞給 tab 順序的下一個輸入欄，游標會亂跳
        if not dirty and btn.hasFocus():
            btn.clearFocus()
        btn.setEnabled(dirty)


# ══════════════════════════════════════════════════════════════════
# 歸檔資料夾（admin / archive 皆可改）
# ══════════════════════════════════════════════════════════════════
class ArchiveRootPanel(_SettingsPanel):
    def __init__(self, db_path, parent=None):
        super().__init__("歸檔資料夾", db_path, parent)

    def _build(self):
        v = QVBoxLayout(self)
        v.setSpacing(10)
        v.setContentsMargins(16, 14, 16, 12)

        # 頂部說明：比照其他區塊（簽收表標題）的灰字小字格式
        hint = QLabel(
            "請選擇本年度的 PDF 掃描資料夾（至少需要有刑案資料夾和一般資料夾兩種分類），"
            "可使用本機儲存空間或網路空間(SMB)。\n"
            "使用網路空間時，選擇後會自動轉成網路路徑(如 \\\\PC-DATA\\掃描檔)，"
            "不受各電腦磁碟機代號（如 Z:）影響。")
        hint.setStyleSheet(_HINT_SS)
        hint.setWordWrap(True)
        v.addWidget(hint)

        # 路徑列：可編輯 UNC + 選擇鈕
        self.w_path = QLineEdit()
        self.w_path.setPlaceholderText("如：Z:\\案件掃描檔\\115年")
        btn_pick = QPushButton("選擇資料夾")
        row = QHBoxLayout()
        row.addWidget(self.w_path, 1)
        row.addWidget(btn_pick)
        v.addLayout(row)
        btn_pick.clicked.connect(self._pick)

        # 子夾對應：兩欄並排、固定寬（全寬下拉的箭頭會跑到最右邊，離標籤太遠）
        _COMBO_W = 340
        sub_row = QHBoxLayout()
        sub_row.setSpacing(24)
        self.cb_crim = QComboBox()
        self.cb_gen  = QComboBox()
        for cb, label in ((self.cb_crim, "刑案子資料夾"),
                          (self.cb_gen,  "一般子資料夾")):
            cb.setEditable(True)
            cb.lineEdit().setPlaceholderText("下拉或手動輸入資料夾名稱")
            cb.setFixedWidth(_COMBO_W)
            cell = QVBoxLayout()
            cell.setSpacing(4)
            cell.addWidget(QLabel(label))
            cell.addWidget(cb)
            sub_row.addLayout(cell)
        sub_row.addStretch()
        v.addLayout(sub_row)

        note = QLabel(
            "上列路徑將使用在「資料庫瀏覽」與「檔案歸檔」分頁，"
            "若未正確設定將無法開啟已歸檔檔案及使用歸檔功能。\n"
            "本路徑在新年度重置後須重新指定。")
        note.setStyleSheet(_HINT_SS)
        note.setWordWrap(True)
        v.addWidget(note)

        self._btn_save = _save_row(v)
        self._btn_save.clicked.connect(self._save)
        # 任一輸入變動 → 依 dirty 狀態亮/灰儲存鈕
        self.w_path.textChanged.connect(self._updateSaveBtn)
        self.cb_crim.currentTextChanged.connect(self._updateSaveBtn)
        self.cb_gen.currentTextChanged.connect(self._updateSaveBtn)

    def reload(self):
        """重讀 DB 值（切入系統設定子頁時呼叫，確保畫面與 DB 一致）。"""
        from lib.db_utils import getSetting, ARCHIVE_ROOT_KEY
        cur_root = getSetting(self.db_path, ARCHIVE_ROOT_KEY, "")
        cur_crim = getSetting(self.db_path, "archive_subdir_crim", "")
        cur_gen  = getSetting(self.db_path, "archive_subdir_gen", "")
        self.w_path.setText(cur_root)
        self.w_path.setStyleSheet("")
        for cb, cur in ((self.cb_crim, cur_crim), (self.cb_gen, cur_gen)):
            cb.blockSignals(True)
            cb.clear()
            if cur:
                cb.addItem(cur)
            cb.setCurrentText(cur)
            cb.blockSignals(False)
        # 以目前路徑（若可存取）預先列出子夾
        self._populateSubdirs(cur_root)
        self._markLoaded()

    def _values(self):
        return (self.w_path.text().strip(),
                self.cb_crim.currentText().strip(),
                self.cb_gen.currentText().strip())

    def _pick(self):
        from lib.db_utils import toUncPath
        start = self.w_path.text().strip()
        folder = QFileDialog.getExistingDirectory(
            self, "選擇本年度歸檔資料夾",
            start if os.path.isdir(start) else "")
        if not folder:
            return
        unc = toUncPath(folder)
        self.w_path.setText(unc if unc else folder.replace("/", "\\"))
        # 轉不出 UNC（非網路磁碟）→ 橘框提示請確認/改貼 UNC
        self.w_path.setStyleSheet("" if unc else "border: 1px solid #e67e22;")
        # 以實際可存取的本機路徑列子夾（剛選的代號路徑保證可達）
        self._populateSubdirs(folder)

    def _populateSubdirs(self, accessible_path):
        try:
            if accessible_path and os.path.isdir(accessible_path):
                subs = sorted(
                    d for d in os.listdir(accessible_path)
                    if os.path.isdir(os.path.join(accessible_path, d)))
            else:
                subs = []
        except Exception:
            subs = []
        for cb, guess in ((self.cb_crim, "刑"), (self.cb_gen, "一般")):
            cur = cb.currentText().strip()
            cb.blockSignals(True)
            cb.clear()
            for d in subs:
                cb.addItem(d)
            if cur and cur not in subs:
                cb.insertItem(0, cur)
            pick = cur or next((d for d in subs if guess in d), "")
            cb.setCurrentText(pick)
            cb.blockSignals(False)

    def _save(self):
        """存檔成功回 True、被擋/中止回 False（切頁「儲存後切換」流程據此決定去留）。"""
        from lib.auth_manager import AuthManager
        from lib.db_utils import (setSetting, getSetting, ARCHIVE_ROOT_KEY,
                                  clearPdfIndexCache, writeAuditSafe, buildDetail)
        # 權限 gate：admin / archive 皆可改（比照原 Dialog 開放範圍）
        if not AuthManager.instance().is_manager():
            return False
        root = self.w_path.text().strip().replace("/", "\\").rstrip("\\")
        if not root:
            self.w_path.setStyleSheet(_ERR_BORDER_SS)
            return False
        old_root = (getSetting(self.db_path, ARCHIVE_ROOT_KEY, "") or "").strip()
        setSetting(self.db_path, ARCHIVE_ROOT_KEY, root)
        setSetting(self.db_path, "archive_subdir_crim", self.cb_crim.currentText().strip())
        setSetting(self.db_path, "archive_subdir_gen",  self.cb_gen.currentText().strip())
        clearPdfIndexCache()
        # 歸檔路徑變更稽核（路徑實際改變才記）
        if root != old_root:
            am = AuthManager.instance()
            writeAuditSafe(self.db_path, role=am.current_role, action="CONFIG",
                           operator=am.actor_name(),
                           detail=buildDetail("系統", "修改",
                                              f"歸檔路徑：{old_root or '（未設定）'} → {root}"))
        self.reload()   # 帶回正規化後的存值＋重設 dirty 基準（儲存鈕隨之回灰）
        return True


# ══════════════════════════════════════════════════════════════════
# 簽收表標題（僅 admin；archive 整塊反灰）
# ══════════════════════════════════════════════════════════════════
class PrintTitlePanel(_SettingsPanel):
    # 字數上限（全形字）：實量 PDF 版面得出。標題列寬→36；現行犯註記在窄的簽收欄→14。
    _TITLE_MAX = 36
    _NOTE_MAX  = 14

    def __init__(self, db_path, parent=None):
        super().__init__("簽收表標題", db_path, parent)

    def _fields(self):
        # (key, 標籤, maxLength)
        from lib.db_utils import PRINT_TITLE_KEYS
        return [
            (PRINT_TITLE_KEYS["task"], "交辦單標題", self._TITLE_MAX),
            (PRINT_TITLE_KEYS["crim"], "刑案陳報標題", self._TITLE_MAX),
            (PRINT_TITLE_KEYS["gen"],  "一般陳報標題", self._TITLE_MAX),
            (PRINT_TITLE_KEYS["reward"], "敘獎標題", self._TITLE_MAX),
            (PRINT_TITLE_KEYS["note"], "現行犯免簽收註記", self._NOTE_MAX),
        ]

    def _build(self):
        from lib.db_utils import PRINT_TITLE_DEFAULTS

        v = QVBoxLayout(self)
        v.setSpacing(6)
        v.setContentsMargins(16, 14, 16, 12)

        hint = QLabel("設定列印簽收單的標題及相關設定")
        hint.setStyleSheet(_HINT_SS)
        v.addWidget(hint)
        v.addSpacing(4)

        # 2×2 網格：每格＝標籤列＋（輸入框＋即時字數「N / 上限」）列。
        # 兩欄等寬、輸入框隨面板寬度撐滿（stretch 1:1），視窗越寬可見字數越多
        grid = QGridLayout()
        grid.setHorizontalSpacing(24)
        grid.setVerticalSpacing(10)
        self._edits = {}
        self._counters = {}
        for i, (key, label, maxlen) in enumerate(self._fields()):
            cell = QVBoxLayout()
            cell.setSpacing(4)
            cell.addWidget(QLabel(label))

            row = QHBoxLayout()
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(10)
            le = QLineEdit()
            le.setMaxLength(maxlen)
            le.setMinimumWidth(280)
            # placeholder 僅在整格清空時當範例；初始值由 reload() 帶入
            le.setPlaceholderText(PRINT_TITLE_DEFAULTS.get(key, ""))
            cnt = QLabel()
            cnt.setAlignment(Qt.AlignVCenter)
            le.textChanged.connect(
                lambda _t, c=cnt, e=le, m=maxlen: self._upd_counter(c, e, m))
            le.textChanged.connect(self._updateSaveBtn)
            row.addWidget(le, 1)
            row.addWidget(cnt)
            cell.addLayout(row)
            grid.addLayout(cell, i // 2, i % 2)
            self._edits[key] = le
            self._counters[key] = (cnt, maxlen)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        v.addLayout(grid)
        v.addSpacing(4)

        # 現行犯註記用途說明（小灰字，可換行）
        note = QLabel("因現行犯卷宗通常隨案移送，此欄位僅提醒收案人本案無卷宗可供簽收。")
        note.setStyleSheet(_HINT_SS)
        note.setWordWrap(True)
        v.addWidget(note)
        v.addSpacing(6)

        # 按鈕列：左「恢復預設」（theme 通用白底灰框）、右「儲存」
        btn_reset = QPushButton("恢復預設")
        btn_reset.clicked.connect(self._restore_defaults)
        self._btn_save = _save_row(v, extra_left=btn_reset)
        self._btn_save.clicked.connect(self._save)

    def reload(self):
        """重讀 DB 值：已設定→存值；未設定→帶入預設字串當可編輯文字（非 placeholder）。"""
        from lib.db_utils import getSetting, PRINT_TITLE_DEFAULTS
        for key, le in self._edits.items():
            cur = getSetting(self.db_path, key, "")
            le.setText(cur if cur else PRINT_TITLE_DEFAULTS.get(key, ""))
            cnt, maxlen = self._counters[key]
            self._upd_counter(cnt, le, maxlen)
        self._markLoaded()

    def _values(self):
        return {k: le.text().strip() for k, le in self._edits.items()}

    @staticmethod
    def _upd_counter(cnt_label, le, maxlen):
        """更新「N / 上限」即時字數；逼近上限(≥90%)橘、到頂紅。"""
        n = len(le.text()) if isinstance(le, QLineEdit) else 0
        cnt_label.setText(f"{n} / {maxlen}")
        if n >= maxlen:
            color = "#e74c3c"      # 到頂（再多打不進去）
        elif n >= maxlen * 0.9:
            color = "#e67e22"      # 逼近
        else:
            color = "#8e8e93"      # 一般
        # 只動顏色、不設字級（沿用全域字級，不擅自縮放）
        cnt_label.setStyleSheet(f"color: {color}; font-weight: 400;")

    def _restore_defaults(self):
        """把各欄填回預設字串（不立即寫 DB，按儲存才生效）。"""
        from lib.db_utils import PRINT_TITLE_DEFAULTS
        for key, le in self._edits.items():
            le.setText(PRINT_TITLE_DEFAULTS.get(key, ""))

    def _save(self):
        """存檔成功回 True、被擋回 False（切頁「儲存後切換」流程據此決定去留）。"""
        from lib.auth_manager import AuthManager
        from lib.db_utils import setSetting, getSetting, writeAuditSafe, buildDetail
        # 權限 gate：僅 admin（面板反灰之外的保底，防替代觸發路徑繞過）
        if not AuthManager.instance().is_admin():
            return False
        changed = False
        for key, le in self._edits.items():
            new = le.text().strip()
            old = (getSetting(self.db_path, key, "") or "").strip()
            if new != old:
                changed = True
            setSetting(self.db_path, key, new)
        if changed:
            am = AuthManager.instance()
            writeAuditSafe(self.db_path, role=am.current_role, action="CONFIG",
                           operator=am.actor_name(),
                           detail=buildDetail("系統", "修改", "簽收表標題已變更"))
        self.reload()   # 重設 dirty 基準（儲存鈕隨之回灰）
        return True


# ══════════════════════════════════════════════════════════════════
# 閒置逾時（僅 admin；archive 整塊反灰；重啟生效）
# ══════════════════════════════════════════════════════════════════
class IdleTimeoutPanel(_SettingsPanel):
    def __init__(self, db_path, parent=None):
        super().__init__("閒置逾時", db_path, parent)

    def _build(self):
        from lib.db_utils import IDLE_TIMEOUT_RANGE

        v = QVBoxLayout(self)
        v.setSpacing(10)
        v.setContentsMargins(16, 14, 16, 12)

        lo, hi = IDLE_TIMEOUT_RANGE

        # 說明置頂，與其他區塊風格一致
        hint = QLabel(
            "強制關閉時間需大於自動登出時間。儲存後於程式下次啟動時生效。(設為0時不作用)\n"
            "閒置自動登出僅適用於管理者與歸檔管理身分。")
        hint.setStyleSheet(_HINT_SS)
        hint.setWordWrap(True)
        v.addWidget(hint)

        # 自動登出（整數分；0＝停用）。數值框拿掉上下箭頭（NoButtons）：
        # 以鍵盤輸入為主，且 Windows 樣式的箭頭在固定寬度下渲染擁擠難看
        row1 = QHBoxLayout()
        row1.setSpacing(10)
        row1.addWidget(QLabel("閒置自動登出（分）"))
        self.sp_logout = QSpinBox()
        self.sp_logout.setRange(0, int(hi))
        self.sp_logout.setButtonSymbols(QAbstractSpinBox.NoButtons)
        self.sp_logout.setFixedWidth(90)
        self.sp_logout.setAlignment(Qt.AlignCenter)
        row1.addWidget(self.sp_logout)
        row1.addStretch()
        v.addLayout(row1)

        # 強制關閉（可帶一位小數，如 14.5；0＝停用）
        row2 = QHBoxLayout()
        row2.setSpacing(10)
        row2.addWidget(QLabel("閒置強制關閉（分）"))
        self.sp_close = QDoubleSpinBox()
        self.sp_close.setRange(0.0, hi)
        self.sp_close.setDecimals(1)
        self.sp_close.setSingleStep(0.5)
        self.sp_close.setButtonSymbols(QAbstractSpinBox.NoButtons)
        self.sp_close.setFixedWidth(90)
        self.sp_close.setAlignment(Qt.AlignCenter)
        row2.addWidget(self.sp_close)
        row2.addStretch()
        v.addLayout(row2)

        self._btn_save = _save_row(v)
        self._btn_save.clicked.connect(self._save)
        self.sp_logout.valueChanged.connect(self._updateSaveBtn)
        self.sp_close.valueChanged.connect(self._updateSaveBtn)

    def reload(self):
        """重讀 DB 值；未設定／不合法顯示預設。"""
        from lib.db_utils import (getSetting, parseIdleMinutes, IDLE_TIMEOUT_KEYS)
        logout = parseIdleMinutes(
            "logout", getSetting(self.db_path, IDLE_TIMEOUT_KEYS["logout"], ""))
        close = parseIdleMinutes(
            "close", getSetting(self.db_path, IDLE_TIMEOUT_KEYS["close"], ""))
        self.sp_logout.setValue(int(logout))
        self.sp_close.setValue(close)
        self._markLoaded()

    def _values(self):
        return (self.sp_logout.value(), self.sp_close.value())

    def _save(self):
        """存檔成功回 True、被擋/驗證失敗回 False（切頁「儲存後切換」流程據此決定去留）。"""
        from lib.auth_manager import AuthManager
        from lib.db_utils import (setSetting, getSetting, parseIdleMinutes,
                                  IDLE_TIMEOUT_KEYS, writeAuditSafe, buildDetail)
        # 權限 gate：僅 admin（面板反灰之外的保底，防替代觸發路徑繞過）
        if not AuthManager.instance().is_admin():
            return False
        from lib.db_utils import IDLE_TIMEOUT_RANGE
        logout = float(self.sp_logout.value())
        close  = float(self.sp_close.value())
        lo = IDLE_TIMEOUT_RANGE[0]
        # 0＝停用該機制；非 0 時最小 1 分（0<x<1 存了也會被讀取端視為壞值退回預設）
        if 0 < close < lo:
            msgWarning("設定錯誤",
                       f"強制關閉時間最小為 {lo:g} 分（設為 0 表示不作用）。", self)
            return False
        # 兩者皆啟用時才比大小；任一設 0（停用）即不受此限
        if logout > 0 and close > 0 and close <= logout:
            msgWarning("設定錯誤",
                       "強制關閉時間須大於自動登出時間，請調整後再儲存。", self)
            return False
        old_logout = parseIdleMinutes(
            "logout", getSetting(self.db_path, IDLE_TIMEOUT_KEYS["logout"], ""))
        old_close = parseIdleMinutes(
            "close", getSetting(self.db_path, IDLE_TIMEOUT_KEYS["close"], ""))
        # 整數存整數字串（10 存 "10" 非 "10.0"），顯示與稽核都乾淨
        fmt = lambda x: f"{x:g}"
        setSetting(self.db_path, IDLE_TIMEOUT_KEYS["logout"], fmt(logout))
        setSetting(self.db_path, IDLE_TIMEOUT_KEYS["close"],  fmt(close))
        if (logout, close) != (old_logout, old_close):
            am = AuthManager.instance()
            writeAuditSafe(self.db_path, role=am.current_role, action="CONFIG",
                           operator=am.actor_name(),
                           detail=buildDetail(
                               "系統", "修改",
                               f"閒置逾時：登出 {fmt(old_logout)}→{fmt(logout)} 分、"
                               f"關閉 {fmt(old_close)}→{fmt(close)} 分"))
        self.reload()   # 重設 dirty 基準（儲存鈕隨之回灰）
        return True


# ══════════════════════════════════════════════════════════════════
# 唯讀設定（三表新增鎖；僅 admin；archive 整塊反灰；即時生效）
# ══════════════════════════════════════════════════════════════════
class InputLockPanel(_SettingsPanel):
    # (kind, 勾選框標籤)
    _ROWS = [
        ("dispatch", "唯讀交辦單發文"),
        ("task",     "唯讀交辦單收文"),
        ("crim",     "唯讀刑案陳報"),
        ("gen",      "唯讀一般陳報"),
    ]

    def __init__(self, db_path, parent=None):
        super().__init__("唯讀設定", db_path, parent)

    def _build(self):
        v = QVBoxLayout(self)
        v.setSpacing(10)
        v.setContentsMargins(16, 14, 16, 12)

        hint = QLabel(
            "勾選後，該頁面將進入唯讀模式：\n"
            "一般使用者無法收發交辦單，也不能新增、修改、刪除陳報案件；"
            "管理者與歸檔管理不受限制。儲存後立即生效。")
        hint.setStyleSheet(_HINT_SS)
        hint.setWordWrap(True)
        v.addWidget(hint)

        self._checks = {}
        for kind, label in self._ROWS:
            cb = QCheckBox(label)
            cb.stateChanged.connect(self._updateSaveBtn)
            v.addWidget(cb)
            self._checks[kind] = cb

        self._btn_save = _save_row(v)
        self._btn_save.clicked.connect(self._save)

    def reload(self):
        """重讀 DB：值為 "1" 才勾。"""
        from lib.db_utils import getSetting, INPUT_LOCK_KEYS
        for kind, cb in self._checks.items():
            cur = (getSetting(self.db_path, INPUT_LOCK_KEYS[kind], "") or "").strip()
            cb.blockSignals(True)
            cb.setChecked(cur == "1")
            cb.blockSignals(False)
        self._markLoaded()

    def _values(self):
        return {k: cb.isChecked() for k, cb in self._checks.items()}

    def _save(self):
        """存檔成功回 True、被擋回 False。"""
        from lib.auth_manager import AuthManager
        from lib.db_utils import (setSetting, getSetting, INPUT_LOCK_KEYS,
                                  writeAuditSafe, buildDetail)
        # 權限 gate：僅 admin（面板反灰之外的保底，防替代觸發路徑繞過）
        if not AuthManager.instance().is_admin():
            return False
        changes = []
        for kind, label in self._ROWS:
            new = "1" if self._checks[kind].isChecked() else ""
            old = (getSetting(self.db_path, INPUT_LOCK_KEYS[kind], "") or "").strip()
            if (new == "1") != (old == "1"):
                changes.append(f"{label} {'開啟' if new == '1' else '關閉'}")
            setSetting(self.db_path, INPUT_LOCK_KEYS[kind], new)
        if changes:
            am = AuthManager.instance()
            writeAuditSafe(self.db_path, role=am.current_role, action="CONFIG",
                           operator=am.actor_name(),
                           detail=buildDetail("系統", "修改",
                                              "唯讀設定：" + "、".join(changes)))
        self.reload()   # 重設 dirty 基準（儲存鈕隨之回灰）
        return True


# ══════════════════════════════════════════════════════════════════
# 自動備份（第二備份位置／異地副本；僅 admin；下次開啟程式生效）
# ══════════════════════════════════════════════════════════════════
class BackupPanel(_SettingsPanel):
    # 異地副本最近備份超過此天數即紅字提醒（技術參數，不放 UI 設定）
    _STALE_DAYS = 7

    def __init__(self, db_path, parent=None):
        super().__init__("自動備份", db_path, parent)

    def _build(self):
        v = QVBoxLayout(self)
        v.setSpacing(10)
        v.setContentsMargins(16, 14, 16, 12)

        hint = QLabel(
            "程式開啟時會自動備份至資料庫旁的 backups 資料夾。\n"
            "可額外指定異地備份位置（建議選另一顆網路磁碟或本機硬碟），程式會於下次開啟時"
            "一併備份一份到該位置，防範整顆硬碟故障造成資料毀損，該備份位置請於程式開啟時"
            "保持可連線(讀寫)狀態，以免異地備份失敗。")
        hint.setStyleSheet(_HINT_SS)
        hint.setWordWrap(True)
        v.addWidget(hint)

        self.w_path = QLineEdit()
        self.w_path.setPlaceholderText("留空時不啟用異地備份")
        btn_pick = QPushButton("選擇資料夾")
        row = QHBoxLayout()
        row.addWidget(self.w_path, 1)
        row.addWidget(btn_pick)
        v.addLayout(row)
        btn_pick.clicked.connect(self._pick)

        # 異地副本最近備份時間（reload 時更新；過舊紅字、正常灰字）
        self.lbl_status = QLabel("")
        self.lbl_status.setWordWrap(True)
        v.addWidget(self.lbl_status)

        self._btn_save = _save_row(v)
        self._btn_save.clicked.connect(self._save)
        self.w_path.textChanged.connect(self._updateSaveBtn)

    def _pick(self):
        from lib.db_utils import toUncPath
        start = self.w_path.text().strip()
        folder = QFileDialog.getExistingDirectory(
            self, "選擇第二備份位置",
            start if os.path.isdir(start) else "")
        if not folder:
            return
        # 能轉 UNC 就轉（網路碟跨機共用）；轉不出（本機碟）保留原路徑——
        # 備份到本機碟是 DB 在網路碟時的合法異地選擇，非錯誤，故不加橘框警示。
        unc = toUncPath(folder)
        self.w_path.setText(unc if unc else self._normPath(folder))

    def reload(self):
        from lib.db_utils import getSetting, BACKUP_SECOND_DIR_KEY
        cur = (getSetting(self.db_path, BACKUP_SECOND_DIR_KEY, "") or "").strip()
        self.w_path.setText(cur)
        self._refreshStatus(cur)
        self._markLoaded()

    def _refreshStatus(self, path):
        """更新「最近副本備份」狀態字：未設定→隱藏；有設定→顯示最新日期，
        無備份／過舊給提醒色。"""
        from datetime import date
        from lib.db_backup import latest_backup_date
        if not path:
            self.lbl_status.setText("")
            return
        latest = latest_backup_date(path)
        if latest is None:
            # 尚無備份：試寫確認此位置可用；不可寫（權限／未登入網路位置）→ 紅字
            if self._testWritable(path):
                self.lbl_status.setStyleSheet(_HINT_SS)
                self.lbl_status.setText(
                    "此位置尚無備份，將於下次開啟程式時建立。")
            else:
                self.lbl_status.setStyleSheet(
                    "color: #c0392b; font-size: 11pt; font-weight: 400;")
                self.lbl_status.setText(
                    "⚠ 此位置目前無法寫入，請確認資料夾權限或連線狀態；"
                    "若為需要登入的網路位置，請先開啟過該位置並勾選「記住我的認證」。")
            return
        age = (date.today() - latest).days
        if age > self._STALE_DAYS:
            self.lbl_status.setStyleSheet(
                "color: #c0392b; font-size: 11pt; font-weight: 400;")
            self.lbl_status.setText(
                f"⚠ 最近異地備份：{latest:%Y-%m-%d}（已逾 {age} 天，"
                "請確認此位置是否正常可寫入）。")
        else:
            self.lbl_status.setStyleSheet(_HINT_SS)
            self.lbl_status.setText(f"最近異地備份：{latest:%Y-%m-%d}。")

    def _values(self):
        return (self.w_path.text().strip(),)

    def _save(self):
        """存檔成功回 True、被擋回 False。"""
        from lib.auth_manager import AuthManager
        from lib.db_utils import (setSetting, getSetting, BACKUP_SECOND_DIR_KEY,
                                  writeAuditSafe, buildDetail)
        # 權限 gate：僅 admin（面板反灰之外的保底，防替代觸發路徑繞過）
        if not AuthManager.instance().is_admin():
            return False
        new = self._normPath(self.w_path.text())
        old = (getSetting(self.db_path, BACKUP_SECOND_DIR_KEY, "") or "").strip()
        setSetting(self.db_path, BACKUP_SECOND_DIR_KEY, new)
        if new != old:
            am = AuthManager.instance()
            writeAuditSafe(self.db_path, role=am.current_role, action="CONFIG",
                           operator=am.actor_name(),
                           detail=buildDetail(
                               "系統", "修改",
                               f"第二備份位置：{old or '（未設定）'} → {new or '（未設定）'}"))
        # 帳密／權限問題（如未登入的網路位置）由 reload→_refreshStatus 以紅字呈現，
        # 不彈 popup。
        self.reload()   # 重設 dirty 基準（儲存鈕隨之回灰）＋更新狀態字
        return True

    @staticmethod
    def _normPath(raw):
        """正規化備份路徑：治本用 os.path.normpath，Windows 上正確保留磁碟根
        （Z:\\）與 UNC 根（\\\\server\\share），並把斜線收斂成反斜線。
        空字串維持空字串（normpath("") 會回 "."，須先擋）。
        裸磁碟代號（如 D:）自動補根目錄反斜線成 D:\\，避免被當相對路徑。"""
        raw = (raw or "").strip()
        if not raw:
            return ""
        result = os.path.normpath(raw)
        # "D:" 這類裸磁碟代號在 Windows 是相對路徑，補尾斜線變絕對根路徑
        if len(result) == 2 and result[1] == ":" and result[0].isalpha():
            result += os.sep
        return result

    @staticmethod
    def _testWritable(path):
        """試建目錄並寫入／刪除一個測試檔，驗證此位置目前可寫入。回 True/False。"""
        import tempfile
        try:
            os.makedirs(path, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=path, prefix=".backup_test_", suffix=".tmp")
            os.close(fd)
            os.remove(tmp)
            return True
        except Exception:
            return False


# ══════════════════════════════════════════════════════════════════
# 輸入模式（自助取號／送文者輸入；僅 admin 可改；即時生效）
# ══════════════════════════════════════════════════════════════════
class InputModePanel(_SettingsPanel):

    def __init__(self, db_path, parent=None):
        super().__init__("陳報模式", db_path, parent)

    def _build(self):
        v = QVBoxLayout(self)
        v.setSpacing(10)
        v.setContentsMargins(16, 14, 16, 12)

        intro = QLabel("請依所內運作選擇陳報模式，儲存後立即生效。")
        intro.setStyleSheet(_HINT_SS)
        intro.setWordWrap(True)
        v.addWidget(intro)

        self._btn_group = QButtonGroup(self)
        self._radio_sender = QRadioButton("送文者輸入模式")
        self._radio_self   = QRadioButton("自助取號模式")
        self._btn_group.addButton(self._radio_sender, 0)
        self._btn_group.addButton(self._radio_self,   1)
        self._radio_sender.setChecked(True)
        self._radio_sender.toggled.connect(self._updateSaveBtn)
        self._radio_self.toggled.connect(self._updateSaveBtn)

        hint_sender = QLabel("送文者統一輸入案件，輸入時填寫陳報日期與發文人員。")
        hint_sender.setStyleSheet(_HINT_SS)
        hint_sender.setWordWrap(True)
        hint_sender.setContentsMargins(22, 0, 0, 6)

        hint_self = QLabel(
            "承辦人自行輸入取得文號，再由送文者於陳報日到列印頁執行「結算發文」，"
            "補齊發文資訊後列印簽收表。")
        hint_self.setStyleSheet(_HINT_SS)
        hint_self.setWordWrap(True)
        hint_self.setContentsMargins(22, 0, 0, 0)

        v.addWidget(self._radio_sender)
        v.addWidget(hint_sender)
        v.addWidget(self._radio_self)
        v.addWidget(hint_self)

        self._btn_save = _save_row(v)
        self._btn_save.clicked.connect(self._save)

    def reload(self):
        from lib.db_utils import isSelfServiceMode
        is_self = isSelfServiceMode(self.db_path)
        self._radio_self.blockSignals(True)
        self._radio_sender.blockSignals(True)
        self._radio_self.setChecked(is_self)
        self._radio_sender.setChecked(not is_self)
        self._radio_self.blockSignals(False)
        self._radio_sender.blockSignals(False)
        self._markLoaded()

    def _values(self):
        return {"mode": "1" if self._radio_self.isChecked() else "0"}

    def _save(self):
        from lib.auth_manager import AuthManager
        from lib.db_utils import (setSetting, getSetting, REPORT_INPUT_MODE_KEY,
                                  writeAuditSafe, buildDetail)
        if not AuthManager.instance().is_admin():
            return False
        new = "1" if self._radio_self.isChecked() else ""
        old = (getSetting(self.db_path, REPORT_INPUT_MODE_KEY, "") or "").strip()
        setSetting(self.db_path, REPORT_INPUT_MODE_KEY, new)
        if (new == "1") != (old == "1"):
            mode_name = "自助取號模式" if new == "1" else "送文者輸入模式"
            am = AuthManager.instance()
            writeAuditSafe(self.db_path, role=am.current_role, action="CONFIG",
                           operator=am.actor_name(),
                           detail=buildDetail("系統", "修改",
                                              f"陳報輸入模式切換為「{mode_name}」"))
        self.reload()
        return True
