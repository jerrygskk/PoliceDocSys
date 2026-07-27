from dataclasses import FrozenInstanceError

import pytest

from lib.app_profile import ENTRY_PROFILE, FULL_PROFILE


FULL_TAB_KEYS = (
    "assignment_issue", "assignment_receive", "report", "reward",
    "reward_issue", "ticket", "print", "browse", "archive",
    "settings", "audit",
)


def test_full_profile_preserves_current_tab_order():
    assert FULL_PROFILE.tab_keys == FULL_TAB_KEYS


def test_entry_profile_is_strict_allowlist():
    assert ENTRY_PROFILE.product_name == "警政快速登錄系統"
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
