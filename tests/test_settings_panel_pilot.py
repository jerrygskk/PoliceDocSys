"""GUI pilot：系統設定六面板的「接線」與「髒值判斷」。

**接線**指的是這條接縫：面板把值寫進 `App_Settings` 的某個 key，別處的程式再把它
讀出來用。兩邊分開維護，寫錯 key、正規化方式不一致、或消費端改讀別的 key，
**不會有任何錯誤訊息**，症狀只有「設定了但沒作用」——使用者往往以為是自己沒按到
儲存。既有測試只涵蓋其中兩個面板（輸入模式、簽收表標題），歸檔資料夾、閒置逾時、
備份設定三個完全沒有，唯讀鎖只測過「不會動到別的流程」。

**髒值判斷**是共用基底 `_SettingsPanel.isDirty` 的行為：六個面板都靠它決定儲存鈕
亮不亮、切頁要不要攔。目前零測試，壞掉的症狀是「改了值按不了儲存」或「沒改也
一直提示未存」，使用者會直接抱怨。

**不做**：「按鈕有沒有 connect 到面板」這一層——組裝已由
`tests/test_standalone_settings.py` 涵蓋，再測一次是數線頭。

替身：只有提示框（離線 modal 會無限等待，PITFALLS TST-4）。

只建面板、不建 `DocumentManager`，故留在 qt 層、不需行程隔離（PITFALLS TST-5）。
"""

import os
import shutil
import sqlite3

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    import pytest
except ModuleNotFoundError as exc:  # 讓 unittest discover 在缺 pytest 時記為「跳過」而非 ImportError
    if exc.name != "pytest":
        raise
    import unittest

    raise unittest.SkipTest("需 pytest/pytest-qt，請以 pytest 執行此檔")

from lib.auth_manager import AuthManager
from lib.db_schema import applySchema
from lib.db_seed import seedFreshDb
from lib.db_utils import (
    PRINT_TITLE_KEYS, archiveDefaultDir, getBackupSecondDir, getIdleTimeoutsMs,
    isInputLocked, isSelfServiceMode, printTitle)
import ui_utils.settings_panels as panels_module
from ui_utils.settings_panels import (
    ArchiveRootPanel, BackupPanel, IdleTimeoutPanel, InputLockPanel,
    InputModePanel, PrintTitlePanel)


ARCHIVE_ROOT = r"Z:\案件掃描檔\115年"
BACKUP_DIR = r"\\nas\備份\公文"
NEW_TITLE = "測試所刑案陳報單發文簽收表"


@pytest.fixture(scope="session")
def _db_template(tmp_path_factory):
    path = tmp_path_factory.mktemp("panel-template") / "template.db"
    conn = sqlite3.connect(path)
    applySchema(conn)
    seedFreshDb(conn)
    conn.commit()
    conn.close()
    return str(path)


@pytest.fixture
def db_path(tmp_path, _db_template):
    path = tmp_path / "panel-pilot.db"
    shutil.copy2(_db_template, path)
    return str(path)


@pytest.fixture(autouse=True)
def _admin_role():
    AuthManager.instance()._role = "admin"
    yield
    AuthManager.instance()._role = "user"


@pytest.fixture(autouse=True)
def _quiet_dialogs(monkeypatch):
    """面板在驗證失敗時會彈提示；離線環境一律攔掉。"""
    seen = []
    for name in ("msgWarning", "msgCritical", "msgInfo"):
        if hasattr(panels_module, name):
            monkeypatch.setattr(
                panels_module, name,
                lambda title, text=None, *a, **kw: seen.append(title))
    return seen


# ── 六個面板的「改什麼 → 寫哪裡 → 消費端讀出來該是什麼」對照表 ──────
# ⚠️ 新增系統設定面板時補一列即可，不要另寫一段流程。

def _set_archive(panel):
    panel.w_path.setText(ARCHIVE_ROOT)
    panel.cb_crim.setCurrentText("刑案")
    panel.cb_gen.setCurrentText("一般")


def _set_print_title(panel):
    panel._edits[PRINT_TITLE_KEYS["crim"]].setText(NEW_TITLE)


def _set_idle(panel):
    panel.sp_logout.setValue(5)
    panel.sp_close.setValue(20)


def _set_input_lock(panel):
    panel._checks["reward"].setChecked(True)


def _set_backup(panel):
    panel.w_path.setText(BACKUP_DIR)


def _set_input_mode(panel):
    panel._radios["ticket"][1].setChecked(True)      # (送文者鈕, 自助鈕)


PANELS = {
    "歸檔資料夾": {
        "make": ArchiveRootPanel,
        "change": _set_archive,
        # 消費端：歸檔頁選資料夾的預設起點＝根 + 該類別子夾
        "expect": lambda db: archiveDefaultDir(db, "crim") == os.path.join(
            ARCHIVE_ROOT, "刑案"),
        "roles_allowed": ("admin", "archive"),   # 歸檔管理也能改
    },
    "簽收表標題": {
        "make": PrintTitlePanel,
        "change": _set_print_title,
        "expect": lambda db: printTitle(db, "crim") == NEW_TITLE,
        "roles_allowed": ("admin",),
    },
    "閒置逾時": {
        "make": IdleTimeoutPanel,
        "change": _set_idle,
        # 消費端：主視窗啟動時換算成毫秒設定計時器
        "expect": lambda db: getIdleTimeoutsMs(db) == (5 * 60000, 20 * 60000),
        "roles_allowed": ("admin",),
    },
    "唯讀鎖": {
        "make": InputLockPanel,
        "change": _set_input_lock,
        "expect": lambda db: isInputLocked(db, "reward") is True,
        "roles_allowed": ("admin",),
    },
    "備份設定": {
        "make": BackupPanel,
        "change": _set_backup,
        "expect": lambda db: getBackupSecondDir(db) == BACKUP_DIR,
        "roles_allowed": ("admin",),
    },
    "輸入模式": {
        "make": InputModePanel,
        "change": _set_input_mode,
        "expect": lambda db: isSelfServiceMode(db, "ticket") is True,
        "roles_allowed": ("admin",),
    },
}


def _make(qtbot, db_path, name):
    panel = PANELS[name]["make"](db_path)
    qtbot.addWidget(panel)
    return panel


# ── 接線 ──────────────────────────────────────────────────────

@pytest.mark.parametrize("name", list(PANELS))
def test_panel_save_is_readable_by_its_consumer(qtbot, db_path, name):
    """面板存進去的值，消費端必須讀得出來。

    刻意用**消費端自己的讀取函式**斷言，而不是直接查 `App_Settings`：只查 key 的話，
    寫錯 key 名或正規化方式與讀取端不一致仍會漏掉——那正是「設定了但沒作用」的成因。"""
    spec = PANELS[name]
    panel = _make(qtbot, db_path, name)
    assert not spec["expect"](db_path), f"{name}：前置狀態不該已符合預期"

    spec["change"](panel)
    assert panel._save() is True, f"{name}：存檔應成功"

    assert spec["expect"](db_path), f"{name}：消費端讀不到面板存進去的值"


@pytest.mark.parametrize("name", list(PANELS))
def test_panel_save_is_blocked_for_roles_without_permission(
        qtbot, db_path, name):
    """面板反灰之外的保底：無權身分呼叫存檔要回 False 且不得寫入任何值。"""
    spec = PANELS[name]
    panel = _make(qtbot, db_path, name)
    spec["change"](panel)
    AuthManager.instance()._role = (
        "user" if "archive" in spec["roles_allowed"] else "archive")

    assert panel._save() is False, f"{name}：無權身分不得存檔成功"
    assert not spec["expect"](db_path), f"{name}：無權身分不得寫入設定值"


def test_archive_root_panel_also_allows_archive_role(qtbot, db_path):
    """歸檔資料夾是唯一開放給歸檔管理身分的面板（比照原本的對話框開放範圍），
    不得被誤縮成僅 admin。"""
    panel = _make(qtbot, db_path, "歸檔資料夾")
    _set_archive(panel)
    AuthManager.instance()._role = "archive"

    assert panel._save() is True
    assert PANELS["歸檔資料夾"]["expect"](db_path)


# ── 髒值判斷（共用基底 _SettingsPanel）────────────────────────

@pytest.mark.parametrize("name", list(PANELS))
def test_save_button_tracks_dirty_state(qtbot, db_path, name):
    """儲存鈕的亮／灰完全由髒值判斷驅動：初始灰、改了亮、存完回灰。
    壞掉的症狀是「改了值按不了儲存」或「沒改也一直提示未存」。"""
    spec = PANELS[name]
    panel = _make(qtbot, db_path, name)
    assert panel.isDirty() is False, f"{name}：剛載入不該是髒的"
    assert panel._btn_save.isEnabled() is False, f"{name}：初始儲存鈕應為灰"

    spec["change"](panel)
    assert panel.isDirty() is True, f"{name}：改了值應為髒"
    assert panel._btn_save.isEnabled() is True, f"{name}：改了值儲存鈕應亮"

    assert panel._save() is True
    assert panel.isDirty() is False, f"{name}：存檔後應重設基準"
    assert panel._btn_save.isEnabled() is False, f"{name}：存檔後儲存鈕應回灰"


@pytest.mark.parametrize("name", list(PANELS))
def test_reload_resets_dirty_baseline_and_discards_edits(qtbot, db_path, name):
    """reload 會把畫面重讀成 DB 現值並重設基準——改到一半按「重整」等於放棄修改，
    儲存鈕必須跟著回灰，否則會出現「按得下去但其實沒有變更」的錯覺。"""
    spec = PANELS[name]
    panel = _make(qtbot, db_path, name)
    spec["change"](panel)
    assert panel.isDirty() is True

    panel.reload()

    assert panel.isDirty() is False
    assert panel._btn_save.isEnabled() is False
    assert not spec["expect"](db_path), "reload 不得把畫面值寫進 DB"


@pytest.mark.parametrize("name", list(PANELS))
def test_saving_same_values_twice_leaves_panel_clean(qtbot, db_path, name):
    """存檔後重建面板，載入的就是剛存的值 → 不得被判為髒（否則每次進設定頁
    都會亮著儲存鈕、切頁還會攔一次）。"""
    spec = PANELS[name]
    panel = _make(qtbot, db_path, name)
    spec["change"](panel)
    assert panel._save() is True

    fresh = _make(qtbot, db_path, name)

    assert fresh.isDirty() is False
    assert fresh._btn_save.isEnabled() is False


def test_archive_root_rejects_blank_path_without_saving(qtbot, db_path):
    """歸檔資料夾留白 → 存檔回 False 並亮紅框，不得把空路徑寫進設定
    （空路徑會讓歸檔頁的預設起點失效，且沒有任何錯誤訊息）。"""
    panel = _make(qtbot, db_path, "歸檔資料夾")
    _set_archive(panel)
    assert panel._save() is True

    panel.w_path.setText("   ")

    assert panel._save() is False
    assert archiveDefaultDir(db_path, "crim") == os.path.join(ARCHIVE_ROOT, "刑案"), \
        "留白存檔失敗後，原本的設定必須原封不動"


def test_idle_panel_rejects_close_not_greater_than_logout(qtbot, db_path):
    """強制關閉時間必須大於自動登出時間，否則使用者會在被登出前就先被關掉程式。
    驗證失敗時要提示且不得寫入。"""
    panel = _make(qtbot, db_path, "閒置逾時")
    panel.sp_logout.setValue(10)
    panel.sp_close.setValue(10)

    assert panel._save() is False
    assert getIdleTimeoutsMs(db_path) == (10 * 60000, int(14.5 * 60000)), \
        "驗證失敗時應維持預設值，不得寫入不合法組合"
