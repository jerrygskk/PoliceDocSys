# -*- coding: utf-8 -*-
"""罰單修改對話框（兩種來源，比照 `reward_dialog.RewardEditDialog`）。

`source="entry"`（罰單登錄頁，預設）：所有已登入身分皆可用，只改「開立人員」
與「罰單編號」——登錄日期／發文日期／發文人員一律保留原值（發文由結算流程或
發文者登錄當下決定，不在此竄改），儲存走 `lib.ticket_utils.updateTicket`。

`source="browse"`（資料庫瀏覽頁）：**僅 admin** 可用，可改全部業務欄位（含
登錄日期／發文日期／發文人員），儲存走 `lib.ticket_utils.updateTicketFromBrowse`
——它在 helper 層維持三態不變式（`''`＝未發文、日期＝已發文、拒收 `None`）與
「已發文必有發文人員」約束。

⚠️ `source` 必填正確：傳錯或漏傳會直接 `ValueError`，不做靜默降級——否則
瀏覽頁誤用 entry 版本會開出唯讀彈窗、admin 改不了東西也不報錯。

所有寫入走 domain helper，本檔不自組業務 SQL；被 except 接住的例外一律
`reportError`（Validation／Duplicate／併發刪除三種例外訊息本身已是白話，改以
`msgWarning` 呈現並移回焦點）。
"""
from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (
    QComboBox, QDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QVBoxLayout,
)

from lib.auth_manager import AuthManager
from lib.db_utils import getConn, loadActivePersonnel
from lib.ticket_utils import (
    TICKET_ACTIVE_SQL, TICKET_NO_MAX_LEN, TicketDuplicateError,
    TicketNotFoundError, TicketValidationError, updateTicket,
    updateTicketFromBrowse,
)
from .edit_dialog import _BaseEditDialog, _CRIMGEN_QSS
from .ui_common import BTN_CANCEL, BTN_CONFIRM, msgWarning, reportError
from .widgets import NullableDateEdit


# 併發刪除白話提示（開啟時列已不存在／儲存時查無列共用）
_ROW_GONE_TITLE = "資料已刪除"
_ROW_GONE_MSG = "本筆罰單資料已被刪除，畫面將更新。"


class TicketEditDialog(_BaseEditDialog):
    """罰單修改；`source` 決定欄位集、儲存 API 與權限。

    沿用 `_BaseEditDialog` 的版面常數與白底樣式（QSS-3：新彈窗必設背景＋文字
    色），與交辦／刑案／一般／敘獎四個彈窗一致，不另抄 stylesheet。
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
        self.setWindowTitle("罰單登錄修改" if source == "entry"
                            else "罰單資料修改")
        self.setMinimumWidth(self._LABEL_W + self._FIELD_W + self._MARGIN)
        self.setStyleSheet(_CRIMGEN_QSS)
        self._build_ui()
        self._load_data()
        if not self._row_missing:
            self.w_ticket_no.setFocus()

    def exec(self):
        """開啟前該列已不存在時，彈白話提示並直接視同取消（不顯示彈窗）。"""
        if self._row_missing:
            msgWarning(_ROW_GONE_TITLE, _ROW_GONE_MSG)
            return QDialog.Rejected
        return super().exec()

    # ── 版面 ────────────────────────────────────────────────
    def _build_ui(self):
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight)
        form.setSpacing(10)

        self.lbl_doc_id = QLabel(self.doc_id)
        self.lbl_doc_id.setStyleSheet("font-weight: bold;")
        form.addRow("編號：", self.lbl_doc_id)

        personnel = loadActivePersonnel(self.db_path)[0]

        if self.source == "browse":
            # 登錄日期：有效資料必填，但用可空白日期框（避免 QDateEdit 空白哨兵
            # 亂象，見 DEVELOPER『可空白日期框』）；空白會在儲存時擋下。
            self.w_create_date = NullableDateEdit()
            self.w_create_date.setPlaceholderText("必填")
            form.addRow("登錄日期：", self.w_create_date)
            # 發文日期：三態——空白＝未發文（存 ''）、有日期＝已發文。
            self.w_register_date = NullableDateEdit()
            self.w_register_date.setPlaceholderText("未發文")
            form.addRow("發文日期：", self.w_register_date)
            # 發文者：可空白（未發文時 NULL）；保留空白項忠實顯示未結算狀態。
            self.w_sender = QComboBox()
            self.w_sender.addItem("", None)
            for staff_id, staff_name, _sort in personnel:
                self.w_sender.addItem(staff_name, staff_id)
            form.addRow("發文者：", self.w_sender)
        else:
            # entry：登錄／發文／發文者一律唯讀（發文不在登錄頁竄改）。
            self.w_create_date = QLabel("")
            form.addRow("登錄日期：", self.w_create_date)
            self.w_register_date = QLabel("")
            form.addRow("發文日期：", self.w_register_date)
            self.w_sender_name = QLabel("")
            form.addRow("發文者：", self.w_sender_name)

        # 開立人員：單一人員，故用一般下拉（不用 RecipientCombo，不解析多人）
        self.w_issuer = QComboBox()
        self.w_issuer.addItem("", None)
        for staff_id, staff_name, _sort in personnel:
            self.w_issuer.addItem(staff_name, staff_id)
        form.addRow("開立人員：", self.w_issuer)

        self.w_ticket_no = QLineEdit()
        self.w_ticket_no.setMaxLength(TICKET_NO_MAX_LEN)
        self.w_ticket_no.setPlaceholderText("請輸入罰單編號")
        form.addRow("罰單編號：", self.w_ticket_no)

        self.btn_save = QPushButton("儲存")
        self.btn_save.setStyleSheet(BTN_CONFIRM)
        self.btn_cancel = QPushButton("取消")
        self.btn_cancel.setStyleSheet(BTN_CANCEL)
        # 罰單編號欄按 Enter 不誤觸儲存（比照敘獎修改彈窗）
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

    # ── 載入 ────────────────────────────────────────────────
    def _load_data(self):
        conn = getConn(self.db_path)
        try:
            row = conn.execute(
                "SELECT create_date, register_date, sender_id, sender_name, "
                "issuer_id, ticket_no FROM Document_Ticket_Full "
                f"WHERE doc_id=? AND {TICKET_ACTIVE_SQL}",
                (self.doc_id,)).fetchone()
        finally:
            conn.close()
        if not row:
            # 併發刪除：不 raise，改標記後由 exec() 彈提示並視同取消。
            self._row_missing = True
            return
        create_date, register_date, sender_id, sender_name, issuer_id, ticket_no = row
        self._orig_register_date = register_date
        if self.source == "browse":
            if create_date:
                self.w_create_date.setDate(
                    QDate.fromString(str(create_date), "yyyy-MM-dd"))
            else:
                self.w_create_date.clear()
            # register_date=''（未發文哨兵）→ 日期框留空；有日期＝已發文。
            if register_date:
                self.w_register_date.setDate(
                    QDate.fromString(str(register_date), "yyyy-MM-dd"))
            else:
                self.w_register_date.clear()
            self._set_combo(self.w_sender, sender_id)
        else:
            self.w_create_date.setText(str(create_date or ""))
            # register_date 三態：''＝尚未發文（自助登錄），日期字串＝已發文。
            self.w_register_date.setText(str(register_date) if register_date
                                         else "未發文")
            self.w_sender_name.setText(str(sender_name or "－"))
        self._set_combo(self.w_issuer, issuer_id)
        self.w_ticket_no.setText(ticket_no or "")

    # ── 儲存 ────────────────────────────────────────────────
    def _on_save(self):
        # 瀏覽頁的罰單修改為 admin 專屬（歸檔管理不可，比照敘獎／交辦）。
        if self.source == "browse" and not AuthManager.instance().is_admin():
            msgWarning("權限不足", "目前身分無法修改資料庫瀏覽中的罰單資料。")
            return
        missing = []
        if not self.w_issuer.currentData():
            missing.append("開立人員")
        if not self.w_ticket_no.text().strip():
            missing.append("罰單編號")
        create_date = register_date = sender_id = None
        if self.source == "browse":
            # 登錄日期：有效資料必填、格式錯擋下。
            if self.w_create_date.hasError():
                self.w_create_date.validateNow()
                return
            cdate = self.w_create_date.getDate()
            if cdate is None:
                missing.append("登錄日期")
            else:
                create_date = cdate.toString("yyyy-MM-dd")
            # 發文日期：空白＝未發文（''、清 sender）；有效日期＝已發文，發文者必填。
            ok, register_date, sender_id, issued = self._resolveReportDate(
                self.w_register_date, self.w_sender,
                blank_value="", field_label="發文日期")
            if not ok:
                return
            if issued and not sender_id:
                missing.append("發文者")
        if missing:
            msgWarning("欄位未填", f"請填寫以下必填欄位：\n{'、'.join(missing)}")
            return
        conn = None
        try:
            conn = getConn(self.db_path)
            if self.source == "browse":
                updateTicketFromBrowse(
                    conn,
                    doc_id=self.doc_id,
                    create_date=create_date,
                    register_date=register_date,
                    sender_id=sender_id,
                    issuer_id=self.w_issuer.currentData(),
                    ticket_no=self.w_ticket_no.text(),
                    role=AuthManager.instance().current_role,
                )
            else:
                updateTicket(
                    conn,
                    doc_id=self.doc_id,
                    issuer_id=self.w_issuer.currentData(),
                    ticket_no=self.w_ticket_no.text(),
                    role=AuthManager.instance().current_role,
                )
            conn.commit()
        except TicketDuplicateError as exc:
            conn.rollback()
            msgWarning("罰單編號重複", str(exc))
            self.w_ticket_no.setFocus()
            self.w_ticket_no.selectAll()
            return
        except TicketValidationError as exc:
            conn.rollback()
            msgWarning("資料有誤", str(exc))
            self.w_ticket_no.setFocus()
            return
        except TicketNotFoundError:
            conn.rollback()
            # 併發刪除：非成功，彈提示、不 accept，由呼叫端重整畫面移除失效列。
            self._row_missing = True
            msgWarning(_ROW_GONE_TITLE, _ROW_GONE_MSG)
            self.reject()
            return
        except Exception as exc:
            if conn:
                conn.rollback()
            reportError("儲存失敗", exc)
            return
        finally:
            if conn:
                conn.close()
        self._updated = (self.doc_id, self.w_issuer.currentData(),
                         self.w_ticket_no.text().strip().upper())
        self.accept()

    def get_updated(self):
        return self._updated
