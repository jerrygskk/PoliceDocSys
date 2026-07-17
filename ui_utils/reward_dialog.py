from PySide6.QtCore import Qt, QDate
from PySide6.QtWidgets import (
    QDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QDateEdit,
    QPushButton, QVBoxLayout,
)

from lib.auth_manager import AuthManager
from lib.db_utils import getConn, loadActivePersonnel
from .ui_common import BTN_CONFIRM, BTN_CANCEL, msgWarning, reportError
from .edit_dialog import _BaseEditDialog, _CRIMGEN_QSS
from .widgets import parse_recipient_names, setupRecipientLineEdit


# 併發刪除白話提示（開啟時列已不存在／儲存時 0 列受影響共用）
_ROW_GONE_TITLE = "資料已刪除"
_ROW_GONE_MSG = "本筆敘獎資料已被刪除，畫面將更新。"


class RewardEditDialog(_BaseEditDialog):
    """敘獎修改對話框；entry 開放三角色，browse 僅管理角色。

    沿用 ``_BaseEditDialog`` 的版面常數（_LABEL_W/_FIELD_W/_MARGIN）與
    共用白底樣式，與交辦／刑案／一般三彈窗一致（不另抄 stylesheet）。
    """

    def __init__(self, db_path, doc_id, parent=None, *, source="entry"):
        super().__init__(parent)
        if source not in ("entry", "browse"):
            raise ValueError("source 必須是 entry 或 browse")
        self.db_path = db_path
        self.doc_id = str(doc_id)
        self.source = source
        self._updated = None
        self._row_missing = False   # 開啟時或儲存時偵測到該列已被併發刪除
        self.setWindowTitle("敘獎登錄修改")
        self.setMinimumWidth(self._LABEL_W + self._FIELD_W + self._MARGIN)
        self.setStyleSheet(_CRIMGEN_QSS)
        self._build_ui()
        self._load_data()
        if not self._row_missing:
            self.w_reason.setFocus()

    def exec(self):
        """開啟前該列已不存在時，彈白話提示並直接視同取消（不顯示彈窗）。
        呼叫端沿用 ``if dlg.exec():`` 即安全，無需改字。"""
        if self._row_missing:
            msgWarning(_ROW_GONE_TITLE, _ROW_GONE_MSG)
            return QDialog.Rejected
        return super().exec()

    def _build_ui(self):
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight)
        form.setSpacing(10)
        self.lbl_doc_id = QLabel(self.doc_id)
        self.lbl_doc_id.setStyleSheet("font-weight: bold;")
        form.addRow("編號：", self.lbl_doc_id)
        self.w_date = QDateEdit()
        self.w_date.setCalendarPopup(True)
        self.w_date.setDisplayFormat("yyyy-MM-dd")
        form.addRow("發文日期：", self.w_date)
        self.w_reason = QLineEdit()
        self.w_reason.setPlaceholderText("請輸入敘獎原因")
        form.addRow("敘獎事由：", self.w_reason)
        self.w_recipients = QLineEdit()
        personnel, alias_map = loadActivePersonnel(self.db_path)
        setupRecipientLineEdit(self.w_recipients, personnel, alias_map=alias_map)
        form.addRow("敘獎人員：", self.w_recipients)

        self.btn_save = QPushButton("儲存")
        self.btn_save.setStyleSheet(BTN_CONFIRM)
        self.btn_cancel = QPushButton("取消")
        self.btn_cancel.setStyleSheet(BTN_CANCEL)
        self.btn_save.setAutoDefault(False)
        self.btn_save.setDefault(False)
        self.btn_cancel.setAutoDefault(False)
        buttons = QHBoxLayout()
        buttons.addStretch()
        buttons.addWidget(self.btn_save)
        buttons.addWidget(self.btn_cancel)
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 20)
        root.setSpacing(8)
        root.addLayout(form)
        root.addLayout(buttons)
        self.btn_save.clicked.connect(self._on_save)
        self.btn_cancel.clicked.connect(self.reject)

    def _load_data(self):
        conn = getConn(self.db_path)
        try:
            row = conn.execute(
                "SELECT register_date,reason,recipients FROM Document_Reward "
                "WHERE doc_id=? AND register_date IS NOT NULL", (self.doc_id,)).fetchone()
        finally:
            conn.close()
        if not row:
            # 併發刪除：不 raise，改標記後由 exec() 彈提示並視同取消，
            # 讓瀏覽頁既有 `if dlg.exec():` 呼叫點不改字也安全。
            self._row_missing = True
            return
        qd = QDate.fromString(str(row[0]), "yyyy-MM-dd")
        self.w_date.setDate(qd)
        self.w_reason.setText(row[1] or "")
        self.w_recipients.setText(row[2] or "")

    def _on_save(self):
        if self.source == "browse" and not AuthManager.instance().is_manager():
            msgWarning("權限不足", "目前身分無法修改資料庫瀏覽中的敘獎資料。")
            return
        reason = self.w_reason.text().strip()
        names = parse_recipient_names(self.w_recipients.text())
        missing = []
        if not self.w_date.date().isValid():
            missing.append("發文日期")
        if not reason:
            missing.append("敘獎事由")
        if not names:
            missing.append("敘獎人員")
        if missing:
            msgWarning("欄位未填", f"請填寫以下必填欄位：\n{'、'.join(missing)}")
            return
        date = self.w_date.date().toString("yyyy-MM-dd")
        recipients = ",".join(names)
        conn = None
        try:
            conn = getConn(self.db_path)
            cur = conn.execute(
                "UPDATE Document_Reward SET register_date=?,reason=?,recipients=? "
                "WHERE doc_id=? AND register_date IS NOT NULL",
                (date, reason, recipients, self.doc_id))
            conn.commit()
            if cur.rowcount == 0:
                # 併發刪除：無列受影響 → 非成功，彈提示、不 accept，
                # 標記後由呼叫端重整畫面移除失效列。
                self._row_missing = True
                msgWarning(_ROW_GONE_TITLE, _ROW_GONE_MSG)
                self.reject()
                return
            self._updated = (self.doc_id, date, reason, recipients)
            self.accept()
        except Exception as exc:
            reportError("儲存失敗", exc)
        finally:
            if conn:
                conn.close()

    def get_updated(self):
        return self._updated
