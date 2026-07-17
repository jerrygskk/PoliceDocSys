# ui_utils/help_dialog.py
# 程式內 HELP 共用 Dialog：各 Tab 右上 ? 鈕點擊後開啟，顯示該頁說明。
# 內容來自 help_content.HELP_HTML（單一來源）。
#
# 風格比照 confirmBox（Apple HIG）：白底黑字、單顆「關閉」鈕、Enter/Esc 皆關。
# ⚠ 新 QDialog 必須明設背景＋文字色（否則繼承全域深色看不見），見 README §5。

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTextBrowser, QPushButton, QLabel,
    QToolButton, QWidget, QTabWidget, QFrame,
)
from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QIcon, QFont

# 內文字距（百分比，100=預設）。QTextBrowser 不吃 CSS letter-spacing，
# 只能在字型物件上設；CJK 內文加一點點字距較好讀。要調鬆／緊改這裡。
_LETTER_SPACING = 92

from lib.db_utils import getResourcePath
from .ui_common import BTN_CONFIRM
from .help_content import HELP_HTML, HELP_TITLES, HELP_TIPS


_DIALOG_QSS = """
QDialog { background-color: #FFFFFF; }
QTextBrowser {
    background-color: #FFFFFF; color: #1c1c1e;
    border: none; padding: 2px 8px;
}
"""


def helpDialog(parent, tab_index):
    """開啟指定頁的說明視窗（modal）。tab_index 對應 TAB_CLASSES 索引。"""
    html = HELP_HTML.get(tab_index)
    if html is None:
        return
    title = HELP_TITLES.get(tab_index, "說明")

    dlg = QDialog(parent)
    dlg.setWindowTitle(title)
    dlg.setStyleSheet(_DIALOG_QSS)
    dlg.setMinimumSize(660, 600)

    lay = QVBoxLayout(dlg)
    lay.setContentsMargins(22, 16, 22, 14)
    lay.setSpacing(8)

    # 標題列：左大標 +「使用說明」淺灰，右上警徽 LOGO；下方一條全寬鋼藍橫線
    head_row = QHBoxLayout()
    head_row.setContentsMargins(2, 0, 2, 0)
    header = QLabel(
        f'<span style="font-size:19pt; font-weight:600; color:#1c1c1e;">{title}</span>'
        f'<span style="font-size:12pt; color:#a0a0a5;">　使用說明</span>')
    header.setStyleSheet("QLabel { background: transparent; }")
    head_row.addWidget(header)
    head_row.addStretch(1)
    logo = QLabel()
    logo.setPixmap(QIcon(getResourcePath("res/buttons/police_badge.svg")).pixmap(QSize(36, 36)))
    logo.setStyleSheet("QLabel { background: transparent; }")
    head_row.addWidget(logo, 0, Qt.AlignVCenter)
    lay.addLayout(head_row)

    line = QFrame()
    line.setFrameShape(QFrame.HLine)
    line.setFrameShadow(QFrame.Plain)
    line.setStyleSheet("QFrame { background: #4977b1; border: none; max-height: 2px; }")
    lay.addWidget(line)

    browser = QTextBrowser()
    browser.setOpenExternalLinks(False)
    browser.setFrameShape(QFrame.NoFrame)
    f = browser.font()
    f.setLetterSpacing(QFont.PercentageSpacing, _LETTER_SPACING)
    browser.setFont(f)
    browser.setHtml(f'<div style="font-size:13pt; color:#1c1c1e;">{html}</div>')
    lay.addWidget(browser, 1)

    btn_row = QHBoxLayout()
    btn_row.addStretch(1)
    btn_close = QPushButton("關閉")
    btn_close.setStyleSheet(BTN_CONFIRM)
    btn_close.clicked.connect(dlg.accept)
    btn_close.setDefault(True)        # Enter 觸發
    btn_row.addWidget(btn_close)
    lay.addLayout(btn_row)

    dlg.exec()


# ── 接線：分頁列右上角說明鈕（線圖示，依當前頁開對應說明）＋ 套各欄位 tooltip ──
_HELP_BTN_QSS = (
    "QToolButton { background-color: transparent; border: none; padding: 0 8px; }"
    "QToolButton:hover { background-color: #EAEFF5; border-radius: 6px; }"
)


def attachHelpButton(tab_widget: QTabWidget, window: QWidget):
    """在 tabWidget 分頁列右上角放一顆說明鈕（help 線圖示），點擊開啟當前分頁的
    說明；並依 HELP_TIPS 為各欄位／按鈕套上 tooltip。於所有 Tab setup 完成後呼叫一次。"""
    if not tab_widget:
        return

    btn = QToolButton(tab_widget)
    btn.setIcon(QIcon(":/icon_help.svg"))
    btn.setIconSize(QSize(24, 24))
    btn.setToolTip("本頁使用說明")
    btn.setCursor(Qt.PointingHandCursor)
    btn.setStyleSheet(_HELP_BTN_QSS)
    # clicked 會多塞一個 checked 布林，用 lambda 吃掉（見 CLAUDE.md 踩雷表）
    btn.clicked.connect(lambda _=False: helpDialog(window, tab_widget.currentIndex()))
    tab_widget.setCornerWidget(btn, Qt.TopRightCorner)

    # 套 tooltip：以物件名稱在 window 樹中尋找對應 widget
    for tips in HELP_TIPS.values():
        for name, text in tips.items():
            w = window.findChild(QWidget, name)
            if w is not None:
                w.setToolTip(text)
