# ui_utils/ui_common.py
# 通用 UI 元件：Dialog 按鈕樣式常數、訊息／確認彈窗、.ui 載入。
# 原本散在 lib/db_utils.py，與資料庫邏輯混雜；集中到此，db_utils 回歸純資料層。
# 只依賴 PySide6，不 import 專案其他模組（避免循環匯入）。

import html as _html

from PySide6.QtWidgets import QMessageBox, QSpacerItem, QSizePolicy, QGridLayout
from PySide6.QtUiTools import QUiLoader
from PySide6.QtCore import QFile, Qt


# ── Dialog 按鈕樣式常數 ───────────────────────────────────────
_BTN_BASE     = "border-radius: 6px; padding: 4px 16px; min-width: 80px; font-weight: bold;"
_BTN_DISABLED = "QPushButton:disabled { background-color: #e5e5ea; color: #b0b0b5; }"
BTN_CONFIRM  = f"QPushButton {{ background-color: #D0ECF5; color: #000000; {_BTN_BASE} }} QPushButton:hover {{ background-color: #B8D8E8; }} {_BTN_DISABLED}"
BTN_DANGER   = f"QPushButton {{ background-color: #F5D4D0; color: #000000; {_BTN_BASE} }} QPushButton:hover {{ background-color: #E0BDB8; }} {_BTN_DISABLED}"
BTN_CANCEL   = f"QPushButton {{ background-color: #F2F2F7; color: #000000; {_BTN_BASE} }} QPushButton:hover {{ background-color: #E5E5EA; }} {_BTN_DISABLED}"


# ── 通用訊息彈窗（確定按鈕中文，統一樣式）────────────────────
def _makeMsg(icon, title, text, parent=None):
    msg = QMessageBox(parent)
    msg.setWindowTitle(title)
    msg.setText(text)
    msg.setIcon(icon)
    btn = msg.addButton("確定", QMessageBox.AcceptRole)
    btn.setStyleSheet(BTN_CONFIRM)
    msg.exec()

def msgInfo(title, text, parent=None):
    _makeMsg(QMessageBox.Information, title, text, parent)

def msgWarning(title, text, parent=None):
    _makeMsg(QMessageBox.Warning, title, text, parent)

def msgCritical(title, text, parent=None):
    _makeMsg(QMessageBox.Critical, title, text, parent)


def reportError(title, exc, parent=None):
    """except 區塊統一錯誤處理：寫 error.log（完整 traceback）＋彈白話視窗。

    取代散落各處的 msgCritical(title, str(e))——舊寫法既漏記 error.log，
    又把 SQLite 英文原文（如 attempt to write a readonly database）丟給使用者。
    （延遲 import 維持本模組「module 級不依賴專案其他模組」的原則。）
    """
    import logging
    import traceback
    from lib.db_utils import friendlyErrorMessage
    logging.error("".join(
        traceback.format_exception(type(exc), exc, exc.__traceback__)))
    msgCritical(title, friendlyErrorMessage(type(exc), exc), parent)


# ── 通用確認彈窗 ───────────────────────────────────────────────
def confirmBox(title, text, confirm_text="確認", cancel_text="取消",
               confirm_danger=False, default_confirm=True, parent=None,
               informative="", min_width=0):
    """
    Apple HIG 風格確認對話框。版面統一為「左確認、右取消」。
    confirm_danger=True：確認按鈕顯示紅色（破壞性操作）
    default_confirm=False：預設選取「取消」
    informative：次要說明（顯示為較小的灰字，置於主訊息下方，HIG 兩層式）
    min_width：對話框最小內容寬度(px)；用於長檔名等需要更寬不換行的場合（有上限）
    回傳 True 表示使用者點確認
    """
    msg = QMessageBox(parent)
    msg.setWindowTitle(title)
    if informative:
        # Windows 的 QMessageBox 不會自動把 informativeText 縮小／變灰（那是 macOS
        # 原生行為），故用 rich text 自行做 HIG 兩層式：主訊息正常、次要說明灰字。
        body = (
            f'<div style="font-size:14pt; color:#1c1c1e;">{_html.escape(text)}</div>'
            f'<div style="font-size:14pt; color:#6b6b6e; margin-top:10px; '
            f'line-height:150%;">{_html.escape(informative).replace(chr(10), "<br>")}</div>'
        )
        msg.setTextFormat(Qt.RichText)
        msg.setText(body)
    else:
        msg.setText(text)
    msg.setIcon(QMessageBox.Question)

    # 拉寬對話框：QMessageBox 無直接設寬 API，於 grid layout 末列塞水平 spacer 撐出
    # 最小寬度；超過上限的超長內容仍會自動換行（不會無限拉寬）。
    if min_width:
        lay = msg.layout()
        if isinstance(lay, QGridLayout):
            lay.addItem(
                QSpacerItem(min_width, 0, QSizePolicy.Minimum, QSizePolicy.Expanding),
                lay.rowCount(), 0, 1, lay.columnCount())

    # 兩顆都用 ActionRole，避免 Qt 依平台慣例重排左右；
    # 如此按加入順序排列 → 左：確認、右：取消。
    btn_ok     = msg.addButton(confirm_text, QMessageBox.ActionRole)
    btn_cancel = msg.addButton(cancel_text,  QMessageBox.ActionRole)

    btn_ok.setStyleSheet(BTN_DANGER if confirm_danger else BTN_CONFIRM)
    btn_cancel.setStyleSheet(BTN_CANCEL)

    # Enter 預設鈕、Esc 對應取消
    msg.setDefaultButton(btn_ok if default_confirm else btn_cancel)
    msg.setEscapeButton(btn_cancel)
    msg.exec()
    return msg.clickedButton() == btn_ok


def loadUi(path):
    """載入 .ui 檔案，回傳 widget；找不到檔案時彈出錯誤並回傳 None"""
    f = QFile(path)
    if not f.exists():
        msgCritical("錯誤", f"找不到 UI 檔案: {path}")
        return None
    f.open(QFile.ReadOnly)
    loader = QUiLoader()
    # 註冊自訂元件，讓 .ui 內 class="NullableDateEdit" 的可空白日期框被正確建立
    from .widgets import NullableDateEdit
    loader.registerCustomWidget(NullableDateEdit)
    widget = loader.load(f)
    f.close()
    return widget
