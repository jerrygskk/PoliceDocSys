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

from lib.app_profile import ENTRY_PROFILE, FULL_PROFILE
from lib.auth_manager import AuthManager
from lib.db_schema import applySchema
import main as main_module
import standalone_main
from main import DocumentManager, MainMenu, runApplication


@pytest.fixture
def shell_db(tmp_path, monkeypatch):
    """建立套用真實 schema 的 temp DB，並讓 main.getResourcePath('dbfile.db')
    指向此 temp DB；其他資源路徑（.ui／.svg 等）仍走真實 getResourcePath。"""
    db_path = tmp_path / "shell.db"
    conn = sqlite3.connect(db_path)
    applySchema(conn)
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
    """AuthManager 是單例，DocumentManager 會把 _updateTitle 掛上 role_changed。
    正式程式只建立一個 manager 且活到程式結束，故不受影響；但測試會反覆建立
    manager，widget 被回收後連線仍留在單例上，之後任何測試切換身分都會打到
    已釋放的視窗（RuntimeError: Internal C++ object already deleted），
    在 pytest-qt 的例外攔截下會讓「別支」測試莫名紅燈。故每支測試後拆掉本次
    新增的連線，回到乾淨狀態。"""
    auth = AuthManager.instance()
    auth._role = "user"
    signal = auth.role_changed
    yield
    try:
        signal.disconnect()
    except (RuntimeError, TypeError):
        pass   # 本來就沒有連線
    auth._role = "user"


def _visible_tab_keys(manager):
    return tuple(
        key for key, index in manager.tab_index_by_key.items()
        if manager.tab_widget.isTabVisible(index)
    )


def test_full_manager_keeps_all_current_tab_keys(qtbot, shell_db):
    manager = DocumentManager(profile=FULL_PROFILE)
    qtbot.addWidget(manager.window)
    assert tuple(manager.tab_index_by_key) == FULL_PROFILE.tab_keys
    assert manager.tab_index("settings") == 9
    assert manager.tab_index("browse") == 7
    assert manager.tab_index("audit") == 10
    assert manager.tab_widget.count() == 11


def test_full_manager_initial_user_visibility_hides_archive_and_audit(
        qtbot, shell_db):
    manager = DocumentManager(profile=FULL_PROFILE)
    qtbot.addWidget(manager.window)
    assert _visible_tab_keys(manager) == (
        "assignment_issue", "assignment_receive", "report", "reward",
        "reward_issue", "ticket", "print", "browse", "settings",
    )
    assert manager.tab_widget.count() == 11
    assert manager.tab_index("settings") == 9
    assert manager.tab_index("audit") == 10


def test_role_change_updates_visibility_without_reindexing(qtbot, shell_db):
    manager = DocumentManager(profile=FULL_PROFILE)
    qtbot.addWidget(manager.window)
    original_mapping = dict(manager.tab_index_by_key)

    manager._applyTabVisibility("archive")
    assert _visible_tab_keys(manager) == tuple(
        key for key in FULL_PROFILE.tab_keys if key != "audit"
    )

    manager._applyTabVisibility("admin")
    assert _visible_tab_keys(manager) == FULL_PROFILE.tab_keys
    assert manager.tab_index_by_key == original_mapping
    assert manager.tab_widget.count() == 11


def test_request_hidden_tab_routes_user_to_settings_login(qtbot, shell_db):
    manager = DocumentManager(profile=FULL_PROFILE)
    qtbot.addWidget(manager.window)

    assert manager.requestTab("archive") is False
    assert manager.tab_widget.currentIndex() == manager.tab_index("settings")
    assert manager._prev_tab_index == manager.tab_index("settings")
    assert manager._pending_tab_key == "archive"

    settings = manager.tabs[manager.tab_index("settings")]
    assert settings._outer_stack.currentIndex() == 0
    assert "檔案歸檔" in settings._lbl_login_ttl.text()


def test_request_visible_tab_opens_it_without_pending_login(qtbot, shell_db):
    manager = DocumentManager(profile=FULL_PROFILE)
    qtbot.addWidget(manager.window)

    assert manager.requestTab("reward_issue") is True
    assert manager.tab_widget.currentIndex() == manager.tab_index("reward_issue")
    assert manager._pending_tab_key is None


def test_archive_login_continues_archive_but_not_audit(qtbot, shell_db):
    manager = DocumentManager(profile=FULL_PROFILE)
    qtbot.addWidget(manager.window)
    auth = AuthManager.instance()

    manager.requestTab("archive")
    auth._role = "archive"
    auth.role_changed.emit("archive")
    assert manager.tab_widget.currentIndex() == manager.tab_index("archive")
    assert manager._pending_tab_key is None

    auth._role = "user"
    auth.role_changed.emit("user")
    manager.requestTab("audit")
    auth._role = "archive"
    auth.role_changed.emit("archive")
    assert manager.tab_widget.currentIndex() == manager.tab_index("settings")
    assert manager._pending_tab_key is None


def test_admin_login_continues_audit_target(qtbot, shell_db):
    manager = DocumentManager(profile=FULL_PROFILE)
    qtbot.addWidget(manager.window)
    auth = AuthManager.instance()

    manager.requestTab("audit")
    auth._role = "admin"
    auth.role_changed.emit("admin")
    assert manager.tab_widget.currentIndex() == manager.tab_index("audit")
    assert manager._pending_tab_key is None


def test_unknown_key_clears_older_pending_target(qtbot, shell_db):
    manager = DocumentManager(profile=FULL_PROFILE)
    qtbot.addWidget(manager.window)

    manager.requestTab("audit")
    assert manager._pending_tab_key == "audit"

    assert manager.requestTab("not-a-tab") is False
    assert manager._pending_tab_key is None


def test_login_prompt_resets_when_returning_to_user(qtbot, shell_db):
    manager = DocumentManager(profile=FULL_PROFILE)
    qtbot.addWidget(manager.window)
    settings = manager.tabs[manager.tab_index("settings")]

    settings.showLoginPrompt("操作紀錄")
    assert "操作紀錄" in settings._lbl_login_ttl.text()
    settings._onRoleChanged("user")
    assert settings._lbl_login_ttl.text() == "管理者驗證"


def test_restricted_route_tracks_settings_as_previous_tab(
        qtbot, shell_db, monkeypatch):
    manager = DocumentManager(profile=FULL_PROFILE)
    qtbot.addWidget(manager.window)
    settings = manager.tabs[manager.tab_index("settings")]
    calls = []
    monkeypatch.setattr(
        settings, "_promptUnsaved",
        lambda context: calls.append(context),
    )

    manager.requestTab("archive")
    manager.requestTab("browse")

    assert calls == ["leave"]


def test_leaving_login_page_abandons_pending_target(qtbot, shell_db):
    manager = DocumentManager(profile=FULL_PROFILE)
    qtbot.addWidget(manager.window)
    auth = AuthManager.instance()

    manager.requestTab("audit")
    manager.tab_widget.setCurrentIndex(manager.tab_index("browse"))
    assert manager._pending_tab_key is None

    auth._role = "admin"
    auth.role_changed.emit("admin")
    assert manager.tab_widget.currentIndex() == manager.tab_index("browse")


def test_failed_login_while_staying_on_login_page_retains_pending(
        qtbot, shell_db):
    manager = DocumentManager(profile=FULL_PROFILE)
    qtbot.addWidget(manager.window)
    settings = manager.tabs[manager.tab_index("settings")]

    manager.requestTab("audit")
    settings.w_password.setText("incorrect-password")
    settings._doLogin()

    assert manager.tab_widget.currentIndex() == manager.tab_index("settings")
    assert manager._pending_tab_key == "audit"
    assert settings.lbl_login_err.text() == "密碼錯誤，請再試一次"


def test_entry_manager_visibility_never_adds_removed_tabs(qtbot, shell_db):
    manager = DocumentManager(profile=ENTRY_PROFILE)
    qtbot.addWidget(manager.window)
    manager._applyTabVisibility("admin")
    assert _visible_tab_keys(manager) == ENTRY_PROFILE.tab_keys
    assert manager.tab_widget.count() == 4


def test_entry_manager_builds_only_four_tabs(qtbot, shell_db):
    manager = DocumentManager(profile=ENTRY_PROFILE)
    qtbot.addWidget(manager.window)
    assert tuple(manager.tab_index_by_key) == ("reward", "ticket", "browse", "settings")
    assert manager.tab_widget.count() == 4
    assert manager.tab_index("reward") == 0
    assert manager.tab_index("ticket") == 1
    assert manager.tab_index("browse") == 2
    assert manager.tab_index("settings") == 3
    assert manager.tab_index("assignment_issue") is None


def _visible_menu_keys(menu):
    return {
        key for key, button in menu.buttons_by_key.items()
        if not button.isHidden()
    }


def test_entry_menu_has_exactly_four_visible_actions(qtbot):
    menu = MainMenu(
        profile=ENTRY_PROFILE,
        tab_index_by_key={"reward": 0, "ticket": 1, "browse": 2, "settings": 3},
    )
    qtbot.addWidget(menu.ui)
    assert menu.ui.titleLabel.text() == "公文快速登錄系統"
    # 標題列不可沿用 .ui 內寫死的完整版名稱
    assert menu.ui.windowTitle() == "公文快速登錄系統 - 主選單"
    assert _visible_menu_keys(menu) == {"reward", "ticket", "browse", "settings"}


def test_full_menu_still_shows_all_eleven_actions(qtbot):
    menu = MainMenu(
        profile=FULL_PROFILE,
        tab_index_by_key={key: idx for idx, key in enumerate(FULL_PROFILE.tab_keys)},
    )
    qtbot.addWidget(menu.ui)
    assert menu.ui.titleLabel.text() == "公文收發管理系統"
    assert _visible_menu_keys(menu) == set(FULL_PROFILE.menu_keys)


def test_standalone_main_delegates_to_shared_runner(monkeypatch):
    seen = {}

    def fake_run_application(profile):
        seen["profile"] = profile
        return 0

    monkeypatch.setattr(standalone_main, "runApplication", fake_run_application)
    assert standalone_main.main() == 0
    assert seen["profile"] is ENTRY_PROFILE


def test_run_application_default_profile_is_full():
    import inspect

    sig = inspect.signature(runApplication)
    assert sig.parameters["profile"].default is FULL_PROFILE


def test_entry_manager_never_builds_full_only_tabs(qtbot, shell_db):
    from tabs import TabRewardIssue, TabPrint, TabArchive

    manager = DocumentManager(profile=ENTRY_PROFILE)
    qtbot.addWidget(manager.window)
    tab_types = {type(tab) for tab in manager.tabs.values()}
    assert TabRewardIssue not in tab_types
    assert TabPrint not in tab_types
    assert TabArchive not in tab_types


def test_entry_profile_forbids_startup_db_rescue():
    """規格 §8：獨立版遇到需要還原的情況只提示改用完整版，不得開啟還原工具。
    開機救援會覆蓋共用 dbfile.db，屬破壞性作業；獨立版連設定頁的備份還原子頁
    都不建立，開機路徑自然也不能成為繞道。"""
    assert FULL_PROFILE.allows_db_rescue is True
    assert ENTRY_PROFILE.allows_db_rescue is False


def test_full_profile_corrupt_db_opens_startup_rescue(monkeypatch):
    """完整版：DB 損毀→開既有開機救援（行為驗證，非只看原始碼順序）。"""
    import ui_utils.rescue_dialog as rescue_mod
    called = {}
    monkeypatch.setattr(rescue_mod, "runStartupRescue",
                        lambda db: called.setdefault("db", db))
    assert main_module.handleCorruptDb(FULL_PROFILE, "X:/fake.db") == 0
    assert called["db"] == "X:/fake.db"


def test_entry_profile_corrupt_db_never_opens_rescue(monkeypatch):
    """獨立版：DB 損毀→只出正式提示並結束，絕不建立／開啟救援視窗。"""
    import ui_utils.rescue_dialog as rescue_mod
    import ui_utils

    def _boom(*a, **k):
        raise AssertionError("獨立版不得開啟開機救援視窗")

    monkeypatch.setattr(rescue_mod, "runStartupRescue", _boom)
    shown = {}
    monkeypatch.setattr(ui_utils, "msgCritical",
                        lambda title, text: shown.update(title=title, text=text))
    assert main_module.handleCorruptDb(ENTRY_PROFILE, "X:/fake.db") == 1
    assert "公文收發管理系統" in shown["text"]


def test_profile_menu_labels_cannot_be_mutated_in_place():
    """frozen dataclass 只擋重新指定欄位，擋不住就地改 dict 內容——
    那會污染全域 profile（Codex 驗證指出）。menu_labels 必須是唯讀 mapping。"""
    with pytest.raises(TypeError):
        ENTRY_PROFILE.menu_labels["settings"] = "其他文字"
    assert ENTRY_PROFILE.menu_labels["settings"] == "系統設定"
