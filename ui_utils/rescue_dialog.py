"""
rescue_dialog.py — 開機期資料庫損毀救援對話框

quick_check 在載入前偵測到 dbfile.db 損毀時（主視窗、設定頁都還沒建立），
由 main.py 呼叫 runStartupRescue()。因為「備份還原」子頁在程式內、DB 壞到開不了
時根本進不去，故把還原路徑前移到開機期，讓災難當下真的救得回來。

行為（與維護者議定）：
  - 程式自動從所有備份（backups／異地／留底，最新在前）逐份 quick_check，
    挑第一份完好的當預設還原來源；全壞／找不到才讓使用者手動選檔（預設開 backups）。
  - 還原為破壞性操作，仍要管理者密碼——但本體已壞、驗不了，改驗「將還原的那份備份」
    內的 admin_password_hash。
  - 還原成功後往還原好的 DB 補一筆「開機還原」稽核，提示重新開啟程式後結束
    （不自動重啟：救援情境多按一次開程式可接受，且開機期不宜依賴主程式的重啟碼）。

多機互斥不在此重複判斷：main.py 於本對話框之前已跑過 app_lock 使用中勸導。
"""
import os

from PySide6.QtCore    import Qt
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QFileDialog,
)

from lib.db_backup import formatDocCounts

from .ui_common import msgInfo, msgWarning

_DIALOG_SS = """
    QDialog { background-color: #ffffff; }
    QLabel { color: #1c1c1e; background: transparent; font-size: 13pt; }
    QLabel#title { font-size: 16pt; font-weight: 700; color: #c0392b; }
    QLabel#err { color: #c0392b; font-size: 11pt; }
    QLineEdit {
        background-color: #ffffff; color: #000000;
        border: 1px solid #cccccc; border-radius: 4px; padding: 6px 10px;
        font-size: 13pt;
    }
    QLineEdit:focus { border: 1px solid #8fa8c8; }
    QPushButton {
        background-color: #ffffff; color: #1c1c1e;
        border: 1px solid #c6c6c8; border-radius: 8px;
        padding: 8px 20px; font-weight: 600;
    }
    QPushButton:hover { background-color: #f2f2f7; }
    QPushButton#danger {
        background-color: #e74c3c; color: #ffffff; border: none;
    }
    QPushButton#danger:hover    { background-color: #c0392b; }
    QPushButton#danger:disabled { background-color: #e6b8b3; color: #ffffff; }
"""


def _formatDocCounts(counts):
    """開機救援來源的內容摘要；None 表示該表不存在或無法讀取。"""
    return formatDocCounts(counts, prefix="內含：")


class RescueDialog(QDialog):
    def __init__(self, db_path, parent=None):
        super().__init__(parent)
        self.db_path = db_path
        self._path = None          # 當前選定的還原來源備份
        self._restored = False
        self.setWindowTitle("資料庫損毀 — 還原")
        self.setStyleSheet(_DIALOG_SS)
        self.setMinimumWidth(520)
        self._build()
        self._autoPick()

    def _build(self):
        v = QVBoxLayout(self)
        v.setContentsMargins(24, 20, 24, 20)
        v.setSpacing(12)

        title = QLabel("偵測到資料庫損毀")
        title.setObjectName("title")
        v.addWidget(title)

        self.lbl_info = QLabel("")
        self.lbl_info.setWordWrap(True)
        v.addWidget(self.lbl_info)

        # 密碼列（有可用備份時才啟用）
        pw_row = QHBoxLayout()
        pw_row.setSpacing(10)
        pw_row.addWidget(QLabel("管理者密碼"))
        self.w_pw = QLineEdit()
        self.w_pw.setEchoMode(QLineEdit.Password)
        self.w_pw.returnPressed.connect(self._restore)
        pw_row.addWidget(self.w_pw, 1)
        v.addLayout(pw_row)

        self.lbl_err = QLabel("")
        self.lbl_err.setObjectName("err")
        v.addWidget(self.lbl_err)

        # 按鈕列
        row = QHBoxLayout()
        self.btn_pick = QPushButton("改選其他備份檔")
        self.btn_pick.clicked.connect(self._pickOther)
        row.addWidget(self.btn_pick)
        row.addStretch()
        btn_quit = QPushButton("結束")
        btn_quit.clicked.connect(self.reject)
        row.addWidget(btn_quit)
        self.btn_restore = QPushButton("還原並結束")
        self.btn_restore.setObjectName("danger")
        self.btn_restore.clicked.connect(self._restore)
        row.addWidget(self.btn_restore)
        v.addLayout(row)

    def _autoPick(self):
        """自動挑最新可用備份；無則進手動選檔模式。"""
        from lib.db_backup import find_latest_usable_backup
        from lib.db_utils import getBackupSecondDir
        second = getBackupSecondDir(self.db_path)   # 壞 DB 多半仍讀得到 App_Settings；讀不到回空
        e = find_latest_usable_backup(
            self.db_path, extra_dirs=[second] if second else None)
        if e:
            self._setSource(e["path"], auto=True)
        else:
            self._path = None
            self.lbl_info.setText(
                "資料庫檔案已損毀，且在備份資料夾中找不到可用的備份。\n"
                "可按「改選其他備份檔」自其他位置（例如隨身碟）選擇一份備份還原，"
                "或聯絡維護人員。")
            self._updateButtons()

    def _setSource(self, path, auto=False):
        """設定還原來源並顯示其日期／內含筆數。"""
        from lib.db_backup import backup_doc_counts
        self._path = path
        counts = backup_doc_counts(path)
        if counts:
            detail = _formatDocCounts(counts)
        else:
            detail = "（無法讀取內容摘要）"
        lead = "偵測到可用備份" if auto else "已選擇備份"
        self.lbl_info.setText(
            f"資料庫檔案已損毀。{lead}：\n"
            f"{os.path.basename(path)}\n{detail}\n\n"
            "請輸入管理者密碼以還原（將以此備份覆蓋損毀的資料庫）。")
        self.lbl_err.setText("")
        self._updateButtons()

    def _updateButtons(self):
        has = self._path is not None
        self.btn_restore.setEnabled(has)
        self.w_pw.setEnabled(has)
        if has:
            self.w_pw.setFocus()

    def _pickOther(self):
        from lib.db_backup import verify_backup
        start = os.path.join(
            os.path.dirname(os.path.abspath(self.db_path)), "backups")
        if not os.path.isdir(start):
            start = os.path.dirname(os.path.abspath(self.db_path))
        path, _ = QFileDialog.getOpenFileName(
            self, "選擇備份檔", start, "SQLite 資料庫 (*.db);;所有檔案 (*.*)")
        if not path:
            return
        ok, msg = verify_backup(path)
        if not ok:
            msgWarning("無法使用此檔案", msg, self)
            return
        self._setSource(path, auto=False)

    def _restore(self):
        from lib.db_backup import verify_admin_password, restore_backup
        from lib.db_utils import writeAuditSafe, buildDetail
        if not self._path:
            return
        pw = self.w_pw.text()
        if not pw:
            self.lbl_err.setText("請輸入管理者密碼。")
            return
        if not verify_admin_password(self._path, pw):
            self.lbl_err.setText("管理者密碼錯誤（此備份當時的密碼）。")
            self.w_pw.clear()
            self.w_pw.setFocus()
            return
        ok, msg = restore_backup(self.db_path, self._path)
        if not ok:
            msgWarning("還原失敗", msg, self)
            return
        # 還原好的 DB 補一筆稽核（開機救援；本體壞掉時原無法記錄）
        writeAuditSafe(self.db_path, role="admin", operator="管理者",
                       action="CONFIG",
                       detail=buildDetail("系統", "還原",
                                          f"開機救援還原：{os.path.basename(self._path)}"))
        self._restored = True
        msgInfo("還原完成",
                "資料庫已還原，請重新開啟程式。\n\n"
                "提醒：於備份時間點之後歸檔的電子檔，其歸檔狀態可能與歸檔資料夾不符，"
                "請至「檔案歸檔」頁核對。", self)
        self.accept()


def runStartupRescue(db_path):
    """開機期 DB 損毀救援。回 True＝已還原（呼叫端應提示重開並結束）、
    False＝使用者未還原（呼叫端仍應結束，不得載入壞 DB）。"""
    dlg = RescueDialog(db_path)
    dlg.exec()
    return dlg._restored
