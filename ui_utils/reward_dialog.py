from PySide6.QtCore import Qt, QDate
from PySide6.QtWidgets import (
    QComboBox, QDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QVBoxLayout,
)

from lib.auth_manager import AuthManager
from lib.db_utils import getConn, loadActivePersonnel
from .ui_common import BTN_CONFIRM, BTN_CANCEL, msgWarning, reportError
from .edit_dialog import _BaseEditDialog, _CRIMGEN_QSS
from .widgets import NullableDateEdit, parse_recipient_names, setupRecipientLineEdit


# 併發刪除白話提示（開啟時列已不存在／儲存時 0 列受影響共用）
_ROW_GONE_TITLE = "資料已刪除"
_ROW_GONE_MSG = "本筆敘獎資料已被刪除，畫面將更新。"


class _RecipientCombo(QComboBox):
    """敘獎人員下拉：張開下拉瞬間快照當下欄位文字。

    選取項目時 Qt 會先把整欄換成選中文字，處理器需還原張開當下的內容再附加
    姓名；快照若靠 textEdited 維護會漏掉 completer/程式填字（textEdited 只在
    使用者打字時發出），故一律以張開瞬間為準。
    """
    popup_snapshot = ""

    def showPopup(self):
        self.popup_snapshot = self.lineEdit().text()
        super().showPopup()


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
        # 發文日期：可空白（未發文＝''）又要能手打／挑月曆，故用 NullableDateEdit，
        # 不用 QDateEdit（後者當可空白欄會冒 1752 殘值／fixup 還原，見 DEVELOPER
        # 『可空白日期框』）。空白＝維持未發文；填日期＝管理者在此直接補發單筆。
        self.w_date = NullableDateEdit()
        self.w_date.setPlaceholderText("未發文")
        form.addRow("發文日期：", self.w_date)
        # 發文人員（比照刑案／一般編輯彈窗；保留空白項忠實顯示自助未結算的 NULL）
        self.w_sender = QComboBox()
        self.w_sender.addItem("", None)
        personnel, alias_map = loadActivePersonnel(self.db_path)
        for sid, sname, _ in personnel:
            self.w_sender.addItem(sname, sid)
        form.addRow("發文人員：", self.w_sender)
        self.w_reason = QLineEdit()
        self.w_reason.setPlaceholderText("請輸入敘獎原因")
        form.addRow("敘獎事由：", self.w_reason)
        # 敘獎人員：可編輯下拉（比照發文人員可點選展開；彈窗無右側名條）。
        # 下拉選取＝附加姓名到清單（非取代整欄）；打字仍有候選 completer。
        self.w_recipients = _RecipientCombo()
        self.w_recipients.setEditable(True)
        self.w_recipients.setInsertPolicy(QComboBox.NoInsert)
        for _, sname, _ in personnel:
            self.w_recipients.addItem(sname)
        self.w_recipients.setCurrentIndex(-1)
        le = self.w_recipients.lineEdit()
        self._recipients_ctl = setupRecipientLineEdit(
            le, personnel, alias_map=alias_map)
        self.w_recipients.activated.connect(self._on_recipient_picked)
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

    def _on_recipient_picked(self, index):
        """下拉選取：Qt 會先把整欄文字換成選中項，先還原張開下拉當下的快照
        再附加該姓名。"""
        name = self.w_recipients.itemText(index)
        le = self.w_recipients.lineEdit()
        le.setText(self.w_recipients.popup_snapshot)
        self._recipients_ctl.add_person(name)

    def _load_data(self):
        conn = getConn(self.db_path)
        try:
            row = conn.execute(
                "SELECT register_date,sender_id,reason,recipients FROM Document_Reward "
                "WHERE doc_id=? AND register_date IS NOT NULL", (self.doc_id,)).fetchone()
        finally:
            conn.close()
        if not row:
            # 併發刪除：不 raise，改標記後由 exec() 彈提示並視同取消，
            # 讓瀏覽頁既有 `if dlg.exec():` 呼叫點不改字也安全。
            self._row_missing = True
            return
        # register_date=''（未發文哨兵）→ 日期框留空；有日期＝已發文。
        # 管理者可在此填日期直接補發單筆、或清空回未發文（不必跳結算）。
        if row[0]:
            self.w_date.setDate(QDate.fromString(str(row[0]), "yyyy-MM-dd"))
        else:
            self.w_date.clear()
        self._set_combo(self.w_sender, row[1])
        self.w_reason.setText(row[2] or "")
        self.w_recipients.setCurrentText(row[3] or "")

    def _on_save(self):
        if self.source == "browse" and not AuthManager.instance().is_manager():
            msgWarning("權限不足", "目前身分無法修改資料庫瀏覽中的敘獎資料。")
            return
        reason = self.w_reason.text().strip()
        names = parse_recipient_names(self.w_recipients.currentText())
        # 日期：空白＝未發文（存 '' 哨兵、清 sender）；填有效日期＝發文，此時
        # 發文人員必填（不讓發出的單沒有送文者）。格式錯（非空非法）擋下亮紅框。
        ok, date, sender_id, issued = self._resolveReportDate(
            self.w_date, self.w_sender, blank_value="", field_label="發文日期")
        if not ok:
            return
        missing = []
        if not reason:
            missing.append("敘獎事由")
        if not names:
            missing.append("敘獎人員")
        if issued and not sender_id:
            missing.append("發文人員")
        if missing:
            msgWarning("欄位未填", f"請填寫以下必填欄位：\n{'、'.join(missing)}")
            return
        # 維持不變式：未發文 ⟺ (register_date='' 且 sender=NULL)
        recipients = ",".join(names)
        conn = None
        try:
            conn = getConn(self.db_path)
            cur = conn.execute(
                "UPDATE Document_Reward SET register_date=?,sender_id=?,reason=?,recipients=? "
                "WHERE doc_id=? AND register_date IS NOT NULL",
                (date, sender_id, reason, recipients, self.doc_id))
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
