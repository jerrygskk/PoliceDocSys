"""GUI pilot：跨年度重置一條龍（確認視窗 → 稽核 → 自動備份 → 重置 → 善後）。

跨年度重置是全系統最破壞性的操作：清空五張主表、刪掉停用的參照項、重編 id、
文號歸零、清空歸檔路徑，而且不可復原。既有測試涵蓋兩端——底層
`performYearEndReset` 在 `test_db_utils.py`，按鈕接線與**降權時的三道複核**在
`test_standalone_settings.py`（該檔把確認視窗與重置函式都換成假的）。

**沒人看的是中段**：真的確認視窗、真的備份、真的重置串起來會發生什麼。本檔補的
就是這一段，重點有二——

1. **稽核必須寫在備份之前**：`performYearEndReset` 會清空當前庫的 `Audit_Log`，
   所以那筆「重置」紀錄只可能保存在備份檔裡。順序一顛倒，紀錄就永遠消失，
   而且不會有任何錯誤訊息。
2. **備份失敗一定要中止**：沒備份就重置等於資料直接沒了。

替身（其餘全用真的）：確認視窗的 `exec()`（就地驅動；離線 modal 會無限等待，
PITFALLS TST-4）、另存備份的原生視窗、各式提示框、**重啟程式**（絕不能真的重啟）。

不做：`_restartApp` 內部的 PyInstaller 打包分支——要 frozen 環境才驗得到。

只建設定頁一個分頁、不建 `DocumentManager`，故留在 qt 層、不需行程隔離
（PITFALLS TST-5）。
"""

import os
import sqlite3

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    import pytest
except ModuleNotFoundError as exc:  # 讓 unittest discover 在缺 pytest 時記為「跳過」而非 ImportError
    if exc.name != "pytest":
        raise
    import unittest

    raise unittest.SkipTest("需 pytest/pytest-qt，請以 pytest 執行此檔")

from PySide6.QtWidgets import QDialog, QTabWidget, QWidget

from lib.auth_manager import AuthManager
from lib.db_backup import RESET_KEEP
from lib.db_schema import applySchema
from lib.db_seed import seedFreshDb
from lib.db_utils import ARCHIVE_ROOT_KEY, getSetting, setSetting
import tabs.tab_settings as settings_module
from tabs.tab_settings import TabSettings
from ui_utils.settings_dialogs import ResetDialog


# 本檔建立的設定頁；收尾要逐一拆掉掛在 AuthManager 單例上的連線（見 _admin_role）
_MADE_TABS = []

ACTIVE_STAFF = ("P01", "王小明")
INACTIVE_STAFF = ("P02", "李小華")     # 停用項目：重置時應被刪除


@pytest.fixture
def db_path(tmp_path):
    """暫存 DB：真實 schema ＋ 種子，再補一筆待清空的公文、一個停用人員、
    一個歸檔路徑設定，讓重置有東西可清。"""
    path = tmp_path / "reset-pilot.db"
    conn = sqlite3.connect(path)
    applySchema(conn)
    seedFreshDb(conn)
    conn.execute(
        "INSERT OR REPLACE INTO Ref_Personnel"
        "(staff_id,staff_name,is_active,sort_order) VALUES(?,?,?,?)",
        (*INACTIVE_STAFF, 0, 9))
    conn.execute(
        "INSERT INTO Document_Criminal"
        "(doc_id,create_date,report_date,processor_id,subject_summary,is_reported)"
        " VALUES(?,?,?,?,?,?)",
        ("1", "2026-08-01", "2026-08-01", ACTIVE_STAFF[0], "待清空的刑案", 0))
    conn.execute("UPDATE Seq_DocId SET last_id=7 WHERE table_name='Document_Criminal'")
    conn.commit()
    conn.close()
    setSetting(str(path), ARCHIVE_ROOT_KEY, str(tmp_path / "archive"))
    return str(path)


@pytest.fixture(autouse=True)
def _admin_role():
    """重置僅管理身分可為。收尾必須拆掉 `role_changed` 連線——`TabSettings.setup`
    會把處理函式掛上 `AuthManager` 單例，分頁被回收後連線仍在，之後別支測試
    切換身分就會打到已釋放的 C++ 物件，紅在毫不相干的檔案上（本專案踩過）。"""
    auth = AuthManager.instance()
    auth._role = "admin"
    yield
    while _MADE_TABS:
        tab = _MADE_TABS.pop()
        try:
            auth.role_changed.disconnect(tab._onRoleChanged)
        except (RuntimeError, TypeError):
            pass   # 已隨 widget 一併失效
    auth._role = "user"


@pytest.fixture
def quiet_dialogs(monkeypatch):
    """攔掉所有 modal 與重啟：確認框固定回「確定」，其餘只記標題供斷言。"""
    seen = {"confirm": [], "warning": [], "critical": [], "info": [], "error": [],
            "restart": 0}
    monkeypatch.setattr(
        settings_module, "confirmBox",
        lambda title, text=None, **kw: (seen["confirm"].append(title), True)[1])
    for name, bucket in (("msgWarning", "warning"), ("msgCritical", "critical"),
                         ("msgInfo", "info")):
        monkeypatch.setattr(
            settings_module, name,
            lambda title, text=None, *a, _b=bucket, **kw: seen[_b].append(title))
    monkeypatch.setattr(
        settings_module, "reportError",
        lambda title, exc=None, *a, **kw: seen["error"].append(title))
    monkeypatch.setattr(
        TabSettings, "_restartApp",
        lambda self: seen.__setitem__("restart", seen["restart"] + 1))
    # 另存備份的原生視窗：預設不另存（另存分支另有專測）
    monkeypatch.setattr(
        settings_module.QFileDialog, "getSaveFileName",
        staticmethod(lambda *a, **kw: ("", "")))
    return seen


def _make_settings(qtbot, db_path):
    tabs = QTabWidget()
    tabs.addTab(QWidget(), "設定")
    qtbot.addWidget(tabs)
    tab = TabSettings(tabs, db_path)
    tab.setup(0)
    tab._applyRolePermissions()
    _MADE_TABS.append(tab)
    return tab


def _drive_reset_dialog(monkeypatch, *, word="RESET"):
    """把確認視窗的 exec() 換成就地驅動：填入確認字串後按「執行重置」。
    仍走真實的 `_submit` 驗證邏輯，只是不進 modal 事件迴圈。"""
    driven = []

    def _exec(self):
        self.w_confirm.setText(word)
        self._submit()
        driven.append(self.result())
        return int(self.result())

    monkeypatch.setattr(ResetDialog, "exec", _exec)
    return driven


def _backups(db_path):
    db_dir = os.path.dirname(db_path)
    return sorted(f for f in os.listdir(db_dir)
                  if f.startswith("dbfile_backup_") and f.endswith(".db"))


def _query(path, sql):
    conn = sqlite3.connect(path)
    try:
        return conn.execute(sql).fetchall()
    finally:
        conn.close()


# ── 測試 ──────────────────────────────────────────────────────

def test_reset_dialog_requires_exact_confirm_word(qtbot, db_path):
    """確認視窗防誤按：打錯字不放行並提示，打對 RESET 才 accept。"""
    dlg = ResetDialog(db_path, doc_summary="刑案 1 筆")
    qtbot.addWidget(dlg)

    dlg.w_confirm.setText("reset")          # 大小寫不符
    dlg._submit()
    assert dlg.result() != int(QDialog.DialogCode.Accepted)
    assert "RESET" in dlg.lbl_err.text()
    assert dlg.w_confirm.text() == "", "打錯後應清空輸入框，避免再按一次就過"

    dlg.w_confirm.setText("RESET")
    dlg._submit()
    assert dlg.result() == int(QDialog.DialogCode.Accepted)


def test_cancelling_dialog_leaves_everything_untouched(
        qtbot, db_path, quiet_dialogs, monkeypatch):
    """確認視窗取消 → 不備份、不重置、不重啟。"""
    settings = _make_settings(qtbot, db_path)
    monkeypatch.setattr(ResetDialog, "exec", lambda self: 0)

    settings._doReset()

    assert _backups(db_path) == []
    assert _query(db_path, "SELECT COUNT(*) FROM Document_Criminal")[0][0] == 1
    assert quiet_dialogs["restart"] == 0


def test_audit_is_written_before_backup_so_it_survives_in_the_backup_file(
        qtbot, db_path, quiet_dialogs, monkeypatch):
    """重置稽核必須寫在備份**之前**——`performYearEndReset` 會清空當前庫的
    `Audit_Log`，那筆紀錄只可能保存在備份檔裡。順序顛倒的話紀錄永遠消失，
    而且不會有任何錯誤訊息，只有這條斷言看得出來。"""
    settings = _make_settings(qtbot, db_path)
    _drive_reset_dialog(monkeypatch)

    settings._doReset()

    backups = _backups(db_path)
    assert len(backups) == 1, "應在資料庫同目錄產生一份自動備份"
    backup_path = os.path.join(os.path.dirname(db_path), backups[0])

    rows = _query(backup_path,
                  "SELECT action, detail FROM Audit_Log WHERE action='RESET'")
    assert len(rows) == 1, "備份檔裡必須查得到那筆重置稽核"
    assert "重置" in rows[0][1]

    assert _query(db_path, "SELECT COUNT(*) FROM Audit_Log")[0][0] == 0, \
        "當前庫的操作紀錄已被重置清空（故備份是唯一留存處）"
    # 備份是重置「之前」的快照：舊資料仍在
    assert _query(backup_path, "SELECT COUNT(*) FROM Document_Criminal")[0][0] == 1


def test_full_reset_clears_documents_refs_sequence_and_archive_root(
        qtbot, db_path, quiet_dialogs, monkeypatch):
    """跑完整條流程後的最終狀態：主表清空、停用項刪除、id 重編、文號歸零、
    歸檔路徑清空，並提示完成後重啟。"""
    settings = _make_settings(qtbot, db_path)
    _drive_reset_dialog(monkeypatch)

    settings._doReset()

    assert _query(db_path, "SELECT COUNT(*) FROM Document_Criminal")[0][0] == 0
    staff = _query(db_path, "SELECT staff_id, staff_name FROM Ref_Personnel")
    assert INACTIVE_STAFF[1] not in [name for _sid, name in staff], "停用人員應被刪除"
    assert [sid for sid, _n in staff] == ["P01"], "存活人員 id 應重編為連續"
    assert _query(
        db_path,
        "SELECT last_id FROM Seq_DocId WHERE table_name='Document_Criminal'"
    )[0][0] == 0
    assert getSetting(db_path, ARCHIVE_ROOT_KEY, "") == ""
    assert quiet_dialogs["info"] == ["重置完成"]
    assert quiet_dialogs["restart"] == 1
    assert not quiet_dialogs["error"] and not quiet_dialogs["critical"]


def test_backup_failure_aborts_before_touching_any_data(
        qtbot, db_path, quiet_dialogs, monkeypatch):
    """自動備份失敗 → 提示並中止，資料一筆都不能動。
    這是整條流程最要緊的一條：沒有備份就重置等於資料直接沒了。"""
    settings = _make_settings(qtbot, db_path)
    _drive_reset_dialog(monkeypatch)

    def _boom(src, dst):
        raise OSError("磁碟空間不足")

    monkeypatch.setattr(settings_module.shutil, "copy2", _boom)
    reset_called = []
    monkeypatch.setattr(settings_module, "performYearEndReset",
                        lambda path: reset_called.append(path))

    settings._doReset()

    assert quiet_dialogs["critical"] == ["備份失敗"]
    assert reset_called == [], "備份失敗後不得執行重置"
    assert _query(db_path, "SELECT COUNT(*) FROM Document_Criminal")[0][0] == 1
    assert getSetting(db_path, ARCHIVE_ROOT_KEY, "") != ""
    assert quiet_dialogs["restart"] == 0


def test_old_reset_backups_are_pruned_to_keep_limit(
        qtbot, db_path, quiet_dialogs, monkeypatch):
    """重置留底只保留最新 RESET_KEEP 份，最舊的會被修剪掉。"""
    db_dir = os.path.dirname(db_path)
    stale = [f"dbfile_backup_2020010{i}_000000.db" for i in range(1, RESET_KEEP + 2)]
    for name in stale:
        with open(os.path.join(db_dir, name), "wb") as fh:
            fh.write(b"old")

    settings = _make_settings(qtbot, db_path)
    _drive_reset_dialog(monkeypatch)

    settings._doReset()

    remaining = _backups(db_path)
    assert len(remaining) == RESET_KEEP, f"應只保留最新 {RESET_KEEP} 份"
    assert stale[0] not in remaining, "最舊的留底應被修剪"


def test_optional_extra_backup_is_saved_to_chosen_path(
        qtbot, db_path, quiet_dialogs, monkeypatch, tmp_path):
    """另存備份分支：使用者選了位置就要真的存出一份可讀的資料庫，
    且不影響自動備份與重置本身。"""
    dest = tmp_path / "外接硬碟備份.db"
    monkeypatch.setattr(
        settings_module.QFileDialog, "getSaveFileName",
        staticmethod(lambda *a, **kw: (str(dest), "")))
    settings = _make_settings(qtbot, db_path)
    _drive_reset_dialog(monkeypatch)

    settings._doReset()

    assert dest.exists(), "另存的備份應真的產生"
    assert _query(str(dest), "SELECT COUNT(*) FROM Document_Criminal")[0][0] == 1
    assert len(_backups(db_path)) == 1, "自動備份仍應存在"
    assert _query(db_path, "SELECT COUNT(*) FROM Document_Criminal")[0][0] == 0
