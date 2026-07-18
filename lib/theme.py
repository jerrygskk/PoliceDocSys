# Apple HIG 全域樣式表
# arrow.svg 路徑在 main.py 啟動時動態替換（ARROW_PLACEHOLDER → 絕對路徑）
# 打包後從 _MEIPASS 讀，開發時從當前目錄讀

APPLE_STYLE = """
/* ── 全域基礎 ── */
* {
    font-size: 14pt;
    font-family: "Microsoft JhengHei", "PingFang TC", "Noto Sans TC", sans-serif;
}

/* ── 視窗 / Dialog 背景 ── */
QMainWindow, QDialog {
    background-color: #f2f2f7;
}
QWidget {
    background-color: transparent;
}
QMainWindow > QWidget, QDialog > QWidget {
    background-color: #f2f2f7;
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
QPushButton#crim_paper_only:pressed,
QPushButton#gen_paper_only:pressed,
QPushButton#crim_do_archive:pressed,
QPushButton#gen_do_archive:pressed {
    background-color: #39649a;
}
/* 只歸紙本禁用態（未選公文）*/
QPushButton#crim_paper_only:disabled,
QPushButton#gen_paper_only:disabled {
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
