"""GUI pilot：登出當下，開著的真實編輯視窗會被關掉且不寫入資料庫。

與 `test_standalone_shell.py` 既有的登出測試不同——那邊用假的 `_StubDialog`
驗「有沒有被 reject」，這裡用**真的** `RewardEditDialog` 搭**真的**
`DocumentManager`，走完「進管理頁 → 開修改視窗 → 改了欄位還沒按儲存 →
閒置自動登出」整條路，斷言使用者實際會看到的結果：視窗消失、改的字沒進 DB、
身分掉回 user、頁面依原本規則安置。

⚠️ 全檔不得呼叫 `dialog.exec()`：離線環境的 modal 會無限等待（PITFALLS TST-4）。
⚠️ 本檔會在行程內建立 `DocumentManager`，故必須列在根 `conftest.py` 的
   `ISOLATED_MODULES`（PITFALLS TST-5）。
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

from PySide6.QtWidgets import QDialog

from lib.app_profile import FULL_PROFILE
from lib.auth_manager import AuthManager
from lib.db_schema import applySchema
import main as main_module
from main import DocumentManager
from ui_utils.reward_dialog import RewardEditDialog


DOC_ID = "A001"
ORIGINAL_REASON = "查獲毒品案件"
TYPED_REASON = "尚未按下儲存的新事由"


@pytest.fixture
def pilot_db(tmp_path, monkeypatch):
    """套用真實 schema 的暫存 DB，並讓 main.getResourcePath('dbfile.db') 指向它；
    其餘資源路徑（.ui／.svg）仍走真實解析。"""
    db_path = tmp_path / "logout-pilot.db"
    conn = sqlite3.connect(db_path)
    applySchema(conn)
    conn.execute(
        "INSERT INTO Ref_Personnel(staff_id,staff_name,is_active,sort_order)"
        " VALUES(?,?,?,?)",
        ("P01", "王小明", 1, 1),
    )
    conn.execute(
        "INSERT INTO Document_Reward"
        "(doc_id,create_date,register_date,sender_id,reason,recipients)"
        " VALUES(?,?,?,?,?,?)",
        (DOC_ID, "2026-08-01", "2026-08-01", "P01", ORIGINAL_REASON, "王小明"),
    )
    conn.commit()
    conn.close()

    real_get_resource_path = main_module.getResourcePath

    def fake_get_resource_path(rel):
        if rel == "dbfile.db":
            return str(db_path)
        return real_get_resource_path(rel)

    monkeypatch.setattr(main_module, "getResourcePath", fake_get_resource_path)
    return str(db_path)


@pytest.fixture(autouse=True)
def _detach_manager_signals():
    """AuthManager 是單例；測試反覆建立 manager 會把已回收的視窗留在 role_changed
    上，之後任何切換身分都會打到已釋放的 C++ 物件而讓別支測試莫名紅燈。
    同 `test_standalone_shell.py` 的處理。"""
    auth = AuthManager.instance()
    auth._role = "user"
    yield
    try:
        auth.role_changed.disconnect()
    except (RuntimeError, TypeError):
        pass   # 本來就沒有連線
    auth._role = "user"


def _read_reason(db_path):
    conn = sqlite3.connect(db_path)
    try:
        return conn.execute(
            "SELECT reason FROM Document_Reward WHERE doc_id=?", (DOC_ID,)
        ).fetchone()[0]
    finally:
        conn.close()


def _enter_admin(manager, tab_key):
    auth = AuthManager.instance()
    auth._role = "admin"
    auth.role_changed.emit("admin")
    manager.requestTab(tab_key)
    assert manager.tab_widget.currentIndex() == manager.tab_index(tab_key)
    return auth


def _open_edit_dialog(qtbot, manager, db_path):
    """走瀏覽頁真正使用的建構方式（見 tabs/tab_dbbrowse.py 的 _onEdit）。
    只 show() 不 exec()：離線 modal 會卡死（PITFALLS TST-4）。"""
    dialog = RewardEditDialog(db_path, DOC_ID, manager.window, source="browse")
    qtbot.addWidget(dialog)
    dialog.show()
    qtbot.waitExposed(dialog)
    assert dialog.w_reason.text() == ORIGINAL_REASON
    dialog.w_reason.setText(TYPED_REASON)      # 使用者改了字，但還沒按儲存
    return dialog


def _idle_logout(manager, monkeypatch):
    """觸發閒置自動登出。`_onIdleTimeout` 內部會彈 modal 提示，離線環境必須換掉。"""
    notices = []
    monkeypatch.setattr(
        main_module, "msgInfo",
        lambda title, text, parent=None: notices.append((title, text)),
    )
    manager._onIdleTimeout()
    return notices


def test_idle_logout_closes_edit_dialog_and_discards_typed_text(
        qtbot, pilot_db, monkeypatch):
    """管理頁開著修改視窗、改了字沒存 → 閒置登出後視窗消失、DB 維持原值。

    這是「權限在 modal 開啟期間掉下來」最容易出事的一條：改動前視窗會留在畫面上，
    回座後按下儲存仍會以舊身分寫進去。"""
    manager = DocumentManager(profile=FULL_PROFILE)
    qtbot.addWidget(manager.window)
    _enter_admin(manager, "audit")
    dialog = _open_edit_dialog(qtbot, manager, pilot_db)

    notices = _idle_logout(manager, monkeypatch)

    assert not dialog.isVisible()
    assert dialog.result() == QDialog.DialogCode.Rejected
    assert _read_reason(pilot_db) == ORIGINAL_REASON
    assert AuthManager.instance().current_role == "user"
    assert notices and notices[0][0] == "自動登出"


def test_idle_logout_from_admin_page_lands_on_login_and_returns_after_login(
        qtbot, pilot_db, monkeypatch):
    """原頁是管理專用頁 → 停在設定頁的登入畫面並標示原功能名稱；
    重新登入後自動切回那一頁，使用者不必自己再點一次。"""
    manager = DocumentManager(profile=FULL_PROFILE)
    qtbot.addWidget(manager.window)
    auth = _enter_admin(manager, "audit")
    _open_edit_dialog(qtbot, manager, pilot_db)

    _idle_logout(manager, monkeypatch)

    settings = manager.tabs[manager.tab_index("settings")]
    assert manager.tab_widget.currentIndex() == manager.tab_index("settings")
    assert not manager.tab_widget.isTabVisible(manager.tab_index("audit"))
    assert settings._outer_stack.currentIndex() == 0      # 登入畫面
    assert "操作紀錄" in settings._lbl_login_ttl.text()
    assert manager._pending_tab_key == "audit"

    auth._role = "admin"
    auth.role_changed.emit("admin")

    assert manager.tab_widget.currentIndex() == manager.tab_index("audit")
    assert manager._pending_tab_key is None


def test_idle_logout_on_shared_page_keeps_page_but_still_closes_dialog(
        qtbot, pilot_db, monkeypatch):
    """原頁一般使用者也能用 → 留在原頁不跳走；但開著的視窗一樣要關掉。
    「關窗」與「換頁」是兩件事，不得因為沒換頁就把窗留著。"""
    manager = DocumentManager(profile=FULL_PROFILE)
    qtbot.addWidget(manager.window)
    _enter_admin(manager, "reward")
    dialog = _open_edit_dialog(qtbot, manager, pilot_db)

    _idle_logout(manager, monkeypatch)

    assert not dialog.isVisible()
    assert _read_reason(pilot_db) == ORIGINAL_REASON
    assert manager.tab_widget.currentIndex() == manager.tab_index("reward")
    assert manager._pending_tab_key is None


def test_manual_logout_closes_edit_dialog_without_saving(qtbot, pilot_db):
    """手動按登出走的是同一條 role_changed 路徑，行為必須與閒置登出一致。"""
    manager = DocumentManager(profile=FULL_PROFILE)
    qtbot.addWidget(manager.window)
    auth = _enter_admin(manager, "audit")
    dialog = _open_edit_dialog(qtbot, manager, pilot_db)

    auth.logout()

    assert not dialog.isVisible()
    assert _read_reason(pilot_db) == ORIGINAL_REASON
    assert AuthManager.instance().current_role == "user"
