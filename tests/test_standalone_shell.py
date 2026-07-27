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
from lib.db_schema import applySchema
import main as main_module
from main import DocumentManager, MainMenu


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


def test_full_manager_keeps_all_current_tab_keys(qtbot, shell_db):
    manager = DocumentManager(profile=FULL_PROFILE)
    qtbot.addWidget(manager.window)
    assert tuple(manager.tab_index_by_key) == FULL_PROFILE.tab_keys
    assert manager.tab_index("settings") == 9
    assert manager.tab_index("browse") == 7
    assert manager.tab_index("audit") == 10
    assert manager.tab_widget.count() == 11


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
    assert menu.ui.titleLabel.text() == "警政快速登錄系統"
    assert _visible_menu_keys(menu) == {"reward", "ticket", "browse", "settings"}


def test_full_menu_still_shows_all_eleven_actions(qtbot):
    menu = MainMenu(
        profile=FULL_PROFILE,
        tab_index_by_key={key: idx for idx, key in enumerate(FULL_PROFILE.tab_keys)},
    )
    qtbot.addWidget(menu.ui)
    assert menu.ui.titleLabel.text() == "公文管理系統"
    assert _visible_menu_keys(menu) == set(FULL_PROFILE.menu_keys)
