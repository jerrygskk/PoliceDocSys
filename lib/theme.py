# Apple HIG 全域樣式表
# arrow.svg 路徑在 main.py 啟動時動態替換（ARROW_PLACEHOLDER → 絕對路徑）
# 打包後從 _MEIPASS 讀，開發時從當前目錄讀

# 可打字 QComboBox 提示文字／正常文字色（供 ui_utils.widgets.attachComboHint 使用）。
# HINT_COLOR 與下方 QLineEdit::placeholder 同色，統一全專案的「提示灰」。
HINT_COLOR = "#aeaeb2"
TEXT_COLOR = "#1c1c1e"

APPLE_STYLE = """
/* ── 全域基礎 ── */
* {
    font-size: 14pt;
    font-family: "Microsoft JhengHei", "PingFang TC", "Noto Sans TC", sans-serif;
}

/* ── 視窗 / Dialog 背景 ── */
/* ⚠️ **這兩條的順序有意義，不可對調**（2026-08-07 以算繪像素實測定案）。

   `QDialog` 也是 `QWidget`，兩條選擇器特異度相同（各一個型別選擇器），Qt 依
   CSS 規則由**後者勝**。所以必須先宣告 `QWidget` 透明、再宣告視窗底色；反過來
   寫的話 `transparent` 會把 `QMainWindow`／`QDialog` 的底色中和掉，視窗自己變成
   透明——在 Windows 上會渲染成整塊黑（同 QToolTip 那段的 Qt 行為）。

   容器維持 transparent 是刻意的：它們透出視窗底色，整個視窗因此是一致的一片，
   不會出現一塊一塊的色差。

   ⚠️ 這裡曾經有第三條 `QMainWindow > QWidget, QDialog > QWidget { #f2f2f7 }`，
   是上述順序寫反時用來替視窗「補畫」內容的補丁。它有嚴重副作用：
   `QLineEdit`／`QComboBox`／`QDateEdit` 都是 `QWidget`，只要**直接放在視窗或
   對話框底下**就會被它匹配到，而兩個型別選擇器的特異度高於單獨的 `QLineEdit`，
   於是輸入框的白底被容器灰底蓋掉；停用態則因 `:disabled` 特異度更高而倖存。
   順序修正後該補丁已無必要，整條移除。**不要把它加回來。** */
QWidget {
    background-color: transparent;
}
QMainWindow, QDialog {
    background-color: #f2f2f7;
}

/* ── 彈窗公版（2026-08-08）──
   本區塊是**彈窗專用的一組標準值**，用 `QDialog` 限定範圍。它還原 v1.2.10 的
   彈窗外觀：白底、輸入框 4px 圓角、較緊的內距（欄位自然高 33px，分頁是 37px）。

   為什麼要有這一組：v1.2.10 時六個編輯彈窗、設定彈窗與救援視窗**各自帶一份**
   同樣數值的區域 QSS，其中五份漏了 `:disabled`，於是「欄位鎖住了卻看不出來」
   （見 PITFALLS QSS-8）。那些複製品已全部移除，改由這裡統一提供——外觀一樣，
   但只有一個地方，日後改彈窗外觀不必再找六個檔案。

   ⚠️ **範圍只到彈窗，刻意不動分頁**：分頁與 `.ui` 裡有 71 處寫死 36／38 的高度、
   程式另有 5 處 `setFixedHeight`／`FIELD_H`。把這組值套到全域會讓沒鎖死的欄位
   矮 4px、鎖死的不動，同一頁高低不齊——正是 PITFALLS LAY-6 記過的雷。

   ⚠️ **不宣告 `color`**：維持公版的 `#1c1c1e`（`TEXT_COLOR` token）。v1.2.10 那份
   寫的是 `#000000`，但 `attachComboHint` 的正常色吃的是 `TEXT_COLOR`，還原純黑會
   讓同一個下拉在彈窗內外呈現兩種黑。

   ⚠️ **不宣告任何停用態**：`QLineEdit:disabled` 等帶偽狀態、特異度高於這裡的
   兩個型別選擇器，公版的反灰照樣生效（2026-08-08 以算繪像素實測確認）。
   **不要為了「補齊」在這裡加 `:disabled`**，那會把反灰又鎖死成固定值。

   ⚠️ 位置在 `QMessageBox` 區塊**之前**是刻意的：QMessageBox 是 QDialog 子類，
   它自己那條底色規則在後面、同特異度後者勝，故訊息框維持灰底（與 v1.2.10 一致）。*/
QDialog {
    background-color: #ffffff;
}
QDialog QLineEdit, QDialog QComboBox, QDialog QDateEdit {
    border: 1px solid #cccccc;
    border-radius: 4px;
    padding: 4px 8px;
}
QDialog QComboBox, QDialog QDateEdit {
    padding: 4px 32px 4px 8px;
}

/* ── 標籤 ── */
QLabel {
    color: #1c1c1e;
    background-color: transparent;
}

/* ── 工具提示 ──
   QToolTip 是 QLabel 子類，會吃到上面 QWidget/QLabel 的 transparent 背景；
   tooltip 為獨立頂層視窗，透明背景在 Windows 會渲染成整塊黑，必須明確給底色。*/
QToolTip {
    background-color: #ffffff;
    color: #1c1c1e;
    border: 1px solid #c6c6c8;
    padding: 4px 8px;
}

/* ── 右鍵選單（QMenu）── */
QMenu {
    background-color: #ffffff;
    border: 1px solid #c6c6c8;
    border-radius: 8px;
    padding: 4px;
}
QMenu::item {
    color: #1c1c1e;
    padding: 6px 56px 6px 32px;
    border-radius: 6px;
}
QMenu::item:selected {
    background-color: #6e8fac;
    color: #ffffff;
}
QMenu::item:disabled {
    color: #aeaeb2;
}
QMenu::separator {
    height: 1px;
    background-color: #e5e5ea;
    margin: 4px 8px;
}
QMenu::icon {
    width: 16px;
    height: 16px;
}

/* ── 輸入框 ── */
QLineEdit {
    background-color: #ffffff;
    border: 1px solid #c6c6c8;
    border-radius: 8px;
    padding: 6px 10px;
    color: #1c1c1e;
    selection-background-color: #8fa8c8;
}
QLineEdit:focus {
    border: 2px solid #8fa8c8;
}
QLineEdit::placeholder {
    color: #aeaeb2;
}

/* ── 下拉選單 ── */
QComboBox {
    background-color: #ffffff;
    border: 1px solid #c6c6c8;
    border-radius: 8px;
    padding: 6px 32px 6px 10px;
    color: #1c1c1e;
}
QComboBox:focus {
    border: 2px solid #8fa8c8;
}
QComboBox::drop-down {
    subcontrol-origin: border;
    subcontrol-position: top right;
    width: 28px;
    border: none;
    background: transparent;
}
QComboBox::down-arrow {
    image: url(:/arrow.svg);
    width: 12px;
    height: 8px;
}
QComboBox QAbstractItemView {
    background-color: #ffffff;
    border: 1px solid #c6c6c8;
    border-radius: 8px;
    selection-background-color: #6e8fac;
    selection-color: #ffffff;
    outline: none;
    padding: 2px;
}
QComboBox QAbstractItemView::item {
    background-color: #ffffff;
    color: #1c1c1e;
    padding: 4px 8px;
    min-height: 28px;
}
QComboBox QAbstractItemView::item:hover {
    background-color: #e5e5ea;
    color: #1c1c1e;
}
QComboBox QAbstractItemView::item:selected {
    background-color: #6e8fac;
    color: #ffffff;
}
QComboBox QAbstractItemView::item:selected:hover {
    background-color: #5c7a9a;
    color: #ffffff;
}

/* ── 日期選擇器 ── */
QDateEdit {
    background-color: #ffffff;
    border: 1px solid #c6c6c8;
    border-radius: 8px;
    padding: 6px 32px 6px 10px;
    color: #1c1c1e;
}
QDateEdit:focus {
    border: 2px solid #8fa8c8;
}
QDateEdit::drop-down {
    subcontrol-origin: border;
    subcontrol-position: top right;
    width: 28px;
    border: none;
    background: transparent;
}
QDateEdit::down-arrow {
    image: url(:/arrow.svg);
    width: 12px;
    height: 8px;
}

/* ── 月曆（QCalendarWidget）── */
QCalendarWidget {
    background-color: #ffffff;
}
QCalendarWidget QWidget {
    background-color: #ffffff;
    color: #1c1c1e;
    alternate-background-color: #f2f2f7;
}
QCalendarWidget QAbstractItemView {
    background-color: #ffffff;
    color: #1c1c1e;
    selection-background-color: #007aff;
    selection-color: #ffffff;
}
QCalendarWidget QAbstractItemView:enabled {
    color: #1c1c1e;
    background-color: #ffffff;
}
QCalendarWidget QAbstractItemView:disabled {
    color: #aeaeb2;
}
QCalendarWidget QToolButton {
    background-color: #f2f2f7;
    border: none;
    border-radius: 6px;
    color: #1c1c1e;
    padding: 4px 8px;
}
QCalendarWidget QToolButton:hover {
    background-color: #e5e5ea;
}
QCalendarWidget #qt_calendar_navigationbar {
    background-color: #f2f2f7;
    padding: 4px;
}

/* ── 按鈕 ── */
QPushButton {
    background-color: #ffffff;
    border: 1px solid #c6c6c8;
    border-radius: 8px;
    padding: 8px 18px;
    color: #1c1c1e;
    font-weight: 500;
}
QPushButton:hover {
    background-color: #e5e5ea;
}
QPushButton:pressed {
    background-color: #d1d1d6;
}
/* ⚠️ 通用停用態（2026-08-07 補）。在此之前公版**只有** hover／pressed，沒有
   `:disabled`——每一支自訂樣式的按鈕都得自己記得補一行，忘了就不會反灰
   （PITFALLS QSS-4 記過的雷，長年靠人記得）。而「按鈕反灰」是本專案權限與
   流程的主要視覺提示，少了它使用者會一直去點沒有反應的鈕。
   ⚠️ 帶 objectName 的特化按鈕（#deleteBtn、#btn_send 等）特異度較高，不會
   自動吃到這條；每個特化 selector 群組都必須另有明確的 `:disabled` 規則。 */
QPushButton:disabled {
    background-color: #e5e5ea;
    color: #aeaeb2;
    border-color: #d1d1d6;
}

/* ── 刪除按鈕（表格內紅色 X） ── */
QPushButton#deleteBtn {
    background-color: #e74c3c;
    color: white;
    font-size: 8px;
    font-weight: bold;
    border: none;
    border-radius: 3px;
    padding: 0;
    max-width: 18px;
    max-height: 18px;
}
QPushButton#deleteBtn:hover   { background-color: #c0392b; }
QPushButton#deleteBtn:pressed { background-color: #a93226; }
QPushButton#deleteBtn:disabled { background-color: #d1d1d6; color: #f2f2f7; }

/* ── 送出按鈕（發文 / 收文 / 陳報）墨藍 ── */
QPushButton#btn_send,
QPushButton#btn_recv_submit,
QPushButton#btn_rpt_submit,
QPushButton#btn_reward_submit,
QPushButton#ticket_add,
QPushButton#crim_paper_only,
QPushButton#gen_paper_only,
QPushButton#crim_do_archive,
QPushButton#gen_do_archive {
    background-color: #a1b4cb;
    color: white;
    border: none;
    border-radius: 8px;
    font-weight: 600;
}
QPushButton#btn_send:hover,
QPushButton#btn_recv_submit:hover,
QPushButton#btn_rpt_submit:hover,
QPushButton#btn_reward_submit:hover,
QPushButton#ticket_add:hover,
QPushButton#crim_paper_only:hover,
QPushButton#gen_paper_only:hover,
QPushButton#crim_do_archive:hover,
QPushButton#gen_do_archive:hover {
    background-color: #4977b1;
}
QPushButton#btn_send:pressed,
QPushButton#btn_recv_submit:pressed,
QPushButton#btn_rpt_submit:pressed,
QPushButton#btn_reward_submit:pressed,
QPushButton#ticket_add:pressed,
QPushButton#crim_paper_only:pressed,
QPushButton#gen_paper_only:pressed,
QPushButton#crim_do_archive:pressed,
QPushButton#gen_do_archive:pressed {
    background-color: #39649a;
}
/* 主要動作鈕停用態：九顆共用同一規則，避免 objectName selector 蓋掉通用灰。 */
QPushButton#btn_send:disabled,
QPushButton#btn_recv_submit:disabled,
QPushButton#btn_rpt_submit:disabled,
QPushButton#btn_reward_submit:disabled,
QPushButton#ticket_add:disabled,
QPushButton#crim_paper_only:disabled,
QPushButton#gen_paper_only:disabled,
QPushButton#crim_do_archive:disabled,
QPushButton#gen_do_archive:disabled {
    background-color: #d1d9e3;
    color: #ffffff;
}

/* ── Tab 標籤 ── */
QTabWidget::pane {
    border: none;
    background-color: #ffffff;
}
QTabBar::tab {
    background-color: #e5e5ea;
    color: #636366;
    border: none;
    border-radius: 6px;
    padding: 8px 18px;
    margin-right: 4px;
    font-weight: 500;
}
QTabBar::tab:selected {
    background-color: #ffffff;
    color: #8fa8c8;
    font-weight: 600;
}
QTabBar::tab:hover:!selected {
    background-color: #d1d1d6;
}

/* ── 分隔線 ── */
QFrame[frameShape="4"],
QFrame[frameShape="5"] {
    color: #e5e5ea;
}

/* ── ScrollBar ── */
QScrollBar:vertical {
    background: transparent;
    width: 8px;
    margin: 0;
}
QScrollBar::handle:vertical {
    background: #c7c7cc;
    border-radius: 4px;
    min-height: 30px;
}
QScrollBar::add-line:vertical,
QScrollBar::sub-line:vertical { height: 0; }
QScrollBar:horizontal {
    background: transparent;
    height: 8px;
}
QScrollBar::handle:horizontal {
    background: #c7c7cc;
    border-radius: 4px;
    min-width: 30px;
}
QScrollBar::add-line:horizontal,
QScrollBar::sub-line:horizontal { width: 0; }

/* ── Checkbox ── */
QCheckBox {
    color: #1c1c1e;
    spacing: 6px;
}
QCheckBox::indicator {
    width: 18px;
    height: 18px;
    border: 1.5px solid #c6c6c8;
    border-radius: 4px;
    background-color: #ffffff;
}
QCheckBox::indicator:checked {
    background-color: #8fa8c8;
    border-color: #8fa8c8;
}
QCheckBox:disabled {
    color: #aeaeb2;
}
QCheckBox::indicator:disabled {
    background-color: #e5e5ea;
    border-color: #d1d1d6;
}

/* ── RadioButton ── */
QRadioButton {
    color: #1c1c1e;
    spacing: 6px;
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
QRadioButton:disabled {
    color: #aeaeb2;
}
QRadioButton::indicator:disabled {
    background-color: #e5e5ea;
    border-color: #d1d1d6;
}

/* ── 停用狀態（反灰） ── */
QDateEdit:disabled {
    background-color: #e5e5ea;
    color: #aeaeb2;
    border-color: #d1d1d6;
}
QComboBox:disabled {
    background-color: #e5e5ea;
    color: #aeaeb2;
    border-color: #d1d1d6;
}
QLineEdit:disabled {
    background-color: #e5e5ea;
    color: #aeaeb2;
    border-color: #d1d1d6;
}

/* ── MessageBox ── */
QMessageBox {
    background-color: #f2f2f7;
}
QMessageBox QLabel {
    color: #1c1c1e;
}
QDialog QLabel {
    font-size: 14pt;
}

/* ── 主選單標題 ── */
QLabel#titleLabel {
    font-size: 22pt;
    font-weight: 700;
    color: #1c1c1e;
    padding: 20px 0 4px 0;
}
QLabel#subtitleLabel {
    font-size: 13pt;
    color: #636366;
    padding: 0 0 16px 0;
}
QLabel#versionLabel {
    font-size: 11pt;
    color: #aeaeb2;
}
"""
