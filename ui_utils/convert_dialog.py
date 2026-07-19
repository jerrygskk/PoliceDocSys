"""ConvertDialog — 刑案 ↔ 一般 類別互轉的補填視窗。

設計凍結於 docs/handover_doc_convert.md §5–6。純邏輯在 lib/doc_convert.py。
由 CriminalEditDialog／GeneralEditDialog 底部「轉換類別」鈕開啟；轉換成功
`accept()`，並以 self.new_doc_id／self.dst_kind 回傳給呼叫端刷新。

⚠️ 權限：僅 is_manager()。呼叫端已 gate，本檔 exec 前再 guard 一次（保底）。
"""

import os
import shutil

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLabel, QLineEdit, QComboBox, QPushButton, QRadioButton, QButtonGroup,
    QGroupBox,
)
from PySide6.QtCore import Qt, QDate

from lib.auth_manager import AuthManager
from lib.db_utils import (
    getConn, archiveDefaultDir, resolveArchivedPdf, clearPdfIndexCache,
)
from lib.archive_text import _sanitize
from lib import doc_convert

from .ui_common import msgCritical, msgInfo, reportError, BTN_CONFIRM, BTN_CANCEL
from .widgets import setupFilterCombo, NullableDateEdit
from .edit_dialog import _CRIMGEN_QSS, CriminalEditDialog, GeneralEditDialog


# 鎖定（唯讀）欄樣式：灰底灰字，同 :disabled 慣例
_LOCKED_QSS = ("background:#e5e5ea; color:#636366; border:1px solid #d1d1d6;"
               " border-radius:4px; padding:4px 8px;")
# 補填區（藍框強調）／丟失清單（紅框警示）
_FILL_GROUP_QSS = (
    "QGroupBox { font-weight:600; color:#1c1c1e; border:1.5px solid #8fa8c8;"
    " border-radius:8px; margin-top:10px; padding:10px 12px 12px 12px; }"
    " QGroupBox::title { subcontrol-origin:margin; left:12px; padding:0 4px; }"
)
_LOST_GROUP_QSS = (
    "QGroupBox { color:#a8442e; border:1px solid #ecc7c1; background:#fdf2f0;"
    " border-radius:8px; margin-top:10px; padding:10px 12px 12px 12px; }"
    " QGroupBox::title { subcontrol-origin:margin; left:12px; padding:0 4px; }"
    " QLabel { color:#7a3120; background:transparent; }"
)


class ConvertDialog(QDialog):
    _LABEL_W = 120
    _FIELD_W = 340
    _MARGIN  = 40

    def __init__(self, db_path, src_kind, doc_id, parent=None):
        super().__init__(parent)
        self.db_path  = db_path
        self.src_kind = src_kind            # 'crim' or 'gen'
        self.doc_id   = str(doc_id)
        self.dst_kind, self.src_cat, self.dst_cat = doc_convert.convertKinds(src_kind)
        self.new_doc_id = None              # 成功後填入
        self.setWindowTitle(f"轉換為{self.dst_cat}案類")
        self.setMinimumWidth(self._LABEL_W + self._FIELD_W + self._MARGIN)
        self.setStyleSheet(_CRIMGEN_QSS)

        self._src_row = {}
        self._load_src()
        self._build_ui()

    # ── 載入來源列＋參照清單（含丟失欄顯示名）──────────────────────
    def _load_src(self):
        conn = getConn(self.db_path)
        try:
            src_table = ("Document_Criminal" if self.src_kind == "crim"
                         else "Document_General")
            cur = conn.execute(
                f"SELECT * FROM {src_table} WHERE doc_id=?", (self.doc_id,))
            r = cur.fetchone()
            if r:
                self._src_row = dict(zip([d[0] for d in cur.description], r))
            self._personnel = conn.execute(
                "SELECT staff_id, staff_name FROM Ref_Personnel "
                "WHERE is_active=1 ORDER BY sort_order").fetchall()
            _ct_rows = conn.execute(
                "SELECT case_type_id, case_type_name, alias FROM Ref_CaseTypes "
                "WHERE is_active=1 ORDER BY sort_order").fetchall()
            self._case_types = [(r[0], r[1]) for r in _ct_rows]
            self._casetype_alias_map = {
                r[1]: [a.strip() for a in (r[2] or "").split(",") if a.strip()]
                for r in _ct_rows if r[2]
            }
            self._depts = conn.execute(
                "SELECT dept_id, dept_name FROM Ref_Departments "
                "WHERE is_active=1 ORDER BY sort_order").fetchall()
            # 丟失欄清單（顯示名）
            nr = doc_convert.makeNameResolver(conn)
            self._lost = doc_convert.lostFields(self.src_kind, self._src_row, nr)
            # 沿用欄顯示名
            self._name = {sid: sname for sid, sname in self._personnel}
        finally:
            conn.close()

    def _staff_name(self, sid):
        return self._name.get(sid, str(sid) if sid else "")

    # ── 版面 ────────────────────────────────────────────────────
    def _build_ui(self):
        root = QVBoxLayout(self)

        # 1) 原編號（鎖定）
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight)
        form.setSpacing(10)
        old_lbl = QLabel(f"{self.src_cat} {self.doc_id}（轉換後作廢）")
        old_lbl.setStyleSheet(_LOCKED_QSS)
        form.addRow("原編號：", old_lbl)
        # 2) 新編號（鎖定；不預先取號）
        new_lbl = QLabel(f"{self.dst_cat}（送出後產生）")
        new_lbl.setStyleSheet(_LOCKED_QSS)
        form.addRow("新編號：", new_lbl)

        # 3) 沿用區（唯讀）
        r = self._src_row
        for label, val in self._carry_over_rows(r):
            w = QLabel(val or "")
            w.setStyleSheet(_LOCKED_QSS)
            form.addRow(label, w)
        root.addLayout(form)

        # 4) 補填區
        root.addWidget(self._build_fill_group())

        # 5) 丟失清單
        if self._lost:
            root.addWidget(self._build_lost_group())

        # 6) 動作列
        btn_confirm = QPushButton("確認轉換")
        btn_cancel  = QPushButton("取消")
        btn_confirm.setStyleSheet(BTN_CONFIRM)
        btn_cancel.setStyleSheet(BTN_CANCEL)
        btn_confirm.clicked.connect(self._on_confirm)
        btn_cancel.clicked.connect(self.reject)
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_row.addWidget(btn_confirm)
        btn_row.addWidget(btn_cancel)
        root.addSpacing(8)
        root.addLayout(btn_row)

    def _carry_over_rows(self, r):
        """沿用欄（唯讀顯示，兩方向共通）：陳報日期／發文人員／承辦人／主旨。"""
        subject = r.get("subject_summary") if self.src_kind == "crim" else r.get("subject")
        proc_lbl = "承辦人：" if self.dst_kind == "crim" else "陳報人："
        return [
            # 未發文列（自助取號未結算）：顯示「未發文」而非空白，比照瀏覽頁
            ("陳報日期：", str(r.get("report_date") or "未發文")),
            ("發文人員：", self._staff_name(r.get("sender_id"))),
            (proc_lbl,     self._staff_name(r.get("processor_id"))),
            ("陳報主旨：", str(subject or "")),
        ]

    def _build_fill_group(self):
        g = QGroupBox("補填欄位")
        g.setStyleSheet(_FILL_GROUP_QSS)
        form = QFormLayout(g)
        form.setLabelAlignment(Qt.AlignRight)
        form.setSpacing(10)
        if self.dst_kind == "crim":
            self._build_fill_crim(form)
        else:
            self._build_fill_gen(form)
        return g

    def _build_fill_crim(self, form):
        # 案件分類（必填，可篩選）
        self.w_casetype = QComboBox()
        self.w_casetype.setEditable(True)
        setupFilterCombo(self.w_casetype, self._case_types,
                         alias_map=self._casetype_alias_map)
        form.addRow("案件分類：", self.w_casetype)
        # 發文分類（必填，radio）
        self._status_radios, radio_row = self._radio_row(
            CriminalEditDialog.STATUS_OPTIONS)
        form.addRow("發文分類：", radio_row)
        # 受理人（可空白）
        self.w_receiver = QComboBox()
        self.w_receiver.addItem("", None)
        for sid, sname in self._personnel:
            self.w_receiver.addItem(sname, sid)
        form.addRow("受理人：", self.w_receiver)
        # 查獲日期（必填）
        self.w_occ_date = NullableDateEdit()
        self.w_occ_date.setPlaceholderText("下拉選擇日期")
        form.addRow("查獲日期：", self.w_occ_date)
        # 報案人（可空白）
        self.w_reporter = QLineEdit()
        self.w_reporter.setPlaceholderText("請輸入報案人（可空白）")
        form.addRow("報案人：", self.w_reporter)

    def _build_fill_gen(self, form):
        # 業務單位（必填，決策 #12）
        self.w_dept = QComboBox()
        self.w_dept.addItem("", None)
        for did, dname in self._depts:
            self.w_dept.addItem(dname, did)
        form.addRow("業務單位：", self.w_dept)
        # 分類（必填，radio）
        self._cat_radios, radio_row = self._radio_row(GeneralEditDialog.CAT_OPTIONS)
        form.addRow("分類：", radio_row)

    def _radio_row(self, options):
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        radios = []
        group = QButtonGroup(self)
        for i, (val, label) in enumerate(options):
            rb = QRadioButton(label)
            rb.setStyleSheet(CriminalEditDialog.RADIO_STYLE)
            rb.setMinimumWidth(65)   # 比照 Layout3.ui：125% 下 sizeHint 算不準會切字，鎖最小寬
            group.addButton(rb, i)
            radios.append((val, rb))
            if i == 0:
                rb.setChecked(True)
        row.addWidget(radios[0][1])
        for _v, rb in radios[1:]:
            row.addSpacing(12)
            row.addWidget(rb)
        row.addStretch()
        # 防 QButtonGroup 被 GC：掛成屬性
        setattr(self, f"_grp_{id(group)}", group)
        return radios, row

    def _build_lost_group(self):
        g = QGroupBox("以下欄位資訊將被捨棄")
        g.setStyleSheet(_LOST_GROUP_QSS)
        v = QVBoxLayout(g)
        v.setSpacing(6)
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight)
        form.setSpacing(6)
        for label, val in self._lost:
            lbl = QLabel(label)
            lbl.setStyleSheet("font-weight:600; color:#a8604e;")
            val_w = QLabel(val or "")
            form.addRow(lbl, val_w)
        v.addLayout(form)
        return g

    # ── 送出 ────────────────────────────────────────────────────
    def _radio_value(self, radios):
        for val, rb in radios:
            if rb.isChecked():
                return val
        return radios[0][0]

    def _collect_fill(self):
        """回傳 (fill_values dict, error_list)。error_list 非空即擋下。"""
        errors = []
        if self.dst_kind == "crim":
            case_type = self.w_casetype.currentData()
            if not case_type:
                errors.append("案件分類")
            self.w_occ_date.validateNow()
            if self.w_occ_date.isBlank():
                errors.append("查獲日期")
            elif self.w_occ_date.hasError():
                errors.append("查獲日期格式（請用 yyyy-MM-dd）")
            occ = self.w_occ_date.getDate()
            reporter = self.w_reporter.text().strip()
            fill = {
                "case_type":       case_type,
                "case_status":     self._radio_value(self._status_radios),
                "occurrence_date": occ.toString("yyyy-MM-dd") if occ else None,
                "receiver_id":     self.w_receiver.currentData(),
                "reporter_name":   reporter or None,
            }
        else:
            dept_id = self.w_dept.currentData()
            if not dept_id:
                errors.append("業務單位")
            fill = {
                "dept_id":    dept_id,
                "gen_cat_id": self._radio_value(self._cat_radios),
            }
        return fill, errors

    def _on_confirm(self):
        # 保底權限 guard（呼叫端已 gate，防未來加快捷路徑繞過）
        if not AuthManager.instance().is_manager():
            return
        fill, errors = self._collect_fill()
        if errors:
            from .ui_common import msgWarning
            msgWarning("欄位未填", f"請填寫以下必填欄位：\n{'、'.join(errors)}")
            return

        # ── 先決定 PDF 處理方式（transaction 外）──────────────────
        old_ie = (self._src_row.get("is_electronic") or "").strip()
        old_path = None                     # 需搬移時的來源路徑
        pdf_missing = False                 # 找不到電子檔→新單列未歸檔，完成後提示
        if old_ie:
            path, status = resolveArchivedPdf(self.db_path, self.src_kind, old_ie)
            if status in ("noroot", "noaccess"):
                msgCritical(
                    "無法存取歸檔資料夾",
                    "電子檔所在的歸檔資料夾目前無法存取，無法完成轉換。\n"
                    "請確認網路磁碟機已連線、歸檔資料夾設定正確後再試。")
                return
            if status == "notfound":
                pdf_missing = True          # 轉未歸檔
            else:                           # ok
                old_path = path

        # ── transaction：先動檔案、DB 失敗把檔案還原（比照 _doArchive）──
        am = AuthManager.instance()
        conn = None
        moved = None                        # (dest_path, old_path) 供還原
        try:
            conn = getConn(self.db_path)
            nr = doc_convert.makeNameResolver(conn)
            new_id, _snap = doc_convert.convertDoc(
                conn, src_kind=self.src_kind, doc_id=self.doc_id,
                fill_values=fill, role=am.current_role, operator=am.actor_name(),
                is_electronic="", name_resolver=nr)

            if old_path:
                new_name = _sanitize(doc_convert.renamePdfWithNewPk(old_ie, new_id))
                dest_dir = archiveDefaultDir(self.db_path, self.dst_kind)
                if not dest_dir or not os.path.isdir(dest_dir):
                    raise RuntimeError("目標歸檔資料夾無法存取")
                dest_path = os.path.join(dest_dir, new_name)
                # 防禦縱深：落點仍在歸檔根下（比照 _doArchive commonpath）
                base = os.path.abspath(dest_dir)
                if os.path.commonpath([base, os.path.abspath(dest_path)]) != base:
                    raise RuntimeError("產生的檔名不安全")
                if os.path.exists(dest_path):
                    raise RuntimeError(f"目標資料夾已有同名檔案：{new_name}")
                shutil.move(old_path, dest_path)        # 檔案先走
                moved = (dest_path, old_path)
                conn.execute(
                    f"UPDATE Document_{'Criminal' if self.dst_kind=='crim' else 'General'} "
                    "SET is_electronic=? WHERE doc_id=?", (new_name, new_id))

            conn.commit()
            self.new_doc_id = new_id
        except Exception as e:
            if conn is not None:
                try:
                    conn.rollback()
                except Exception:
                    pass
            if moved:                       # DB 失敗→把檔案搬回原位
                try:
                    shutil.move(moved[0], moved[1])
                except Exception:
                    pass
            reportError("轉換失敗", e)
            return
        finally:
            if conn is not None:
                conn.close()

        if old_path:
            clearPdfIndexCache()
        msg = f"已轉換至{self.dst_cat}案類，新編號：{new_id}"
        if pdf_missing:
            msg += f"\n找不到原電子檔（{old_ie}），新單已列為未歸檔。"
        msgInfo("轉換完成", msg, parent=self)
        self.accept()
