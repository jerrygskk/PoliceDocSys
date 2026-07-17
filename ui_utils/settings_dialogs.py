"""
settings_dialogs.py — 設定頁彈窗

包含：
  - RefItemDialog                                   參照項（人員／部門／案類）新增 / 修改共用
      REF_PERSONNEL / REF_DEPT / REF_CASETYPE       三份設定表驅動同一類別
  - ChangePasswordDialog                            變更密碼
  - ResetDialog                                     跨年度重置確認
（歸檔資料夾／簽收表標題已改為「系統設定」子頁嵌入面板，見 settings_panels.py）
"""
import os
import re
import sqlite3

from PySide6.QtCore    import Qt, QRegularExpression
from PySide6.QtGui     import QRegularExpressionValidator
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLabel, QLineEdit, QPushButton, QCheckBox,
    QScrollArea,
)

from .ui_common import BTN_CONFIRM, BTN_CANCEL, BTN_DANGER, reportError

# ── 共用樣式 ───────────────────────────────────────────────────────
_DIALOG_SS = """
    QDialog, QWidget {
        background-color: #FFFFFF;
        color: #000000;
    }
    QLineEdit {
        background-color: #FFFFFF;
        color: #000000;
        border: 1px solid #CCCCCC;
        border-radius: 4px;
        padding: 4px 8px;
    }
    QLineEdit:focus {
        border: 1px solid #8fa8c8;
    }
    QCheckBox { color: #000000; }
    QLabel    { color: #000000; }
"""

_LABEL_W = 100
_FIELD_W = 280
_MARGIN  = 40

# 輸入框驗證失敗（必填留空）的紅框樣式
_ERR_BORDER_SS = "border: 1px solid #e74c3c; border-radius: 4px; padding: 4px 8px;"


def _add_buttons(dlg, layout, confirm_text='儲存', danger=False, default_confirm=True):
    row = QHBoxLayout()
    row.addStretch()
    btn_cancel = QPushButton('取消')
    btn_ok     = QPushButton(confirm_text)
    btn_cancel.setStyleSheet(BTN_CANCEL)
    btn_ok.setStyleSheet(BTN_DANGER if danger else BTN_CONFIRM)
    row.addWidget(btn_cancel)
    row.addWidget(btn_ok)
    layout.addLayout(row)
    btn_cancel.clicked.connect(dlg.reject)
    # default_confirm=True：Enter 確認（確認鈕為 default）
    # default_confirm=False：Enter 不確認，改由取消鈕為 default（高風險操作用，防誤按）
    if default_confirm:
        btn_cancel.setAutoDefault(False); btn_cancel.setDefault(False)
        btn_ok.setAutoDefault(True);      btn_ok.setDefault(True)
    else:
        btn_ok.setAutoDefault(False);     btn_ok.setDefault(False)
        btn_cancel.setAutoDefault(True);  btn_cancel.setDefault(True)
    return btn_cancel, btn_ok


def _next_id(conn, table, id_col, prefix, digits=2):
    rows = conn.execute(f"SELECT {id_col} FROM {table}").fetchall()
    nums = []
    for (val,) in rows:
        m = re.search(r'(\d+)$', str(val))
        if m:
            nums.append(int(m.group(1)))
    nxt = (max(nums) + 1) if nums else 1
    return f"{prefix}{nxt:0{digits}d}"


def _next_sort(conn, table):
    """新增參照項的 sort_order：取最小值-1（排到最前）；空表 fallback 1。"""
    row = conn.execute(f"SELECT MIN(sort_order) FROM {table}").fetchone()
    return (row[0] - 1) if row and row[0] is not None else 1


def _parseAddPosition(text, existing_count):
    """新增對話框「順序」欄位驗證（純邏輯，可單測）。
    留空＝合法、回 (True, None)（套用預設行為：塞最前）。
    合法範圍 1～existing_count+1（新增後清單會變 existing_count+1 筆）。
    回傳 (is_valid, 0-based目標索引或None)；不合法回 (False, None)。"""
    text = (text or "").strip()
    if text == "":
        return True, None
    if not text.isdigit():
        return False, None
    n = int(text)
    if not (1 <= n <= existing_count + 1):
        return False, None
    return True, n - 1


def _parseSeqMoveTarget(text, row_count):
    """既有列「序號」欄編輯驗證（純邏輯，可單測）。
    回傳 0-based 目標索引；不合法（非數字／超出 1~row_count）回 None。"""
    text = (text or "").strip()
    if not text.isdigit():
        return None
    n = int(text)
    if not (1 <= n <= row_count):
        return None
    return n - 1


# ══════════════════════════════════════════════════════════════════
# 參照項（人員／部門／案類）新增 / 修改 —— 設定表驅動的單一 Dialog
# ══════════════════════════════════════════════════════════════════

def _has_alias_col(conn, table="Ref_Personnel"):
    """指定表的 alias 欄是否已存在（冪等補欄前的保護）。
    未套補丁時別名相關讀寫一律跳過，避免缺欄報錯。"""
    return any(r[1] == "alias"
               for r in conn.execute(f"PRAGMA table_info({table})"))


def _audit_ref(conn, category, act, content, table=None, ref_id=None):
    """參照表維護稽核（operator＝登入身分）。用同一 conn，由呼叫端 commit。"""
    from lib.db_utils import writeAudit, buildDetail
    from lib.auth_manager import AuthManager
    am = AuthManager.instance()
    writeAudit(conn, role=am.current_role, action="REF",
               target_table=table, target_id=ref_id,
               operator=am.actor_name(),
               detail=buildDetail(category, act, content))


# 三種參照項的差異全部收斂成設定表，RefItemDialog 只讀這裡、不寫死任何實體。
#   table / pk_col / name_col：資料表與欄位
#   prefix / digits          ：新增時自動編號（P01 / D01 / CT01）
#   category                 ：稽核分類名（人員／部門／案類）
#   name_label / placeholder ：主欄位（姓名／部門名稱／類型名稱）標籤與提示
#   retired_label            ：停用勾選框文字（人員為「離職」，其餘「停用」）
#   title_add / title_edit   ：視窗標題
#   extra_fields             ：額外欄位（人員／案類有「別名」）；每項為
#       {attr, col, label, placeholder}，資料驅動、非特例分支
#   audit_name_change        ：改名是否寫「修改：舊名→新名」稽核（省略＝True；
#       案類設 False＝改名不留操作紀錄，維護者要求）
REF_PERSONNEL = {
    "table": "Ref_Personnel",   "pk_col": "staff_id",     "name_col": "staff_name",
    "prefix": "P",  "digits": 2, "category": "人員",
    "name_label": "姓名：",     "placeholder": "例：王小明 或 王小明-19.06",
    "retired_label": "離職",
    "title_add": "新增人員",    "title_edit": "修改人員",
    "extra_fields": [
        {"attr": "alias", "col": "alias", "label": "別名：",
         "placeholder": "綽號/簡稱，半形逗號分隔"},
    ],
}

REF_DEPT = {
    "table": "Ref_Departments", "pk_col": "dept_id",      "name_col": "dept_name",
    "prefix": "D",  "digits": 2, "category": "部門",
    "name_label": "部門名稱：", "placeholder": "例：刑事組",
    "retired_label": "停用",
    "title_add": "新增部門",    "title_edit": "修改部門",
    "extra_fields": [],
}

REF_CASETYPE = {
    "table": "Ref_CaseTypes",   "pk_col": "case_type_id", "name_col": "case_type_name",
    "prefix": "CT", "digits": 2, "category": "案類",
    "name_label": "類型名稱：", "placeholder": "例：277傷害",
    "retired_label": "停用",
    "title_add": "新增案件類型", "title_edit": "修改案件類型",
    "audit_name_change": False,   # 案類改名不寫操作紀錄（維護者要求）
    "extra_fields": [
        {"attr": "alias", "col": "alias", "label": "別名：",
         "placeholder": "簡稱/俗稱，半形逗號分隔"},
    ],
}


class RefItemDialog(QDialog):
    """參照項（人員／部門／案類）新增 / 修改共用彈窗。

    - 由 cfg（REF_PERSONNEL / REF_DEPT / REF_CASETYPE）驅動，差異全在設定表
    - existing=None            → 新增模式（自動編號、INSERT、順序欄可留空塞最前）
    - existing=(pk, seq, name, is_active) → 修改模式（UPDATE、順序欄預填目前列位置）
    - 對外 API 與舊六個類別相容：get_result() / get_target_position()
    """

    def __init__(self, cfg, db_path, existing=None, parent=None):
        super().__init__(parent)
        self.cfg      = cfg
        self.db_path  = db_path
        self.is_edit  = existing is not None
        self._result  = None
        self._target_pos = None
        self._extra_widgets = {}     # attr -> QLineEdit
        if self.is_edit:
            self._pk, self._seq, self._old_name, old_active = existing
            self._old_active = bool(old_active)
        else:
            self._pk = None          # 於 _build 產生
            self._seq = None
            self._old_name = None
            self._old_active = None
        self.setWindowTitle(cfg["title_edit"] if self.is_edit else cfg["title_add"])
        self.setMinimumWidth(_LABEL_W + _FIELD_W + _MARGIN)
        self.setStyleSheet(_DIALOG_SS)
        self._build()

    def _build(self):
        cfg = self.cfg
        # 取目前筆數（供順序欄提示合法範圍）；新增模式順手取自動編號
        conn  = sqlite3.connect(self.db_path)
        count = conn.execute(f"SELECT COUNT(*) FROM {cfg['table']}").fetchone()[0]
        if not self.is_edit:
            self._pk = _next_id(conn, cfg["table"], cfg["pk_col"],
                                cfg["prefix"], digits=cfg["digits"])
        conn.close()
        # 合法範圍上限：新增可插到最後（count+1），修改在既有列間搬移（count）
        seq_max = count + 1 if not self.is_edit else count

        vlay = QVBoxLayout(self)
        vlay.setSpacing(16)
        vlay.setContentsMargins(24, 20, 24, 16)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight)
        form.setSpacing(10)

        # 主欄位（姓名／部門名稱／類型名稱）
        self.w_name = QLineEdit(self._old_name if self.is_edit else "")
        if not self.is_edit:
            self.w_name.setPlaceholderText(cfg["placeholder"])
        self.w_name.setFixedWidth(_FIELD_W)
        form.addRow(cfg["name_label"], self.w_name)

        # 額外欄位（人員別名）：資料驅動；修改模式從 DB 預填
        for f in cfg["extra_fields"]:
            cur = self._load_extra(f["col"]) if self.is_edit else ""
            w = QLineEdit(cur)
            w.setPlaceholderText(f["placeholder"])
            w.setFixedWidth(_FIELD_W)
            form.addRow(f["label"], w)
            self._extra_widgets[f["attr"]] = w

        # 順序欄
        self.w_seq = QLineEdit(str(self._seq) if self.is_edit else "")
        self.w_seq.setValidator(QRegularExpressionValidator(
            QRegularExpression(r"[0-9]*"), self.w_seq))
        self.w_seq.setFixedWidth(80)
        lbl_seq = QLabel("順序：")
        lbl_seq.setFixedWidth(_LABEL_W)
        lbl_seq.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        # 順序欄右側提示合法範圍：新增「（選填，1～N）」、修改「（1～N）」
        hint = (f"（選填，1～{seq_max}）" if not self.is_edit
                else f"（1～{seq_max}）")
        seq_row = QHBoxLayout()
        seq_row.addWidget(self.w_seq)
        seq_row.addWidget(QLabel(hint))
        seq_row.addStretch()
        form.addRow(lbl_seq, seq_row)

        # 狀態（離職／停用）
        self.w_retired = QCheckBox(cfg["retired_label"])
        self.w_retired.setChecked(self._old_active is False if self.is_edit else False)
        form.addRow("狀態：", self.w_retired)

        vlay.addLayout(form)
        _, btn_ok = _add_buttons(
            self, vlay, confirm_text=('儲存' if self.is_edit else '新增'))
        btn_ok.clicked.connect(self._submit)
        self.w_name.returnPressed.connect(self._submit)
        self.w_name.setFocus()

    def _load_extra(self, col):
        """修改模式預填額外欄位（缺欄／查不到則空字串）。"""
        try:
            conn = sqlite3.connect(self.db_path)
            if col == "alias" and not _has_alias_col(conn, self.cfg["table"]):
                conn.close()
                return ""
            row = conn.execute(
                f"SELECT {col} FROM {self.cfg['table']} WHERE {self.cfg['pk_col']}=?",
                (self._pk,)).fetchone()
            conn.close()
            return (row[0] if row and row[0] else "")
        except Exception:
            return ""

    def _write_extra(self, conn):
        """寫入額外欄位（別名有缺欄保護）。用呼叫端的同一 conn。"""
        for f in self.cfg["extra_fields"]:
            col = f["col"]
            if col == "alias" and not _has_alias_col(conn, self.cfg["table"]):
                continue
            val = self._extra_widgets[f["attr"]].text().strip()
            conn.execute(
                f"UPDATE {self.cfg['table']} SET {col}=? WHERE {self.cfg['pk_col']}=?",
                (val, self._pk))

    def _submit(self):
        cfg  = self.cfg
        name = self.w_name.text().strip()
        is_active = 0 if self.w_retired.isChecked() else 1
        if not name:
            self.w_name.setStyleSheet(_ERR_BORDER_SS)
            return
        try:
            conn  = sqlite3.connect(self.db_path)
            count = conn.execute(
                f"SELECT COUNT(*) FROM {cfg['table']}").fetchone()[0]

            if self.is_edit:
                target = _parseSeqMoveTarget(self.w_seq.text(), count)
                seq_bad = target is None
            else:
                valid, target = _parseAddPosition(self.w_seq.text(), count)
                seq_bad = not valid
            if seq_bad:
                self.w_seq.setStyleSheet(_ERR_BORDER_SS)
                conn.close()
                return
            self.w_seq.setStyleSheet("")

            if self.is_edit:
                conn.execute(
                    f"UPDATE {cfg['table']} SET {cfg['name_col']}=?, is_active=? "
                    f"WHERE {cfg['pk_col']}=?",
                    (name, is_active, self._pk))
                self._write_extra(conn)
                if name != self._old_name and cfg.get("audit_name_change", True):
                    _audit_ref(conn, cfg["category"], "修改",
                               f"{self._old_name} → {name}", cfg["table"], self._pk)
                if bool(is_active) != self._old_active:
                    _audit_ref(conn, cfg["category"],
                               "啟用" if is_active else "停用", name,
                               cfg["table"], self._pk)
            else:
                new_sort = _next_sort(conn, cfg["table"])
                conn.execute(
                    f"INSERT INTO {cfg['table']} "
                    f"({cfg['pk_col']}, {cfg['name_col']}, is_active, sort_order) "
                    f"VALUES (?,?,?,?)",
                    (self._pk, name, is_active, new_sort))
                self._write_extra(conn)
                _audit_ref(conn, cfg["category"], "新增", name,
                           cfg["table"], self._pk)

            conn.commit()
            conn.close()
            self._target_pos = target
            self._result = (self._pk, name, bool(is_active))
            self.accept()
        except Exception as e:
            reportError("更新失敗" if self.is_edit else "寫入失敗", e, self)

    def get_result(self):
        return self._result

    def get_target_position(self):
        return self._target_pos


# ══════════════════════════════════════════════════════════════════
# 變更密碼
# ══════════════════════════════════════════════════════════════════

class ChangePasswordDialog(QDialog):

    def __init__(self, db_path, parent=None):
        super().__init__(parent)
        self.db_path = db_path
        from lib.auth_manager import AuthManager
        self._actor = AuthManager.instance().actor_name()
        self.setWindowTitle(f'變更{self._actor}密碼')
        self.setMinimumWidth(_LABEL_W + _FIELD_W + _MARGIN)
        self.setStyleSheet(_DIALOG_SS)
        self._build()

    def _build(self):
        vlay = QVBoxLayout(self)
        vlay.setSpacing(16)
        vlay.setContentsMargins(24, 20, 24, 16)

        lbl_who = QLabel(f"目前變更的是「{self._actor}」的登入密碼")
        lbl_who.setStyleSheet("color: #6b6b6e;")
        vlay.addWidget(lbl_who)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight)
        form.setSpacing(10)

        self.w_old = QLineEdit()
        self.w_old.setEchoMode(QLineEdit.Password)
        self.w_old.setFixedWidth(_FIELD_W)
        self.w_old.setPlaceholderText("請輸入目前密碼")
        form.addRow("目前密碼：", self.w_old)

        self.w_new = QLineEdit()
        self.w_new.setEchoMode(QLineEdit.Password)
        self.w_new.setFixedWidth(_FIELD_W)
        self.w_new.setPlaceholderText("請輸入新密碼")
        form.addRow("新密碼：", self.w_new)

        self.w_confirm = QLineEdit()
        self.w_confirm.setEchoMode(QLineEdit.Password)
        self.w_confirm.setFixedWidth(_FIELD_W)
        self.w_confirm.setPlaceholderText("再次輸入新密碼")
        form.addRow("確認新密碼：", self.w_confirm)

        self.lbl_err = QLabel("")
        self.lbl_err.setStyleSheet("color: #e74c3c;")
        self.lbl_err.setFixedWidth(_FIELD_W)
        self.lbl_err.setWordWrap(True)
        # 放進 form 的欄位欄（空標籤），使紅字與三個輸入框對齊同一條垂直線
        form.addRow("", self.lbl_err)

        vlay.addLayout(form)
        _, btn_ok = _add_buttons(self, vlay, confirm_text='變更密碼', default_confirm=False)
        btn_ok.clicked.connect(self._submit)
        # 變更密碼為高風險操作，不綁 Enter 送出，須以滑鼠點按「變更密碼」
        self.w_old.setFocus()

    def _submit(self):
        old     = self.w_old.text()
        new     = self.w_new.text()
        confirm = self.w_confirm.text()

        if not old or not new or not confirm:
            self.lbl_err.setText("所有欄位均為必填")
            return
        if new != confirm:
            self.lbl_err.setText("新密碼與確認密碼不一致")
            self.w_confirm.clear()
            self.w_confirm.setFocus()
            return
        if len(new) < 4:
            self.lbl_err.setText("新密碼至少需要 4 個字元")
            return

        from lib.auth_manager import AuthManager
        am = AuthManager.instance()
        actor = am.actor_name()
        res = am.change_password(old, new, self.db_path)
        if res == 'ok':
            # 變更密碼事件稽核（不記密碼內容）
            from lib.db_utils import writeAuditSafe, buildDetail
            writeAuditSafe(self.db_path, role=am.current_role, action="PWD",
                           operator=actor,
                           detail=buildDetail("系統", "修改", f"{actor}變更密碼"))
            self.accept()
        elif res == 'conflict':
            # 撞到另一組管理密碼（兩組同值 archive 永遠登不進）。
            # 提示刻意不說明原因，避免變成試出另一組密碼的探針
            self.lbl_err.setText("此密碼無法使用，請重新設定")
            self.w_new.clear()
            self.w_confirm.clear()
            self.w_new.setFocus()
        elif res == 'wrong_old':
            self.lbl_err.setText("目前密碼錯誤")
            self.w_old.clear()
            self.w_old.setFocus()
        else:
            # res == 'error'：讀寫失敗（例如網路碟當下無法寫入），非密碼問題。
            # 勿沿用「目前密碼錯誤」，否則使用者會誤以為自己打錯而反覆重試。
            self.lbl_err.setText("儲存失敗，請稍後再試")


# ══════════════════════════════════════════════════════════════════
# 跨年度重置確認
# ══════════════════════════════════════════════════════════════════
class ResetDialog(QDialog):
    """
    跨年度重置確認彈窗（高風險操作）。

    - 顯示重置範圍警語
    - 動態列出本次將清除的停用項目（人員 / 部門 / 案類）
    - 須手動輸入「RESET」才能執行（防誤按：確認鈕非 default、輸入框不綁 Enter）

    本 Dialog 只負責「取得使用者明確同意」，回傳 accept/reject；
    實際重置由呼叫端（tab_settings）執行。
    """

    _CONFIRM_WORD = "RESET"

    def __init__(self, db_path, parent=None, doc_summary=""):
        super().__init__(parent)
        self.db_path = db_path
        self.doc_summary = doc_summary
        self.setWindowTitle("跨年度重置")
        self.setMinimumWidth(_LABEL_W + _FIELD_W + _MARGIN)
        self.setStyleSheet(_DIALOG_SS)
        self._build()

    def _build(self):
        from lib.db_utils import listInactiveRefItems

        vlay = QVBoxLayout(self)
        vlay.setSpacing(14)
        vlay.setContentsMargins(24, 20, 24, 16)

        lbl_title = QLabel("跨年度重置將執行下列不可復原的操作：")
        lbl_title.setStyleSheet("font-weight: 700; font-size: 14pt;")
        vlay.addWidget(lbl_title)

        lbl_db = QLabel(f"目標資料庫：{os.path.basename(self.db_path)}")
        lbl_db.setStyleSheet("color: #8e8e93;")
        vlay.addWidget(lbl_db)

        lbl_scope = QLabel(
            "1. 清空全部交辦單、刑案陳報、一般陳報及敘獎登錄資料"
            + (f"（{self.doc_summary}）" if self.doc_summary else "") + "\n"
            "2. 移除已停用的人員、部門、案件類型（如需保留請先返回啟用）\n"
            "3. 流水號歸零\n"
            "4. 清除歸檔資料夾路徑設定（需於新年度重新指定）"
        )
        lbl_scope.setStyleSheet("color: #3a3a3c;")
        vlay.addWidget(lbl_scope)

        # 動態列出待清停用項目
        inactive = listInactiveRefItems(self.db_path)
        if inactive:
            lbl_hint = QLabel(f"本次將一併移除以下停用項目（共 {len(inactive)} 項）：")
            lbl_hint.setStyleSheet("color: #c0392b; font-weight: 600;")
            vlay.addWidget(lbl_hint)

            lines = "\n".join(f"• {kind}　{name}" for kind, _id, name in inactive)
            lbl_inactive = QLabel(lines)
            lbl_inactive.setStyleSheet("color: #c0392b; background: transparent; border: none;")

            scroll = QScrollArea()
            scroll.setWidget(lbl_inactive)
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QScrollArea.NoFrame)
            scroll.setMaximumHeight(230)  # 項目多時改捲動，避免彈窗撐爆畫面
            scroll.setStyleSheet(
                "QScrollArea { background-color: #FDF2F2; border: 1px solid #f5c6c6; "
                "border-radius: 6px; }"
                "QScrollArea > QWidget > QWidget { background: transparent; }"
            )
            # padding 套在內層 label，避免捲軸貼邊
            lbl_inactive.setContentsMargins(12, 8, 12, 8)
            vlay.addWidget(scroll)
        else:
            lbl_none = QLabel("（目前無停用項目需移除）")
            lbl_none.setStyleSheet("color: #8e8e93;")
            vlay.addWidget(lbl_none)

        lbl_warn = QLabel("執行前請確認已備份資料。此操作無法復原。")
        lbl_warn.setStyleSheet("color: #c0392b; font-weight: 600;")
        vlay.addWidget(lbl_warn)

        # 確認字串輸入
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight)
        self.w_confirm = QLineEdit()
        self.w_confirm.setFixedWidth(_FIELD_W)
        self.w_confirm.setPlaceholderText(f"請輸入 {self._CONFIRM_WORD} 以確認")
        form.addRow(f"輸入「{self._CONFIRM_WORD}」：", self.w_confirm)
        vlay.addLayout(form)

        self.lbl_err = QLabel("")
        self.lbl_err.setStyleSheet("color: #e74c3c;")
        self.lbl_err.setAlignment(Qt.AlignRight)
        vlay.addWidget(self.lbl_err)

        # 按鈕：確認鈕為危險樣式、非 default；不綁 Enter（防誤按）
        _, btn_ok = _add_buttons(
            self, vlay, confirm_text="執行重置", danger=True, default_confirm=False)
        btn_ok.clicked.connect(self._submit)
        self.w_confirm.setFocus()

    def _submit(self):
        if self.w_confirm.text().strip() != self._CONFIRM_WORD:
            self.lbl_err.setText(f"請正確輸入 {self._CONFIRM_WORD}")
            self.w_confirm.clear()
            self.w_confirm.setFocus()
            return
        self.accept()
