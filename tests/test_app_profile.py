from dataclasses import FrozenInstanceError

import pytest

from lib.app_profile import (
    ENTRY_PROFILE,
    FULL_PROFILE,
    visibleTabKeys,
)


FULL_TAB_KEYS = (
    "assignment_issue", "assignment_receive", "report", "reward",
    "reward_issue", "ticket", "print", "browse", "archive",
    "settings", "audit",
)


def test_full_profile_preserves_current_tab_order():
    assert FULL_PROFILE.tab_keys == FULL_TAB_KEYS


def test_entry_profile_is_strict_allowlist():
    assert ENTRY_PROFILE.product_name == "公文快速登錄系統"
    assert ENTRY_PROFILE.exe_name == "Police-Entry-Manager.exe"
    assert ENTRY_PROFILE.tab_keys == ("reward", "ticket", "browse", "settings")
    assert ENTRY_PROFILE.menu_keys == ("reward", "ticket", "browse", "settings")
    assert ENTRY_PROFILE.browse_keys == ("reward", "ticket")
    assert ENTRY_PROFILE.preload_keys == ()
    assert ENTRY_PROFILE.menu_labels["settings"] == "系統設定"
    assert ENTRY_PROFILE.settings_pages == ("personnel", "system")
    assert ENTRY_PROFILE.system_panels == ("idle", "input_lock", "input_mode")
    assert ENTRY_PROFILE.input_lock_flows == ("reward", "ticket")
    assert ENTRY_PROFILE.input_mode_flows == ("ticket",)


def test_profiles_are_immutable():
    with pytest.raises(FrozenInstanceError):
        ENTRY_PROFILE.product_name = "changed"


def test_full_profile_separates_preload_from_browse_keys():
    assert FULL_PROFILE.preload_keys != FULL_PROFILE.browse_keys
    assert FULL_PROFILE.preload_keys == ("task", "crim", "gen")


def test_profiles_select_their_own_loading_banner():
    assert FULL_PROFILE.banner_path == "res/buttons/banner.png"
    assert ENTRY_PROFILE.banner_path == "res/buttons/reward_ticket_banner.png"


def test_menu_labels_reject_every_mutation_kind():
    """frozen dataclass 只擋「重新指定欄位」，擋不住就地改內容——那會污染
    全域 profile。修改／新增／刪除三種都必須被擋（Codex 驗證指出）。"""
    for profile in (FULL_PROFILE, ENTRY_PROFILE):
        with pytest.raises(TypeError):
            profile.menu_labels["settings"] = "改掉"
        with pytest.raises(TypeError):
            profile.menu_labels["新key"] = "新增"
        with pytest.raises(TypeError):
            del profile.menu_labels["settings"]


def test_menu_labels_still_readable_after_hardening():
    assert FULL_PROFILE.menu_labels["settings"] == "資料庫設定"
    assert ENTRY_PROFILE.menu_labels["settings"] == "系統設定"
    assert FULL_PROFILE.menu_labels["print"] == "簽收單列印"
    assert set(ENTRY_PROFILE.menu_labels) == set(ENTRY_PROFILE.menu_keys)


def test_full_profile_visible_tabs_follow_role_matrix():
    assert visibleTabKeys("user", FULL_PROFILE) == (
        "assignment_issue", "assignment_receive", "report", "reward",
        "reward_issue", "ticket", "print", "browse", "settings",
    )
    assert visibleTabKeys("archive", FULL_PROFILE) == (
        "assignment_issue", "assignment_receive", "report", "reward",
        "reward_issue", "ticket", "print", "browse", "archive", "settings",
    )
    assert visibleTabKeys("admin", FULL_PROFILE) == FULL_PROFILE.tab_keys


def test_entry_profile_role_matrix_never_adds_full_only_tabs():
    for role in ("user", "archive", "admin"):
        assert visibleTabKeys(role, ENTRY_PROFILE) == ENTRY_PROFILE.tab_keys


def test_unknown_role_uses_least_privileged_visibility():
    assert visibleTabKeys("unexpected", FULL_PROFILE) == visibleTabKeys(
        "user", FULL_PROFILE
    )


def test_general_user_keeps_both_issue_tabs_and_settings():
    visible = set(visibleTabKeys("user", FULL_PROFILE))
    assert {"assignment_issue", "reward_issue", "settings"} <= visible
    assert {"archive", "audit"}.isdisjoint(visible)
